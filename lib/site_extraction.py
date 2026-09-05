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
from bs4.element import Comment
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
_CONTACT_CONTEXT_TAGS = (
    _ASSERTION_CONTEXT_TAGS
    - {
        "aside",
        "body",
        "footer",
        "header",
        "main",
        "nav",
        "section",
    }
) | {"a"}
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
_CONDITIONAL_TERMS = frozenset(
    {"if", "unless", "whether", "assuming", "depending", "might", "may", "subject"}
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
            and words[index + 1]
            in {
                "only",
                "just",
            }
        ):
            continue
        if word in terms or word.endswith("n't"):
            return True
    return False


def _occurrence_is_negated(text: str, start: int, length: int) -> bool:
    preceding_sentence = _SENTENCE_BREAK_PATTERN.split(text[:start])[-1]
    preceding_clause = _CONTRAST_BREAK_PATTERN.split(preceding_sentence)[-1]
    preceding_words = [
        word.replace("’", "'") for word in _WORD_PATTERN.findall(preceding_clause)
    ][-6:]
    if _words_contain_negation(preceding_words):
        return True

    following_text = _LEADING_PARENTHETICAL_CONTRAST.sub(" ", text[start + length :])
    following_sentence = _SENTENCE_BREAK_PATTERN.split(following_text)[0]
    following_clause = _CONTRAST_BREAK_PATTERN.split(following_sentence)[0]
    following_words = [
        word.replace("’", "'") for word in _WORD_PATTERN.findall(following_clause)
    ][:6]
    return _words_contain_negation(following_words, postposed=True)


def _occurrence_is_nonassertive(text: str, start: int, length: int) -> bool:
    before = text[:start]
    after = text[start + length :]
    preceding_clause = re.split(r"[.!?]", before)[-1]
    following_match = re.search(r"[.!?]", after)
    following_clause = after[: following_match.start()] if following_match else after
    following_boundary = following_match.group(0) if following_match else ""
    if following_boundary == "?":
        return True
    surrounding_words = [
        word.replace("’", "'")
        for word in (
            _WORD_PATTERN.findall(preceding_clause)[-8:]
            + _WORD_PATTERN.findall(following_clause)[:8]
        )
    ]
    return any(word in _CONDITIONAL_TERMS for word in surrounding_words)


def _contact_destination(value: str) -> tuple[str, str] | None:
    parsed = urlsplit(html.unescape(value).strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"tel", "mailto"}:
        return None
    destination = unquote(parsed.path).strip()
    return (scheme, destination) if destination else None


def _attribute_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        yield from (item for item in value if isinstance(item, str))


