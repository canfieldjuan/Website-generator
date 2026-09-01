"""Provider-neutral text generation and generated-HTML admission checks."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from openai import DefaultHttpxClient, OpenAI

from lib.clients import OPENROUTER_API_KEY, OPENROUTER_BASE_URL


DEFAULT_LOCAL_MODEL = "qwen/qwen3.8-27b"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_LOCAL_API_KEY = "lm-studio"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_OUTPUT_TOKENS = 16384
MAX_HTML_BYTES = 2 * 1024 * 1024
SUPPORTED_PROVIDERS = frozenset(("local", "openrouter"))


class GenerationConfigurationError(ValueError):
    """The selected provider cannot be configured from explicit inputs."""


class GenerationProviderUnavailable(RuntimeError):
    """The configured generation provider or model is not currently usable."""


class GenerationResponseError(RuntimeError):
    """The provider returned no usable completed response."""


class GeneratedHtmlError(ValueError):
    """Generated output is not a complete standalone HTML document."""


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

    timeout_seconds = _positive_float_env(
        "GENERATION_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
    )
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
        **client_options,
    )


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
    selected_client = client or create_generation_client(config)
    parts = tuple(user_parts)
    if config.provider == "openrouter":
        system_content: Any = [
            _openrouter_content_part(system_prompt, cache_system_prompt)
        ]
        user_content: Any = [
            _openrouter_content_part(part.text, part.cacheable) for part in parts
        ]
    else:
        system_content = system_prompt
        user_content = "\n\n".join(part.text for part in parts)

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
