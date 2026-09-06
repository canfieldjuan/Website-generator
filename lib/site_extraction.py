"""Local structure and source-evidence admission for URL redesign extraction."""

from __future__ import annotations

import copy
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from jsonschema import Draft202012Validator


MAX_ANALYSIS_BYTES = 200_000
MAX_TEXT_LENGTH = 20_000
MAX_ITEMS = 200


class SiteExtractionError(ValueError):
    """Raised when model extraction is not structurally and evidentially safe."""


def _string(*, nullable: bool = False, max_length: int = MAX_TEXT_LENGTH) -> dict:
    value = {
        "type": "string",
        "minLength": 1,
        "maxLength": max_length,
        "pattern": r"\S",
    }
    return {"anyOf": [value, {"type": "null"}]} if nullable else value


def _array(items: dict, *, max_items: int = MAX_ITEMS) -> dict:
    return {"type": "array", "items": items, "maxItems": max_items}


def _object(properties: dict[str, dict], *, required: Iterable[str] = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


TEXT = _string()
NULLABLE_TEXT = _string(nullable=True)
URL = _string(max_length=8_192)
NULLABLE_URL = _string(nullable=True, max_length=8_192)

SITE_TYPES = (
    "radio",
    "news",
    "local-business",
    "restaurant",
    "church",
    "civic",
    "nonprofit",
    "ecommerce",
    "portfolio",
    "services",
    "other",
)
SECTION_TYPES = (
    "hero",
    "news",
    "sports",
    "calendar",
    "promo-grid",
    "services",
    "menu",
    "testimonials",
    "team",
    "contact",
    "faq",
    "ad-block",
    "social",
    "misc",
)
IMAGE_CONTEXTS = (
    "logo",
    "hero",
    "promo",
    "ad",
    "show",
    "team",
    "content",
    "icon",
    "background",
)
PAGE_TYPES = (
    "contact",
    "about",
    "services",
    "single-service",
    "menu",
    "team",
    "faq",
    "gallery",
    "blog",
    "location",
    "other",
)
HOMEPAGE_SECTION_TYPES = (
    "hero",
    "inline-form",
    "services-grid",
    "services-list",
    "services-featured-row",
    "team-grid",
    "team-list",
    "testimonial-block",
    "map-block",
    "hours-block",
    "cta-band",
    "gallery-grid",
    "news-feed",
    "stats-band",
    "partner-logos",
    "social-block",
    "about-text",
    "video-block",
)

CONTACT_SCHEMA = _object(
    {
        "phone": NULLABLE_TEXT,
        "email": NULLABLE_TEXT,
        "address": NULLABLE_TEXT,
        "addresses": _array(TEXT),
        "hours": NULLABLE_TEXT,
    }
)

CONTENT_ITEM_SCHEMA = _object(
    {
        "title": NULLABLE_TEXT,
        "description": NULLABLE_TEXT,
        "url": NULLABLE_URL,
        "image_url": NULLABLE_URL,
        "tag": NULLABLE_TEXT,
        "date": NULLABLE_TEXT,
        "meta": NULLABLE_TEXT,
    }
)

SITE_ANALYSIS_SCHEMA = _object(
    {
        "site": _object(
            {
                "name": TEXT,
                "tagline": NULLABLE_TEXT,
                "type": _enum(*SITE_TYPES),
                "location": NULLABLE_TEXT,
                "contact": CONTACT_SCHEMA,
            },
            required=("name",),
        ),
        "brand": _object(
            {
                "logo_url": NULLABLE_URL,
                "colors": _object(
                    {
                        "raw": _array(TEXT),
                        "background": NULLABLE_TEXT,
                        "primary": NULLABLE_TEXT,
                        "secondary": NULLABLE_TEXT,
                        "text": NULLABLE_TEXT,
                        "link": NULLABLE_TEXT,
                        "nav_bg": NULLABLE_TEXT,
                        "button_bg": NULLABLE_TEXT,
                    }
                ),
                "color_mode": _enum("light", "dark", "unknown"),
                "fonts": _object({"display": NULLABLE_TEXT, "body": NULLABLE_TEXT}),
                "style_notes": _array(TEXT),
            }
        ),
        "nav": _array(_object({"label": TEXT, "url": URL}, required=("label", "url"))),
        "cta": _object({"label": NULLABLE_TEXT, "url": NULLABLE_URL}),
        "sections": _array(
            _object(
                {
                    "type": _enum(*SECTION_TYPES),
                    "headline": NULLABLE_TEXT,
                    "items": _array(CONTENT_ITEM_SCHEMA),
                },
                required=("type",),
            )
        ),
        "images": _array(
            _object(
                {"url": URL, "alt": NULLABLE_TEXT, "context": _enum(*IMAGE_CONTEXTS)},
                required=("url", "context"),
            )
        ),
        "image_generation_prompt": NULLABLE_TEXT,
        "social": _array(
            _object({"platform": TEXT, "url": URL}, required=("platform", "url"))
        ),
        "footer_links": _array(
            _object({"label": TEXT, "url": URL}, required=("label", "url"))
        ),
        "pages_to_fetch": _array(
            _object(
                {
                    "label": TEXT,
                    "url": URL,
                    "page_type": _enum(*PAGE_TYPES),
                    "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                    "fetchable": {"type": "boolean"},
                },
                required=("label", "url", "page_type", "priority", "fetchable"),
            )
        ),
        "site_structure": _enum("multi-page", "single-page", "mixed"),
        "single_page_sections": _array(
            _object(
                {
                    "nav_label": TEXT,
                    "anchor": NULLABLE_URL,
                    "page_type": TEXT,
                    "content": _object(
                        {
                            "headline": NULLABLE_TEXT,
                            "body_text": NULLABLE_TEXT,
                            "items": _array(CONTENT_ITEM_SCHEMA),
                            "form_fields": _array(TEXT),
                            "contact_info": CONTACT_SCHEMA,
                        }
                    ),
                },
                required=("nav_label", "page_type"),
            )
        ),
        "conversion_profile": _object(
            {
                "urgency_type": _enum("emergency", "planned", "both"),
                "primary_goal": _enum("call", "form", "booking", "order", "inquiry"),
                "has_emergency_service": {"type": "boolean"},
                "phone": NULLABLE_TEXT,
                "booking_platform": NULLABLE_TEXT,
                "existing_ctas": _array(TEXT),
                "trust_signals": _object(
                    {
                        "review_summary": NULLABLE_TEXT,
                        "certifications": _array(TEXT),
                        "awards": _array(TEXT),
                        "social_proof_lines": _array(TEXT),
                    }
                ),
            }
        ),
        "homepage_blueprint": _object(
            {
                "hero_type": _enum(
                    "hero-image",
                    "hero-split",
                    "hero-typography",
                    "hero-video",
                    "hero-carousel",
                    "none",
                ),
                "above_fold_form": {"type": "boolean"},
                "section_sequence": _array(_enum(*HOMEPAGE_SECTION_TYPES)),
                "footer_layout": _enum(
                    "footer-1col",
                    "footer-2col",
                    "footer-3col",
                    "footer-4col",
                    "footer-stack",
                ),
                "notes": NULLABLE_TEXT,
            }
        ),
    },
    required=("site",),
)

ENRICHMENT_ITEM_SCHEMA = _object(
    {
        "title": NULLABLE_TEXT,
        "url": NULLABLE_URL,
        "image_url": NULLABLE_URL,
        "tag": NULLABLE_TEXT,
        "meta": NULLABLE_TEXT,
    }
)

CONTENT_ENRICHMENT_SCHEMA = _object(
    {
        "type": _enum("services", "team", "misc"),
        "headline": NULLABLE_TEXT,
        "items": _array(ENRICHMENT_ITEM_SCHEMA),
        "source_url": URL,
    },
    required=("type", "items", "source_url"),
)

CONTACT_ENRICHMENT_SCHEMA = _object(
    {
        "form_fields": _array(TEXT),
        "contact_info": CONTACT_SCHEMA,
        "source_url": URL,
    },
    required=("source_url",),
)

_ANALYSIS_VALIDATOR = Draft202012Validator(SITE_ANALYSIS_SCHEMA)
_CONTENT_ENRICHMENT_VALIDATOR = Draft202012Validator(CONTENT_ENRICHMENT_SCHEMA)
_CONTACT_ENRICHMENT_VALIDATOR = Draft202012Validator(CONTACT_ENRICHMENT_SCHEMA)

_TEXT_ATTRIBUTES = {
    "alt",
    "title",
    "aria-label",
    "placeholder",
    "value",
    "content",
}
_ACTION_URL_ATTRIBUTES = {"href", "xlink:href"}
_IMAGE_ATTRIBUTES = {"src", "data-src", "data-lazy-src", "data-original"}
_IMAGE_METADATA_URL_PROPERTIES = frozenset(
    {
        "og:image",
        "og:image:secure_url",
        "og:image:url",
        "twitter:image",
        "twitter:image:src",
    }
)
_IMAGE_METADATA_ROOT_PROPERTIES = frozenset({"og:image", "twitter:image"})
_IMAGE_METADATA_ALT_PROPERTIES = frozenset({"og:image:alt", "twitter:image:alt"})
_IMAGE_CSS_PROPERTIES = frozenset(
    {
        "-webkit-mask",
        "-webkit-mask-image",
        "background",
        "background-image",
        "border-image",
        "border-image-source",
        "content",
        "cursor",
        "list-style",
        "list-style-image",
        "mask",
        "mask-image",
    }
)
_ACTION_INPUT_TYPES = frozenset(
    {
        "button",
        "image",
        "reset",
        "submit",
    }
)
_NON_DATA_INPUT_TYPES = {
    "button",
    "hidden",
    "image",
    "reset",
    "submit",
}
_SOCIAL_HOST_PLATFORMS = (
    ("facebook.com", "Facebook"),
    ("fb.com", "Facebook"),
    ("instagram.com", "Instagram"),
    ("linkedin.com", "LinkedIn"),
    ("nextdoor.com", "Nextdoor"),
    ("pinterest.com", "Pinterest"),
    ("tiktok.com", "TikTok"),
    ("twitter.com", "X"),
    ("x.com", "X"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("yelp.com", "Yelp"),
)
_RECORD_ITEM_LINK_LABELS = frozenset(
    {
        "details",
        "learn more",
        "more information",
        "read more",
        "view details",
    }
)
_LOGO_CONTAINER_MARKERS = frozenset(
    {
        "brand-logo",
        "custom-logo-link",
        "header-logo",
        "logo-link",
        "navbar-brand",
        "site-brand",
        "site-identity",
        "site-logo",
    }
)
_IDENTITY_TEXT_MARKERS = frozenset(
    {
        "brand-name",
        "logo-text",
        "site-name",
        "site-title",
    }
)
_ASSERTION_CONTEXT_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "body",
    "button",
    "dd",
    "details",
    "div",
    "dt",
    "figcaption",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "label",
    "li",
    "main",
    "nav",
    "p",
    "section",
    "summary",
    "td",
    "th",
}
_IGNORED_TEXT_TAGS = {
    "del",
    "noscript",
    "s",
    "script",
    "strike",
    "style",
    "template",
}
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]{1,64}@"
    r"(?:[A-Z0-9-]{1,63}\.)+[A-Z]{2,63}(?![A-Z0-9-])",
    re.I,
)
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?1[\s.()-]*)?(?:\(?\d{3}\)?[\s.()-]*)"
    r"\d{3}[\s.-]*\d{4}(?:\s*(?:x|ext\.?)[\s]*\d+)?(?!\d)",
    re.I,
)
_PHONE_EXTENSION_SUFFIX_PATTERN = re.compile(
    r"\s*(?:x|ext\.?)\s*\d+\s*$",
    re.I,
)
_PHONE_ROLE_PATTERN = re.compile(
    r"\b(?P<role>fax|facsimile|phone|telephone|mobile|cell|call)\b"
    r"(?:\s+(?:[A-Z][A-Z0-9_-]*\s+){0,4}(?:number|no)\.?)?"
    r"\s*(?:[:#-]\s*)?",
    re.I,
)
_CONTACT_GROUP_BREAK_PATTERN = re.compile(r"[.!?;|¦•·●▪‣∙◦○◆◇–—]")
_CSS_URL_PATTERN = re.compile(r"url\(\s*['\"]?([^)'\"\s]+)", re.I)
_CSS_DECLARATION_PATTERN = re.compile(
    r"(?:^|[;{])\s*([\w-]+)\s*:\s*([^;{}]+)",
    re.I,
)
_RENDER_SUPPRESSION_STYLE_PATTERN = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|"
    r"content-visibility\s*:\s*hidden)\s*(?:!\s*important\s*)?(?:;|$)",
    re.I,
)
_SENTENCE_BREAK_PATTERN = re.compile(r"[.!?;]")
_CONTRAST_BREAK_PATTERN = re.compile(r"\b(?:but|however|yet|except)\b", re.I)
_LEADING_PARENTHETICAL_CONTRAST = re.compile(
    r"^\s*,\s*(?:however|though|nevertheless)\s*,\s*",
    re.I,
)
_AFFIRMATIVE_CONTACT_NEGATION_PATTERN = re.compile(
    r"\b(?:please\s+)?(?:do\s+not|don['’]t|never)\s+hesitate\s+to\s+"
    r"(?:call|contact|email)\b",
    re.I,
)
_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?", re.I)
_NEGATION_TERMS = frozenset(
    {"no", "not", "never", "without", "neither", "nor", "cannot", "non"}
)
_POSTPOSED_NEGATION_TERMS = frozenset(
    {
        "no",
        "not",
        "never",
        "neither",
        "nor",
        "cannot",
        "unavailable",
        "prohibited",
        "excluded",
        "denied",
        "disallowed",
        "revoked",
        "expired",
        "suspended",
    }
)
_RESTRICTION_TERMS = frozenset(
    {
        "except",
        "only",
        "solely",
        "exclusive",
        "exclusively",
        "restricted",
        "limited",
    }
)
_CONDITIONAL_TERMS = frozenset(
    {
        "if",
        "unless",
        "whether",
        "assuming",
        "depending",
        "might",
        "may",
        "subject",
        "when",
    }
)
_TRAILING_SCOPE_QUALIFIER_TERMS = frozenset(
    {
        "after",
        "at",
        "before",
        "by",
        "during",
        "for",
        "from",
        "on",
        "through",
        "until",
        "upon",
        "with",
        "within",
    }
)
_ASSERTION_PRESERVING_TO_FOLLOWERS = frozenset(
    {"ask", "book", "call", "contact", "learn", "request", "schedule"}
)
_ASSERTION_PRESERVING_PREFIXES = frozenset(
    {
        ("call", "for"),
        ("call", "to", "request"),
        ("call", "us", "for"),
        ("not", "only"),
        ("we", "are"),
        ("we", "offer"),
        ("we", "provide"),
    }
)
_PRESENTATION_FIELD_LABELS = (
    "location",
    "address",
    "street address",
    "hours",
    "business hours",
    "office hours",
)


