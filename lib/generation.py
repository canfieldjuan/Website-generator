"""Provider-neutral text generation and generated-HTML admission checks."""

from __future__ import annotations

import ipaddress
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, replace
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from openai import DefaultHttpxClient, OpenAI

from lib.clients import OPENROUTER_API_KEY, OPENROUTER_BASE_URL


DEFAULT_LOCAL_MODEL = "qwen/qwen3.8-27b"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_LOCAL_API_KEY = "no-key"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_LOCAL_TIMEOUT_SECONDS = 7200.0
LOCAL_PREFLIGHT_TIMEOUT_SECONDS = 10.0
# Non-HTML generation keeps the historical ceiling. HTML callers apply the
# tighter body-only ceiling before trusted code assembles the final document.
DEFAULT_MAX_OUTPUT_TOKENS = 65536
MAX_GENERATED_BODY_TOKENS = 8192
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_GENERATED_BODY_BYTES = 512 * 1024
SUPPORTED_PROVIDERS = frozenset(("local", "openrouter"))
HOMEPAGE_SHARED_PAGE_CLASSES = frozenset(("page-wrap",))
REQUIRED_FOOTER_CLASS_COUNTS = (
    ("site-footer", 1),
    ("footer-grid", 1),
    ("footer-bottom", 1),
)
REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES = (
    ("site-footer", ("footer-grid", "footer-bottom")),
)
_RENDERED_TEXT_BOUNDARY_TAGS = frozenset(
    (
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    )
)
DEFAULT_DOCUMENT_ACCENT = "#1D4ED8"
DEFAULT_DOCUMENT_SECONDARY = "#1F3A5F"


class GenerationConfigurationError(ValueError):
    """The selected provider cannot be configured from explicit inputs."""


class GenerationProviderUnavailable(RuntimeError):
    """The configured generation provider or model is not currently usable."""


class GenerationResponseError(RuntimeError):
    """The provider returned no usable completed response."""


class GeneratedHtmlError(ValueError):
    """Generated output is not a complete standalone HTML document."""


class GeneratedBodyError(ValueError):
    """Generated output is not an admissible template body fragment."""


@dataclass(frozen=True)
class PromptPart:
    text: str
    cacheable: bool = False


@dataclass(frozen=True)
class GenerationConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    trust_env: bool = True


@dataclass(frozen=True)
class GenerationResult:
    provider: str
    model: str
    content: str
    finish_reason: str | None
    usage: dict[str, Any]


@dataclass(frozen=True)
class DocumentColors:
    accent: str
    accent_dark: str
    secondary: str


@dataclass(frozen=True)
class ThemeDefinition:
    font_link: str
    font_display: str
    font_body: str
    font_serif: str
    card_radius: str


class _DocumentStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self.content_container_depth = 0
        self.has_content_outside_content = False

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() == "doctype html":
            self.events.append(("declaration", "doctype html"))
        elif self.content_container_depth == 0:
            self.has_content_outside_content = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"html", "head", "body"}:
            self.events.append(("start", tag))
        if tag in {"head", "body"}:
            self.content_container_depth += 1
        elif tag != "html" and self.content_container_depth == 0:
            self.has_content_outside_content = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"html", "head", "body"}:
            self.events.append(("end", tag))
        if tag in {"head", "body"} and self.content_container_depth:
            self.content_container_depth -= 1
        elif tag != "html" and self.content_container_depth == 0:
            self.has_content_outside_content = True

    def handle_data(self, data: str) -> None:
        if data.strip() and self.content_container_depth == 0:
            self.has_content_outside_content = True

    def handle_pi(self, data: str) -> None:
        if self.content_container_depth == 0:
            self.has_content_outside_content = True

    def unknown_decl(self, data: str) -> None:
        if self.content_container_depth == 0:
            self.has_content_outside_content = True


