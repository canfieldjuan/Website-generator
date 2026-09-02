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
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000/v1"
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
HTML_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
PHONE_LIKE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?1[\s()./-]*)?\(?[2-9]\d{2}\)?[\s./-]*"
    r"[2-9]\d{2}[\s./-]*\d{4}(?!\d)"
)
STREET_ADDRESS_LIKE_PATTERN = re.compile(
    r"(?<!\w)\d{1,7}\s+"
    r"(?:(?:n|s|e|w|north|south|east|west)\.?\s+)?"
    r"(?:(?=[\w.'-]*[A-Za-z])[\w.'-]+\s+){1,6}"
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|"
    r"court|ct|highway|hwy|route|rte|parkway|pkwy|circle|cir|trail|trl|way)"
    r"\.?(?!\w)",
    re.IGNORECASE,
)
DOM_ADJACENCY_BOUNDARY = ":"
DOM_ADJACENCY_BOUNDARY_TAGS = frozenset(
    {
        "a",
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
    }
)
BIDI_PHONE_CONTROLS = frozenset(
    {
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)
ACTIONABLE_URL_ATTRIBUTES = ("href", "action", "formaction", "xlink:href")
EMAIL_LIKE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63})"
    r"(?![A-Za-z0-9-])"
)
UNSTRUCTURED_TESTIMONIAL_TAGS = frozenset(("blockquote", "cite"))
REVIEW_ROOT_CLASSES = frozenset(
    ("review-card", "reviews-aggregate", "reviews-summary-row")
)
ATTRIBUTED_PROSE_PATTERN = re.compile(
    r"[.!?][\"”'‘’]?\s*[—–]\s*[A-Z][A-Za-z'.’\-]+"
    r"(?:\s+(?:[A-Z][A-Za-z'.’\-]+|[A-Z]\.)){0,3}\b"
)
TRUSTED_IMAGE_ERROR_HANDLER = "this.style.display='none'"
NONDETERMINISTIC_RENDERING_TAGS = frozenset(
    {
        "audio",
        "canvas",
        "datalist",
        "details",
        "dialog",
        "iframe",
        "map",
        "noscript",
        "object",
        "template",
        "video",
    }
)
_EXPECTED_PHONE_UNSET = object()
_EXPECTED_EMAIL_UNSET = object()
_EXPECTED_ADDRESS_UNSET = object()
_EXPECTED_FORM_ACTION_UNSET = object()
_EXPECTED_REVIEWS_UNSET = object()
REQUIRED_FOOTER_CLASS_COUNTS = (
    ("site-footer", 1),
    ("footer-grid", 1),
    ("footer-bottom", 1),
)
REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES = (
    ("site-footer", ("footer-grid", "footer-bottom")),
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
class ReviewEvidence:
    author: str
    rating: int | float
    date: str
    platform: str
    text: str


@dataclass(frozen=True)
class ReviewAdmissionContract:
    mode: str
    source_reviews: tuple[ReviewEvidence, ...] = ()
    aggregate_score: int | float | None = None
    aggregate_count: int | None = None
    reviews_url: str | None = None


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
        self.nondeterministic_rendering_tags: list[str] = []
        self.has_content_outside_body = False
        self.visible_text_parts: list[str] = []
        self.decoded_attribute_values: list[str] = []
        self.comment_values: list[str] = []
        self.executable_attributes: list[str] = []
        self.duplicate_attributes: list[str] = []
        self.class_names: set[str] = set()
        self.class_name_counts: dict[str, int] = {}
        self.open_descendants: list[str] = []
        self.structure_errors: list[str] = []
        self.svg_depth = 0

    def handle_decl(self, decl: str) -> None:
        self.has_content_outside_body = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        seen_attribute_names: set[str] = set()
        for name, _value in attrs:
            normalized_name = name.casefold()
            if normalized_name in seen_attribute_names:
                self.duplicate_attributes.append(normalized_name)
            seen_attribute_names.add(normalized_name)
        self.decoded_attribute_values.extend(
            value for _name, value in attrs if value is not None
        )
        element_class_names: set[str] = set()
        for name, value in attrs:
            normalized_name = name.casefold()
            local_name = normalized_name.rsplit(":", 1)[-1]
            decoded_value = unquote(value) if value is not None else ""
            compact_value = re.sub(r"[\x00-\x20\x7f]+", "", decoded_value)
            if (
                local_name.startswith("on")
                or local_name == "srcdoc"
                or compact_value.casefold().startswith(
                    ("javascript:", "vbscript:")
                )
            ):
                self.executable_attributes.append(name)
            if normalized_name != "class" or not value:
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
        if tag_name in NONDETERMINISTIC_RENDERING_TAGS:
            self.nondeterministic_rendering_tags.append(tag_name)
        if tag_name in {"html", "head", "style", "script", "base", "link", "meta"}:
            self.forbidden_tags.append(tag_name)
        elif tag_name == "title" and self.svg_depth == 0:
            self.forbidden_tags.append(tag_name)
        if tag_name == "svg":
            self.svg_depth += 1
        if self.body_depth == 0:
            self.has_content_outside_body = True
        elif tag_name not in HTML_VOID_ELEMENTS:
            self.open_descendants.append(tag_name)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "body":
            self.body_events.append("end")
            if self.open_descendants:
                self.structure_errors.append(
                    f"unclosed <{self.open_descendants[-1]}> before </body>"
                )
            if self.body_depth:
                self.body_depth -= 1
            else:
                self.has_content_outside_body = True
            return
        if tag_name in NONDETERMINISTIC_RENDERING_TAGS:
            self.nondeterministic_rendering_tags.append(tag_name)
        if tag_name in {"html", "head", "style", "script", "base", "link", "meta"}:
            self.forbidden_tags.append(tag_name)
        elif tag_name == "title" and self.svg_depth == 0:
            self.forbidden_tags.append(tag_name)
        if tag_name == "svg" and self.svg_depth:
            self.svg_depth -= 1
        if self.body_depth:
            if tag_name in HTML_VOID_ELEMENTS:
                self.structure_errors.append(
                    f"unexpected closing tag </{tag_name}> for a void element"
                )
            elif not self.open_descendants:
                self.structure_errors.append(f"unexpected closing tag </{tag_name}>")
            elif self.open_descendants[-1] != tag_name:
                self.structure_errors.append(
                    f"misnested closing tag </{tag_name}> while "
                    f"<{self.open_descendants[-1]}> is open"
                )
            else:
                self.open_descendants.pop()
        else:
            self.has_content_outside_body = True

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() == "body":
            self.body_events.extend(("start", "end"))
            self.has_content_outside_body = True
            return
        tag_name = tag.lower()
        is_svg_content = self.svg_depth > 0 or tag_name == "svg"
        self.handle_starttag(tag, attrs)
        if tag_name in HTML_VOID_ELEMENTS:
            return
        if not is_svg_content:
            self.structure_errors.append(
                f"non-void HTML element <{tag_name}> cannot self-close"
            )
        if self.open_descendants and self.open_descendants[-1] == tag_name:
            self.open_descendants.pop()
        if tag_name == "svg" and self.svg_depth:
            self.svg_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.body_depth:
            self.visible_text_parts.append(data)
        elif data.strip():
            self.has_content_outside_body = True

    def handle_comment(self, data: str) -> None:
        if self.body_depth:
            self.comment_values.append(data)
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
                or os.environ.get("VLLM_BASE_URL")
                or DEFAULT_LOCAL_BASE_URL
            ),
            api_key=(
                os.environ.get("LOCAL_GENERATION_API_KEY")
                or os.environ.get("VLLM_API_KEY")
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
    # the configured vLLM URL itself is local. OpenRouter continues to
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
    health_url, models_url, _chat_url = _local_openai_urls(config.base_url)
    preflight_timeout = min(config.timeout_seconds, LOCAL_PREFLIGHT_TIMEOUT_SECONDS)
    try:
        health_response = selected_client.get(
            health_url,
            timeout=preflight_timeout,
            allow_redirects=False,
        )
        _raise_for_local_response_status(health_response)

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
            f"{config.base_url}. Start standalone vLLM with: "
            "scripts/start_vllm_server.sh"
        ) from exc
    if config.model not in available:
        raise GenerationProviderUnavailable(
            f"Local model alias {config.model!r} is not served by vLLM. "
            "Start it with: scripts/start_vllm_server.sh"
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
    _health_url, _models_url, endpoint = _local_openai_urls(config.base_url)
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


def _compact_claim_match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _alphanumeric_tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []
    for character in unicodedata.normalize("NFKC", value).casefold():
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


def _contains_complete_token_sequence(surface: str, expected: str) -> bool:
    expected_compact = _compact_claim_match_text(expected)
    if not expected_compact:
        return False
    tokens = _alphanumeric_tokens(surface)
    for start in range(len(tokens)):
        candidate = ""
        for token in tokens[start:]:
            candidate += token
            if candidate == expected_compact:
                return True
            if (
                len(candidate) >= len(expected_compact)
                or not expected_compact.startswith(candidate)
            ):
                break
    return False


def _phone_scan_components(value: str) -> tuple[str, frozenset[int]]:
    characters: list[str] = []
    bidi_boundaries: set[int] = set()
    for character in unicodedata.normalize("NFKC", value):
        if character.isdecimal():
            characters.append(str(unicodedata.decimal(character)))
        elif unicodedata.category(character) == "Pd":
            characters.append("-")
        elif character in BIDI_PHONE_CONTROLS:
            bidi_boundaries.add(len(characters))
        elif unicodedata.category(character) != "Cf":
            characters.append(character)
    return "".join(characters), frozenset(bidi_boundaries)


def _normalize_phone_scan_text(value: str) -> str:
    return _phone_scan_components(value)[0]


def _canonical_phone_digits(value: str) -> str:
    digits = "".join(
        character
        for character in _normalize_phone_scan_text(value)
        if character.isascii() and character.isdecimal()
    )
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _phone_like_digit_values(value: str) -> set[str]:
    normalized, bidi_boundaries = _phone_scan_components(value)
    digits: set[str] = set()
    for match in PHONE_LIKE_PATTERN.finditer(normalized):
        if any(
            match.start() <= boundary <= match.end()
            for boundary in bidi_boundaries
        ):
            raise GeneratedBodyError(
                "Generated body contains directional controls in phone-shaped data."
            )
        digits.add(_canonical_phone_digits(match.group(0)))
    return digits


def _email_like_values(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value)
    return {
        match.group(1).casefold()
        for match in EMAIL_LIKE_PATTERN.finditer(normalized)
    }


def _canonical_email_value(value: str) -> str | None:
    candidate = unicodedata.normalize("NFKC", unquote(value)).strip()
    match = EMAIL_LIKE_PATTERN.fullmatch(candidate)
    return match.group(1).casefold() if match else None


def _claim_exposure_texts(
    body_root: Tag,
    *,
    excluded_root_classes: Iterable[str] = (),
) -> tuple[tuple[str, str], str]:
    visual_parts: list[str] = []
    phone_visual_parts: list[str] = []
    id_targets: dict[str, list[Tag]] = {}
    excluded_classes = frozenset(excluded_root_classes)

    def is_excluded(node: Tag) -> bool:
        return bool(_exact_class_names(node) & excluded_classes) or any(
            _exact_class_names(parent) & excluded_classes
            for parent in node.parents
            if isinstance(parent, Tag)
        )

    for element in (body_root, *body_root.find_all(True)):
        if is_excluded(element):
            continue
        identifier = element.get("id")
        if isinstance(identifier, str) and identifier:
            id_targets.setdefault(identifier, []).append(element)

    def is_hidden_input(node: Tag) -> bool:
        return (
            node.name.casefold() == "input"
            and str(node.get("type") or "").casefold() == "hidden"
        )

    def is_render_suppressed(node: Tag) -> bool:
        if is_hidden_input(node) or node.has_attr("hidden"):
            return True
        style = node.get("style")
        if not isinstance(style, str):
            return False
        return bool(
            re.search(
                r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|"
                r"content-visibility\s*:\s*hidden)\s*"
                r"(?:!\s*important\s*)?(?:;|$)",
                style,
                re.IGNORECASE,
            )
        )

    def replacement_text(node: Tag) -> str:
        if node.name.casefold() == "img":
            value = node.get("alt")
            return value if isinstance(value, str) else ""
        if node.name.casefold() in {"input", "textarea"}:
            value = node.get("value") or node.get("placeholder")
            return value if isinstance(value, str) else ""
        return ""

    def tooltip_text(node: Tag) -> str:
        value = node.get("title")
        return value if isinstance(value, str) else ""

    def visit_visual(node: Any) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            text = str(node)
            visual_parts.append(text)
            phone_visual_parts.append(text)
            return
        if not isinstance(node, Tag):
            return
        if is_excluded(node):
            return
        if is_render_suppressed(node):
            return
        has_text_boundary = node.name.casefold() in DOM_ADJACENCY_BOUNDARY_TAGS
        if has_text_boundary:
            phone_visual_parts.append(DOM_ADJACENCY_BOUNDARY)
        tooltip = tooltip_text(node)
        if tooltip:
            visual_parts.append(tooltip)
        replacement = replacement_text(node)
        if replacement:
            visual_parts.append(replacement)
            phone_visual_parts.append(replacement)
        for child in node.children:
            visit_visual(child)
        if has_text_boundary:
            phone_visual_parts.append(DOM_ADJACENCY_BOUNDARY)

    def resolve_references(
        node: Tag,
        attribute: str,
        active_references: frozenset[str],
    ) -> str:
        value = node.get(attribute)
        if not isinstance(value, str) or not value.strip():
            return ""
        resolved_parts: list[str] = []
        for reference in value.split():
            targets = id_targets.get(reference, ())
            if len(targets) != 1 or reference in active_references:
                raise GeneratedBodyError(
                    "Generated body contains an invalid indirect accessibility "
                    f"text reference in {attribute}: {reference!r}."
                )
            resolved_parts.append(
                accessible_text(targets[0], active_references | {reference})
            )
        return " ".join(resolved_parts)

    def accessible_text(node: Any, active_references: frozenset[str]) -> str:
        if isinstance(node, Comment):
            return ""
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        if is_excluded(node):
            return ""
        if is_hidden_input(node):
            return ""
        aria_hidden = node.get("aria-hidden")
        if not active_references and (
            is_render_suppressed(node)
            or (
                isinstance(aria_hidden, str)
                and aria_hidden.strip().casefold() == "true"
            )
        ):
            return ""

        labelled_by = node.get("aria-labelledby")
        label = node.get("aria-label")
        if isinstance(labelled_by, str) and labelled_by.strip():
            primary_text = resolve_references(
                node,
                "aria-labelledby",
                active_references,
            )
        elif isinstance(label, str) and label:
            primary_text = label
        else:
            primary_text = replacement_text(node) + "".join(
                accessible_text(child, active_references) for child in node.children
            )

        direct_description = node.get("aria-description")
        descriptions = (
            [direct_description]
            if isinstance(direct_description, str) and direct_description
            else []
        )
        descriptions.extend(
            resolve_references(node, attribute, active_references)
            for attribute in ("aria-describedby", "aria-details", "aria-errormessage")
            if isinstance(node.get(attribute), str) and node.get(attribute).strip()
        )
        return " ".join((primary_text, *descriptions))

    accessible_parts: list[str] = []

    def visit_accessible(node: Any) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            accessible_parts.append(str(node))
            return
        if (
            not isinstance(node, Tag)
            or is_excluded(node)
            or is_hidden_input(node)
        ):
            return
        aria_hidden = node.get("aria-hidden")
        if is_render_suppressed(node) or (
            isinstance(aria_hidden, str)
            and aria_hidden.strip().casefold() == "true"
        ):
            return
        accessible_parts.append(accessible_text(node, frozenset()))
        for child in node.children:
            visit_accessible(child)

    visit_visual(body_root)
    visit_accessible(body_root)
    return (
        (" ".join(visual_parts), " ".join(accessible_parts)),
        "".join(phone_visual_parts),
    )


def _exact_class_names(element: Tag) -> set[str]:
    classes = element.get("class", ())
    if isinstance(classes, str):
        return set(classes.split())
    return {value for value in classes if isinstance(value, str)}


def _elements_with_class(root: Tag, class_name: str) -> list[Tag]:
    return [
        element
        for element in (root, *root.find_all(True))
        if class_name in _exact_class_names(element)
    ]


def _inside_review_root(element: Tag) -> bool:
    return bool(_exact_class_names(element) & REVIEW_ROOT_CLASSES) or any(
        _exact_class_names(parent) & REVIEW_ROOT_CLASSES
        for parent in element.parents
        if isinstance(parent, Tag)
    )


def _validate_no_unstructured_testimonials(body_root: Tag) -> None:
    for element in (body_root, *body_root.find_all(True)):
        if _inside_review_root(element):
            continue
        if element.name.casefold() in UNSTRUCTURED_TESTIMONIAL_TAGS:
            raise GeneratedBodyError(
                "Generated body contains an unstructured testimonial tag."
            )

    exposure_surfaces, inline_surface = _claim_exposure_texts(
        body_root,
        excluded_root_classes=REVIEW_ROOT_CLASSES,
    )
    if any(
        ATTRIBUTED_PROSE_PATTERN.search(surface)
        for surface in (*exposure_surfaces, inline_surface)
    ):
        raise GeneratedBodyError(
            "Generated body contains unstructured testimonial content."
        )


def _single_component(root: Tag, class_name: str, owner: str) -> Tag:
    matches = _elements_with_class(root, class_name)
    if len(matches) != 1:
        raise GeneratedBodyError(
            f"Generated body {owner} must contain exactly one {class_name}."
        )
    return matches[0]


def _canonical_component(
    root: Tag,
    class_name: str,
    tag_name: str,
    owner: str,
    *,
    allowed_attributes: Iterable[str] = (),
) -> Tag:
    element = _single_component(root, class_name, owner)
    if element.name.casefold() != tag_name:
        if tag_name == "a":
            raise GeneratedBodyError(
                f"Generated body {owner} CTA must be an anchor."
            )
        raise GeneratedBodyError(
            f"Generated body {owner} {class_name} must be a {tag_name} element."
        )
    if _exact_class_names(element) != {class_name}:
        raise GeneratedBodyError(
            f"Generated body {owner} {class_name} has an invalid class shape."
        )
    allowed = {"class", *allowed_attributes}
    unexpected = sorted(set(element.attrs) - allowed)
    if unexpected:
        raise GeneratedBodyError(
            "Generated body review component attribute is unsupported: "
            + ", ".join(unexpected[:3])
            + "."
        )
    return element


def _require_direct_components(
    parent: Tag,
    expected: tuple[Tag, ...],
    owner: str,
    *,
    allow_direct_text: bool = False,
) -> None:
    actual: list[Tag] = []
    has_unexpected_content = False
    for child in parent.children:
        if isinstance(child, Tag):
            actual.append(child)
        elif isinstance(child, Comment):
            has_unexpected_content = True
        elif isinstance(child, NavigableString):
            if child.strip() and not allow_direct_text:
                has_unexpected_content = True
        else:
            has_unexpected_content = True
    if tuple(actual) != expected or has_unexpected_content:
        raise GeneratedBodyError(
            f"Generated body {owner} has an invalid component hierarchy."
        )


def _canonical_star_component(
    root: Tag,
    class_name: str,
    owner: str,
) -> Tag:
    stars = _canonical_component(
        root,
        class_name,
        "span",
        owner,
        allowed_attributes=("style",),
    )
    if _normalized_plain_review_text(stars, owner) != "★★★★★":
        raise GeneratedBodyError(
            f"Generated body {owner} has invalid review star content."
        )
    return stars


def _score_style_value(element: Tag, owner: str) -> float:
    style = element.get("style")
    if not isinstance(style, str):
        raise GeneratedBodyError(f"Generated body {owner} has no review score style.")
    declarations = re.findall(
        r"(?:^|;)\s*--score\s*:\s*([^;]+?)\s*(?=;|$)",
        style,
        re.IGNORECASE,
    )
    if len(declarations) != 1 or not re.fullmatch(
        r"(?:\d+(?:\.\d*)?|\.\d+)",
        declarations[0].strip(),
    ):
        raise GeneratedBodyError(
            f"Generated body {owner} has an invalid review score style."
        )
    return float(declarations[0])


def _direct_text(element: Tag) -> str:
    return " ".join(
        str(child)
        for child in element.children
        if isinstance(child, NavigableString)
    )


def _normalized_plain_review_text(element: Tag, owner: str) -> str:
    if any(
        isinstance(child, (Tag, Comment))
        for child in element.children
    ):
        raise GeneratedBodyError(
            f"Generated body {owner} must contain plain canonical review text."
        )
    return _normalize_claim_match_text(_direct_text(element))


def _normalized_review_evidence(card: Tag) -> ReviewEvidence:
    canonical_card = _canonical_component(card, "review-card", "div", "review card")
    stars = _canonical_star_component(
        canonical_card,
        "review-stars-sm",
        "review card",
    )
    text = _canonical_component(
        canonical_card,
        "review-text",
        "p",
        "review card",
    )
    meta = _canonical_component(
        canonical_card,
        "review-meta",
        "div",
        "review card",
    )
    author = _canonical_component(
        canonical_card,
        "review-author",
        "span",
        "review card",
    )
    date = _canonical_component(
        canonical_card,
        "review-date",
        "span",
        "review card",
    )
    platform = _canonical_component(
        canonical_card,
        "review-platform",
        "span",
        "review card",
    )
    _require_direct_components(canonical_card, (stars, text, meta), "review card")
    _require_direct_components(meta, (author, platform), "review card")
    _require_direct_components(
        author,
        (date,),
        "review card author",
        allow_direct_text=True,
    )
    return ReviewEvidence(
        author=_normalize_claim_match_text(_direct_text(author)),
        rating=_score_style_value(stars, "review card"),
        date=_normalized_plain_review_text(date, "review card date"),
        platform=_normalized_plain_review_text(platform, "review card platform"),
        text=_normalized_plain_review_text(text, "review card text"),
    )


def _normalized_source_review(review: ReviewEvidence) -> ReviewEvidence:
    return ReviewEvidence(
        author=_normalize_claim_match_text(review.author),
        rating=float(review.rating),
        date=_normalize_claim_match_text(review.date),
        platform=_normalize_claim_match_text(review.platform),
        text=_normalize_claim_match_text(review.text),
    )


def _ambient_review_claim_values(body_root: Tag) -> tuple[list[float], list[int]]:
    exposure_surfaces, inline_surface = _claim_exposure_texts(
        body_root,
        excluded_root_classes=REVIEW_ROOT_CLASSES,
    )
    text = _normalize_claim_match_text(
        " ".join((*exposure_surfaces, inline_surface))
    )
    score_patterns = (
        r"\b(?:rated|rating)\s*(?:at\s*)?([0-5](?:\.\d+)?)\b",
        r"\b([0-5](?:\.\d+)?)\s*(?:/|out\s+of)\s*5\b",
        r"\b([0-5](?:\.\d+)?)\s*stars?\b",
        r"\b([0-5](?:\.\d+)?)\s+from\s+\d+\s+(?:google\s+)?reviews?\b",
    )
    count_patterns = (
        r"\b(\d+)\s+(?:google\s+)?reviews?\b",
        r"\b(?:rated|rating)\s*(?:at\s*)?[0-5](?:\.\d+)?\s+"
        r"(?:by|from)\s+(\d+)\s+(?:customers?|reviewers?)\b",
    )
    scores = [
        float(match.group(1))
        for pattern in score_patterns
        for match in re.finditer(pattern, text)
    ]
    counts = [
        int(match.group(1))
        for pattern in count_patterns
        for match in re.finditer(pattern, text)
    ]
    return scores, counts


def _validate_ambient_review_claims(
    body_root: Tag,
    contract: ReviewAdmissionContract,
) -> None:
    score = contract.aggregate_score
    count = contract.aggregate_count
    scores, counts = _ambient_review_claim_values(body_root)
    if scores and score is None:
        raise GeneratedBodyError(
            "Generated body contains an unsourced ambient review score."
        )
    if any(candidate != float(score) for candidate in scores):
        raise GeneratedBodyError(
            "Generated body contains an unexpected ambient review score."
        )
    if counts and count is None:
        raise GeneratedBodyError(
            "Generated body contains an unsourced ambient review count."
        )
    if any(candidate != count for candidate in counts):
        raise GeneratedBodyError(
            "Generated body contains an unexpected ambient review count."
        )

    if _elements_with_class(body_root, "form-trust-stars"):
        raise GeneratedBodyError(
            "Generated body contains a review star widget without a scored overlay."
        )
    for class_name in ("trust-stars", "cta-trust-stars"):
        for stars in _elements_with_class(body_root, class_name):
            if score is None:
                raise GeneratedBodyError(
                    "Generated body contains an unsourced ambient review star widget."
                )
            canonical_stars = _canonical_star_component(
                stars,
                class_name,
                "ambient review widget",
            )
            if _score_style_value(canonical_stars, "ambient review widget") != float(score):
                raise GeneratedBodyError(
                    "Generated body contains an unexpected ambient review score."
                )


def _validate_review_summary(
    root: Tag,
    contract: ReviewAdmissionContract,
    *,
    aggregate: bool,
) -> None:
    owner = "aggregate review" if aggregate else "review summary"
    score_class = "reviews-score" if aggregate else "reviews-summary-text"
    stars_class = "reviews-stars-lg" if aggregate else "reviews-summary-stars"
    count_class = "reviews-count" if aggregate else "reviews-summary-text"
    link_class = "reviews-cta" if aggregate else "reviews-summary-cta"
    score = contract.aggregate_score
    count = contract.aggregate_count
    if score is None or count is None or contract.reviews_url is None:
        raise GeneratedBodyError(
            f"Generated body {owner} has no complete source review evidence."
        )

    root_class = "reviews-aggregate" if aggregate else "reviews-summary-row"
    canonical_root = _canonical_component(root, root_class, "div", owner)
    stars = _canonical_star_component(canonical_root, stars_class, owner)
    if _score_style_value(stars, owner) != float(score):
        raise GeneratedBodyError(f"Generated body {owner} has the wrong review score.")
    score_element = _canonical_component(
        canonical_root,
        score_class,
        "div" if aggregate else "span",
        owner,
    )
    count_element = (
        _canonical_component(canonical_root, count_class, "div", owner)
        if aggregate
        else score_element
    )
    link = _canonical_component(
        canonical_root,
        link_class,
        "a",
        owner,
        allowed_attributes=("href", "target", "rel"),
    )
    if aggregate:
        of_five = _canonical_component(
            score_element,
            "of-five",
            "span",
            owner,
        )
        _require_direct_components(
            score_element,
            (of_five,),
            owner,
            allow_direct_text=True,
        )
        _require_direct_components(
            canonical_root,
            (stars, score_element, count_element, link),
            owner,
        )
        if _normalize_claim_match_text(_direct_text(score_element)) != (
            _normalize_claim_match_text(str(score))
        ):
            raise GeneratedBodyError(f"Generated body {owner} has the wrong review score.")
        if _normalized_plain_review_text(of_five, owner) != "out of 5":
            raise GeneratedBodyError(f"Generated body {owner} has invalid score text.")
        if _normalized_plain_review_text(count_element, owner) != (
            _normalize_claim_match_text(f"Based on {count} reviews on Google")
        ):
            raise GeneratedBodyError(f"Generated body {owner} has the wrong review count.")
        allowed_link_text = {
            "read all reviews on google",
            "read all reviews on google →",
        }
    else:
        strong_elements = tuple(score_element.find_all("strong", recursive=False))
        if len(strong_elements) != 1 or strong_elements[0].attrs:
            raise GeneratedBodyError(
                "Generated body review summary has an invalid score element."
            )
        _require_direct_components(
            score_element,
            strong_elements,
            owner,
            allow_direct_text=True,
        )
        _require_direct_components(
            canonical_root,
            (stars, score_element, link),
            owner,
        )
        if _normalized_plain_review_text(
            strong_elements[0], owner
        ) != _normalize_claim_match_text(f"{score} out of 5"):
            raise GeneratedBodyError(f"Generated body {owner} has the wrong review score.")
        summary_count_text = _normalize_claim_match_text(
            _direct_text(score_element)
        ).removeprefix("·").strip()
        if summary_count_text != _normalize_claim_match_text(
            f"Based on {count} Google Reviews"
        ):
            raise GeneratedBodyError(f"Generated body {owner} has the wrong review count.")
        allowed_link_text = {
            "read all on google",
            "read all on google →",
        }
    if _normalized_plain_review_text(link, owner) not in allowed_link_text:
        raise GeneratedBodyError(f"Generated body {owner} has invalid CTA text.")
    if link.get("href") != contract.reviews_url:
        raise GeneratedBodyError(f"Generated body {owner} has the wrong reviews URL.")


def _validate_review_contract(
    body_root: Tag,
    contract: ReviewAdmissionContract,
) -> None:
    _validate_no_unstructured_testimonials(body_root)
    if contract.mode == "omit":
        _validate_ambient_review_claims(body_root, contract)
        return
    if contract.mode == "aggregate":
        aggregate = _single_component(
            body_root,
            "reviews-aggregate",
            "aggregate review",
        )
        _validate_review_summary(aggregate, contract, aggregate=True)
        _validate_ambient_review_claims(body_root, contract)
        return
    if contract.mode != "cards" or len(contract.source_reviews) < 3:
        raise GeneratedBodyError("Expected review admission contract is invalid.")

    grid = _canonical_component(
        body_root,
        "reviews-card-grid",
        "div",
        "review cards",
    )
    cards = _elements_with_class(grid, "review-card")
    if len(cards) != 3:
        raise GeneratedBodyError(
            "Generated body review cards must contain exactly three review cards."
        )
    _require_direct_components(grid, tuple(cards), "review cards")
    available = [
        _normalized_source_review(review) for review in contract.source_reviews
    ]
    for card in cards:
        rendered = _normalized_review_evidence(card)
        try:
            matched_index = available.index(rendered)
        except ValueError as exc:
            raise GeneratedBodyError(
                "Generated body review card does not match a source review entry."
            ) from exc
        available.pop(matched_index)

    summaries = _elements_with_class(body_root, "reviews-summary-row")
    has_aggregate = (
        contract.aggregate_score is not None
        and contract.aggregate_count is not None
        and contract.reviews_url is not None
    )
    if has_aggregate:
        if len(summaries) != 1:
            raise GeneratedBodyError(
                "Generated body review cards require one sourced review summary."
            )
        _validate_review_summary(summaries[0], contract, aggregate=False)
    elif summaries:
        raise GeneratedBodyError(
            "Generated body review cards contain an unsourced review summary."
        )
    _validate_ambient_review_claims(body_root, contract)


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


def _validate_expected_address(
    body_root: Tag,
    expected_address: object,
    address_surfaces: Iterable[str],
) -> None:
    address_components = _elements_with_class(body_root, "ft-address")
    expected_compact = None
    if expected_address is None:
        if address_components:
            raise GeneratedBodyError(
                "Generated body contains a footer address with no verified address."
            )
    else:
        if not isinstance(expected_address, str) or not expected_address.strip():
            raise GeneratedBodyError("Expected business address must be text or null.")
        if len(address_components) != 1:
            raise GeneratedBodyError(
                "Generated body must contain exactly one verified footer address."
            )
        expected_tokens = _alphanumeric_tokens(expected_address)
        actual_tokens = _alphanumeric_tokens(
            " ".join(address_components[0].stripped_strings)
        )
        if not expected_tokens or actual_tokens[: len(expected_tokens)] != expected_tokens:
            raise GeneratedBodyError(
                "Generated body footer address does not match the verified address."
            )
        expected_compact = _compact_claim_match_text(expected_address)

    for surface in address_surfaces:
        for match in STREET_ADDRESS_LIKE_PATTERN.finditer(
            unicodedata.normalize("NFKC", surface)
        ):
            address_compact = _compact_claim_match_text(match.group(0))
            if expected_compact is None or address_compact not in expected_compact:
                raise GeneratedBodyError(
                    "Generated body contains an unexpected physical address."
                )


def _validate_exact_source_claims(
    claim_surfaces: Iterable[str],
    exact_source_claims: Iterable[tuple[str, str, str]],
) -> None:
    normalized_surfaces = tuple(
        _normalize_claim_match_text(surface) for surface in claim_surfaces
    )
    for label, trigger, exact_phrase in exact_source_claims:
        if not all(
            isinstance(value, str) and _normalize_claim_match_text(value)
            for value in (label, trigger, exact_phrase)
        ):
            raise GeneratedBodyError("Exact source-claim contract is invalid.")
        normalized_trigger = _normalize_claim_match_text(trigger)
        normalized_phrase = _normalize_claim_match_text(exact_phrase)
        trigger_pattern = re.compile(
            rf"(?<!\w){re.escape(normalized_trigger)}(?!\w)"
        )
        exact_pattern = re.compile(
            rf"{re.escape(normalized_phrase)}(?!\w)"
        )
        if not trigger_pattern.match(normalized_phrase):
            raise GeneratedBodyError("Exact source-claim trigger is invalid.")
        for surface in normalized_surfaces:
            for match in trigger_pattern.finditer(surface):
                if exact_pattern.match(surface, match.start()) is None:
                    raise GeneratedBodyError(
                        "Generated body contains a source-owned claim that does "
                        f"not match verified {label}."
                    )


def validate_generated_body(
    result: GenerationResult,
    *,
    max_bytes: int = MAX_GENERATED_BODY_BYTES,
    forbidden_square_placeholders: Iterable[str] = (),
    forbidden_visible_phrases: Iterable[str] = (),
    forbidden_comment_markers: Iterable[str] = (),
    forbidden_class_names: Iterable[str] = (),
    allowed_class_names: Iterable[str] | None = None,
    required_exposed_values: Iterable[tuple[str, str]] = (),
    expected_phone: object = _EXPECTED_PHONE_UNSET,
    expected_email: object = _EXPECTED_EMAIL_UNSET,
    expected_address: object = _EXPECTED_ADDRESS_UNSET,
    exact_source_claims: Iterable[tuple[str, str, str]] = (),
    expected_form_action: object = _EXPECTED_FORM_ACTION_UNSET,
    expected_reviews: object = _EXPECTED_REVIEWS_UNSET,
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
    if parser.structure_errors or parser.open_descendants:
        detail = (
            parser.structure_errors[0]
            if parser.structure_errors
            else f"unclosed <{parser.open_descendants[-1]}>"
        )
        raise GeneratedBodyError(
            f"Generated body has invalid descendant structure: {detail}."
        )
    if parser.forbidden_tags:
        names = ", ".join(sorted(set(parser.forbidden_tags)))
        raise GeneratedBodyError(
            "Generated body contains forbidden document, metadata, or "
            f"executable tags: {names}."
        )
    if parser.duplicate_attributes:
        names = ", ".join(sorted(set(parser.duplicate_attributes)))
        raise GeneratedBodyError(
            f"Generated body contains a duplicate attribute name: {names}."
        )
    if parser.executable_attributes:
        names = ", ".join(sorted(set(parser.executable_attributes)))
        raise GeneratedBodyError(
            f"Generated body contains an executable attribute: {names}."
        )
    if parser.nondeterministic_rendering_tags:
        names = ", ".join(sorted(set(parser.nondeterministic_rendering_tags)))
        raise GeneratedBodyError(
            f"Generated body contains a browser-inert tag: {names}."
        )
    normalized_comments = tuple(
        _normalize_claim_match_text(comment) for comment in parser.comment_values
    )
    compact_comments = tuple(
        _compact_claim_match_text(comment) for comment in parser.comment_values
    )
    leaked_comment_markers = sorted(
        {
            marker
            for marker in forbidden_comment_markers
            if isinstance(marker, str)
            and marker
            and (
                any(
                    _normalize_claim_match_text(marker) in comment
                    for comment in normalized_comments
                )
                or any(
                    _compact_claim_match_text(marker) in comment
                    for comment in compact_comments
                )
            )
        },
        key=str.casefold,
    )
    if leaked_comment_markers:
        leaked = ", ".join(leaked_comment_markers[:3])
        raise GeneratedBodyError(
            "Generated body contains code-owned deployment metadata in a "
            f"comment: {leaked}."
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
        case_variants = sorted(
            candidate
            for candidate in parser.class_name_counts
            if candidate != class_name
            and candidate.casefold() == class_name.casefold()
        )
        if case_variants:
            class_count_mismatches.append(
                f"{class_name} has invalid case variant: {', '.join(case_variants[:3])}"
            )
            continue
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
    if allowed_class_names is not None:
        allowed_classes = {
            class_name
            for class_name in allowed_class_names
            if isinstance(class_name, str) and class_name
        }
        unknown_class_names = sorted(
            parser.class_names - allowed_classes,
            key=str.casefold,
        )
        if unknown_class_names:
            unknown = ", ".join(unknown_class_names[:3])
            raise GeneratedBodyError(
                "Generated body contains classes outside the allowed class "
                f"catalog: {unknown}."
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

    if expected_reviews is not _EXPECTED_REVIEWS_UNSET:
        if not isinstance(expected_reviews, ReviewAdmissionContract):
            raise GeneratedBodyError("Expected review admission contract is invalid.")
        _validate_review_contract(body_root, expected_reviews)

    if expected_form_action is not _EXPECTED_FORM_ACTION_UNSET:
        if not isinstance(expected_form_action, str) or not expected_form_action:
            raise GeneratedBodyError(
                "Expected contact form action must be a non-empty string."
            )
        forms = body_root.find_all("form")
        if len(forms) != 1:
            raise GeneratedBodyError(
                "Generated body must contain exactly one generated form."
            )
        contact_form = forms[0]
        if "contact-form-wrap" not in _exact_class_names(contact_form):
            raise GeneratedBodyError(
                "Generated body must contain exactly one contact form action owner."
            )
        actual_action = contact_form.get("action")
        if actual_action != expected_form_action:
            raise GeneratedBodyError(
                "Generated body contact form action does not match the verified endpoint."
            )
        alternate_actions = [
            element.get("formaction")
            for element in body_root.find_all(True)
            if element.has_attr("formaction")
        ]
        if any(action != expected_form_action for action in alternate_actions):
            raise GeneratedBodyError(
                "Generated body contains an alternate unverified contact form action."
            )

    exposure_surfaces, dom_adjacent_visual_surface = _claim_exposure_texts(body_root)
    claim_surfaces = (
        *exposure_surfaces,
        *parser.decoded_attribute_values,
        *(unquote(value) for value in parser.decoded_attribute_values),
    )
    exact_claim_surfaces = (
        exposure_surfaces[0],
        body_root.get_text(" ", strip=True),
        *parser.decoded_attribute_values,
        *(unquote(value) for value in parser.decoded_attribute_values),
    )
    if expected_address is not _EXPECTED_ADDRESS_UNSET:
        _validate_expected_address(
            body_root,
            expected_address,
            exact_claim_surfaces,
        )
    _validate_exact_source_claims(exact_claim_surfaces, exact_source_claims)
    missing_exposed_values = []
    for label, value in required_exposed_values:
        if not any(
            _contains_complete_token_sequence(surface, value)
            for surface in exposure_surfaces
        ):
            missing_exposed_values.append(label)
    if missing_exposed_values:
        missing = ", ".join(missing_exposed_values[:3])
        raise GeneratedBodyError(
            f"Generated body is missing required visible substitution: {missing}."
        )

    if expected_email is not _EXPECTED_EMAIL_UNSET:
        expected_email_value = None
        if expected_email is not None:
            if not isinstance(expected_email, str):
                raise GeneratedBodyError(
                    "Expected business email must be text or null."
                )
            expected_email_value = _canonical_email_value(expected_email)
            if expected_email_value is None:
                raise GeneratedBodyError(
                    "Expected business email must be one complete email address."
                )

        email_surfaces = (
            dom_adjacent_visual_surface,
            *parser.decoded_attribute_values,
            *(unquote(value) for value in parser.decoded_attribute_values),
        )
        exposed_emails: set[str] = set()
        for surface in email_surfaces:
            exposed_emails.update(_email_like_values(surface))
        mailto_targets = []
        for element in (body_root, *body_root.find_all(True)):
            for attribute in ("href", "xlink:href"):
                value = element.get(attribute)
                if not isinstance(value, str):
                    continue
                decoded_value = unquote(value).strip()
                if decoded_value.casefold().startswith("mailto:"):
                    mailbox = decoded_value[7:].split("?", 1)[0].strip()
                    mailto_targets.append(_canonical_email_value(mailbox))

        if expected_email_value is None:
            if exposed_emails or mailto_targets:
                raise GeneratedBodyError(
                    "Generated body contains an email with no verified business email."
                )
        elif (
            exposed_emails - {expected_email_value}
            or any(target != expected_email_value for target in mailto_targets)
        ):
            raise GeneratedBodyError(
                "Generated body contains an unexpected business email."
            )

    if expected_phone is not _EXPECTED_PHONE_UNSET:
        exposed_phone_digits: set[str] = set()
        for surface in (*exposure_surfaces, dom_adjacent_visual_surface):
            exposed_phone_digits.update(_phone_like_digit_values(surface))
        actionable_phone_digits: set[str] = set()
        tel_targets = []
        for element in (body_root, *body_root.find_all(True)):
            for attribute in ACTIONABLE_URL_ATTRIBUTES:
                value = element.get(attribute)
                if not isinstance(value, str):
                    continue
                decoded_value = unquote(value).strip()
                actionable_phone_digits.update(
                    _phone_like_digit_values(decoded_value)
                )
                if (
                    attribute in {"href", "xlink:href"}
                    and decoded_value.casefold().startswith("tel:")
                ):
                    tel_targets.append(decoded_value)
        if expected_phone is None:
            if exposed_phone_digits or actionable_phone_digits:
                raise GeneratedBodyError(
                    "Generated body contains a phone-like value with no verified phone."
                )
            if tel_targets:
                raise GeneratedBodyError(
                    "Generated body contains a tel target with no verified phone."
                )
        else:
            expected_digits = _canonical_phone_digits(str(expected_phone))
            unexpected_exposed_phone = exposed_phone_digits - {expected_digits}
            if unexpected_exposed_phone:
                raise GeneratedBodyError(
                    "Generated body contains an unexpected exposed phone."
                )
            if not tel_targets:
                raise GeneratedBodyError(
                    "Generated body is missing the required tel target for phone."
                )
            unexpected_targets = [
                target
                for target in tel_targets
                if _canonical_phone_digits(target[4:]) != expected_digits
            ]
            if unexpected_targets:
                raise GeneratedBodyError(
                    "Generated body contains an unexpected tel target for phone."
                )
            unexpected_actionable_phone = actionable_phone_digits - {expected_digits}
            if unexpected_actionable_phone:
                raise GeneratedBodyError(
                    "Generated body contains an unexpected actionable phone."
                )
    normalized_claim_surfaces = tuple(
        _normalize_claim_match_text(surface) for surface in claim_surfaces
    )
    compact_claim_surfaces = tuple(
        _compact_claim_match_text(surface) for surface in claim_surfaces
    )
    leaked_phrases = sorted(
        {
            phrase
            for phrase in forbidden_visible_phrases
            if isinstance(phrase, str)
            and phrase
            and _normalize_claim_match_text(phrase)
            and (
                any(
                    _normalize_claim_match_text(phrase) in surface
                    for surface in normalized_claim_surfaces
                )
                or any(
                    _compact_claim_match_text(phrase) in surface
                    for surface in compact_claim_surfaces
                )
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


def _add_trusted_image_fallbacks(body: str) -> str:
    parsed_body = BeautifulSoup(body, "html.parser")
    body_root = parsed_body.find("body")
    if not isinstance(body_root, Tag):
        raise GeneratedHtmlError("Generated body root could not be parsed for assembly.")
    images = body_root.find_all("img")
    if not images:
        return body
    for image in images:
        image["onerror"] = TRUSTED_IMAGE_ERROR_HANDLER
    return str(body_root)


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
    forbidden_comment_markers: Iterable[str] = (),
    forbidden_class_names: Iterable[str] = (),
    allowed_class_names: Iterable[str] | None = None,
    required_exposed_values: Iterable[tuple[str, str]] = (),
    expected_phone: object = _EXPECTED_PHONE_UNSET,
    expected_email: object = _EXPECTED_EMAIL_UNSET,
    expected_address: object = _EXPECTED_ADDRESS_UNSET,
    exact_source_claims: Iterable[tuple[str, str, str]] = (),
    expected_form_action: object = _EXPECTED_FORM_ACTION_UNSET,
    expected_reviews: object = _EXPECTED_REVIEWS_UNSET,
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
        forbidden_comment_markers=forbidden_comment_markers,
        forbidden_class_names=forbidden_class_names,
        allowed_class_names=allowed_class_names,
        required_exposed_values=required_exposed_values,
        expected_phone=expected_phone,
        expected_email=expected_email,
        expected_address=expected_address,
        exact_source_claims=exact_source_claims,
        expected_form_action=expected_form_action,
        expected_reviews=expected_reviews,
        required_class_counts=required_class_counts,
        required_child_class_sequences=required_child_class_sequences,
    )
    body = _add_trusted_image_fallbacks(body)
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


def _local_openai_urls(base_url: str) -> tuple[str, str, str]:
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