def _normalize_text(value: str) -> str:
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", decoded)
    return " ".join(normalized.split()).casefold()


def _phone_variants(value: str) -> set[str]:
    values = (value, _PHONE_EXTENSION_SUFFIX_PATTERN.sub("", value))
    variants: set[str] = set()
    for candidate in values:
        digits = "".join(
            character for character in candidate if character.isdigit()
        )
        if len(digits) < 7:
            continue
        variants.add(digits)
        if len(digits) == 11 and digits.startswith("1"):
            variants.add(digits[1:])
    return variants


def _phrase_occurrences(text: str, phrase: str) -> Iterable[int]:
    start = 0
    while True:
        index = text.find(phrase, start)
        if index < 0:
            return
        end = index + len(phrase)
        starts_on_boundary = index == 0 or not text[index - 1].isalnum()
        ends_on_boundary = end == len(text) or not text[end].isalnum()
        if starts_on_boundary and ends_on_boundary:
            yield index
        start = index + max(len(phrase), 1)


def _words_contain_negation(words: list[str], *, postposed: bool = False) -> bool:
    terms = _POSTPOSED_NEGATION_TERMS if postposed else _NEGATION_TERMS
    for index, word in enumerate(words):
        if (
            word == "not"
            and index + 1 < len(words)
            and words[index + 1] in _RESTRICTION_TERMS | {"just"}
        ):
            continue
        if word in terms or word.endswith("n't"):
            return True
    return False


def _words_contain_restriction(words: list[str]) -> bool:
    if any(word in _CONDITIONAL_TERMS for word in words):
        return True
    return any(
        word in _RESTRICTION_TERMS and not (index > 0 and words[index - 1] == "not")
        for index, word in enumerate(words)
    )


def _words_contain_scope_qualifier(words: list[str]) -> bool:
    for index, word in enumerate(words):
        if word in _TRAILING_SCOPE_QUALIFIER_TERMS:
            return True
        if word == "as" and index + 1 < len(words) and words[index + 1] == "part":
            return True
        if word == "to":
            preceding_scope = words[:index]
            if any(
                preceding_scope[position] == "not"
                and preceding_scope[position + 1] in _RESTRICTION_TERMS
                for position in range(len(preceding_scope) - 1)
            ):
                continue
            if (
                index + 1 < len(words)
                and words[index + 1] in _ASSERTION_PRESERVING_TO_FOLLOWERS
            ):
                continue
            return True
    return False


def _preceding_clause_scopes_claim(words: list[str]) -> bool:
    if not words:
        return False
    return tuple(words) not in _ASSERTION_PRESERVING_PREFIXES


def _occurrence_is_negated(text: str, start: int, length: int) -> bool:
    preceding_sentence = _SENTENCE_BREAK_PATTERN.split(text[:start])[-1]
    preceding_clause = _CONTRAST_BREAK_PATTERN.split(preceding_sentence)[-1]
    preceding_words = [
        word.replace("’", "'") for word in _WORD_PATTERN.findall(preceding_clause)
    ]
    if _words_contain_negation(preceding_words):
        return True

    following_text = _LEADING_PARENTHETICAL_CONTRAST.sub(" ", text[start + length :])
    following_sentence = _SENTENCE_BREAK_PATTERN.split(following_text)[0]
    following_clause = _CONTRAST_BREAK_PATTERN.split(following_sentence)[0]
    following_words = [
        word.replace("’", "'") for word in _WORD_PATTERN.findall(following_clause)
    ]
    return _words_contain_negation(following_words, postposed=True)


def _occurrence_is_nonassertive(
    text: str,
    start: int,
    length: int,
    *,
    strict_claim: bool = False,
) -> bool:
    before = text[:start]
    after = text[start + length :]
    preceding_clause = re.split(r"[.!?]", before)[-1]
    following_match = re.search(r"[.!?]", after)
    following_clause = after[: following_match.start()] if following_match else after
    following_boundary = following_match.group(0) if following_match else ""
    if following_boundary == "?":
        return True
    preceding_words = [
        word.replace("’", "'")
        for word in _WORD_PATTERN.findall(preceding_clause)
    ]
    following_words = [
        word.replace("’", "'")
        for word in _WORD_PATTERN.findall(following_clause)
    ]
    if _words_contain_restriction(preceding_words + following_words):
        return True
    if strict_claim:
        if _preceding_clause_scopes_claim(preceding_words):
            return True
        # Asserted facts may omit only a controlled leading request/provider
        # wrapper. Unknown trailing predicates can narrow, condition, or reverse
        # the extracted phrase, so they must remain part of the admitted claim.
        if tuple(preceding_words) == ("not", "only"):
            return not following_words or following_words[0] != "but"
        return bool(following_words)
    if not strict_claim and _words_contain_scope_qualifier(preceding_words):
        return True
    return _words_contain_scope_qualifier(following_words)


def _occurrence_has_presentation_label(
    text: str,
    start: int,
    labels: tuple[str, ...],
) -> bool:
    if not labels:
        return False
    prefix = re.sub(r"\s*[:\-–—]\s*$", "", text[:start].strip())
    return prefix in labels