class _GeneratedBodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body_depth = 0
        self.body_events: list[str] = []
        self.forbidden_tags: list[str] = []
        self.has_content_outside_body = False
        self.visible_text_parts: list[str] = []
        self.decoded_attribute_values: list[str] = []
        self.class_names: set[str] = set()
        self.class_name_counts: dict[str, int] = {}
        self.svg_depth = 0

    def handle_decl(self, decl: str) -> None:
        self.has_content_outside_body = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.decoded_attribute_values.extend(
            value for _name, value in attrs if value is not None
        )
        element_class_names: set[str] = set()
        for name, value in attrs:
            if name.casefold() != "class" or not value:
                continue
            for class_name in value.split():
                self.class_names.add(class_name)
                element_class_names.add(class_name)
        for class_name in element_class_names:
            self.class_name_counts[class_name] = (
                self.class_name_counts.get(class_name, 0) + 1
            )
        tag_name = tag.lower()
        if tag_name == "body":
            self.body_events.append("start")
            self.body_depth += 1
            return
        if tag_name in {"html", "head", "style", "script", "base", "link", "meta"}:
            self.forbidden_tags.append(tag_name)
        elif tag_name == "title" and self.svg_depth == 0:
            self.forbidden_tags.append(tag_name)
        if tag_name == "svg":
            self.svg_depth += 1
        if self.body_depth == 0:
            self.has_content_outside_body = True

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "body":
            self.body_events.append("end")
            if self.body_depth:
                self.body_depth -= 1
            else:
                self.has_content_outside_body = True
            return
        if tag_name in {"html", "head", "style", "script", "base", "link", "meta"}:
            self.forbidden_tags.append(tag_name)
        elif tag_name == "title" and self.svg_depth == 0:
            self.forbidden_tags.append(tag_name)
        if tag_name == "svg" and self.svg_depth:
            self.svg_depth -= 1
        if self.body_depth == 0:
            self.has_content_outside_body = True

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() == "body":
            self.body_events.extend(("start", "end"))
            self.has_content_outside_body = True
            return
        self.handle_starttag(tag, attrs)
        if tag.lower() == "svg":
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.body_depth:
            self.visible_text_parts.append(data)
        elif data.strip():
            self.has_content_outside_body = True

    def handle_pi(self, data: str) -> None:
        if self.body_depth == 0:
            self.has_content_outside_body = True

    def unknown_decl(self, data: str) -> None:
        self.has_content_outside_body = True


def resolve_generation_config(
    provider: str = "local",
    model: str | None = None,
) -> GenerationConfig:
    provider_name = provider.strip().lower()
    if provider_name not in SUPPORTED_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise GenerationConfigurationError(
            f"Unsupported generation provider {provider!r}; choose one of: {allowed}."
        )

    default_timeout = (
        DEFAULT_LOCAL_TIMEOUT_SECONDS
        if provider_name == "local"
        else DEFAULT_TIMEOUT_SECONDS
    )
    timeout_seconds = _positive_float_env("GENERATION_TIMEOUT_SECONDS", default_timeout)
    max_output_tokens = _positive_int_env(
        "GENERATION_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS
    )

    if provider_name == "local":
        local_model = (
            model
            or os.environ.get("LOCAL_GENERATION_MODEL")
            or os.environ.get("GENERATION_MODEL")
            or DEFAULT_LOCAL_MODEL
        )
        return GenerationConfig(
            provider="local",
            model=local_model,
            base_url=(
                os.environ.get("LOCAL_GENERATION_BASE_URL")
                or os.environ.get("LLAMA_CPP_BASE_URL")
                or DEFAULT_LOCAL_BASE_URL
            ),
            api_key=(
                os.environ.get("LOCAL_GENERATION_API_KEY")
                or os.environ.get("LLAMA_CPP_API_KEY")
                or DEFAULT_LOCAL_API_KEY
            ),
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )

    openrouter_model = model or os.environ.get("OPENROUTER_GENERATION_MODEL")
    if not openrouter_model:
        raise GenerationConfigurationError(
            "OpenRouter generation requires --generation-model or "
            "OPENROUTER_GENERATION_MODEL."
        )
    if not OPENROUTER_API_KEY:
        raise GenerationConfigurationError(
            "OpenRouter generation requires OPENROUTER_API_KEY."
        )
    return GenerationConfig(
        provider="openrouter",
        model=openrouter_model,
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )


def create_generation_client(config: GenerationConfig) -> OpenAI:
    client_options: dict[str, Any] = {}
    if not config.trust_env:
        client_options["http_client"] = DefaultHttpxClient(trust_env=False)
    return OpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=config.timeout_seconds,
        max_retries=0,
        **client_options,
    )


