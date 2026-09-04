"""Bounded stdin/stdout contract for the Website Generator desktop host."""

from __future__ import annotations

import base64
import hashlib
import io
import ipaddress
import json
import math
import sys
from contextlib import redirect_stdout
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from lib.clients import OPENROUTER_BASE_URL
from lib.generation import (
    DEFAULT_LOCAL_API_KEY,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_MODEL,
    DEFAULT_LOCAL_TIMEOUT_SECONDS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    GeneratedBodyError,
    GeneratedHtmlError,
    GenerationConfig,
    GenerationProviderUnavailable,
    GenerationResponseError,
    MAX_HTML_BYTES,
    preflight_generation_provider,
)
from lib.site_artifact import (
    MAX_PROSPECT_BYTES,
    generate_prepared_site_artifact,
    prepare_site_prospect,
)


DESKTOP_PROTOCOL_VERSION = 1
MAX_DESKTOP_REQUEST_BYTES = MAX_PROSPECT_BYTES + 16_384
MAX_DESKTOP_RESPONSE_BYTES = ((MAX_HTML_BYTES + 2) // 3 * 4) + 65_536
MAX_MODEL_LENGTH = 500
MAX_API_KEY_LENGTH = 4_096
MAX_BASE_URL_LENGTH = 2_048
OPERATIONS = frozenset(("prospect.validate", "generation.status", "site.generate"))


class DesktopProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate member: {key}")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite number")
    return parsed


def _reject_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _reject_surrogates(value: Any) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise ValueError("JSON strings must contain Unicode scalar values")
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


def decode_desktop_request(payload: bytes) -> dict[str, Any]:
    if not payload:
        raise DesktopProtocolError("REQUEST_INVALID", "Desktop request is empty.")
    if len(payload) > MAX_DESKTOP_REQUEST_BYTES:
        raise DesktopProtocolError("INPUT_TOO_LARGE", "Desktop request is too large.")
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_finite_float,
            parse_constant=_reject_constant,
        )
        _reject_surrogates(document)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise DesktopProtocolError(
            "REQUEST_INVALID", "Desktop request must be strict UTF-8 JSON."
        ) from exc
    if not isinstance(document, dict):
        raise DesktopProtocolError("REQUEST_INVALID", "Desktop request must be an object.")
    return document


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
    *,
    code: str = "REQUEST_INVALID",
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise DesktopProtocolError(
            code, f"{label} fields are invalid: {'; '.join(details)}."
        )