def _starts_presentation_field(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(
        normalized == label
        or re.match(rf"^{re.escape(label)}\s*[:\-–—]\s*\S", normalized)
        is not None
        for label in _PRESENTATION_FIELD_LABELS
    )


def _assertion_heading_level(element: Any) -> int | None:
    match = re.fullmatch(
        r"h([1-6])",
        getattr(element, "name", "") or "",
        re.IGNORECASE,
    )
    return int(match.group(1)) if match is not None else None


def _contact_occurrence_is_negated(text: str, start: int, length: int) -> bool:
    without_affirmative_idiom = _AFFIRMATIVE_CONTACT_NEGATION_PATTERN.sub(
        lambda match: " " * len(match.group(0)),
        text,
    )
    return _occurrence_is_negated(without_affirmative_idiom, start, length)


def _contact_occurrence_is_noncallable(
    text: str,
    start: int,
    length: int,
) -> bool:
    """Return whether the owning role in this bounded assertion is non-callable."""
    occurrence_end = start + length
    all_roles = tuple(_PHONE_ROLE_PATTERN.finditer(text))
    all_numbers = tuple(_PHONE_PATTERN.finditer(text))
    protected_spans = tuple(
        (match.start(), match.end()) for match in (*all_roles, *all_numbers)
    )
    clause_breaks = tuple(
        match.start()
        for match in _CONTACT_GROUP_BREAK_PATTERN.finditer(text)
        if not any(
            protected_start <= match.start() < protected_end
            for protected_start, protected_end in protected_spans
        )
    )
    clause_start = max(
        (boundary + 1 for boundary in clause_breaks if boundary < start),
        default=0,
    )
    clause_end = min(
        (boundary for boundary in clause_breaks if boundary >= occurrence_end),
        default=len(text),
    )
    roles = tuple(
        role
        for role in all_roles
        if role.start() >= clause_start and role.end() <= clause_end
    )
    if not roles:
        return False
    numbers = tuple(
        number
        for number in all_numbers
        if number.start() >= clause_start and number.end() <= clause_end
    )

    def span_distance(
        first_start: int,
        first_end: int,
        second_start: int,
        second_end: int,
    ) -> int:
        if first_end <= second_start:
            return second_start - first_end
        if first_start >= second_end:
            return first_start - second_end
        return 0

    role_kinds = {role.group("role").casefold() for role in roles}
    if len(role_kinds) == 1:
        return next(iter(role_kinds)) in {"fax", "facsimile"}

    def is_prefix_role(role: re.Match[str]) -> bool:
        label = role.group(0).rstrip()
        if label.endswith((":", "#", "-")):
            return True
        previous = next(
            (number for number in reversed(numbers) if number.end() <= role.start()),
            None,
        )
        following = next(
            (number for number in numbers if number.start() >= role.end()),
            None,
        )
        if previous is None:
            return True
        if following is None:
            return False
        return (following.start() - role.end()) <= (role.start() - previous.end())

    governed_roles: list[re.Match[str]] = []
    preceding = next(
        (role for role in reversed(roles) if role.end() <= start),
        None,
    )
    if preceding is not None and is_prefix_role(preceding):
        governed_roles.append(preceding)
    following = next(
        (role for role in roles if role.start() >= occurrence_end),
        None,
    )
    if following is not None and not is_prefix_role(following):
        governed_roles.append(following)
    if not governed_roles:
        return any(
            role.group("role").casefold() in {"fax", "facsimile"}
            for role in roles
        )
    governed_role_kinds = {
        role.group("role").casefold() in {"fax", "facsimile"}
        for role in governed_roles
    }
    if len(governed_role_kinds) > 1:
        return True
    owner = min(
        governed_roles,
        key=lambda role: span_distance(
            role.start(), role.end(), start, occurrence_end
        ),
    )
    return owner.group("role").casefold() in {"fax", "facsimile"}


def _contact_destination(value: str) -> tuple[str, str] | None:
    parsed = urlsplit(html.unescape(value).strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"tel", "mailto"}:
        return None
    destination = unquote(parsed.path).strip()
    return (scheme, destination) if destination else None


def _contact_destination_context(context: Any, action: Any, destination: str) -> str:
    if context is None:
        return _normalize_text(destination)
    parts: list[str] = []
    for node in context.descendants:
        if node is action:
            action_text = source_visible_text(action)
            parts.append(action_text)
            destination_is_visible = (
                destination.casefold() in action_text.casefold()
                if "@" in destination
                else any(
                    _phone_variants(match.group(0)) & _phone_variants(destination)
                    for match in _PHONE_PATTERN.finditer(action_text)
                )
            )
            if not destination_is_visible:
                parts.append(destination)
            continue
        if isinstance(node, Comment):
            continue
        if isinstance(node, str):
            if action in node.parents:
                continue
            parent = node.parent
            if parent is None or parent.name not in _IGNORED_TEXT_TAGS:
                parts.append(str(node))
    return _normalize_text(" ".join(parts))


def same_site_origin(first_url: Any, second_url: Any) -> bool:
    if not isinstance(first_url, str) or not isinstance(second_url, str):
        return False
    first = urlsplit(first_url)
    second = urlsplit(second_url)
    if (
        first.scheme.casefold() not in {"http", "https"}
        or second.scheme.casefold() not in {"http", "https"}
        or not first.hostname
        or not second.hostname
    ):
        return False

    def identity(parsed: Any) -> tuple[str, str, int | None]:
        scheme = parsed.scheme.casefold()
        hostname = (parsed.hostname or "").casefold()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return (scheme, hostname, parsed.port or (443 if scheme == "https" else 80))

    try:
        return identity(first) == identity(second)
    except ValueError:
        return False


def _resolved_distinct_fetchable_page(
    value: Any,
    source_url: str | None,
    resolution_base_url: str | None,
) -> str | None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or not source_url
        or not resolution_base_url
    ):
        return None
    source = urlsplit(source_url)
    destination = urlsplit(
        urljoin(resolution_base_url, html.unescape(value).strip())
    )
    if (
        source.scheme.casefold() not in {"http", "https"}
        or destination.scheme.casefold() not in {"http", "https"}
        or not source.hostname
        or not destination.hostname
    ):
        return None

    if not same_site_origin(source_url, destination.geturl()):
        return None
    if (destination.path or "/", destination.query) == (
        source.path or "/",
        source.query,
    ):
        return None
    return destination._replace(fragment="").geturl()


def _attribute_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        yield from (item for item in value if isinstance(item, str))


def _srcset_urls(value: str) -> set[str]:
    return {
        candidate.strip().split()[0]
        for candidate in value.split(",")
        if candidate.strip()
    }


def css_image_urls(value: str) -> set[str]:
    """Return URL resources from CSS declarations that carry image content."""
    urls: set[str] = set()
    for match in _CSS_DECLARATION_PATTERN.finditer(value):
        if match.group(1).casefold() in _IMAGE_CSS_PROPERTIES:
            urls.update(_CSS_URL_PATTERN.findall(match.group(2)))
    return urls


def is_render_suppressed_element(element: Any) -> bool:
    """Return whether one element is explicitly removed from rendering."""
    tag_name = str(getattr(element, "name", "") or "").casefold()
    if tag_name == "input" and str(element.get("type") or "").casefold() == "hidden":
        return True
    if element.has_attr("hidden"):
        return True
    style = element.get("style")
    return isinstance(style, str) and bool(
        _RENDER_SUPPRESSION_STYLE_PATTERN.search(style)
    )


def _element_has_marker(element: Any, markers: frozenset[str]) -> bool:
    for attribute in (
        element.get("id"),
        element.get("class"),
        element.get("itemprop"),
        element.get("data-role"),
    ):
        for value in _attribute_values(attribute):
            marker = value.strip().casefold()
            if any(token in markers for token in marker.split()):
                return True
    return False


def _element_has_logo_marker(element: Any) -> bool:
    return _element_has_marker(element, _LOGO_CONTAINER_MARKERS)


def _element_has_identity_text_marker(element: Any) -> bool:
    return _element_has_marker(element, _IDENTITY_TEXT_MARKERS)


def _is_source_logo(image: Any) -> bool:
    """Return whether source semantics identify this image as the site's logo."""
    candidates = [image]
    for ancestor in image.parents:
        candidates.append(ancestor)
        if ancestor.name not in {"a", "picture", "span"}:
            break
    return any(_element_has_logo_marker(element) for element in candidates)


def _source_action_replacement_text(element: Tag) -> str:
    tag_name = element.name.casefold()
    if tag_name in {"img", "area"}:
        value = element.get("alt")
    elif tag_name == "input":
        input_type = str(element.get("type") or "").casefold()
        if input_type == "image":
            value = element.get("alt") or element.get("value")
        elif input_type in {"button", "reset", "submit"}:
            value = element.get("value")
            if value is None:
                value = {"reset": "Reset", "submit": "Submit"}.get(input_type, "")
        else:
            value = ""
    else:
        value = ""
    return value if isinstance(value, str) else ""


def source_visible_text(element: Tag) -> str:
    """Return rendered descendant text with image replacement text, ignoring ARIA."""
    if not is_source_semantic_element(element):
        return ""
    parts: list[str] = [_source_action_replacement_text(element)]
    for child in element.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            parts.append(source_visible_text(child))
    return " ".join(" ".join(part for part in parts if part).split())


def _source_accessible_text(
    element: Tag,
    root: BeautifulSoup | Tag,
    active_references: frozenset[str],
    excluded_element: Tag | None = None,
) -> str:
    if element is excluded_element:
        return ""
    if not is_source_semantic_element(element):
        return ""
    labelled_by = element.get("aria-labelledby")
    if isinstance(labelled_by, str) and labelled_by.strip():
        references = labelled_by.split()
        if len(references) > MAX_ITEMS:
            return ""
        labelled_parts: list[str] = []
        for target_id in references:
            if target_id in active_references:
                return ""
            targets = root.find_all(id=target_id, limit=2)
            if len(targets) != 1:
                return ""
            target_text = _source_accessible_text(
                targets[0],
                root,
                active_references | {target_id},
                excluded_element,
            )
            if not target_text:
                return ""
            labelled_parts.append(target_text)
        return " ".join(" ".join(labelled_parts).split())

    aria_label = element.get("aria-label")
    if isinstance(aria_label, str) and aria_label.strip():
        return " ".join(aria_label.split())

    parts: list[str] = [_source_action_replacement_text(element)]
    for child in element.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            parts.append(
                _source_accessible_text(
                    child,
                    root,
                    active_references,
                    excluded_element,
                )
            )
    return " ".join(" ".join(part for part in parts if part).split())


def source_accessible_name(
    element: Tag,
    root: BeautifulSoup | Tag,
    *,
    excluded_element: Tag | None = None,
) -> str:
    """Return one recursive browser-facing name for a source element."""
    return _source_accessible_text(
        element,
        root,
        frozenset(),
        excluded_element,
    )


def is_source_semantic_element(element: Any) -> bool:
    """Return whether an element is outside browser-inert source containers."""
    return not any(
        getattr(candidate, "name", None) in _IGNORED_TEXT_TAGS
        or is_render_suppressed_element(candidate)
        for candidate in (element, *getattr(element, "parents", ()))
    )


def _source_document_base_from_soup(
    soup: BeautifulSoup | Tag,
    source_url: str | None,
) -> str | None:
    if not source_url:
        return None
    for base in soup.find_all("base", href=True, limit=MAX_ITEMS):
        if any(
            getattr(parent, "name", None) in _IGNORED_TEXT_TAGS
            for parent in base.parents
        ):
            continue
        raw_href = base.get("href")
        if not isinstance(raw_href, str):
            continue
        candidate = urljoin(source_url, html.unescape(raw_href).strip())
        parsed = urlsplit(candidate)
        if parsed.scheme.casefold() in {"http", "https"} and parsed.hostname:
            return candidate
    return source_url


def source_document_base_url(
    source_html: str,
    source_url: str | None,
) -> str | None:
    """Return the browser-effective HTTP(S) base owned by one source document."""
    if not isinstance(source_html, str):
        return source_url
    return _source_document_base_from_soup(
        BeautifulSoup(source_html, "html.parser"),
        source_url,
    )


def is_source_action_available(element: Any) -> bool:
    """Return whether source markup exposes one browser-available control."""
    if not is_source_semantic_element(element):
        return False
    candidates = (element, *getattr(element, "parents", ()))
    if any(candidate.has_attr("inert") for candidate in candidates):
        return False

    tag_name = str(getattr(element, "name", "") or "").casefold()
    if tag_name not in {"button", "input", "select", "textarea"}:
        return True
    if element.has_attr("disabled"):
        return False
    for ancestor in getattr(element, "parents", ()):
        if getattr(ancestor, "name", None) != "fieldset" or not ancestor.has_attr(
            "disabled"
        ):
            continue
        first_legend = ancestor.find("legend", recursive=False)
        if first_legend is None or first_legend not in element.parents:
            return False
    return True


def source_action_accessible_name(
    element: Tag,
    root: BeautifulSoup | Tag,
) -> str:
    """Return one complete source-owned accessible name for an action."""
    accessible_name = source_accessible_name(element, root)
    if accessible_name:
        return accessible_name
    labelled_by = element.get("aria-labelledby")
    if isinstance(labelled_by, str) and labelled_by.strip():
        return ""
    if element.name.casefold() == "input":
        value = element.get("value")
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    title = element.get("title")
    return " ".join(title.split()) if isinstance(title, str) else ""


def action_element_labels(
    element: Tag,
    root: BeautifulSoup | Tag,
) -> tuple[str, ...]:
    """Return every independently rendered or exposed label on one action."""
    accessible_name = source_action_accessible_name(element, root)
    labelled_by = element.get("aria-labelledby")
    if isinstance(labelled_by, str) and labelled_by.strip() and not accessible_name:
        return ()
    labels: list[str] = []
    for value in (
        accessible_name,
        source_visible_text(element),
        element.get("title"),
    ):
        if not isinstance(value, str):
            continue
        candidate = " ".join(value.split())
        if candidate and candidate not in labels:
            labels.append(candidate)
    return tuple(labels)