def create_local_generation_client(config: GenerationConfig) -> requests.Session:
    session = requests.Session()
    # A loopback-only provider must not inherit HTTP(S)_PROXY from the shell:
    # requests may otherwise send the complete prompt to that proxy even though
    # the configured llama.cpp URL itself is local.  OpenRouter continues to
    # honor GenerationConfig.trust_env through create_generation_client.
    session.trust_env = False
    session.headers.update(
        {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
    )
    return session


def body_generation_config(config: GenerationConfig) -> GenerationConfig:
    return replace(
        config,
        max_output_tokens=min(
            config.max_output_tokens,
            MAX_GENERATED_BODY_TOKENS,
        ),
    )


def extract_square_placeholder_tokens(*sources: str) -> tuple[str, ...]:
    """Return prompt-defined square-bracket placeholders for output admission."""
    tokens = {
        match.group(0)
        for source in sources
        for match in re.finditer(r"\[[^\[\]\r\n]{1,160}\]", source)
        if any(character.isalnum() for character in match.group(0))
    }
    return tuple(sorted(tokens, key=str.casefold))


def _raise_for_local_response_status(response: Any) -> None:
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and 300 <= status_code < 400:
        raise requests.HTTPError(
            f"Local generation endpoint returned redirect status {status_code}."
        )
    response.raise_for_status()


def preflight_generation_provider(
    config: GenerationConfig,
    *,
    client: Any | None = None,
) -> None:
    """Fail before work begins when the selected local model is not loaded.

    OpenRouter is intentionally not probed here: selecting it is explicit and
    its authenticated generation request is the authoritative availability
    check.  This avoids an extra paid/cloud request.
    """
    if config.provider != "local":
        return
    selected_client = client or create_local_generation_client(config)
    health_url, models_url, _chat_url = _llama_cpp_urls(config.base_url)
    preflight_timeout = min(config.timeout_seconds, LOCAL_PREFLIGHT_TIMEOUT_SECONDS)
    try:
        health_response = selected_client.get(
            health_url,
            timeout=preflight_timeout,
            allow_redirects=False,
        )
        _raise_for_local_response_status(health_response)
        health_payload = health_response.json()
        if not isinstance(health_payload, dict) or health_payload.get("status") != "ok":
            raise ValueError("health endpoint did not report status=ok")

        models_response = selected_client.get(
            models_url,
            timeout=preflight_timeout,
            allow_redirects=False,
        )
        _raise_for_local_response_status(models_response)
        models_payload = models_response.json()
        model_items = (
            models_payload.get("data") if isinstance(models_payload, dict) else None
        )
        if not isinstance(model_items, list):
            raise ValueError("model endpoint did not return a data list")
        available: set[str] = set()
        for item in model_items:
            model_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(model_id, str) or not model_id:
                raise ValueError("model endpoint returned an invalid model id")
            available.add(model_id)
    except Exception as exc:
        raise GenerationProviderUnavailable(
            "Local generation is unavailable at "
            f"{config.base_url}. Start standalone llama.cpp with: "
            "scripts/start_llama_server.sh"
        ) from exc
    if config.model not in available:
        raise GenerationProviderUnavailable(
            f"Local model alias {config.model!r} is not served by llama.cpp. "
            "Start it with: scripts/start_llama_server.sh"
        )


def generate_text(
    config: GenerationConfig,
    *,
    system_prompt: str,
    user_parts: Iterable[PromptPart],
    temperature: float,
    cache_system_prompt: bool = False,
    client: Any | None = None,
) -> GenerationResult:
    parts = tuple(user_parts)
    if config.provider == "local":
        return _generate_local_text(
            config,
            system_prompt=system_prompt,
            user_content="\n\n".join(part.text for part in parts),
            temperature=temperature,
            client=client,
        )

    selected_client = client or create_generation_client(config)
    system_content: Any = [
        _openrouter_content_part(system_prompt, cache_system_prompt)
    ]
    user_content: Any = [
        _openrouter_content_part(part.text, part.cacheable) for part in parts
    ]

    try:
        response = selected_client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            max_tokens=config.max_output_tokens,
            timeout=config.timeout_seconds,
        )
    except Exception as exc:
        raise GenerationProviderUnavailable(
            f"{config.provider} generation failed for model {config.model!r}: {exc}"
        ) from exc

    choices = getattr(response, "choices", None) or []
    if not choices:
        raise GenerationResponseError("Generation provider returned no choices.")
    choice = choices[0]
    content = getattr(getattr(choice, "message", None), "content", None)
    if not isinstance(content, str):
        raise GenerationResponseError("Generation provider returned no text content.")

    return GenerationResult(
        provider=config.provider,
        model=config.model,
        content=content,
        finish_reason=getattr(choice, "finish_reason", None),
        usage=_usage_dict(getattr(response, "usage", None)),
    )


