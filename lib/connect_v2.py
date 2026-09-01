"""Local Connect v2 HTTP contract for one local website capability."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import ipaddress
import json
import math
import os
import queue
import re
import secrets
import tempfile
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

import build
from lib.connect_entitlement import EntitlementGate
from lib.connect_store import (
    ConnectStore,
    JobConflict,
    ProviderBusy,
    StoredJob,
    canonical_json,
    utc_now,
)
from lib.generation import (
    DEFAULT_LOCAL_MODEL,
    MAX_HTML_BYTES,
    GeneratedHtmlError,
    GenerationConfigurationError,
    GenerationConfig,
    GenerationProviderUnavailable,
    GenerationResponseError,
    resolve_generation_config,
)


PROTOCOL_VERSION = 2
APP_ID = "website-redesign"
APP_NAME = "Website Redesign"
APP_VERSION = "0.1.0"
CAPABILITY_ID = "website.generate.single-page"
CAPABILITY_VERSION = "1.0"
INPUT_MEDIA_TYPE = "application/json"
OUTPUT_MEDIA_TYPE = "text/html"
MAX_INPUT_BYTES = 200_000
MAX_REQUEST_BYTES = 65_536
MAX_MULTIPART_BYTES = MAX_INPUT_BYTES + MAX_REQUEST_BYTES + 65_536
TOKEN_BYTES = 48

UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProtocolError(ValueError):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


class ProviderLock:
    """Exclusive process ownership for one durable provider namespace."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            raise RuntimeError(
                "Another Website Redesign Connect provider already owns this state."
            ) from exc

    def close(self) -> None:
        if self._handle.closed:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()

    def __enter__(self) -> "ProviderLock":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


GenerationFunction = Callable[[bytes], tuple[bytes, str]]