def is_labelled_action_element(element: Any) -> bool:
    """Return whether one DOM element presents a browser action label."""
    tag_name = str(getattr(element, "name", "") or "").casefold()
    roles = str(element.get("role") or "").casefold().split()
    if tag_name in {"a", "area"}:
        return any(element.has_attr(attribute) for attribute in _ACTION_URL_ATTRIBUTES)
    if tag_name == "button" or any(role in {"button", "link"} for role in roles):
        return True
    return tag_name == "input" and (
        str(element.get("type") or "").casefold() in _ACTION_INPUT_TYPES
    )


def _source_form_owner(
    control: Tag,
    root: BeautifulSoup | Tag,
) -> Tag | None:
    form_id = control.get("form")
    if isinstance(form_id, str) and form_id.strip():
        owners = root.find_all("form", id=form_id.strip(), limit=2)
        return owners[0] if len(owners) == 1 else None
    return control.find_parent("form")


def action_element_declared_destinations(element: Tag) -> tuple[str, ...]:
    """Return destinations explicitly declared by one browser action element."""
    tag_name = element.name.casefold()
    if tag_name in {"a", "area"}:
        attributes = ("href", "xlink:href")
    elif tag_name == "form":
        attributes = ("action",)
    elif tag_name in {"button", "input"}:
        attributes = ("formaction",)
    else:
        return ()
    return tuple(
        value
        for attribute in attributes
        if isinstance((value := element.get(attribute)), str)
    )


def is_submit_action_element(element: Tag) -> bool:
    """Return whether one button or input submits its owning form."""
    tag_name = element.name.casefold()
    control_type = str(element.get("type") or "").casefold()
    return (
        tag_name == "button" and control_type not in {"button", "reset"}
        or tag_name == "input" and control_type in {"submit", "image"}
    )


def action_element_destinations(
    element: Tag,
    root: BeautifulSoup | Tag,
) -> tuple[str, ...]:
    """Return the browser-effective destinations owned by one action element."""
    tag_name = element.name.casefold()
    if tag_name in {"a", "area", "form"}:
        return action_element_declared_destinations(element)
    if tag_name not in {"button", "input"} or not is_submit_action_element(element):
        return ()

    owner = _source_form_owner(element, root)
    if owner is None:
        return ()
    if element.has_attr("formaction"):
        formaction = element.get("formaction")
        return (formaction,) if isinstance(formaction, str) else ()
    action = owner.get("action")
    return (action,) if isinstance(action, str) else ()


def _source_form_control_label(
    control: Tag,
    root: BeautifulSoup | Tag,
) -> str:
    accessible_label = (
        _source_accessible_text(control, root, frozenset())
        if control.has_attr("aria-labelledby") or control.has_attr("aria-label")
        else ""
    )
    if not accessible_label:
        labels: list[str] = []
        seen_labels: set[int] = set()

        def append_label(label: Any) -> None:
            identity = id(label)
            if identity not in seen_labels:
                seen_labels.add(identity)
                labels.append(
                    source_accessible_name(
                        label,
                        root,
                        excluded_element=control,
                    )
                )

        wrapping_label = control.find_parent("label")
        if wrapping_label is not None:
            append_label(wrapping_label)
        control_id = control.get("id")
        if isinstance(control_id, str) and control_id.strip():
            for label in root.find_all(
                "label", attrs={"for": control_id}, limit=MAX_ITEMS
            ):
                append_label(label)
        accessible_label = " ".join(label for label in labels if label)
    if not accessible_label:
        accessible_label = str(
            control.get("placeholder") or control.get("title") or ""
        ).strip()
    return _normalize_text(accessible_label)


def _source_form_submitters(
    form: Tag,
    root: BeautifulSoup | Tag,
) -> tuple[Tag, ...]:
    submitters: list[Tag] = []
    for candidate in root.find_all(["button", "input"]):
        if not is_source_action_available(candidate):
            continue
        if is_submit_action_element(candidate) and _source_form_owner(candidate, root) is form:
            submitters.append(candidate)
    return tuple(submitters)


def _source_form_action_url(
    form: Tag,
    root: BeautifulSoup | Tag,
    *,
    resolution_base_url: str | None,
    source_url: str | None,
) -> str | None:
    submitters = _source_form_submitters(form, root)
    raw_actions: list[str | None]
    if submitters:
        raw_actions = [
            next(iter(action_element_destinations(submitter, root)), source_url)
            for submitter in submitters
        ]
    else:
        raw_actions = [
            next(iter(action_element_declared_destinations(form)), source_url)
        ]

    actions: list[str] = []
    for raw_action in raw_actions:
        action_candidate = urljoin(
            resolution_base_url or "",
            html.unescape(raw_action).strip() if isinstance(raw_action, str) else "",
        )
        parsed_action = urlsplit(action_candidate)
        if (
            parsed_action.scheme.casefold() not in {"http", "https"}
            or not parsed_action.hostname
        ):
            return None
        if action_candidate not in actions:
            actions.append(action_candidate)
    return actions[0] if len(actions) == 1 else None


def _marked_identity_text_parts(
    element: Tag,
    root: BeautifulSoup | Tag,
) -> tuple[str, ...]:
    """Return bounded name text from a broader brand/logo container."""
    parts: list[str] = []

    def append(value: Any) -> None:
        if not isinstance(value, str):
            return
        candidate = " ".join(value.split())
        if candidate and candidate not in parts:
            parts.append(candidate)

    if _element_has_identity_text_marker(element):
        append(element.get_text(" ", strip=True))

    if element.find(True) is None:
        append(element.get_text(" ", strip=True))

    marked_descendants = [
        candidate
        for candidate in element.find_all(True, limit=MAX_ITEMS)
        if _element_has_identity_text_marker(candidate)
    ]
    if len(marked_descendants) == 1:
        append(marked_descendants[0].get_text(" ", strip=True))

    h1_candidates = element.find_all("h1", limit=2)
    if len(h1_candidates) == 1:
        append(h1_candidates[0].get_text(" ", strip=True))

    if element.name == "a":
        append(source_action_accessible_name(element, root))
    return tuple(parts)


_ALL_HEADING_TAG_PATTERN = re.compile(r"h([1-6])", re.I)
_HEADING_TAG_PATTERN = re.compile(r"h([2-6])", re.I)
_TITLE_SEPARATOR_PATTERN = re.compile(r"(?:\s*[|–—•·]\s*|\s+-\s+)")
_GENERIC_PAGE_IDENTITY_PARTS = frozenset(
    {
        "about",
        "about us",
        "blog",
        "contact",
        "contact us",
        "faq",
        "frequently asked questions",
        "gallery",
        "home",
        "menu",
        "news",
        "our services",
        "our team",
        "services",
        "team",
    }
)
_IDENTITY_CANONICAL_PREFIXES = ("welcome to ", "official website of ")
_IDENTITY_CANONICAL_SUFFIXES = (" logo",)
_ATOMIC_RECORD_TAGS = {
    "address",
    "blockquote",
    "details",
    "figure",
    "li",
    "p",
    "td",
    "th",
    "tr",
}
_INDEPENDENT_RECORD_TAGS = {"article", "details", "figure", "section"}
_RECORD_CONTAINER_TAGS = {
    "article",
    "details",
    "div",
    "dl",
    "figure",
    "li",
    "menu",
    "ol",
    "section",
    "table",
    "tr",
    "ul",
}


def _identity_canonical_variants(value: str) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    variants = [normalized] if normalized else []
    for prefix in _IDENTITY_CANONICAL_PREFIXES:
        if normalized.startswith(prefix):
            candidate = normalized[len(prefix) :].strip()
            if candidate and candidate not in variants:
                variants.append(candidate)
    for suffix in _IDENTITY_CANONICAL_SUFFIXES:
        if normalized.endswith(suffix):
            candidate = normalized[: -len(suffix)].strip()
            if candidate and candidate not in variants:
                variants.append(candidate)
    return tuple(variants)


def _identity_candidates_agree(first: str, second: str) -> bool:
    return bool(
        set(_identity_canonical_variants(first))
        & set(_identity_canonical_variants(second))
    )


def _select_supported_identity_parts(
    *candidate_channels: Iterable[str],
) -> tuple[str, ...]:
    """Select one uniquely best-supported canonical identity across channels."""
    channels = tuple(
        tuple(
            dict.fromkeys(
                normalized
                for part in channel
                if (normalized := _normalize_text(part))
            )
        )
        for channel in candidate_channels
    )
    candidates = tuple(dict.fromkeys(part for channel in channels for part in channel))
    if not candidates:
        return ()

    support = {
        candidate: sum(
            any(_identity_candidates_agree(candidate, part) for part in channel)
            for channel in channels
        )
        for candidate in candidates
    }
    strongest = max(support.values())
    winners: list[str] = []
    for candidate in candidates:
        if support[candidate] != strongest or any(
            _identity_candidates_agree(candidate, winner) for winner in winners
        ):
            continue
        winners.append(candidate)
    if len(winners) != 1:
        return ()
    winner = winners[0]
    return tuple(
        part
        for part in candidates
        if _identity_candidates_agree(part, winner)
    )


def _heading_owned_fragment(
    heading: Any,
    *,
    stop_at_record_containers: bool = False,
) -> str:
    match = _ALL_HEADING_TAG_PATTERN.fullmatch(
        getattr(heading, "name", "") or ""
    )
    if match is None:
        return str(heading)
    heading_level = int(match.group(1))
    parts = [str(heading)]
    for sibling in heading.next_siblings:
        sibling_name = getattr(sibling, "name", None)
        if (
            sibling_name in _RECORD_CONTAINER_TAGS
            if stop_at_record_containers
            else sibling_name in {"article", "section"}
        ):
            break
        sibling_heading = (
            _ALL_HEADING_TAG_PATTERN.fullmatch(sibling_name)
            if isinstance(sibling_name, str)
            else None
        )
        if sibling_heading is None and sibling_name is not None:
            nested_heading = sibling.find(_ALL_HEADING_TAG_PATTERN)
            sibling_heading = (
                _ALL_HEADING_TAG_PATTERN.fullmatch(nested_heading.name or "")
                if nested_heading is not None
                else None
            )
        if (
            sibling_heading is not None
            and int(sibling_heading.group(1)) <= heading_level
        ):
            break
        parts.append(str(sibling))
    return "".join(parts)


