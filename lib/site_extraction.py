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


TEXT = _string()
NULLABLE_TEXT = _string(nullable=True)
URL = _string(max_length=8_192)
NULLABLE_URL = _string(nullable=True, max_length=8_192)

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
                "type": TEXT,
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
                "color_mode": TEXT,
                "fonts": _object({"display": NULLABLE_TEXT, "body": NULLABLE_TEXT}),
                "style_notes": _array(TEXT),
            }
        ),
        "nav": _array(_object({"label": TEXT, "url": URL}, required=("label", "url"))),
        "cta": _object({"label": NULLABLE_TEXT, "url": NULLABLE_URL}),
        "sections": _array(
            _object(
                {
                    "type": TEXT,
                    "headline": NULLABLE_TEXT,
                    "items": _array(CONTENT_ITEM_SCHEMA),
                },
                required=("type",),
            )
        ),
        "images": _array(
            _object(
                {"url": URL, "alt": NULLABLE_TEXT, "context": TEXT},
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
                    "page_type": TEXT,
                    "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                    "fetchable": {"type": "boolean"},
                },
                required=("label", "url", "page_type", "priority", "fetchable"),
            )
        ),
        "site_structure": TEXT,
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
                "urgency_type": TEXT,
                "primary_goal": TEXT,
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
                "hero_type": TEXT,
                "above_fold_form": {"type": "boolean"},
                "section_sequence": _array(TEXT),
                "footer_layout": TEXT,
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
        "type": TEXT,
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
_ACTION_URL_ATTRIBUTES = {"href"}
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
_IGNORED_TEXT_TAGS = {"noscript", "script", "style", "template"}
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
_CSS_URL_PATTERN = re.compile(r"url\(\s*['\"]?([^)'\"\s]+)", re.I)
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


def _normalize_text(value: str) -> str:
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", decoded)
    return " ".join(normalized.split()).casefold()


def _phone_variants(value: str) -> set[str]:
    digits = "".join(character for character in value if character.isdigit())
    variants = {digits} if len(digits) >= 7 else set()
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
    if strict_claim and _preceding_clause_scopes_claim(preceding_words):
        return True
    if not strict_claim and _words_contain_scope_qualifier(preceding_words):
        return True
    return _words_contain_scope_qualifier(following_words)


def _contact_occurrence_is_negated(text: str, start: int, length: int) -> bool:
    without_affirmative_idiom = _AFFIRMATIVE_CONTACT_NEGATION_PATTERN.sub(
        lambda match: " " * len(match.group(0)),
        text,
    )
    return _occurrence_is_negated(without_affirmative_idiom, start, length)


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
            parts.append(destination)
        if isinstance(node, Comment):
            continue
        if isinstance(node, str):
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


def _is_distinct_fetchable_page(value: Any, source_url: str | None) -> bool:
    if not isinstance(value, str) or not value.strip() or not source_url:
        return False
    source = urlsplit(source_url)
    destination = urlsplit(urljoin(source_url, html.unescape(value).strip()))
    if (
        source.scheme.casefold() not in {"http", "https"}
        or destination.scheme.casefold() not in {"http", "https"}
        or not source.hostname
        or not destination.hostname
    ):
        return False

    if not same_site_origin(source_url, destination.geturl()):
        return False
    return (destination.path or "/", destination.query) != (
        source.path or "/",
        source.query,
    )


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
    elif tag_name == "input" and str(element.get("type") or "").casefold() == "image":
        value = element.get("alt") or element.get("value")
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
) -> str:
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
            parts.append(_source_accessible_text(child, root, active_references))
    return " ".join(" ".join(part for part in parts if part).split())


def source_accessible_name(
    element: Tag,
    root: BeautifulSoup | Tag,
) -> str:
    """Return one recursive browser-facing name for a source element."""
    return _source_accessible_text(element, root, frozenset())


def is_source_semantic_element(element: Any) -> bool:
    """Return whether an element is outside browser-inert source containers."""
    if getattr(element, "name", None) in _IGNORED_TEXT_TAGS:
        return False
    return not any(
        getattr(ancestor, "name", None) in _IGNORED_TEXT_TAGS
        for ancestor in getattr(element, "parents", ())
    )


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


def is_labelled_action_element(element: Any) -> bool:
    """Return whether one DOM element presents a browser action label."""
    tag_name = str(getattr(element, "name", "") or "").casefold()
    roles = str(element.get("role") or "").casefold().split()
    if tag_name in {"a", "area"}:
        return element.has_attr("href")
    if tag_name == "button" or any(role in {"button", "link"} for role in roles):
        return True
    return tag_name == "input" and (
        str(element.get("type") or "").casefold() in _ACTION_INPUT_TYPES
    )


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