def _bounded_string(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DesktopProtocolError(
            "GENERATION_CONFIGURATION_INVALID", f"{label} must be a non-empty string."
        )
    return value.strip()


def _validate_loopback_base_url(value: str) -> str:
    if len(value) > MAX_BASE_URL_LENGTH:
        raise DesktopProtocolError(
            "GENERATION_CONFIGURATION_INVALID", "Local model endpoint is invalid."
        )
    try:
        endpoint = urlsplit(value)
        hostname = endpoint.hostname
        _ = endpoint.port
    except ValueError as exc:
        raise DesktopProtocolError(
            "GENERATION_CONFIGURATION_INVALID", "Local model endpoint is invalid."
        ) from exc
    if (
        endpoint.scheme.lower() not in {"http", "https"}
        or not endpoint.netloc
        or hostname is None
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.query
        or endpoint.fragment
    ):
        raise DesktopProtocolError(
            "GENERATION_CONFIGURATION_INVALID",
            "Local model endpoint must be a loopback HTTP URL.",
        )
    if endpoint.path.rstrip("/") not in {"", "/v1"}:
        raise DesktopProtocolError(
            "GENERATION_CONFIGURATION_INVALID",
            "Local model endpoint path must be empty or /v1.",
        )
    normalized = hostname.rstrip(".").lower()
    if normalized != "localhost":
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError as exc:
            raise DesktopProtocolError(
                "GENERATION_CONFIGURATION_INVALID",
                "Local model endpoint must be a literal loopback address.",
            ) from exc
        if not address.is_loopback:
            raise DesktopProtocolError(
                "GENERATION_CONFIGURATION_INVALID",
                "Local model endpoint must be a literal loopback address.",
            )
    return value


def resolve_desktop_generation_config(value: Any) -> GenerationConfig:
    if not isinstance(value, dict):
        raise DesktopProtocolError(
            "GENERATION_CONFIGURATION_INVALID", "Generation settings must be an object."
        )
    provider = _bounded_string(value.get("provider"), "Provider", 40).lower()
    if provider == "local":
        allowed = {"provider", "model", "base_url"}
        unexpected = set(value) - allowed
        if unexpected:
            raise DesktopProtocolError(
                "GENERATION_CONFIGURATION_INVALID",
                f"Local generation settings contain unexpected fields: {', '.join(sorted(unexpected))}.",
            )
        model = _bounded_string(
            value.get("model", DEFAULT_LOCAL_MODEL), "Model", MAX_MODEL_LENGTH
        )
        base_url = _validate_loopback_base_url(
            _bounded_string(
                value.get("base_url", DEFAULT_LOCAL_BASE_URL),
                "Local model endpoint",
                MAX_BASE_URL_LENGTH,
            )
        )
        return GenerationConfig(
            provider="local",
            model=model,
            base_url=base_url,
            api_key=DEFAULT_LOCAL_API_KEY,
            timeout_seconds=DEFAULT_LOCAL_TIMEOUT_SECONDS,
            max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            trust_env=False,
        )
    if provider == "openrouter":
        _require_exact_keys(
            value,
            {"provider", "model", "api_key"},
            "OpenRouter settings",
            code="GENERATION_CONFIGURATION_INVALID",
        )
        return GenerationConfig(
            provider="openrouter",
            model=_bounded_string(value.get("model"), "Model", MAX_MODEL_LENGTH),
            base_url=OPENROUTER_BASE_URL,
            api_key=_bounded_string(
                value.get("api_key"), "OpenRouter API key", MAX_API_KEY_LENGTH
            ),
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            trust_env=True,
        )
    raise DesktopProtocolError(
        "GENERATION_CONFIGURATION_INVALID", "Provider must be local or openrouter."
    )


def _validate_request_shape(document: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _require_exact_keys(document, {"protocol", "operation", "payload"}, "Desktop request")
    protocol = document["protocol"]
    if (
        isinstance(protocol, bool)
        or not isinstance(protocol, int)
        or protocol != DESKTOP_PROTOCOL_VERSION
    ):
        raise DesktopProtocolError(
            "PROTOCOL_UNSUPPORTED", "Desktop protocol version is not supported."
        )
    operation = document["operation"]
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise DesktopProtocolError(
            "OPERATION_UNSUPPORTED", "Desktop operation is not supported."
        )
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise DesktopProtocolError("REQUEST_INVALID", "Desktop payload must be an object.")
    return operation, payload


def _prospect_from_payload(payload: dict[str, Any], expected: set[str]) -> Any:
    _require_exact_keys(payload, expected, "Desktop payload")
    prospect = payload.get("prospect")
    if not isinstance(prospect, dict):
        raise DesktopProtocolError("PROSPECT_INVALID", "Prospect must be an object.")
    encoded = json.dumps(
        prospect, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_PROSPECT_BYTES:
        raise DesktopProtocolError("INPUT_TOO_LARGE", "Prospect document is too large.")
    return prospect


def execute_desktop_request(document: dict[str, Any]) -> dict[str, Any]:
    operation, payload = _validate_request_shape(document)
    if operation == "prospect.validate":
        prospect = _prospect_from_payload(payload, {"prospect"})
        try:
            prepared = prepare_site_prospect(prospect)
        except (TypeError, ValueError) as exc:
            raise DesktopProtocolError("PROSPECT_INVALID", str(exc)) from exc
        return {
            "valid": True,
            "business_name": prepared["business_name"],
        }

    if operation == "generation.status":
        _require_exact_keys(payload, {"generation"}, "Desktop payload")
        config = resolve_desktop_generation_config(payload["generation"])
        if config.provider == "local":
            try:
                preflight_generation_provider(config)
            except GenerationProviderUnavailable:
                return {
                    "available": False,
                    "provider": config.provider,
                    "model": config.model,
                    "base_url": config.base_url,
                }
        return {
            "available": True,
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
        }

    prospect = _prospect_from_payload(payload, {"prospect", "generation"})
    config = resolve_desktop_generation_config(payload["generation"])
    try:
        prepared = prepare_site_prospect(prospect)
    except (TypeError, ValueError) as exc:
        raise DesktopProtocolError("PROSPECT_INVALID", str(exc)) from exc
    try:
        preflight_generation_provider(config)
        artifact = generate_prepared_site_artifact(prepared, config)
    except GenerationProviderUnavailable as exc:
        raise DesktopProtocolError(
            "GENERATION_UNAVAILABLE", "The selected generation provider is unavailable."
        ) from exc
    except (GeneratedBodyError, GeneratedHtmlError, GenerationResponseError) as exc:
        raise DesktopProtocolError(
            "GENERATION_FAILED", "The selected provider did not produce an admissible website."
        ) from exc
    return {
        "artifact": {
            "media_type": "text/html",
            "display_name": artifact.display_name,
            "byte_size": len(artifact.html),
            "sha256": hashlib.sha256(artifact.html).hexdigest(),
            "payload_base64": base64.b64encode(artifact.html).decode("ascii"),
        }
    }


def _success(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def run_desktop_stdio(
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    selected_input = input_stream or sys.stdin.buffer
    selected_output = output_stream or sys.stdout.buffer
    try:
        request_bytes = selected_input.read(MAX_DESKTOP_REQUEST_BYTES + 1)
        document = decode_desktop_request(request_bytes)
        with redirect_stdout(io.StringIO()):
            envelope = _success(execute_desktop_request(document))
        exit_code = 0
    except DesktopProtocolError as exc:
        envelope = _failure(exc.code, exc.message)
        exit_code = 2
    except Exception:
        envelope = _failure("INTERNAL_ERROR", "Website Generator could not complete the request.")
        exit_code = 2
    encoded = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_DESKTOP_RESPONSE_BYTES:
        encoded = json.dumps(
            _failure("OUTPUT_TOO_LARGE", "Website Generator response is too large."),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        exit_code = 2
    selected_output.write(encoded + b"\n")
    selected_output.flush()
    return exit_code