def _record_fragments(soup: BeautifulSoup) -> tuple[str, ...]:
    fragments: list[str] = []
    seen: set[str] = set()

    def append(fragment: str) -> None:
        normalized = fragment.strip()
        if normalized and normalized not in seen and len(fragments) < MAX_ITEMS:
            seen.add(normalized)
            fragments.append(normalized)

    for element in soup.find_all(True):
        if element.name in _ATOMIC_RECORD_TAGS:
            if (
                element.find(element.name) is not None
                or element.find(_INDEPENDENT_RECORD_TAGS) is not None
            ):
                continue
            append(str(element))
            continue
        if element.name in {"article", "div", "section"}:
            nested_record = element.find(
                [
                    "article",
                    "details",
                    "div",
                    "dl",
                    "dt",
                    "figure",
                    "li",
                    "section",
                    "tr",
                ]
            )
            if (
                nested_record is None
                and len(element.find_all(_HEADING_TAG_PATTERN)) <= 1
            ):
                append(str(element))

    for term in soup.find_all("dt"):
        parts = [str(term)]
        for sibling in term.next_siblings:
            sibling_name = getattr(sibling, "name", None)
            if sibling_name == "dt":
                break
            if sibling_name is not None and sibling_name != "dd":
                break
            parts.append(str(sibling))
        append("".join(parts))

    for main in soup.find_all("main", limit=MAX_ITEMS):
        heading_candidates = main.find_all(_ALL_HEADING_TAG_PATTERN, limit=2)
        if (
            len(heading_candidates) == 1
            and heading_candidates[0].name.casefold() == "h1"
        ):
            append(
                _heading_owned_fragment(
                    heading_candidates[0],
                    stop_at_record_containers=True,
                )
            )

    for heading in soup.find_all(_HEADING_TAG_PATTERN):
        if _HEADING_TAG_PATTERN.fullmatch(heading.name or "") is None:
            continue
        append(_heading_owned_fragment(heading, stop_at_record_containers=True))
    return tuple(fragments)


def _content_section_fragments(soup: BeautifulSoup) -> tuple[str, ...]:
    fragments: list[str] = []
    seen: set[str] = set()

    def append(fragment: str) -> None:
        normalized = fragment.strip()
        if normalized and normalized not in seen and len(fragments) < MAX_ITEMS:
            seen.add(normalized)
            fragments.append(normalized)

    for element in soup.find_all(["article", "section"], limit=MAX_ITEMS):
        if len(element.find_all(["article", "section"], limit=2)) > 1:
            continue
        append(str(element))

    for element in soup.find_all("main", limit=MAX_ITEMS):
        if element.find(["article", "section"]) is not None:
            continue
        if len(element.find_all("h1", limit=2)) != 1:
            continue
        append(str(element))

    for heading in soup.find_all(_HEADING_TAG_PATTERN, limit=MAX_ITEMS):
        append(_heading_owned_fragment(heading))
    return tuple(fragments)


@dataclass(frozen=True)
class SourceFormEvidence:
    control_labels: tuple[str, ...]
    action_url: str | None