_HEADING_TAG_PATTERN = re.compile(r"h([2-6])", re.I)
_ATOMIC_RECORD_TAGS = {"address", "blockquote", "details", "li", "p", "td", "th", "tr"}
_RECORD_CONTAINER_TAGS = {
    "article",
    "details",
    "div",
    "dl",
    "li",
    "menu",
    "ol",
    "section",
    "table",
    "tr",
    "ul",
}


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
            append(str(element))
            continue
        if element.name == "article":
            if len(element.find_all(_HEADING_TAG_PATTERN)) <= 1:
                append(str(element))
            continue
        if element.name in {"div", "section"}:
            nested_record = element.find(
                ["article", "details", "div", "li", "section", "tr"]
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
        parts = [str(heading)]
        for sibling in heading.next_siblings:
            sibling_name = getattr(sibling, "name", None)
            if sibling_name in _RECORD_CONTAINER_TAGS:
                break
            sibling_heading = (
                _HEADING_TAG_PATTERN.fullmatch(sibling_name)
                if isinstance(sibling_name, str)
                else None
            )
            if sibling_heading is not None:
                break
            parts.append(str(sibling))
        append("".join(parts))
    return tuple(fragments)


@dataclass(frozen=True)
class SourceEvidence:
    text_segments: tuple[str, ...]
    assertion_segments: tuple[str, ...]
    action_labels: frozenset[str]
    action_pairs: frozenset[tuple[str, str]]
    action_urls: frozenset[str]
    image_urls: frozenset[str]
    emails: frozenset[str]
    phones: frozenset[str]
    records: tuple[SourceEvidence, ...]
    section_targets: tuple[tuple[str, SourceEvidence], ...]

    @classmethod
    def from_html(
        cls,
        source_html: str,
        source_url: str | None,
        *,
        _include_records: bool = True,
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
        context_parts: dict[int, list[str]] = {}
        contact_context_parts: dict[int, list[str]] = {}
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
            contact_context = parent
            while (
                contact_context is not None
                and contact_context.name not in _CONTACT_CONTEXT_TAGS
            ):
                contact_context = contact_context.parent
            contact_context_parts.setdefault(
                id(contact_context or parent or node), []
            ).append(value)
        assertion_segments = tuple(
            dict.fromkeys(
                segment
                for parts in context_parts.values()
                if (segment := _normalize_text(" ".join(parts)))
            )
        )
        contact_segments = tuple(
            dict.fromkeys(
                segment
                for parts in contact_context_parts.values()
                if (segment := _normalize_text(" ".join(parts)))
            )
        )
        attribute_parts: list[str] = []
        raw_action_urls: set[str] = set()
        raw_action_pairs: set[tuple[str, str]] = set()
        raw_image_urls: set[str] = set()
        email_values: list[str] = list(contact_segments)
        phone_values: list[str] = list(contact_segments)
        action_labels: set[str] = set()

        for element in soup.find_all(True):
            role = str(element.get("role") or "").casefold()
            action_label = ""
            if (
                element.name in {"a", "area"}
                and element.has_attr("href")
                or element.name == "button"
                or role == "button"
            ):
                action_label = _normalize_text(element.get_text(" ", strip=True))
                if not action_label:
                    action_label = _normalize_text(
                        str(element.get("aria-label") or element.get("title") or "")
                    )
            if (
                element.name == "input"
                and str(element.get("type") or "").casefold() == "submit"
            ):
                action_label = _normalize_text(
                    str(element.get("value") or element.get("aria-label") or "")
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
                            if scheme == "mailto":
                                email_values.append(destination)
                            else:
                                phone_values.append(destination)
                    if name in _IMAGE_ATTRIBUTES:
                        raw_image_urls.add(value)
                    if name == "srcset":
                        srcset_urls = {
                            candidate.strip().split()[0]
                            for candidate in value.split(",")
                            if candidate.strip()
                        }
                        raw_image_urls.update(srcset_urls)
                    if name == "content":
                        property_name = str(
                            element.get("property") or element.get("name") or ""
                        ).casefold()
                        if "image" in property_name:
                            raw_image_urls.add(value)
                style = element.get("style")
                if isinstance(style, str):
                    raw_image_urls.update(_CSS_URL_PATTERN.findall(style))

        for style in soup.find_all("style"):
            raw_image_urls.update(_CSS_URL_PATTERN.findall(style.get_text(" ")))

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

        emails = {
            match.group(0).casefold()
            for segment in email_values
            for match in _EMAIL_PATTERN.finditer(segment)
        }
        phones: set[str] = set()
        for segment in phone_values:
            for match in _PHONE_PATTERN.finditer(segment):
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
                    _include_section_targets=False,
                )
                for fragment in _record_fragments(soup)
            )
            if _include_records
            else ()
        )
        section_targets = (
            tuple(
                (
                    f"#{element_id.strip()}",
                    cls.from_html(
                        str(element),
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
            action_labels=frozenset(action_labels),
            action_pairs=frozenset(
                (label, destination)
                for label, raw_url in raw_action_pairs
                for destination in resolved((raw_url,))
            ),
            action_urls=resolved(raw_action_urls),
            image_urls=resolved(raw_image_urls),
            emails=frozenset(emails),
            phones=frozenset(phones),
            records=records,
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
                    source_text, index, len(normalized)
                ):
                    continue
                return
        if found:
            raise SiteExtractionError(
                f"{path} drops or reverses source assertion context."
            )
        raise SiteExtractionError(f"{path} is not grounded in source text.")

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
    evidence.require_text(f"{path}.address", contact.get("address"))
    for index, address in enumerate(contact.get("addresses") or []):
        evidence.require_text(f"{path}.addresses[{index}]", address)
    evidence.require_text(f"{path}.hours", contact.get("hours"))


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
            container.require_text(
                f"{item_path}.title",
                item.get("title"),
                asserted=not allow_nonassertive_title,
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


def _require_site_facts(document: dict, evidence: SourceEvidence) -> None:
    site = document["site"]
    evidence.require_text("site.name", site["name"])
    evidence.require_text("site.tagline", site.get("tagline"))
    evidence.require_text("site.location", site.get("location"))
    _require_contact(evidence, "site.contact", site.get("contact"))

    brand = document.get("brand") or {}
    evidence.require_url("brand.logo_url", brand.get("logo_url"), image=True)

    for index, item in enumerate(document.get("nav") or []):
        evidence.require_action(f"nav[{index}]", item["label"], item["url"])
    cta = document.get("cta") or {}
    cta_label = cta.get("label")
    cta_url = cta.get("url")
    if cta_label is not None and cta_url is not None:
        evidence.require_action("cta", cta_label, cta_url)
    else:
        evidence.require_action_label("cta.label", cta_label)
        evidence.require_url("cta.url", cta_url)

    for index, section in enumerate(document.get("sections") or []):
        path = f"sections[{index}]"
        evidence.require_text(f"{path}.headline", section.get("headline"))
        _require_content_items(
            evidence,
            f"{path}.items",
            section.get("items"),
            allow_nonassertive_title=section.get("type") == "faq",
        )

    for index, image in enumerate(document.get("images") or []):
        evidence.require_url(f"images[{index}].url", image["url"], image=True)
        evidence.require_text(f"images[{index}].alt", image.get("alt"))
    for index, social in enumerate(document.get("social") or []):
        evidence.require_url(f"social[{index}].url", social["url"])
    for index, item in enumerate(document.get("footer_links") or []):
        evidence.require_action(f"footer_links[{index}]", item["label"], item["url"])
    for index, page in enumerate(document.get("pages_to_fetch") or []):
        evidence.require_action(f"pages_to_fetch[{index}]", page["label"], page["url"])

    for index, section in enumerate(document.get("single_page_sections") or []):
        path = f"single_page_sections[{index}]"
        anchor = section.get("anchor")
        section_evidence = evidence
        if anchor is not None:
            evidence.require_action(path, section["nav_label"], anchor)
            section_evidence = evidence.require_section_target(f"{path}.anchor", anchor)
        else:
            evidence.require_text(f"{path}.nav_label", section["nav_label"])
        content = section.get("content") or {}
        section_evidence.require_text(
            f"{path}.content.headline", content.get("headline")
        )
        section_evidence.require_text(
            f"{path}.content.body_text", content.get("body_text")
        )
        _require_content_items(
            section_evidence,
            f"{path}.content.items",
            content.get("items"),
            allow_nonassertive_title=section.get("page_type") == "faq",
        )
        for field_index, field in enumerate(content.get("form_fields") or []):
            section_evidence.require_text(
                f"{path}.content.form_fields[{field_index}]", field
            )
        _require_contact(
            section_evidence,
            f"{path}.content.contact_info",
            content.get("contact_info"),
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
    _require_site_facts(admitted, evidence)
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
        for index, field in enumerate(admitted.get("form_fields") or []):
            evidence.require_text(f"form_fields[{index}]", field)
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
    else:
        evidence.require_text("headline", admitted.get("headline"))
    derived_tag = (
        "about" if page_type == "about" else "faq" if page_type == "faq" else None
    )
    if derived_tag is not None:
        for item in admitted["items"]:
            if item.get("tag") != derived_tag:
                raise SiteExtractionError(
                    "Enrichment item tag does not match the page type selected by code."
                )
    _require_content_items(
        evidence,
        "items",
        admitted["items"],
        verify_tag=derived_tag is None,
        allow_nonassertive_title=page_type == "faq",
    )
    return admitted