def _generate_local_text(
    config: GenerationConfig,
    *,
    system_prompt: str,
    user_content: str,
    temperature: float,
    client: Any | None,
) -> GenerationResult:
    selected_client = client or create_local_generation_client(config)
    _health_url, _models_url, endpoint = _llama_cpp_urls(config.base_url)
    request_body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": config.max_output_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_format": "deepseek",
    }
    try:
        response = selected_client.post(
            endpoint,
            json=request_body,
            timeout=config.timeout_seconds,
            allow_redirects=False,
        )
        _raise_for_local_response_status(response)
    except Exception as exc:
        raise GenerationProviderUnavailable(
            f"local generation failed for model {config.model!r}: {exc}"
        ) from exc

    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise GenerationResponseError(
            "Local generation provider returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise GenerationResponseError(
            "Local generation provider returned a non-object response."
        )

    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise GenerationResponseError(
            "Local generation provider returned no choices collection."
        )
    if len(choices) != 1:
        raise GenerationResponseError(
            "Local generation provider must return exactly one choice."
        )
    choice = choices[0]
    if not isinstance(choice, dict):
        raise GenerationResponseError(
            "Local generation provider returned an invalid choice."
        )
    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise GenerationResponseError(
            "Local generation provider returned no finish reason."
        )
    message = choice.get("message")
    if not isinstance(message, dict):
        raise GenerationResponseError(
            "Local generation provider returned no message."
        )
    if message.get("reasoning_content") not in (None, ""):
        raise GenerationResponseError(
            "Local generation provider returned reasoning despite thinking being disabled."
        )
    if message.get("tool_calls") not in (None, []):
        raise GenerationResponseError(
            "Local generation provider returned tool calls when none were requested."
        )
    content = message.get("content")
    if not isinstance(content, str):
        raise GenerationResponseError(
            "Local generation provider returned a message without text content."
        )
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise GenerationResponseError(
            "Local generation provider returned no usage object."
        )
    return GenerationResult(
        provider=config.provider,
        model=config.model,
        content=content,
        finish_reason=finish_reason,
        usage=dict(usage),
    )


def require_complete_text(result: GenerationResult) -> str:
    if result.finish_reason != "stop":
        reason = result.finish_reason or "missing"
        raise GenerationResponseError(
            f"Generation did not finish normally (finish_reason={reason})."
        )
    content = result.content.strip()
    if not content:
        raise GenerationResponseError("Generation returned empty text.")
    return content


def make_html_comment(content: str) -> str:
    """Wrap trusted metadata as one syntactically safe HTML comment."""
    if not isinstance(content, str):
        raise GeneratedHtmlError("Trusted comment content must be text.")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise GeneratedHtmlError("Trusted comment content must not be empty.")
    # HTML comments cannot contain a double hyphen. Dynamic prospect/site
    # values are allowed in these code-owned notes, so neutralize the comment
    # delimiter rather than letting data terminate the comment early.
    normalized = normalized.replace("--", "- -")
    if normalized.endswith("-"):
        normalized += " "
    return f"<!--\n{normalized}\n-->"


def _normalize_claim_match_text(value: str) -> str:
    """Canonicalize browser-equivalent whitespace for claim admission."""
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _rendered_claim_text(body_root: Tag) -> str:
    parts: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            parts.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        has_boundary = node.name.casefold() in _RENDERED_TEXT_BOUNDARY_TAGS
        if has_boundary:
            parts.append(" ")
        for child in node.children:
            visit(child)
        if has_boundary:
            parts.append(" ")

    for child in body_root.children:
        visit(child)
    return "".join(parts)


def _exact_class_names(element: Tag) -> set[str]:
    classes = element.get("class", ())
    if isinstance(classes, str):
        return set(classes.split())
    return {value for value in classes if isinstance(value, str)}


def _required_child_sequence_mismatches(
    body_root: Tag,
    requirements: Iterable[tuple[str, tuple[str, ...]]],
) -> list[str]:
    mismatches: list[str] = []
    all_elements = (body_root, *body_root.find_all(True))
    for parent_class, expected_sequence in requirements:
        expected_classes = set(expected_sequence)
        parents = [
            element
            for element in all_elements
            if parent_class in _exact_class_names(element)
        ]
        if not parents:
            mismatches.append(f"{parent_class} parent is missing")
            continue
        for index, parent in enumerate(parents, start=1):
            actual_sequence: list[str] = []
            for child in parent.find_all(True, recursive=False):
                matches = sorted(_exact_class_names(child) & expected_classes)
                if len(matches) == 1:
                    actual_sequence.append(matches[0])
                elif not matches:
                    actual_sequence.append(f"<{child.name}>")
                else:
                    actual_sequence.append("|".join(matches))
            if tuple(actual_sequence) != expected_sequence:
                expected = ", ".join(expected_sequence)
                actual = ", ".join(actual_sequence) or "none"
                mismatches.append(
                    f"{parent_class}[{index}] direct children expected "
                    f"{expected}, got {actual}"
                )
    return mismatches