@dataclass(frozen=True)
class SourceEvidence:
    text_segments: tuple[str, ...]
    assertion_segments: tuple[str, ...]
    assertion_occurrences: tuple[tuple[str, str], ...]
    identity_segments: tuple[str, ...]
    identity_exact_segments: tuple[str, ...]
    heading_segments: tuple[str, ...]
    action_labels: frozenset[str]
    action_pairs: frozenset[tuple[str, str]]
    action_content_pairs: frozenset[tuple[str, str]]
    action_urls: frozenset[str]
    image_urls: frozenset[str]
    image_pairs: frozenset[tuple[str, str]]
    logo_urls: frozenset[str]
    form_control_labels: tuple[str, ...]
    emails: frozenset[str]
    phones: frozenset[str]
    resolution_base_url: str | None
    forms: tuple[SourceFormEvidence, ...]
    records: tuple[SourceEvidence, ...]
    content_sections: tuple[SourceEvidence, ...]
    section_targets: tuple[tuple[str, SourceEvidence], ...]

    @classmethod
    def from_html(
        cls,
        source_html: str,
        source_url: str | None,
        *,
        _include_records: bool = True,
        _include_content_sections: bool = True,
        _include_section_targets: bool = True,
        _group_heading_claims: bool = True,
        _resolution_base_url: str | None = None,
    ) -> "SourceEvidence":
        if not isinstance(source_html, str) or not source_html.strip():
            raise SiteExtractionError("Source HTML must be non-empty text.")
        if source_url is not None and (
            not isinstance(source_url, str) or not source_url.strip()
        ):
            raise SiteExtractionError(
                "Source URL must be non-empty text when supplied."
            )

        soup = BeautifulSoup(source_html, "html.parser")
        resolution_base_url = _resolution_base_url or _source_document_base_from_soup(
            soup,
            source_url,
        )
        preserved_image_urls: set[str] = set()
        for inventory in soup.find_all(
            "template",
            attrs={"data-code-owned-image-inventory": "true"},
            limit=MAX_ITEMS,
        ):
            for image in inventory.find_all("img", limit=MAX_ITEMS):
                preserved_image_urls.update(_attribute_values(image.get("src")))
        for style in soup.find_all("style", limit=MAX_ITEMS):
            preserved_image_urls.update(css_image_urls(style.get_text(" ")))
        for suppressed_container in soup.find_all(True):
            if (
                suppressed_container.parent is not None
                and is_render_suppressed_element(suppressed_container)
            ):
                suppressed_container.decompose()
        for ignored_container in soup.find_all(tuple(_IGNORED_TEXT_TAGS)):
            ignored_container.decompose()

        context_parts: dict[int, list[str]] = {}
        context_elements: dict[int, Any] = {}
        for node in soup.find_all(string=True):
            if isinstance(node, Comment):
                continue
            value = str(node).strip()
            if not value:
                continue
            parent = node.parent
            if parent is not None and parent.name in _IGNORED_TEXT_TAGS:
                continue
            context = parent
            while context is not None and context.name not in _ASSERTION_CONTEXT_TAGS:
                context = context.parent
            context_key = id(context or node)
            context_parts.setdefault(context_key, []).append(value)
            context_elements.setdefault(context_key, context or node)
        assertion_occurrences: list[tuple[str, str]] = []
        claim_scope_parent_tags = {
            "article",
            "details",
            "div",
            "figure",
            "li",
            "main",
            "section",
            "td",
            "th",
        }
        transparent_claim_wrapper_tags = {"div", "main"}
        paragraph_claim_tags = {"p", "small"}
        assertion_context_ids = set(context_parts)

        def is_flat_claim_context(element: Any) -> bool:
            if not isinstance(element, Tag):
                return False
            if not _group_heading_claims:
                return element.name in paragraph_claim_tags
            return (
                id(element) in assertion_context_ids
                and element.name not in _INDEPENDENT_RECORD_TAGS
                and _assertion_heading_level(element) is None
            )

        def first_claim_boundary(element: Any) -> Tag | None:
            if not isinstance(element, Tag):
                return None
            return next(
                (
                    descendant
                    for descendant in element.descendants
                    if isinstance(descendant, Tag)
                    and (
                        _assertion_heading_level(descendant) is not None
                        or descendant.name in _INDEPENDENT_RECORD_TAGS
                    )
                ),
                None,
            )

        def claim_component_heading_level(element: Any) -> int | None:
            direct_level = _assertion_heading_level(element)
            if direct_level is not None or not isinstance(element, Tag):
                return direct_level
            boundary = first_claim_boundary(element)
            if boundary is not None and claim_component_prefix(element, boundary):
                return None
            return _assertion_heading_level(boundary)

        def raw_claim_component_text(element: Any) -> str:
            if isinstance(element, Comment):
                return ""
            if isinstance(element, NavigableString):
                return _normalize_text(str(element))
            if isinstance(element, Tag):
                return _normalize_text(element.get_text(" ", strip=True))
            return ""

        def claim_component_prefix(element: Tag, boundary: Tag) -> str:
            parts: list[str] = []
            for descendant in element.descendants:
                if descendant is boundary:
                    break
                if isinstance(descendant, NavigableString) and not isinstance(
                    descendant, Comment
                ):
                    parts.append(str(descendant))
            return _normalize_text(" ".join(parts))

        def claim_component_text(element: Any) -> str:
            if not isinstance(element, Tag) or _assertion_heading_level(element) is not None:
                return raw_claim_component_text(element)
            boundary = first_claim_boundary(element)
            if boundary is not None:
                prefix = claim_component_prefix(element, boundary)
                if prefix:
                    return prefix
            return raw_claim_component_text(element)

        def belongs_to_preboundary_fragment(parent: Tag, element: Any) -> bool:
            boundary = first_claim_boundary(parent)
            if boundary is None or not claim_component_prefix(parent, boundary):
                return False
            if isinstance(element, Tag) and any(
                descendant is boundary for descendant in element.descendants
            ):
                return False
            for descendant in parent.descendants:
                if descendant is element:
                    return True
                if descendant is boundary:
                    return False
            return False

        def is_owned_claim_component(
            element: Any, owner_heading_level: int | None
        ) -> bool:
            if not _group_heading_claims:
                return isinstance(element, Tag) and element.name in paragraph_claim_tags
            if isinstance(element, NavigableString):
                return bool(claim_component_text(element))
            if not isinstance(element, Tag):
                return False
            if element.name in _INDEPENDENT_RECORD_TAGS:
                return False
            nested_record = element.find(_INDEPENDENT_RECORD_TAGS)
            if nested_record is not None:
                boundary = first_claim_boundary(element)
                if boundary is None or not claim_component_prefix(element, boundary):
                    return False
            if not claim_component_text(element):
                return False
            component_heading_level = claim_component_heading_level(element)
            if owner_heading_level is None:
                return component_heading_level is None
            return (
                component_heading_level is None
                or component_heading_level > owner_heading_level
            )

        def is_claim_scope_context(element: Any) -> bool:
            return is_flat_claim_context(element) or (
                _group_heading_claims
                and _assertion_heading_level(element) is not None
            )

        for context_key, local_parts in context_parts.items():
            context = context_elements[context_key]
            local_segment = _normalize_text(" ".join(local_parts))
            owner_segment = local_segment
            if is_claim_scope_context(context):
                scope_context = context
                parent = context.parent
                siblings: list[Any] = []
                while isinstance(parent, Tag):
                    siblings = [
                        child
                        for child in parent.children
                        if isinstance(child, Tag) or claim_component_text(child)
                    ]
                    if parent.name in claim_scope_parent_tags and len(siblings) > 1:
                        if (
                            parent.name in transparent_claim_wrapper_tags
                            and belongs_to_preboundary_fragment(parent, scope_context)
                        ):
                            scope_context = parent
                            parent = parent.parent
                            continue
                        break
                    if (
                        parent.name in _INDEPENDENT_RECORD_TAGS
                        or parent.name == "html"
                    ):
                        siblings = []
                        break
                    scope_context = parent
                    parent = parent.parent
                if siblings:
                    context_index = next(
                        (
                            index
                            for index, sibling in enumerate(siblings)
                            if sibling is scope_context
                        ),
                        None,
                    )
                    if context_index is not None:
                        first = context_index
                        last = context_index
                        heading_level = (
                            claim_component_heading_level(scope_context)
                            if _group_heading_claims
                            else None
                        )
                        if heading_level is not None:
                            while (
                                last + 1 < len(siblings)
                                and is_owned_claim_component(
                                    siblings[last + 1], heading_level
                                )
                            ):
                                next_sibling = siblings[last + 1]
                                if _starts_presentation_field(
                                    claim_component_text(next_sibling)
                                ):
                                    break
                                last += 1
                        else:
                            if not _starts_presentation_field(local_segment):
                                while (
                                    first > 0
                                    and is_owned_claim_component(
                                        siblings[first - 1], None
                                    )
                                ):
                                    first -= 1
                                    if _starts_presentation_field(
                                        claim_component_text(siblings[first])
                                    ):
                                        break
                            while (
                                last + 1 < len(siblings)
                                and is_owned_claim_component(
                                    siblings[last + 1], None
                                )
                                and not _starts_presentation_field(
                                    claim_component_text(siblings[last + 1])
                                )
                            ):
                                last += 1
                        if first != last:
                            owner_segment = _normalize_text(
                                " ".join(
                                    claim_component_text(sibling)
                                    for sibling in siblings[first : last + 1]
                                )
                            )
            local_context_is_owned_by_child = (
                isinstance(context, Tag)
                and context.name in claim_scope_parent_tags
                and is_claim_scope_context(context)
                and any(
                    isinstance(child, Tag)
                    and any(
                        id(candidate) in assertion_context_ids
                        for candidate in (child, *child.find_all(True))
                    )
                    and is_owned_claim_component(child, None)
                    and not _starts_presentation_field(claim_component_text(child))
                    for child in context.children
                )
            )
            if local_segment and owner_segment and not local_context_is_owned_by_child:
                assertion_occurrences.append((local_segment, owner_segment))
        assertion_segments = tuple(
            dict.fromkeys(owner for _, owner in assertion_occurrences)
        )
        attribute_parts: list[str] = []
        raw_action_urls: set[str] = set()
        raw_action_pairs: set[tuple[str, str]] = set()
        raw_action_content_pairs: set[tuple[str, str]] = set()
        raw_image_urls: set[str] = set(preserved_image_urls)
        raw_image_pairs: set[tuple[str, str]] = set()
        raw_logo_urls: set[str] = set()
        identity_parts: list[str] = []
        metadata_identity_parts: list[str] = []
        title_parts: list[str] = []
        h1_parts: list[str] = []
        heading_parts: list[str] = []
        email_values: list[str] = list(assertion_segments)
        phone_values: list[str] = list(assertion_segments)
        action_labels: set[str] = set()

        for element in soup.find_all("title", limit=MAX_ITEMS):
            title_parts.append(element.get_text(" ", strip=True))
        for element in soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6"], limit=MAX_ITEMS
        ):
            heading_text = element.get_text(" ", strip=True)
            heading_parts.append(heading_text)
            if element.name == "h1":
                h1_parts.append(heading_text)
        metadata_image_groups: dict[str, list[str]] = {}
        for meta in soup.find_all("meta", limit=MAX_ITEMS):
            property_name = str(
                meta.get("property") or meta.get("name") or ""
            ).casefold()
            if property_name in {"application-name", "og:site_name"}:
                metadata_identity_parts.extend(_attribute_values(meta.get("content")))
            metadata_family = property_name.partition(":")[0]
            metadata_values = tuple(_attribute_values(meta.get("content")))
            if property_name in _IMAGE_METADATA_ROOT_PROPERTIES:
                metadata_image_groups[metadata_family] = list(metadata_values)
                raw_image_urls.update(metadata_values)
            elif property_name in _IMAGE_METADATA_URL_PROPERTIES:
                metadata_image_groups.setdefault(metadata_family, []).extend(
                    metadata_values
                )
                raw_image_urls.update(metadata_values)
            elif property_name in _IMAGE_METADATA_ALT_PROPERTIES:
                raw_image_pairs.update(
                    (image_url, alt)
                    for image_url in metadata_image_groups.get(metadata_family, ())
                    for alt in metadata_values
                )

        for element in soup.find_all(True):
            element_action_labels: tuple[str, ...] = ()
            element_image_urls: set[str] = set()
            action_is_available = is_source_action_available(element)
            is_image_resource = element.name == "img" or (
                element.name == "source" and element.find_parent("picture") is not None
            )
            if action_is_available and is_labelled_action_element(element):
                element_action_labels = tuple(
                    normalized
                    for label in action_element_labels(element, soup)
                    if (normalized := _normalize_text(label))
                )
            if element_action_labels:
                action_labels.update(element_action_labels)
                if element.name in {"a", "area"}:
                    for attribute in _ACTION_URL_ATTRIBUTES:
                        raw_destination = element.get(attribute)
                        if isinstance(raw_destination, str):
                            raw_action_pairs.update(
                                (label, raw_destination)
                                for label in element_action_labels
                            )
                            raw_action_content_pairs.update(
                                (owned_text, raw_destination)
                                for candidate in (
                                    element,
                                    *element.find_all(True, limit=MAX_ITEMS),
                                )
                                if (
                                    owned_text := _normalize_text(
                                        source_visible_text(candidate)
                                    )
                                )
                            )
            for name, raw_value in element.attrs.items():
                for value in _attribute_values(raw_value):
                    if name in _TEXT_ATTRIBUTES:
                        attribute_parts.append(value)
                    is_action_url = (
                        action_is_available
                        and name in _ACTION_URL_ATTRIBUTES
                        and element.name in {"a", "area"}
                    )
                    if is_action_url:
                        raw_action_urls.add(value)
                        contact = _contact_destination(value)
                        if contact is not None:
                            scheme, destination = contact
                            assertion_context = element
                            while (
                                assertion_context is not None
                                and assertion_context.name
                                not in _ASSERTION_CONTEXT_TAGS
                            ):
                                assertion_context = assertion_context.parent
                            contextual_destination = _contact_destination_context(
                                assertion_context,
                                element,
                                destination,
                            )
                            if scheme == "mailto":
                                email_values.append(contextual_destination)
                            else:
                                phone_values.append(contextual_destination)
                    if is_image_resource and name in _IMAGE_ATTRIBUTES:
                        raw_image_urls.add(value)
                        element_image_urls.add(value)
                    if is_image_resource and name == "srcset":
                        srcset_urls = _srcset_urls(value)
                        raw_image_urls.update(srcset_urls)
                        element_image_urls.update(srcset_urls)
            style = element.get("style")
            if isinstance(style, str):
                raw_image_urls.update(css_image_urls(style))
            alt = element.get("alt")
            if element.name == "img" and isinstance(alt, str) and alt.strip():
                picture = element.find_parent("picture")
                if picture is not None:
                    for source in picture.find_all("source", recursive=False):
                        for raw_srcset in _attribute_values(source.get("srcset")):
                            element_image_urls.update(_srcset_urls(raw_srcset))
                raw_image_pairs.update((url, alt) for url in element_image_urls)
            if element.name == "img" and _is_source_logo(element):
                raw_logo_urls.update(element_image_urls)
                identity_parts.extend(_attribute_values(element.get("alt")))
                identity_parts.extend(_attribute_values(element.get("title")))
            if element.name != "img" and _element_has_logo_marker(element):
                identity_parts.extend(_marked_identity_text_parts(element, soup))

        explicit_identity_seeds = tuple(
            segment
            for part in (*metadata_identity_parts, *identity_parts)
            if (segment := _normalize_text(part))
        )
        title_identity_parts: list[str] = []
        has_ambiguous_title_identity = False
        for title in title_parts:
            components = tuple(
                component
                for raw_component in _TITLE_SEPARATOR_PATTERN.split(title)
                if (component := _normalize_text(raw_component))
                and component not in _GENERIC_PAGE_IDENTITY_PARTS
            )
            if len(components) == 1:
                if not explicit_identity_seeds or any(
                    _identity_candidates_agree(seed, components[0])
                    for seed in explicit_identity_seeds
                ):
                    title_identity_parts.extend(components)
                continue
            corroborated = tuple(
                component
                for component in components
                if any(
                    _identity_candidates_agree(seed, component)
                    for seed in explicit_identity_seeds
                )
            )
            if len(corroborated) == 1:
                title_identity_parts.extend(corroborated)
            else:
                has_ambiguous_title_identity = True

        candidate_h1_parts = [
            part
            for part in h1_parts
            if _normalize_text(part) not in _GENERIC_PAGE_IDENTITY_PARTS
        ]
        if candidate_h1_parts:
            identity_seeds = tuple(
                segment
                for part in (
                    *metadata_identity_parts,
                    *identity_parts,
                    *title_identity_parts,
                )
                if (segment := _normalize_text(part))
            )
            corroborated_h1_parts = [
                part
                for part in candidate_h1_parts
                if (normalized := _normalize_text(part))
                and any(
                    _identity_candidates_agree(seed, normalized)
                    for seed in identity_seeds
                )
            ]
            h1_identity_parts = (
                corroborated_h1_parts
                if identity_seeds
                else (
                    []
                    if has_ambiguous_title_identity
                    else list(_select_supported_identity_parts(candidate_h1_parts))
                )
            )
        else:
            h1_identity_parts = []

        admitted_identity_parts = _select_supported_identity_parts(
            metadata_identity_parts,
            identity_parts,
            title_identity_parts,
            h1_identity_parts,
        )

        def resolved(values: Iterable[str]) -> frozenset[str]:
            admitted: set[str] = set()
            for raw in values:
                candidate = html.unescape(raw).strip()
                if not candidate:
                    continue
                admitted.add(candidate)
                if resolution_base_url:
                    admitted.add(urljoin(resolution_base_url, candidate))
            return frozenset(admitted)

        data_controls = tuple(
            control
            for control in soup.find_all(
                ["input", "select", "textarea"], limit=MAX_ITEMS
            )
            if is_source_action_available(control)
            and not (
                control.name == "input"
                and str(control.get("type") or "text").casefold()
                in _NON_DATA_INPUT_TYPES
            )
        )
        forms: list[SourceFormEvidence] = []
        for form in soup.find_all("form", limit=MAX_ITEMS):
            if not is_source_action_available(form):
                continue
            labels = tuple(
                label
                for control in data_controls
                if _source_form_owner(control, soup) is form
                if (label := _source_form_control_label(control, soup))
            )
            action_url = _source_form_action_url(
                form,
                soup,
                resolution_base_url=resolution_base_url,
                source_url=source_url,
            )
            forms.append(SourceFormEvidence(labels, action_url))

        form_control_labels: list[str] = []
        for control in data_controls:
            normalized_label = _source_form_control_label(control, soup)
            if normalized_label:
                form_control_labels.append(normalized_label)

        emails: set[str] = set()
        for raw_segment in email_values:
            segment = _normalize_text(raw_segment)
            for match in _EMAIL_PATTERN.finditer(segment):
                if _contact_occurrence_is_negated(
                    segment, match.start(), len(match.group(0))
                ):
                    continue
                if _occurrence_is_nonassertive(
                    segment, match.start(), len(match.group(0))
                ):
                    continue
                emails.add(match.group(0).casefold())
        phones: set[str] = set()
        for raw_segment in phone_values:
            segment = _normalize_text(raw_segment)
            for match in _PHONE_PATTERN.finditer(segment):
                if _contact_occurrence_is_negated(
                    segment, match.start(), len(match.group(0))
                ):
                    continue
                if _contact_occurrence_is_noncallable(
                    segment,
                    match.start(),
                    len(match.group(0)),
                ):
                    continue
                if _occurrence_is_nonassertive(
                    segment, match.start(), len(match.group(0))
                ):
                    continue
                phones.update(_phone_variants(match.group(0)))

        attribute_segments = tuple(
            dict.fromkeys(
                segment
                for part in attribute_parts
                if (segment := _normalize_text(part))
            )
        )
        records = (
            tuple(
                cls.from_html(
                    fragment,
                    source_url,
                    _include_records=False,
                    _include_content_sections=False,
                    _include_section_targets=False,
                    _group_heading_claims=False,
                    _resolution_base_url=resolution_base_url,
                )
                for fragment in _record_fragments(soup)
            )
            if _include_records
            else ()
        )
        content_sections = (
            tuple(
                cls.from_html(
                    fragment,
                    source_url,
                    _include_content_sections=False,
                    _include_section_targets=False,
                    _group_heading_claims=False,
                    _resolution_base_url=resolution_base_url,
                )
                for fragment in _content_section_fragments(soup)
            )
            if _include_content_sections
            else ()
        )
        section_targets = (
            tuple(
                (
                    f"#{element_id.strip()}",
                    cls.from_html(
                        _heading_owned_fragment(element),
                        source_url,
                        _include_section_targets=False,
                        _group_heading_claims=False,
                        _resolution_base_url=resolution_base_url,
                    ),
                )
                for element in soup.find_all(id=True, limit=MAX_ITEMS)
                if isinstance((element_id := element.get("id")), str)
                and element_id.strip()
            )
            if _include_section_targets
            else ()
        )
        return cls(
            text_segments=tuple(dict.fromkeys(assertion_segments + attribute_segments)),
            assertion_segments=assertion_segments,
            assertion_occurrences=tuple(assertion_occurrences),
            identity_segments=tuple(
                dict.fromkeys(
                    segment
                    for part in admitted_identity_parts
                    if (segment := _normalize_text(part))
                )
            ),
            identity_exact_segments=tuple(
                dict.fromkeys(
                    variant
                    for part in admitted_identity_parts
                    for variant in _identity_canonical_variants(part)
                )
            ),
            heading_segments=tuple(
                dict.fromkeys(
                    segment
                    for part in heading_parts
                    if (segment := _normalize_text(part))
                )
            ),
            action_labels=frozenset(action_labels),
            action_pairs=frozenset(
                (label, destination)
                for label, raw_url in raw_action_pairs
                for destination in resolved((raw_url,))
            ),
            action_content_pairs=frozenset(
                (content, destination)
                for content, raw_url in raw_action_content_pairs
                for destination in resolved((raw_url,))
            ),
            action_urls=resolved(raw_action_urls),
            image_urls=resolved(raw_image_urls),
            image_pairs=frozenset(
                (destination, _normalize_text(alt))
                for raw_url, alt in raw_image_pairs
                for destination in resolved((raw_url,))
            ),
            logo_urls=resolved(raw_logo_urls),
            form_control_labels=tuple(form_control_labels),
            emails=frozenset(emails),
            phones=frozenset(phones),
            resolution_base_url=resolution_base_url,
            forms=tuple(forms),
            records=records,
            content_sections=content_sections,
            section_targets=section_targets,
        )

    def require_text(
        self,
        path: str,
        value: Any,
        *,
        asserted: bool = False,
        presentation_labels: tuple[str, ...] = (),
    ) -> None:
        if value is None:
            return
        normalized = _normalize_text(value)
        if not normalized:
            raise SiteExtractionError(f"{path} is not grounded in source text.")
        found = False
        source_occurrences = (
            self.assertion_occurrences
            if asserted
            else tuple((segment, segment) for segment in self.text_segments)
        )
        normalized_labels = tuple(
            _normalize_text(label) for label in presentation_labels
        )
        for local_segment, owner_segment in source_occurrences:
            source_text = owner_segment
            search_text = local_segment if normalized_labels else source_text
            local_offset = source_text.find(local_segment)
            if normalized_labels and local_offset < 0:
                continue
            search_occurrences = tuple(_phrase_occurrences(search_text, normalized))
            if search_occurrences:
                found = True
            owner_has_presentation_label = False
            if normalized_labels and local_segment != owner_segment:
                owner_prefix = source_text[:local_offset].strip()
                owner_suffix = source_text[
                    local_offset + len(local_segment) :
                ].strip()
                normalized_owner_prefix = re.sub(
                    r"\s*[:\-–—]\s*$", "", owner_prefix
                )
                if (
                    owner_suffix
                    or normalized_owner_prefix not in normalized_labels
                ):
                    continue
                owner_has_presentation_label = True
            for search_index in search_occurrences:
                index = (
                    local_offset + search_index
                    if normalized_labels
                    else search_index
                )
                if _occurrence_is_negated(source_text, index, len(normalized)):
                    continue
                if (
                    asserted
                    and not normalized_labels
                    and local_segment != owner_segment
                    and normalized != owner_segment
                ):
                    continue
                if asserted:
                    assertion_text = source_text
                    assertion_index = index
                    if _occurrence_has_presentation_label(
                        local_segment,
                        search_index,
                        normalized_labels,
                    ) or owner_has_presentation_label:
                        assertion_text = source_text[index:]
                        assertion_index = 0
                    if _occurrence_is_nonassertive(
                        assertion_text,
                        assertion_index,
                        len(normalized),
                        strict_claim=True,
                    ):
                        continue
                return
        if found:
            raise SiteExtractionError(
                f"{path} drops or reverses source assertion context."
            )
        raise SiteExtractionError(f"{path} is not grounded in source text.")

    def require_exact_text(self, path: str, value: Any) -> None:
        if value is None:
            return
        normalized = _normalize_text(value)
        if not normalized or normalized not in self.text_segments:
            raise SiteExtractionError(
                f"{path} is not the complete text of one source context."
            )

    def require_identity(self, path: str, value: Any) -> None:
        if value is None:
            return
        normalized = _normalize_text(value)
        if not normalized:
            raise SiteExtractionError(f"{path} is not grounded in source identity.")
        if (
            normalized in self.identity_exact_segments
            or normalized in self.identity_segments
        ):
            return
        found = False
        for source_text in self.identity_segments:
            for index in _phrase_occurrences(source_text, normalized):
                found = True
                if _occurrence_is_negated(source_text, index, len(normalized)):
                    continue
                if _occurrence_is_nonassertive(source_text, index, len(normalized)):
                    continue
        if found:
            raise SiteExtractionError(f"{path} drops source identity context.")
        raise SiteExtractionError(f"{path} is not grounded in source identity.")

    def require_heading(self, path: str, value: Any) -> None:
        if value is None:
            return
        normalized = _normalize_text(value)
        if not normalized:
            raise SiteExtractionError(f"{path} is not grounded in a source heading.")
        for source_text in self.heading_segments:
            for index in _phrase_occurrences(source_text, normalized):
                if _occurrence_is_negated(source_text, index, len(normalized)):
                    continue
                if _occurrence_is_nonassertive(source_text, index, len(normalized)):
                    continue
                return
        raise SiteExtractionError(f"{path} is not grounded in a source heading.")

    def require_action_label(self, path: str, value: Any) -> None:
        if value is None:
            return
        if _normalize_text(value) not in self.action_labels:
            raise SiteExtractionError(
                f"{path} is not grounded in a source action label."
            )

    def require_action(self, path: str, label: Any, url: Any) -> None:
        normalized_label = _normalize_text(label) if isinstance(label, str) else ""
        normalized_url = html.unescape(url).strip() if isinstance(url, str) else ""
        if (normalized_label, normalized_url) not in self.action_pairs:
            raise SiteExtractionError(
                f"{path}.url and label are not grounded in one source action."
            )

    def require_action_content(self, path: str, content: Any, url: Any) -> None:
        normalized_content = (
            _normalize_text(content) if isinstance(content, str) else ""
        )
        normalized_url = html.unescape(url).strip() if isinstance(url, str) else ""
        if (normalized_content, normalized_url) in self.action_content_pairs:
            return
        if any(
            destination == normalized_url and label in _RECORD_ITEM_LINK_LABELS
            for label, destination in self.action_pairs
        ):
            return
        raise SiteExtractionError(
            f"{path}.url and content are not grounded in one source action."
        )

    def admit_social_platform(self, path: str, platform: Any, url: Any) -> str:
        self.require_url(f"{path}.url", url)
        normalized_url = html.unescape(url).strip() if isinstance(url, str) else ""
        hostname = (urlsplit(normalized_url).hostname or "").casefold()
        for domain, canonical in _SOCIAL_HOST_PLATFORMS:
            if hostname == domain or hostname.endswith(f".{domain}"):
                self.require_action(path, canonical, url)
                return canonical
        self.require_action(path, platform, url)
        return platform

    def require_section_target(self, path: str, anchor: Any) -> "SourceEvidence":
        normalized = html.unescape(anchor).strip() if isinstance(anchor, str) else ""
        fragment = unquote(urlsplit(normalized).fragment).strip()
        target_anchor = f"#{fragment}" if fragment else normalized
        for candidate, target_evidence in self.section_targets:
            if candidate == target_anchor:
                return target_evidence
        raise SiteExtractionError(f"{path} is not grounded in a source section target.")

    def require_email(self, path: str, value: Any) -> None:
        if value is None:
            return
        if value.strip().casefold() not in self.emails:
            raise SiteExtractionError(f"{path} is not grounded in a source email.")

    def require_phone(self, path: str, value: Any) -> None:
        if value is None:
            return
        if not (_phone_variants(value) & self.phones):
            raise SiteExtractionError(f"{path} is not grounded in a source phone.")

    def require_url(self, path: str, value: Any, *, image: bool = False) -> None:
        if value is None:
            return
        allowed = self.image_urls if image else self.action_urls
        if html.unescape(value).strip() not in allowed:
            kind = "image URL" if image else "URL"
            raise SiteExtractionError(f"{path} is not grounded in a source {kind}.")

    def require_image(self, path: str, url: Any, alt: Any) -> None:
        self.require_url(f"{path}.url", url, image=True)
        if alt is None:
            return
        pair = (html.unescape(url).strip(), _normalize_text(alt))
        if pair not in self.image_pairs:
            raise SiteExtractionError(
                f"{path}.alt is not grounded on the same source image as its URL."
            )

    def require_logo(self, path: str, value: Any) -> None:
        if value is None:
            return
        if html.unescape(value).strip() not in self.logo_urls:
            raise SiteExtractionError(
                f"{path} is not grounded in a source image identified as a logo."
            )

    def require_form_fields(self, path: str, values: Any) -> str | None:
        normalized_values = tuple(
            _normalize_text(value) if isinstance(value, str) else ""
            for value in values or []
        )
        if not normalized_values:
            return None

        matches: list[SourceFormEvidence] = []
        for form in self.forms:
            remaining_labels = list(form.control_labels)
            for normalized in normalized_values:
                if not normalized or normalized not in remaining_labels:
                    break
                remaining_labels.remove(normalized)
            else:
                matches.append(form)

        if not matches:
            raise SiteExtractionError(
                f"{path} are not complete labels of distinct controls owned by one "
                "source form."
            )
        actions = tuple(
            dict.fromkeys(form.action_url for form in matches if form.action_url)
        )
        if len(actions) != 1:
            raise SiteExtractionError(
                f"{path} do not identify one source-owned form endpoint."
            )
        return actions[0]