class ProviderRuntime:
    """Own one durable queue and exactly one local generation worker."""

    def __init__(
        self,
        store: ConnectStore,
        generation_function: GenerationFunction | None = None,
    ) -> None:
        self.store = store
        self.instance_id = store.instance_id()
        self._generation_function = generation_function or generate_website_artifact
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._closed = threading.Event()
        self.store.reconcile_interrupted()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="website-redesign-connect-worker",
            daemon=True,
        )
        self._worker.start()
        for job in self.store.accepted_jobs():
            self._queue.put(job.job_id)

    def accept(
        self,
        request_document: dict[str, Any],
        artifact_bytes: bytes,
    ) -> tuple[StoredJob, bool]:
        digest = hashlib.sha256(canonical_json(request_document).encode("utf-8")).hexdigest()
        job, created = self.store.accept(
            request=request_document,
            request_hash=digest,
            input_bytes=artifact_bytes,
        )
        if created:
            self._queue.put(job.job_id)
        return job, created

    def status(self, job_id: str) -> StoredJob | None:
        return self.store.get(job_id)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._queue.put(None)
        self._worker.join(timeout=0.25)

    def wait_for_terminal(self, job_id: str, timeout: float = 2.0) -> StoredJob:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.store.get(job_id)
            if job is not None and job.status in {"completed", "failed"}:
                return job
            time.sleep(0.01)
        raise TimeoutError(f"Connect job {job_id} did not finish before timeout.")

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            if self._closed.is_set():
                return
            if not self.store.mark_processing(job_id):
                continue
            job = self.store.get(job_id)
            if job is None:
                continue
            try:
                output_bytes, display_name = self._generation_function(job.input_bytes)
                if not isinstance(output_bytes, bytes):
                    raise TypeError("Generation function must return bytes.")
                if not output_bytes or len(output_bytes) > MAX_HTML_BYTES:
                    raise GeneratedHtmlError(
                        f"Generated HTML must contain 1 to {MAX_HTML_BYTES} bytes."
                    )
                artifact_id = _new_output_artifact_id(job.input_artifact["artifact_id"])
                self.store.complete(
                    job_id,
                    artifact_id=artifact_id,
                    display_name=sanitize_display_name(display_name),
                    output_bytes=output_bytes,
                )
            except (GeneratedHtmlError, GenerationConfigurationError, GenerationResponseError):
                self._fail_model_response(job_id)
            except GenerationProviderUnavailable:
                self.store.fail(
                    job_id,
                    code="MODEL_RUNTIME_UNAVAILABLE",
                    message=(
                        "Local Qwen generation is unavailable; start LM Studio and "
                        f"load {DEFAULT_LOCAL_MODEL}."
                    ),
                    retryable=True,
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self.store.fail(
                    job_id,
                    code="INPUT_INVALID",
                    message="The input artifact is not a valid prospect document.",
                    retryable=False,
                )
            except Exception:
                self.store.fail(
                    job_id,
                    code="PROVIDER_INTERNAL_ERROR",
                    message="Website generation failed inside the local provider.",
                    retryable=True,
                )

    def _fail_model_response(self, job_id: str) -> None:
        self.store.fail(
            job_id,
            code="MODEL_RESPONSE_INVALID",
            message="The local model did not return a complete valid HTML document.",
            retryable=True,
        )


def manifest(instance_id: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "instance_id": instance_id,
        "app": {"id": APP_ID, "name": APP_NAME, "version": APP_VERSION},
        "capabilities": [
            {
                "id": CAPABILITY_ID,
                "version": CAPABILITY_VERSION,
                "action": {
                    "label": "Generate one-page website",
                    "description": (
                        "Generate a complete local one-page HTML website from a "
                        "structured prospect JSON document."
                    ),
                },
                "accepts": [
                    {"media_type": INPUT_MEDIA_TYPE, "max_bytes": MAX_INPUT_BYTES}
                ],
                "produces": [OUTPUT_MEDIA_TYPE],
                "parameters": [],
                "effects": {"external": False, "confirmation_required": False},
            }
        ],
    }


def create_app(
    runtime: ProviderRuntime,
    bearer_token: str,
    entitlement_gate: EntitlementGate | None = None,
) -> FastAPI:
    selected_entitlement_gate = entitlement_gate or EntitlementGate.from_installation()
    app = FastAPI(
        title="Website Redesign Local Connect Provider",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/v2/manifest")
    async def get_manifest(request: Request):
        denial = _authorize(request, bearer_token, selected_entitlement_gate)
        if denial is not None:
            return denial
        return JSONResponse(manifest(runtime.instance_id))

    @app.post("/v2/jobs")
    async def create_job(request: Request):
        denial = _authorize(request, bearer_token, selected_entitlement_gate)
        if denial is not None:
            return denial
        try:
            request_bytes, artifact_bytes = await read_job_multipart(request)
            request_document = decode_job_request(request_bytes)
            validate_job_request(request_document)
            validate_artifact_identity(request_document, artifact_bytes)
            job, created = runtime.accept(request_document, artifact_bytes)
        except ProtocolError as exc:
            return error_response(exc.status, exc.code, exc.message, exc.retryable)
        except JobConflict as exc:
            return error_response(409, "JOB_ID_CONFLICT", str(exc), False)
        except ProviderBusy as exc:
            return error_response(409, "PROVIDER_BUSY", str(exc), True)
        return JSONResponse(
            job_status_document(job, runtime.instance_id),
            status_code=202 if created else 200,
        )

    @app.get("/v2/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        denial = _authorize(request, bearer_token, selected_entitlement_gate)
        if denial is not None:
            return denial
        if not is_uuid4(job_id):
            return error_response(
                400, "JOB_ID_INVALID", "The job ID must be a lowercase UUIDv4.", False
            )
        job = runtime.status(job_id)
        if job is None:
            return error_response(404, "JOB_NOT_FOUND", "The job was not found.", False)
        return JSONResponse(job_status_document(job, runtime.instance_id))

    return app


def validate_job_request(document: Any) -> None:
    if not isinstance(document, dict):
        raise _invalid_request("The request JSON must be an object.")
    _require_exact_keys(
        document,
        {"protocol_version", "job_id", "capability", "inputs", "parameters"},
        "job request",
    )
    if not _is_json_integer(document["protocol_version"]) or document["protocol_version"] != 2:
        raise _invalid_request("protocol_version must be 2.")
    document["protocol_version"] = int(document["protocol_version"])
    if not is_uuid4(document["job_id"]):
        raise _invalid_request("job_id must be a lowercase UUIDv4.")

    capability = document["capability"]
    if not isinstance(capability, dict):
        raise _invalid_request("capability must be an object.")
    _require_exact_keys(capability, {"id", "version"}, "capability")
    if capability != {"id": CAPABILITY_ID, "version": CAPABILITY_VERSION}:
        raise ProtocolError(
            422,
            "CAPABILITY_UNSUPPORTED",
            f"Only {CAPABILITY_ID} version {CAPABILITY_VERSION} is supported.",
        )

    inputs = document["inputs"]
    if not isinstance(inputs, list) or len(inputs) != 1:
        raise _invalid_request("inputs must contain exactly one artifact.")
    artifact = inputs[0]
    if not isinstance(artifact, dict):
        raise _invalid_request("The input artifact must be an object.")
    _require_exact_keys(
        artifact,
        {
            "artifact_id",
            "media_type",
            "byte_size",
            "sha256",
            "display_name",
            "source_app_id",
        },
        "input artifact",
    )
    if not is_uuid4(artifact["artifact_id"]):
        raise _invalid_request("artifact_id must be a lowercase UUIDv4.")
    if artifact["media_type"] != INPUT_MEDIA_TYPE:
        raise ProtocolError(
            422,
            "INPUT_MEDIA_UNSUPPORTED",
            f"The input artifact must use {INPUT_MEDIA_TYPE}.",
        )
    byte_size = artifact["byte_size"]
    if not _is_json_integer(byte_size) or not 0 <= byte_size <= MAX_INPUT_BYTES:
        raise ProtocolError(
            422,
            "INPUT_SIZE_UNSUPPORTED",
            f"The declared input size must be between 0 and {MAX_INPUT_BYTES} bytes.",
        )
    artifact["byte_size"] = int(byte_size)
    if not isinstance(artifact["sha256"], str) or not SHA256_PATTERN.fullmatch(
        artifact["sha256"]
    ):
        raise _invalid_request("sha256 must be one lowercase hexadecimal digest.")
    display_name = artifact["display_name"]
    if not isinstance(display_name, str) or not 1 <= len(display_name) <= 255:
        raise _invalid_request("display_name must contain 1 to 255 characters.")
    source_app_id = artifact["source_app_id"]
    if (
        not isinstance(source_app_id, str)
        or len(source_app_id) > 100
        or not IDENTIFIER_PATTERN.fullmatch(source_app_id)
    ):
        raise _invalid_request("source_app_id is not a valid application identifier.")

    parameters = document["parameters"]
    if not isinstance(parameters, dict):
        raise _invalid_request("parameters must be an object.")
    if parameters:
        raise ProtocolError(
            422,
            "PARAMETER_UNDECLARED",
            "This capability does not declare any parameters.",
        )


def validate_artifact_identity(document: dict[str, Any], artifact_bytes: bytes) -> None:
    artifact = document["inputs"][0]
    if len(artifact_bytes) != artifact["byte_size"]:
        raise ProtocolError(
            422,
            "ARTIFACT_IDENTITY_MISMATCH",
            "The artifact byte size does not match its request metadata.",
        )
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    if not hmac.compare_digest(digest, artifact["sha256"]):
        raise ProtocolError(
            422,
            "ARTIFACT_IDENTITY_MISMATCH",
            "The artifact digest does not match its request metadata.",
        )


def decode_job_request(request_bytes: bytes) -> dict[str, Any]:
    try:
        text = request_bytes.decode("utf-8")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _invalid_request("The request field must contain strict UTF-8 JSON.") from exc
    if not isinstance(document, dict):
        raise _invalid_request("The request JSON must be an object.")
    return document


async def read_job_multipart(request: Request) -> tuple[bytes, bytes]:
    content_type = request.headers.get("content-type", "")
    media_type, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if media_type.lower() != b"multipart/form-data" or not boundary:
        raise ProtocolError(
            400, "MULTIPART_INVALID", "Content-Type must be multipart/form-data."
        )
    receiver = _MultipartReceiver()
    try:
        parser = MultipartParser(boundary, receiver.callbacks)
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_MULTIPART_BYTES:
                raise ProtocolError(
                    413,
                    "MULTIPART_TOO_LARGE",
                    "The multipart request exceeds the provider limit.",
                )
            parser.write(chunk)
        parser.finalize()
        return receiver.finish()
    except ProtocolError:
        raise
    except Exception as exc:
        raise ProtocolError(
            400, "MULTIPART_INVALID", "The multipart request is invalid."
        ) from exc


class _MultipartReceiver:
    def __init__(self) -> None:
        self.parts: list[tuple[str, bytes]] = []
        self._headers: dict[bytes, bytes] = {}
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._part_name: str | None = None
        self._part_data = bytearray()
        self.callbacks = {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
        }

    def on_part_begin(self) -> None:
        self._headers = {}
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._part_name = None
        self._part_data = bytearray()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value.extend(data[start:end])

    def on_header_end(self) -> None:
        name = bytes(self._header_name).strip().lower()
        value = bytes(self._header_value).strip()
        if not name or name in self._headers:
            raise ProtocolError(
                400, "MULTIPART_INVALID", "Multipart part headers are invalid."
            )
        self._headers[name] = value
        self._header_name = bytearray()
        self._header_value = bytearray()

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(
            self._headers.get(b"content-disposition", b"")
        )
        name = options.get(b"name")
        expected_name = b"request" if not self.parts else b"artifact"
        if disposition.lower() != b"form-data" or name != expected_name:
            expected = expected_name.decode("ascii")
            raise ProtocolError(
                400,
                "MULTIPART_INVALID",
                f"The next multipart field must be {expected!r}.",
            )
        if len(self.parts) >= 2:
            raise ProtocolError(
                400, "MULTIPART_INVALID", "Unexpected multipart fields were provided."
            )
        if name == b"artifact":
            part_type, _ = parse_options_header(self._headers.get(b"content-type", b""))
            if part_type.lower() != b"application/json":
                raise ProtocolError(
                    422,
                    "INPUT_MEDIA_UNSUPPORTED",
                    "The artifact multipart field must use application/json.",
                )
        self._part_name = name.decode("ascii")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._part_name is None:
            raise ProtocolError(
                400, "MULTIPART_INVALID", "Multipart data arrived before its headers."
            )
        self._part_data.extend(data[start:end])
        limit = MAX_REQUEST_BYTES if self._part_name == "request" else MAX_INPUT_BYTES
        if len(self._part_data) > limit:
            code = "REQUEST_TOO_LARGE" if self._part_name == "request" else "INPUT_TOO_LARGE"
            raise ProtocolError(413, code, f"The {self._part_name} field is too large.")

    def on_part_end(self) -> None:
        if self._part_name is None:
            raise ProtocolError(400, "MULTIPART_INVALID", "Multipart part is incomplete.")
        self.parts.append((self._part_name, bytes(self._part_data)))

    def finish(self) -> tuple[bytes, bytes]:
        if [name for name, _ in self.parts] != ["request", "artifact"]:
            raise ProtocolError(
                400,
                "MULTIPART_INVALID",
                "Exactly request then artifact multipart fields are required.",
            )
        return self.parts[0][1], self.parts[1][1]


def job_status_document(job: StoredJob, instance_id: str) -> dict[str, Any]:
    artifact = job.input_artifact
    document: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": job.job_id,
        "capability": {"id": CAPABILITY_ID, "version": CAPABILITY_VERSION},
        "provider": {"app_id": APP_ID, "instance_id": instance_id},
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "input_artifacts": [
            {
                "artifact_id": artifact["artifact_id"],
                "media_type": artifact["media_type"],
                "byte_size": artifact["byte_size"],
                "sha256": artifact["sha256"],
            }
        ],
    }
    if job.status == "completed":
        output = job.output_bytes or b""
        document["result"] = {
            "outputs": [
                {
                    "artifact_id": job.output_artifact_id,
                    "media_type": OUTPUT_MEDIA_TYPE,
                    "display_name": job.output_display_name,
                    "byte_size": len(output),
                    "sha256": hashlib.sha256(output).hexdigest(),
                    "payload_base64": base64.b64encode(output).decode("ascii"),
                }
            ]
        }
    elif job.status == "failed":
        document["error"] = {
            "code": job.error_code,
            "message": job.error_message,
            "retryable": job.error_retryable,
        }
    return document


def resolve_connect_generation_config() -> GenerationConfig:
    """Resolve the pinned local model without permitting a remote endpoint."""
    config = resolve_generation_config("local", DEFAULT_LOCAL_MODEL)
    try:
        endpoint = urlsplit(config.base_url)
        hostname = endpoint.hostname
        _ = endpoint.port
    except ValueError as exc:
        raise GenerationConfigurationError(
            "Connect generation requires a valid loopback HTTP base URL."
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
        raise GenerationConfigurationError(
            "Connect generation requires a valid loopback HTTP base URL."
        )
    normalized_hostname = hostname.rstrip(".").lower()
    if normalized_hostname != "localhost":
        try:
            address = ipaddress.ip_address(normalized_hostname)
        except ValueError as exc:
            raise GenerationConfigurationError(
                "Connect generation requires a literal loopback endpoint."
            ) from exc
        if not address.is_loopback:
            raise GenerationConfigurationError(
                "Connect generation requires a literal loopback endpoint."
            )
    return replace(config, trust_env=False)


def _has_usable_hero_photo(prospect: dict[str, Any]) -> bool:
    photos = prospect.get("photos")
    if not isinstance(photos, list):
        return False
    return any(
        isinstance(photo, dict)
        and photo.get("context") in {"hero", "background"}
        and isinstance(photo.get("url"), str)
        and bool(photo["url"].strip())
        for photo in photos
    )


def _select_connect_hero_shape(prospect: dict[str, Any]) -> None:
    """Keep single-artifact output self-contained when no photo is supplied."""
    if (
        prospect.get("_computed_hero_shape") in {"fullbleed", "split"}
        and not _has_usable_hero_photo(prospect)
    ):
        prospect["_computed_hero_shape"] = "gradient"


def generate_website_artifact(input_bytes: bytes) -> tuple[bytes, str]:
    try:
        prospect_document = json.loads(
            input_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
        prospect = build.prepare_prospect(prospect_document)
        build.apply_design_selections(prospect, announce=False)
        _select_connect_hero_shape(prospect)
        display_name = f"{build.slugify(prospect['business_name'])}-homepage.html"
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("The input artifact is not a valid prospect document.") from exc
    config = resolve_connect_generation_config()
    html = build.generate_build_html(prospect, config)
    return html.encode("utf-8"), display_name


def default_runtime_dir() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if not configured:
        raise RuntimeError(
            "XDG_RUNTIME_DIR is required for owner-private Local Connect discovery."
        )
    root = Path(configured)
    if not root.is_absolute():
        raise RuntimeError("XDG_RUNTIME_DIR must be an absolute path.")
    return root / "local-connect" / "v2" / "providers"


def default_state_dir() -> Path:
    root = os.environ.get("XDG_STATE_HOME")
    if root:
        state_root = Path(root)
        if not state_root.is_absolute():
            raise RuntimeError("XDG_STATE_HOME must be an absolute path.")
        return state_root / APP_ID
    return Path.home() / ".local" / "state" / APP_ID


def new_bearer_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def registration_document(
    *, instance_id: str, port: int, token: str, pid: int | None = None
) -> dict[str, Any]:
    if not is_uuid4(instance_id):
        raise ValueError("Registration instance_id must be a lowercase UUIDv4.")
    if type(port) is not int or not 1 <= port <= 65_535:
        raise ValueError("Registration port must be between 1 and 65535.")
    selected_pid = os.getpid() if pid is None else pid
    if type(selected_pid) is not int or selected_pid < 1:
        raise ValueError("Registration pid must be a positive integer.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise ValueError("Registration token must be URL-safe and 43 to 128 characters.")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "instance_id": instance_id,
        "app_id": APP_ID,
        "pid": selected_pid,
        "started_at": utc_now(),
        "transport": {
            "kind": "http-loopback-v2",
            "base_url": f"http://127.0.0.1:{port}/",
        },
        "auth": {"scheme": "bearer", "token": token},
    }


def write_registration(directory: str | Path, document: dict[str, Any]) -> Path:
    destination_dir = Path(directory)
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination_dir, 0o700)
    destination = destination_dir / f"{APP_ID}-{document['instance_id']}.json"
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            os.chmod(temporary_path, 0o600)
            json.dump(document, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        os.chmod(destination, 0o600)
        directory_fd = os.open(destination_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def remove_registration_if_owned(path: str | Path, token: str) -> None:
    registration_path = Path(path)
    try:
        current = json.loads(registration_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    current_token = (current.get("auth") or {}).get("token")
    if isinstance(current_token, str) and hmac.compare_digest(current_token, token):
        try:
            registration_path.unlink()
        except FileNotFoundError:
            pass


def sanitize_display_name(value: str) -> str:
    basename = Path(str(value)).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip(".-")
    if not sanitized:
        sanitized = "website-homepage"
    if sanitized.lower().endswith(".html"):
        sanitized = sanitized[:-5]
    return f"{sanitized[:250]}.html"


def is_uuid4(value: Any) -> bool:
    if not isinstance(value, str) or not UUID4_PATTERN.fullmatch(value):
        return False
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


def error_response(
    status: int, code: str, message: str, retryable: bool
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        {
            "protocol_version": PROTOCOL_VERSION,
            "error": {"code": code, "message": message, "retryable": retryable},
        },
        status_code=status,
        headers=headers,
    )


def _authenticate(request: Request, token: str) -> JSONResponse | None:
    authorization = request.headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not credential
        or not hmac.compare_digest(credential, token)
    ):
        return error_response(
            401, "AUTHENTICATION_REQUIRED", "A valid bearer token is required.", False
        )
    return None


def _authorize(
    request: Request, token: str, entitlement_gate: EntitlementGate
) -> JSONResponse | None:
    authentication_failure = _authenticate(request, token)
    if authentication_failure is not None:
        return authentication_failure
    if not entitlement_gate.decision().is_active:
        return error_response(
            403,
            "CONNECT_ENTITLEMENT_REQUIRED",
            "An active Local Connect capability-exchange entitlement is required.",
            False,
        )
    return None


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise _invalid_request(f"The {label} has {'; '.join(details)}.")


def _invalid_request(message: str) -> ProtocolError:
    return ProtocolError(400, "JOB_REQUEST_INVALID", message)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Unsupported JSON constant: {value}")


def _new_output_artifact_id(input_artifact_id: str) -> str:
    while True:
        candidate = str(uuid.uuid4())
        if candidate != input_artifact_id:
            return candidate


def _is_json_integer(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and float(value).is_integer()
    )
