"""Provider-neutral text generation and generated-HTML admission checks."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, replace
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from openai import DefaultHttpxClient, OpenAI

from lib.clients import OPENROUTER_API_KEY, OPENROUTER_BASE_URL


DEFAULT_LOCAL_MODEL = "qwen/qwen3.8-27b"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_LOCAL_API_KEY = "lm-studio"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_LOCAL_TIMEOUT_SECONDS = 7200.0
# Non-HTML generation keeps the historical ceiling. HTML callers apply the
# tighter body-only ceiling before trusted code assembles the final document.
DEFAULT_MAX_OUTPUT_TOKENS = 65536
MAX_GENERATED_BODY_TOKENS = 8192
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_GENERATED_BODY_BYTES = 512 * 1024
SUPPORTED_PROVIDERS = frozenset(("local", "openrouter"))


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

    def handle_decl(self, decl: str) -> None:
        self.has_content_outside_body = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "body":
            self.body_events.append("start")
            self.body_depth += 1
            return
        if tag_name in {"html", "head", "style", "script"}:
            self.forbidden_tags.append(tag_name)
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
        if tag_name in {"html", "head", "style", "script"}:
            self.forbidden_tags.append(tag_name)
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

    def handle_data(self, data: str) -> None:
        if data.strip() and self.body_depth == 0:
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
                or os.environ.get("LM_STUDIO_BASE_URL")
                or DEFAULT_LOCAL_BASE_URL
            ),
            api_key=(
                os.environ.get("LOCAL_GENERATION_API_KEY")
                or os.environ.get("LM_STUDIO_API_KEY")
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
    session.trust_env = config.trust_env
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
    selected_client = client or create_generation_client(config)
    try:
        response = selected_client.models.list()
        available = {item.id for item in response.data}
    except Exception as exc:
        raise GenerationProviderUnavailable(
            "Local generation is unavailable at "
            f"{config.base_url}. Start LM Studio and load the model with: "
            f"lms load {config.model}"
        ) from exc
    if config.model not in available:
        raise GenerationProviderUnavailable(
            f"Local model {config.model!r} is not loaded. Run: lms load {config.model}"
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
    endpoint = _native_lm_studio_chat_url(config.base_url)
    request_body = {
        "model": config.model,
        "system_prompt": system_prompt,
        "input": user_content,
        "temperature": temperature,
        "max_output_tokens": config.max_output_tokens,
        "reasoning": "off",
        "store": False,
    }
    try:
        response = selected_client.post(
            endpoint,
            json=request_body,
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
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

    output = payload.get("output")
    if not isinstance(output, list):
        raise GenerationResponseError(
            "Local generation provider returned no output collection."
        )
    messages: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            raise GenerationResponseError(
                "Local generation provider returned non-message output while "
                "reasoning and tools were disabled."
            )
        content = item.get("content")
        if not isinstance(content, str):
            raise GenerationResponseError(
                "Local generation provider returned a message without text content."
            )
        messages.append(content)
    if len(messages) != 1:
        raise GenerationResponseError(
            "Local generation provider must return exactly one text message."
        )

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise GenerationResponseError(
            "Local generation provider returned no token statistics."
        )
    total_output_tokens = stats.get("total_output_tokens")
    if (
        isinstance(total_output_tokens, bool)
        or not isinstance(total_output_tokens, int)
        or total_output_tokens < 0
    ):
        raise GenerationResponseError(
            "Local generation provider returned invalid output-token statistics."
        )
    finish_reason = (
        "length"
        if total_output_tokens >= config.max_output_tokens
        else "stop"
    )
    return GenerationResult(
        provider=config.provider,
        model=config.model,
        content=messages[0],
        finish_reason=finish_reason,
        usage=dict(stats),
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


def validate_generated_body(
    result: GenerationResult,
    *,
    max_bytes: int = MAX_GENERATED_BODY_BYTES,
    forbidden_square_placeholders: Iterable[str] = (),
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
    if re.search(r"{{[^{}]+}}", body):
        raise GeneratedBodyError(
            "Generated body contains unresolved template placeholders."
        )
    folded_body = body.casefold()
    leaked_square_placeholders = sorted(
        {
            token
            for token in forbidden_square_placeholders
            if isinstance(token, str) and token and token.casefold() in folded_body
        },
        key=str.casefold,
    )
    if leaked_square_placeholders:
        leaked = ", ".join(leaked_square_placeholders[:3])
        raise GeneratedBodyError(
            f"Generated body contains unresolved prompt placeholders: {leaked}."
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
            f"Generated body contains forbidden document or executable tags: {names}."
        )
    if parser.has_content_outside_body:
        raise GeneratedBodyError(
            "Generated body contains content outside its body root."
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
    required_leading_comment_markers: Iterable[str] = (),
    forbidden_square_placeholders: Iterable[str] = (),
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
    )
    body = re.sub(
        r"^<body(?:\s[^>]*)?>",
        f'<body class="{body_theme}">',
        body,
        count=1,
        flags=re.IGNORECASE,
    )

    head_comment = ""
    comment_markers = tuple(required_leading_comment_markers)
    if any(not isinstance(marker, str) or not marker for marker in comment_markers):
        raise GeneratedHtmlError(
            "Required deployment-comment markers must be non-empty strings."
        )
    if comment_markers:
        comment_match = re.match(
            r'^(<body class="(?:theme-light|theme-dark)">)\s*(<!--.*?-->)\s*',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if not comment_match:
            raise GeneratedBodyError(
                "Generated body is missing its leading deployment comment."
            )
        head_comment = comment_match.group(2)
        missing_markers = [
            marker
            for marker in comment_markers
            if marker.casefold() not in head_comment.casefold()
        ]
        if missing_markers:
            raise GeneratedBodyError(
                "Generated body's leading comment does not match the required "
                "deployment-comment contract."
            )
        body = comment_match.group(1) + body[comment_match.end() :]

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


def _native_lm_studio_chat_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GenerationConfigurationError(
            "Local generation base URL must be an absolute HTTP(S) URL."
        )
    if parsed.query or parsed.fragment:
        raise GenerationConfigurationError(
            "Local generation base URL cannot contain a query or fragment."
        )

    path = parsed.path.rstrip("/")
    if path.endswith("/api/v1"):
        native_path = f"{path}/chat"
    elif path.endswith("/v1"):
        native_path = f"{path[:-3]}/api/v1/chat"
    elif not path:
        native_path = "/api/v1/chat"
    else:
        raise GenerationConfigurationError(
            "Local generation base URL path must be empty or end in /v1 or /api/v1."
        )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, native_path, "", "")
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