def _validation_error(validator: Draft202012Validator, document: Any) -> str | None:
    try:
        encoded = json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        return f"Extraction is not bounded JSON: {exc}"
    if len(encoded) > MAX_ANALYSIS_BYTES:
        return "Extraction exceeds the local analysis size limit."
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if not errors:
        return None
    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path) or "root"
    return f"Extraction schema rejected {path}: {error.message}"


def _require_contact(evidence: SourceEvidence, path: str, contact: Any) -> None:
    if not isinstance(contact, dict):
        return
    evidence.require_phone(f"{path}.phone", contact.get("phone"))
    evidence.require_email(f"{path}.email", contact.get("email"))
    evidence.require_text(
        f"{path}.address",
        contact.get("address"),
        asserted=True,
        presentation_labels=("address", "street address"),
    )
    for index, address in enumerate(contact.get("addresses") or []):
        evidence.require_text(
            f"{path}.addresses[{index}]",
            address,
            asserted=True,
            presentation_labels=("address", "street address"),
        )
    evidence.require_text(
        f"{path}.hours",
        contact.get("hours"),
        asserted=True,
        presentation_labels=("hours", "business hours", "office hours"),
    )


def _require_content_items(
    evidence: SourceEvidence,
    path: str,
    items: Any,
    *,
    verify_tag: bool = True,
    allow_nonassertive_title: bool = False,
) -> None:
    for index, item in enumerate(items or []):
        item_path = f"{path}[{index}]"
        source_fields = (
            "title",
            "description",
            "url",
            "image_url",
            "date",
            "meta",
            *(("tag",) if verify_tag else ()),
        )
        present_fields = [
            field for field in source_fields if item.get(field) is not None
        ]
        if not present_fields:
            raise SiteExtractionError(f"{item_path} contains no source-owned content.")

        def require_fields(container: SourceEvidence) -> None:
            if allow_nonassertive_title:
                container.require_exact_text(
                    f"{item_path}.title",
                    item.get("title"),
                )
            else:
                container.require_text(
                    f"{item_path}.title",
                    item.get("title"),
                    asserted=True,
                )
            container.require_text(
                f"{item_path}.description", item.get("description"), asserted=True
            )
            container.require_url(f"{item_path}.url", item.get("url"))
            if item.get("title") is not None and item.get("url") is not None:
                container.require_action_content(
                    item_path,
                    item.get("title"),
                    item.get("url"),
                )
            container.require_url(
                f"{item_path}.image_url", item.get("image_url"), image=True
            )
            if verify_tag:
                container.require_text(
                    f"{item_path}.tag", item.get("tag"), asserted=True
                )
            container.require_text(f"{item_path}.date", item.get("date"), asserted=True)
            container.require_text(f"{item_path}.meta", item.get("meta"), asserted=True)

        if len(present_fields) == 1:
            require_fields(evidence)
            continue
        for record in evidence.records:
            try:
                require_fields(record)
            except SiteExtractionError:
                continue
            break
        else:
            raise SiteExtractionError(
                f"{item_path} fields are not grounded in one source container."
            )