def validate_generated_body(
    result: GenerationResult,
    *,
    max_bytes: int = MAX_GENERATED_BODY_BYTES,
    forbidden_square_placeholders: Iterable[str] = (),
    forbidden_visible_phrases: Iterable[str] = (),
    forbidden_class_names: Iterable[str] = (),
    required_class_counts: Iterable[tuple[str, int]] = (),
    required_child_class_sequences: Iterable[
        tuple[str, tuple[str, ...]]
    ] = (),
) -> str:
    body = _strip_outer_code_fence(require_complete_text(result))
    if "```" in body:
        raise GeneratedBodyError(
            "Generated body contains an unexpected code fence."
        )
    if not re.match(r"^<body(?:\s|>)", body, re.IGNORECASE):
        raise GeneratedBodyError(
            "Generated body must begin with one body element and no provider chatter."
        )
    if not re.search(r"</body>\s*$", body, re.IGNORECASE):
        raise GeneratedBodyError(
            "Generated body must end with its closing body tag."
        )
    if len(body.encode("utf-8")) > max_bytes:
        raise GeneratedBodyError(
            f"Generated body exceeds the {max_bytes}-byte limit."
        )
    parser = _GeneratedBodyParser()
    parser.feed(body)
    parser.close()
    if parser.body_events != ["start", "end"] or parser.body_depth:
        raise GeneratedBodyError(
            "Generated body must contain exactly one balanced body root."
        )
    if parser.forbidden_tags:
        names = ", ".join(sorted(set(parser.forbidden_tags)))
        raise GeneratedBodyError(
            "Generated body contains forbidden document, metadata, or "
            f"executable tags: {names}."
        )
    if parser.has_content_outside_body:
        raise GeneratedBodyError(
            "Generated body contains content outside its body root."
        )
    forbidden_class_folds = {
        class_name.casefold()
        for class_name in forbidden_class_names
        if isinstance(class_name, str) and class_name
    }
    leaked_class_names = sorted(
        {
            class_name
            for class_name in parser.class_names
            if class_name.casefold() in forbidden_class_folds
        },
        key=str.casefold,
    )
    if leaked_class_names:
        leaked = ", ".join(leaked_class_names[:3])
        raise GeneratedBodyError(
            f"Generated body contains classes unavailable to this page type: {leaked}."
        )
    class_count_mismatches = []
    for class_name, expected_count in required_class_counts:
        actual_count = parser.class_name_counts.get(class_name, 0)
        if actual_count != expected_count:
            class_count_mismatches.append(
                f"{class_name} expected {expected_count}, got {actual_count}"
            )
    if class_count_mismatches:
        raise GeneratedBodyError(
            "Generated body has invalid required class counts: "
            + "; ".join(class_count_mismatches[:3])
        )

    parsed_body = BeautifulSoup(body, "html.parser")
    body_root = parsed_body.find("body")
    if not isinstance(body_root, Tag):
        raise GeneratedBodyError("Generated body root could not be parsed.")
    child_sequence_mismatches = _required_child_sequence_mismatches(
        body_root,
        required_child_class_sequences,
    )
    if child_sequence_mismatches:
        raise GeneratedBodyError(
            "Generated body has invalid required component structure: "
            + "; ".join(child_sequence_mismatches[:3])
        )

    claim_surfaces = (
        _rendered_claim_text(body_root),
        *parser.decoded_attribute_values,
        *(unquote(value) for value in parser.decoded_attribute_values),
    )
    normalized_claim_surfaces = tuple(
        _normalize_claim_match_text(surface) for surface in claim_surfaces
    )
    leaked_phrases = sorted(
        {
            phrase
            for phrase in forbidden_visible_phrases
            if isinstance(phrase, str)
            and phrase
            and _normalize_claim_match_text(phrase)
            and any(
                _normalize_claim_match_text(phrase) in surface
                for surface in normalized_claim_surfaces
            )
        },
        key=str.casefold,
    )
    if leaked_phrases:
        leaked = ", ".join(leaked_phrases[:3])
        raise GeneratedBodyError(
            f"Generated body contains unsupported prospect claims: {leaked}."
        )
    placeholder_surfaces = (
        body,
        "".join(parser.visible_text_parts),
        *parser.decoded_attribute_values,
        *(unquote(value) for value in parser.decoded_attribute_values),
    )
    leaked_curly_placeholders = sorted(
        {
            match.group(0)
            for surface in placeholder_surfaces
            for match in re.finditer(r"{{[^{}]+}}", surface)
        },
        key=str.casefold,
    )
    if leaked_curly_placeholders:
        leaked = ", ".join(leaked_curly_placeholders[:3])
        raise GeneratedBodyError(
            f"Generated body contains unresolved template placeholders: {leaked}."
        )
    folded_surfaces = tuple(surface.casefold() for surface in placeholder_surfaces)
    leaked_square_placeholders = sorted(
        {
            token
            for token in forbidden_square_placeholders
            if isinstance(token, str)
            and token
            and any(token.casefold() in surface for surface in folded_surfaces)
        },
        key=str.casefold,
    )
    if leaked_square_placeholders:
        leaked = ", ".join(leaked_square_placeholders[:3])
        raise GeneratedBodyError(
            f"Generated body contains unresolved prompt placeholders: {leaked}."
        )
    return body