def _heading_owned_fragment(
    heading: Any,
    *,
    stop_at_record_containers: bool = False,
) -> str:
    match = _HEADING_TAG_PATTERN.fullmatch(getattr(heading, "name", "") or "")
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
            _HEADING_TAG_PATTERN.fullmatch(sibling_name)
            if isinstance(sibling_name, str)
            else None
        )
        if sibling_heading is None and sibling_name is not None:
            nested_heading = sibling.find(_HEADING_TAG_PATTERN)
            sibling_heading = (
                _HEADING_TAG_PATTERN.fullmatch(nested_heading.name or "")
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
class SourceEvidence:
    text_segments: tuple[str, ...]
    assertion_segments: tuple[str, ...]
    identity_segments: tuple[str, ...]
    identity_exact_segments: tuple[str, ...]
    heading_segments: tuple[str, ...]
    action_labels: frozenset[str]
    action_pairs: frozenset[tuple[str, str]]
    action_urls: frozenset[str]
    image_urls: frozenset[str]
    image_pairs: frozenset[tuple[str, str]]
    logo_urls: frozenset[str]
    form_control_labels: tuple[str, ...]
    emails: frozenset[str]
    phones: frozenset[str]
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
        preserved_image_urls: set[str] = set()
        for inventory in soup.find_all(
            "template",
            attrs={"data-code-owned-image-inventory": "true"},
            limit=MAX_ITEMS,
        ):
            for image in inventory.find_all("img", limit=MAX_ITEMS):
                preserved_image_urls.update(_attribute_values(image.get("src")))
        for style in soup.find_all("style", limit=MAX_ITEMS):
            preserved_image_urls.update(
                _CSS_URL_PATTERN.findall(style.get_text(" "))
            )
        for ignored_container in soup.find_all(tuple(_IGNORED_TEXT_TAGS)):
            ignored_container.decompose()

        context_parts: dict[int, list[str]] = {}
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
            context_parts.setdefault(id(context or node), []).append(value)
        assertion_segments = tuple(
            dict.fromkeys(
                segment
                for parts in context_parts.values()
                if (segment := _normalize_text(" ".join(parts)))
            )
        )
        attribute_parts: list[str] = []
        raw_action_urls: set[str] = set()
        raw_action_pairs: set[tuple[str, str]] = set()
        raw_image_urls: set[str] = set(preserved_image_urls)
        raw_image_pairs: set[tuple[str, str]] = set()
        raw_logo_urls: set[str] = set()
        identity_parts: list[str] = []
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
        for meta in soup.find_all("meta", limit=MAX_ITEMS):
            property_name = str(
                meta.get("property") or meta.get("name") or ""
            ).casefold()
            if property_name in {"application-name", "og:site_name"}:
                identity_parts.extend(_attribute_values(meta.get("content")))

        for element in soup.find_all(True):
            action_label = ""
            element_image_urls: set[str] = set()
            is_image_resource = element.name == "img" or (
                element.name == "source" and element.find_parent("picture") is not None
            )
            if is_labelled_action_element(element):
                action_label = _normalize_text(
                    source_action_accessible_name(element, soup)
                )
            if action_label:
                action_labels.add(action_label)
                raw_href = element.get("href")
                if element.name in {"a", "area"} and isinstance(raw_href, str):
                    raw_action_pairs.add((action_label, raw_href))
            for name, raw_value in element.attrs.items():
                for value in _attribute_values(raw_value):
                    if name in _TEXT_ATTRIBUTES:
                        attribute_parts.append(value)
                    is_action_url = name == "href" and element.name in {"a", "area"}
                    if name in _ACTION_URL_ATTRIBUTES and is_action_url:
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
                    if name == "content":
                        property_name = str(
                            element.get("property") or element.get("name") or ""
                        ).casefold()
                        if property_name in _IMAGE_METADATA_URL_PROPERTIES:
                            raw_image_urls.add(value)
            style = element.get("style")
            if isinstance(style, str):
                raw_image_urls.update(_CSS_URL_PATTERN.findall(style))
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
            segment for part in identity_parts if (segment := _normalize_text(part))
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
                for part in (*identity_parts, *title_identity_parts)
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
            identity_parts.extend(
                corroborated_h1_parts
                if identity_seeds
                else ([] if has_ambiguous_title_identity else candidate_h1_parts[:1])
            )

        form_control_labels: list[str] = []
        for control in soup.find_all(["input", "select", "textarea"], limit=MAX_ITEMS):
            if (
                control.name == "input"
                and str(control.get("type") or "text").casefold()
                in _NON_DATA_INPUT_TYPES
            ):
                continue
            accessible_label = (
                _source_accessible_text(control, soup, frozenset())
                if control.has_attr("aria-labelledby") or control.has_attr("aria-label")
                else ""
            )
            if not accessible_label:
                labels = []
                seen_labels: set[int] = set()

                def append_label(label: Any) -> None:
                    identity = id(label)
                    if identity not in seen_labels:
                        seen_labels.add(identity)
                        labels.append(source_accessible_name(label, soup))

                wrapping_label = control.find_parent("label")
                if wrapping_label is not None:
                    append_label(wrapping_label)
                control_id = control.get("id")
                if isinstance(control_id, str) and control_id.strip():
                    for label in soup.find_all(
                        "label", attrs={"for": control_id}, limit=MAX_ITEMS
                    ):
                        append_label(label)
                accessible_label = " ".join(label for label in labels if label)
            if not accessible_label:
                accessible_label = str(
                    control.get("placeholder") or control.get("title") or ""
                ).strip()
            normalized_label = _normalize_text(accessible_label)
            if normalized_label:
                form_control_labels.append(normalized_label)

        def resolved(values: Iterable[str]) -> frozenset[str]:
            admitted: set[str] = set()
            for raw in values:
                candidate = html.unescape(raw).strip()
                if not candidate:
                    continue
                admitted.add(candidate)
                if source_url:
                    admitted.add(urljoin(source_url, candidate))
            return frozenset(admitted)

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
            identity_segments=tuple(
                dict.fromkeys(
                    segment
                    for part in identity_parts
                    if (segment := _normalize_text(part))
                )
            ),
            identity_exact_segments=tuple(
                dict.fromkeys(
                    variant
                    for part in (*title_identity_parts, *identity_parts)
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
            records=records,
            content_sections=content_sections,
            section_targets=section_targets,
        )

    def require_text(self, path: str, value: Any, *, asserted: bool = False) -> None:
        if value is None:
            return
        normalized = _normalize_text(value)
        if not normalized:
            raise SiteExtractionError(f"{path} is not grounded in source text.")
        found = False
        source_segments = self.assertion_segments if asserted else self.text_segments
        for source_text in source_segments:
            for index in _phrase_occurrences(source_text, normalized):
                found = True
                if _occurrence_is_negated(source_text, index, len(normalized)):
                    continue
                if asserted and _occurrence_is_nonassertive(
                    source_text,
                    index,
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

    def admit_social_platform(self, path: str, platform: Any, url: Any) -> str:
        self.require_url(f"{path}.url", url)
        normalized_url = html.unescape(url).strip() if isinstance(url, str) else ""
        hostname = (urlsplit(normalized_url).hostname or "").casefold()
        for domain, canonical in _SOCIAL_HOST_PLATFORMS:
            if hostname == domain or hostname.endswith(f".{domain}"):
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

    def require_form_fields(self, path: str, values: Any) -> None:
        remaining_labels = list(self.form_control_labels)
        for index, value in enumerate(values or []):
            normalized = _normalize_text(value) if isinstance(value, str) else ""
            if not normalized or normalized not in remaining_labels:
                raise SiteExtractionError(
                    f"{path}[{index}] is not the complete label of a distinct "
                    "source form control."
                )
            remaining_labels.remove(normalized)


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
    evidence.require_text(f"{path}.address", contact.get("address"), asserted=True)
    for index, address in enumerate(contact.get("addresses") or []):
        evidence.require_text(f"{path}.addresses[{index}]", address, asserted=True)
    evidence.require_text(f"{path}.hours", contact.get("hours"), asserted=True)


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
    evidence.require_text("site.location", site.get("location"), asserted=True)
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
        page["fetchable"] = _is_distinct_fetchable_page(page["url"], source_url)

    for index, section in enumerate(document.get("single_page_sections") or []):
        path = f"single_page_sections[{index}]"
        anchor = section.get("anchor")
        content = section.get("content") or {}

        def require_content(section_evidence: SourceEvidence) -> None:
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
            section_evidence.require_form_fields(
                f"{path}.content.form_fields", content.get("form_fields")
            )
            _require_contact(
                section_evidence,
                f"{path}.content.contact_info",
                content.get("contact_info"),
            )

        if anchor is not None:
            evidence.require_action(path, section["nav_label"], anchor)
            section_evidence = evidence.require_section_target(f"{path}.anchor", anchor)
            require_content(section_evidence)
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
                require_content(section_evidence)
            except SiteExtractionError:
                continue
            break
        else:
            raise SiteExtractionError(
                f"{path} navigation and content are not grounded in one source section."
            )

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
        evidence.require_form_fields("form_fields", admitted.get("form_fields"))
        _require_contact(evidence, "contact_info", admitted.get("contact_info"))
        contact_info = admitted.get("contact_info") or {}
        has_contact_info = any(
            contact_info.get(field)
            for field in ("phone", "email", "address", "addresses", "hours")
        )
        if not (admitted.get("form_fields") or has_contact_info):
            raise SiteExtractionError("Contact enrichment contains no source content.")
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
    return admitted