def _require_site_facts(
    document: dict, evidence: SourceEvidence, source_url: str | None
) -> None:
    site = document["site"]
    evidence.require_identity("site.name", site["name"])
    evidence.require_text("site.tagline", site.get("tagline"), asserted=True)
    evidence.require_text(
        "site.location",
        site.get("location"),
        asserted=True,
        presentation_labels=("location",),
    )
    _require_contact(evidence, "site.contact", site.get("contact"))

    brand = document.get("brand") or {}
    evidence.require_logo("brand.logo_url", brand.get("logo_url"))

    for index, item in enumerate(document.get("nav") or []):
        evidence.require_action(f"nav[{index}]", item["label"], item["url"])
    cta = document.get("cta") or {}
    cta_label = cta.get("label")
    cta_url = cta.get("url")
    if (cta_label is None) != (cta_url is None):
        raise SiteExtractionError(
            "cta.label and cta.url must both be source-owned or both be null."
        )
    if cta_label is not None:
        evidence.require_action("cta", cta_label, cta_url)

    for index, section in enumerate(document.get("sections") or []):
        path = f"sections[{index}]"
        headline = section.get("headline")
        items = section.get("items") or []

        def require_section(section_evidence: SourceEvidence) -> None:
            section_evidence.require_text(f"{path}.headline", headline, asserted=True)
            _require_content_items(
                section_evidence,
                f"{path}.items",
                items,
                allow_nonassertive_title=section.get("type") == "faq",
            )

        if headline is not None and items:
            for content_section in evidence.content_sections:
                try:
                    require_section(content_section)
                except SiteExtractionError:
                    continue
                break
            else:
                raise SiteExtractionError(
                    f"{path} headline and items are not grounded in one source section."
                )
        else:
            require_section(evidence)

    for index, image in enumerate(document.get("images") or []):
        path = f"images[{index}]"
        evidence.require_image(path, image["url"], image.get("alt"))
        if _normalize_text(image.get("context") or "") == "logo":
            evidence.require_logo(f"{path}.url", image["url"])
    for index, social in enumerate(document.get("social") or []):
        social["platform"] = evidence.admit_social_platform(
            f"social[{index}]", social["platform"], social["url"]
        )
    for index, item in enumerate(document.get("footer_links") or []):
        evidence.require_action(f"footer_links[{index}]", item["label"], item["url"])
    for index, page in enumerate(document.get("pages_to_fetch") or []):
        evidence.require_action(f"pages_to_fetch[{index}]", page["label"], page["url"])
        resolved_url = _resolved_distinct_fetchable_page(
            page["url"],
            source_url,
            evidence.resolution_base_url,
        )
        page["fetchable"] = resolved_url is not None
        if resolved_url is not None:
            page["url"] = resolved_url

    for index, section in enumerate(document.get("single_page_sections") or []):
        path = f"single_page_sections[{index}]"
        anchor = section.get("anchor")
        content = section.get("content") or {}

        def require_content(section_evidence: SourceEvidence) -> str | None:
            section_evidence.require_text(
                f"{path}.content.headline", content.get("headline"), asserted=True
            )
            section_evidence.require_text(
                f"{path}.content.body_text", content.get("body_text"), asserted=True
            )
            _require_content_items(
                section_evidence,
                f"{path}.content.items",
                content.get("items"),
                allow_nonassertive_title=section.get("page_type") == "faq",
            )
            form_action = section_evidence.require_form_fields(
                f"{path}.content.form_fields", content.get("form_fields")
            )
            _require_contact(
                section_evidence,
                f"{path}.content.contact_info",
                content.get("contact_info"),
            )
            return form_action

        if anchor is not None:
            evidence.require_action(path, section["nav_label"], anchor)
            section_evidence = evidence.require_section_target(f"{path}.anchor", anchor)
            form_action = require_content(section_evidence)
            if form_action is not None:
                content["form_action"] = form_action
            continue

        evidence.require_action_label(f"{path}.nav_label", section["nav_label"])
        if not content:
            raise SiteExtractionError(
                f"{path} has no anchor or content that can be scoped to a source section."
            )
        for section_evidence in evidence.content_sections:
            try:
                section_evidence.require_heading(
                    f"{path}.nav_label", section["nav_label"]
                )
                form_action = require_content(section_evidence)
            except SiteExtractionError:
                continue
            break
        else:
            raise SiteExtractionError(
                f"{path} navigation and content are not grounded in one source section."
            )
        if form_action is not None:
            content["form_action"] = form_action

    conversion = document.get("conversion_profile") or {}
    evidence.require_phone("conversion_profile.phone", conversion.get("phone"))
    for index, label in enumerate(conversion.get("existing_ctas") or []):
        evidence.require_action_label(
            f"conversion_profile.existing_ctas[{index}]", label
        )
    trust = conversion.get("trust_signals") or {}
    evidence.require_text(
        "conversion_profile.trust_signals.review_summary",
        trust.get("review_summary"),
        asserted=True,
    )
    for field in ("certifications", "awards", "social_proof_lines"):
        for index, value in enumerate(trust.get(field) or []):
            evidence.require_text(
                f"conversion_profile.trust_signals.{field}[{index}]",
                value,
                asserted=True,
            )


def _canonicalize_admitted_image_urls(document: dict, base_url: str | None) -> None:
    """Resolve every admitted image resource against its source document."""
    if not base_url:
        return

    def visit(value: Any, *, image_record: bool = False) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if isinstance(nested, str) and (
                    key in {"image_url", "logo_url"}
                    or (image_record and key == "url")
                ):
                    value[key] = urljoin(base_url, html.unescape(nested).strip())
                elif key == "images" and isinstance(nested, list):
                    for image in nested:
                        visit(image, image_record=True)
                else:
                    visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested, image_record=image_record)

    visit(document)


def validate_site_analysis(
    document: Any, source_html: str, source_url: str | None = None
) -> dict:
    """Admit one homepage analysis only when its source-owned facts are grounded."""
    admitted = copy.deepcopy(document)
    error = _validation_error(_ANALYSIS_VALIDATOR, admitted)
    if error:
        raise SiteExtractionError(error)
    evidence = SourceEvidence.from_html(source_html, source_url)
    _require_site_facts(admitted, evidence, source_url)
    _canonicalize_admitted_image_urls(admitted, evidence.resolution_base_url)
    return admitted


def validate_enrichment_result(
    document: Any,
    *,
    page_type: str,
    source_html: str,
    source_url: str,
) -> dict:
    """Admit one optional enrichment chunk and assign code-owned provenance."""
    if not isinstance(document, dict):
        raise SiteExtractionError("Enrichment must contain one object.")
    admitted = copy.deepcopy(document)
    admitted["source_url"] = source_url
    validator = (
        _CONTACT_ENRICHMENT_VALIDATOR
        if page_type == "contact"
        else _CONTENT_ENRICHMENT_VALIDATOR
    )
    error = _validation_error(validator, admitted)
    if error:
        raise SiteExtractionError(error)
    evidence = SourceEvidence.from_html(source_html, source_url)

    if page_type == "contact":
        form_action = evidence.require_form_fields(
            "form_fields", admitted.get("form_fields")
        )
        _require_contact(evidence, "contact_info", admitted.get("contact_info"))
        contact_info = admitted.get("contact_info") or {}
        has_contact_info = any(
            contact_info.get(field)
            for field in ("phone", "email", "address", "addresses", "hours")
        )
        if not (admitted.get("form_fields") or has_contact_info):
            raise SiteExtractionError("Contact enrichment contains no source content.")
        if form_action is not None:
            admitted["form_action"] = form_action
        return admitted

    expected_type = {
        "services": "services",
        "single-service": "services",
        "team": "team",
        "about": "misc",
        "faq": "misc",
    }.get(page_type)
    if expected_type is None or admitted["type"] != expected_type:
        raise SiteExtractionError(
            "Enrichment type does not match the page type selected by code."
        )
    if not admitted["items"]:
        raise SiteExtractionError("Content enrichment contains no source items.")
    if page_type == "faq":
        admitted["headline"] = "FAQ"
    derived_tag = (
        "about" if page_type == "about" else "faq" if page_type == "faq" else None
    )
    if derived_tag is not None:
        for item in admitted["items"]:
            if item.get("tag") != derived_tag:
                raise SiteExtractionError(
                    "Enrichment item tag does not match the page type selected by code."
                )
    if page_type == "faq":
        _require_content_items(
            evidence,
            "items",
            admitted["items"],
            verify_tag=False,
            allow_nonassertive_title=True,
        )
    else:
        for section_evidence in evidence.content_sections:
            try:
                section_evidence.require_text(
                    "headline", admitted.get("headline"), asserted=True
                )
                _require_content_items(
                    section_evidence,
                    "items",
                    admitted["items"],
                    verify_tag=derived_tag is None,
                    allow_nonassertive_title=False,
                )
            except SiteExtractionError:
                continue
            break
        else:
            raise SiteExtractionError(
                "Content enrichment headline and items must share one source section."
            )
    _canonicalize_admitted_image_urls(admitted, evidence.resolution_base_url)
    return admitted