def extract_template_body_scaffold(template_html: str) -> str:
    head_close = re.search(r"</head\s*>", template_html, re.IGNORECASE)
    if not head_close:
        raise GeneratedHtmlError("Base template has no closing head tag.")
    match = re.search(
        r"<body(?:\s[^>]*)?>.*?</body\s*>",
        template_html[head_close.end() :],
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise GeneratedHtmlError("Base template has no complete body scaffold.")
    return match.group(0).strip()


def extract_template_class_names(template_html: str) -> tuple[str, ...]:
    """Return the immutable template's HTML/CSS class vocabulary."""
    class_names = {
        class_name
        for match in re.finditer(
            r"\bclass\s*=\s*(['\"])(.*?)\1",
            template_html,
            re.IGNORECASE | re.DOTALL,
        )
        for class_name in match.group(2).split()
        if class_name
    }
    for style_block in re.findall(
        r"<style(?:\s[^>]*)?>(.*?)</style\s*>",
        template_html,
        re.IGNORECASE | re.DOTALL,
    ):
        class_names.update(
            re.findall(r"(?<![\w-])\.([A-Za-z_][A-Za-z0-9_-]*)", style_block)
        )
    if not class_names:
        raise GeneratedHtmlError("Base template body has no class vocabulary.")
    return tuple(sorted(class_names, key=str.casefold))


def extract_interior_only_class_names(template_html: str) -> tuple[str, ...]:
    """Return page-prefixed components that homepage generation must not use."""
    return tuple(
        class_name
        for class_name in extract_template_class_names(template_html)
        if class_name.startswith("page-")
        and class_name not in HOMEPAGE_SHARED_PAGE_CLASSES
    )


def extract_homepage_class_names(template_html: str) -> tuple[str, ...]:
    """Return the template vocabulary without interior-only page components."""
    interior_only = set(extract_interior_only_class_names(template_html))
    return tuple(
        class_name
        for class_name in extract_template_class_names(template_html)
        if class_name not in interior_only
    )


def parse_theme_definition(catalog: str, theme_name: str) -> ThemeDefinition:
    section = re.search(
        rf"^##\s+{re.escape(theme_name)}\s+--.*?$(.*?)(?=^##\s|\Z)",
        catalog,
        re.MULTILINE | re.DOTALL,
    )
    if not section:
        raise GeneratedHtmlError(
            f"Theme {theme_name!r} is not defined in the theme catalog."
        )
    content = section.group(1)
    font_link_match = re.search(
        r'<link href="https://fonts\.googleapis\.com/[^"<>]+" rel="stylesheet">',
        content,
    )
    if not font_link_match:
        raise GeneratedHtmlError(
            f"Theme {theme_name!r} has no admissible Google Fonts link."
        )

    values: dict[str, str] = {}
    for property_name in (
        "--font-display",
        "--font-body",
        "--font-serif",
        "--card-radius",
    ):
        value_match = re.search(
            rf"^{re.escape(property_name)}:\s*(.+?);\s*$",
            content,
            re.MULTILINE,
        )
        if not value_match:
            raise GeneratedHtmlError(
                f"Theme {theme_name!r} has no {property_name} override."
            )
        value = value_match.group(1).strip()
        if any(character in value for character in "{}<>"):
            raise GeneratedHtmlError(
                f"Theme {theme_name!r} has an unsafe {property_name} override."
            )
        values[property_name] = value

    return ThemeDefinition(
        font_link=font_link_match.group(0),
        font_display=values["--font-display"],
        font_body=values["--font-body"],
        font_serif=values["--font-serif"],
        card_radius=values["--card-radius"],
    )


def assemble_generated_html(
    result: GenerationResult,
    *,
    base_template: str,
    theme_catalog: str,
    theme_name: str,
    colors: DocumentColors,
    title: str,
    body_theme: str,
    trusted_head_comment: str | None = None,
    forbidden_square_placeholders: Iterable[str] = (),
    forbidden_visible_phrases: Iterable[str] = (),
    forbidden_class_names: Iterable[str] = (),
    required_class_counts: Iterable[tuple[str, int]] = (),
    required_child_class_sequences: Iterable[
        tuple[str, tuple[str, ...]]
    ] = (),
) -> str:
    if body_theme not in {"theme-light", "theme-dark"}:
        raise GeneratedHtmlError(
            "Body theme must be theme-light or theme-dark."
        )
    style = parse_theme_definition(theme_catalog, theme_name)
    color_values = {
        "--accent": _require_hex_color("accent", colors.accent),
        "--accent-dark": _require_hex_color("accent_dark", colors.accent_dark),
        "--secondary": _require_hex_color("secondary", colors.secondary),
    }
    body = validate_generated_body(
        result,
        forbidden_square_placeholders=forbidden_square_placeholders,
        forbidden_visible_phrases=forbidden_visible_phrases,
        forbidden_class_names=forbidden_class_names,
        required_class_counts=required_class_counts,
        required_child_class_sequences=required_child_class_sequences,
    )
    body = re.sub(
        r"^<body(?:\s[^>]*)?>",
        f'<body class="{body_theme}">',
        body,
        count=1,
        flags=re.IGNORECASE,
    )

    head_comment = ""
    if trusted_head_comment is not None:
        if not isinstance(trusted_head_comment, str):
            raise GeneratedHtmlError("Trusted head comment must be text.")
        head_comment = trusted_head_comment.strip()
        if not re.fullmatch(r"<!--\n?.*?\n?-->", head_comment, re.DOTALL):
            raise GeneratedHtmlError(
                "Trusted head comment must contain exactly one HTML comment."
            )
        comment_content = head_comment[4:-3]
        if (
            "<!--" in comment_content
            or "-->" in comment_content
            or "--" in comment_content
            or comment_content.endswith("-")
        ):
            raise GeneratedHtmlError(
                "Trusted head comment contains an unsafe nested delimiter."
            )

    head_close = re.search(r"</head\s*>", base_template, re.IGNORECASE)
    if not head_close:
        raise GeneratedHtmlError("Base template has no closing head tag.")
    head = base_template[: head_close.end()]
    if not re.match(
        r"^\s*<!doctype\s+html\s*>\s*<html(?:\s|>)",
        head,
        re.IGNORECASE,
    ):
        raise GeneratedHtmlError(
            "Base template must begin with a doctype and html root."
        )
    head, title_count = re.subn(
        r"<title>.*?</title>",
        lambda _: f"<title>{escape(title, quote=False)}</title>",
        head,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if title_count != 1:
        raise GeneratedHtmlError("Base template must contain exactly one title.")
    head, font_count = re.subn(
        r'<link href="https://fonts\.googleapis\.com/[^"<>]+" rel="stylesheet">',
        lambda _: style.font_link,
        head,
        count=1,
    )
    if font_count != 1:
        raise GeneratedHtmlError(
            "Base template must contain exactly one replaceable Google Fonts link."
        )

    root_values = {
        **color_values,
        "--font-display": style.font_display,
        "--font-body": style.font_body,
        "--font-serif": style.font_serif,
        "--card-radius": style.card_radius,
    }
    for property_name, value in root_values.items():
        head = _replace_root_property(head, property_name, value)
    if head_comment:
        head, head_count = re.subn(
            r"<head>",
            lambda _: f"<head>\n{head_comment}",
            head,
            count=1,
            flags=re.IGNORECASE,
        )
        if head_count != 1:
            raise GeneratedHtmlError(
                "Base template must contain exactly one opening head tag."
            )

    document = f"{head}\n{body}\n</html>"
    return validate_generated_html(
        GenerationResult(
            provider=result.provider,
            model=result.model,
            content=document,
            finish_reason="stop",
            usage=result.usage,
        )
    )


def validate_generated_html(
    result: GenerationResult,
    *,
    max_bytes: int = MAX_HTML_BYTES,
) -> str:
    html = require_complete_text(result)
    html = _strip_outer_code_fence(html)
    if html.startswith("\ufeff"):
        html = html[1:].lstrip()
    if "```" in html:
        raise GeneratedHtmlError("Generated HTML contains an unexpected code fence.")
    doctype_match = re.match(r"^<!doctype\s+html\s*>", html, re.IGNORECASE)
    if not doctype_match:
        raise GeneratedHtmlError(
            "Generated HTML must begin with the HTML doctype and no provider chatter."
        )
    if not re.match(
        r"^\s*<html(?:\s|>)",
        html[doctype_match.end() :],
        re.IGNORECASE,
    ):
        raise GeneratedHtmlError(
            "Generated HTML must place the root html element immediately after "
            "the doctype with no provider chatter."
        )
    encoded = html.encode("utf-8")
    if len(encoded) > max_bytes:
        raise GeneratedHtmlError(
            f"Generated HTML is {len(encoded)} bytes; limit is {max_bytes}."
        )
    parser = _DocumentStructureParser()
    parser.feed(html)
    parser.close()
    expected_events = [
        ("declaration", "doctype html"),
        ("start", "html"),
        ("start", "head"),
        ("end", "head"),
        ("start", "body"),
        ("end", "body"),
        ("end", "html"),
    ]
    if parser.events != expected_events:
        raise GeneratedHtmlError(
            "Generated HTML is incomplete or structurally invalid; expected "
            "one ordered doctype, html, head, and body document."
        )
    if not re.search(r"</html>\s*$", html, re.IGNORECASE):
        raise GeneratedHtmlError("Generated HTML contains content after </html>.")
    if parser.has_content_outside_content:
        raise GeneratedHtmlError(
            "Generated HTML contains content outside head or body."
        )
    return html


def atomic_write_text(path: str | os.PathLike[str], content: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _openrouter_content_part(text: str, cacheable: bool) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "text", "text": text}
    if cacheable:
        part["cache_control"] = {"type": "ephemeral"}
    return part


def _require_hex_color(name: str, value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise GeneratedHtmlError(
            f"Document color {name} must be a six-digit hex value."
        )
    return value.upper()


def _replace_root_property(head: str, property_name: str, value: str) -> str:
    pattern = rf"(?m)^(\s*{re.escape(property_name)}\s*:)\s*[^;]+;"
    updated, count = re.subn(
        pattern,
        lambda match: f"{match.group(1)} {value};",
        head,
        count=1,
    )
    if count != 1:
        raise GeneratedHtmlError(
            f"Base template must contain exactly one {property_name} root property."
        )
    return updated


def _llama_cpp_urls(base_url: str) -> tuple[str, str, str]:
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise GenerationConfigurationError(
            "Local generation base URL must be a valid loopback HTTP(S) URL."
        ) from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise GenerationConfigurationError(
            "Local generation base URL must be a loopback HTTP(S) URL."
        )
    normalized_hostname = hostname.rstrip(".").lower()
    if normalized_hostname != "localhost":
        try:
            address = ipaddress.ip_address(normalized_hostname)
        except ValueError as exc:
            raise GenerationConfigurationError(
                "Local generation base URL must use a literal loopback host."
            ) from exc
        if not address.is_loopback:
            raise GenerationConfigurationError(
                "Local generation base URL must use a literal loopback host."
            )
    if parsed.query or parsed.fragment:
        raise GenerationConfigurationError(
            "Local generation base URL cannot contain a query or fragment."
        )

    path = parsed.path.rstrip("/")
    if path not in {"", "/v1"}:
        raise GenerationConfigurationError(
            "Local generation base URL path must be empty or /v1."
        )
    root = urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
    return (
        f"{root}/health",
        f"{root}/v1/models",
        f"{root}/v1/chat/completions",
    )


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    try:
        return dict(usage)
    except (TypeError, ValueError):
        return {}


def _strip_outer_code_fence(content: str) -> str:
    stripped = content.strip()
    match = re.fullmatch(r"```(?:html)?\s*\n?(.*?)\n?```", stripped, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise GenerationConfigurationError(f"{name} must be a number.") from exc
    if value <= 0:
        raise GenerationConfigurationError(f"{name} must be greater than zero.")
    return value


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise GenerationConfigurationError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise GenerationConfigurationError(f"{name} must be greater than zero.")
    return value
