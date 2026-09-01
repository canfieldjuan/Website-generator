"""Fail-closed verification for the Local Connect entitlement-v1 contract."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FEATURE_ID = "connect.capability_exchange"
ENTITLEMENT_FILE_NAME = "entitlement-v1.json"
BUNDLED_KEYRING = Path("website_redesign_data/connect-entitlement-keyring.json")
MAX_ENTITLEMENT_BYTES = 16 * 1024
MAX_KEYRING_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 8192 * 3 // 4
MAX_KEYS = 16
MAX_FEATURES = 32
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64

KEY_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
FEATURE_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class EntitlementDecision(str, Enum):
    ACTIVE = "active"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    MISSING = "missing"
    INVALID = "invalid"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"
    FEATURE_MISSING = "feature_missing"

    @property
    def is_active(self) -> bool:
        return self is EntitlementDecision.ACTIVE


@dataclass(frozen=True)
class EntitlementGate:
    path: Path | None
    keys: Mapping[str, bytes] | None
    now: Callable[[], datetime]

    @classmethod
    def from_installation(cls) -> "EntitlementGate":
        return cls(
            path=_entitlement_path(
                os.environ.get("XDG_CONFIG_HOME"), os.environ.get("HOME")
            ),
            keys=_load_bundled_keyring(),
            now=lambda: datetime.now(timezone.utc),
        )

    @classmethod
    def for_test(
        cls,
        *,
        path: Path,
        keyring_document: bytes,
        now: datetime,
    ) -> "EntitlementGate":
        return cls(
            path=path,
            keys=_parse_keyring(keyring_document),
            now=lambda: now,
        )

    def decision(self) -> EntitlementDecision:
        if not self.keys:
            return EntitlementDecision.AUTHORITY_UNAVAILABLE
        if self.path is None:
            return EntitlementDecision.MISSING
        content = _read_private_entitlement(self.path)
        if content is None:
            return EntitlementDecision.MISSING
        return _evaluate_entitlement(content, self.keys, self.now())


def _entitlement_path(
    xdg_config_home: str | None, home: str | None
) -> Path | None:
    if xdg_config_home:
        root = Path(xdg_config_home)
    elif home:
        root = Path(home) / ".config"
    else:
        return None
    if not root.is_absolute():
        return None
    return root / "local-connect" / ENTITLEMENT_FILE_NAME


def _load_bundled_keyring() -> Mapping[str, bytes] | None:
    """Load only an official package-owned authority, never a runtime override."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not isinstance(bundle_root, str):
        return None
    path = Path(bundle_root) / BUNDLED_KEYRING
    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_KEYRING_BYTES:
            return None
        return _parse_keyring(path.read_bytes())
    except (OSError, TypeError, ValueError):
        return None


def _parse_keyring(content: bytes) -> Mapping[str, bytes]:
    if not content or len(content) > MAX_KEYRING_BYTES:
        raise ValueError("Connect entitlement keyring is empty or oversized.")
    document = _strict_json_object(content)
    _exact_keys(document, {"keys"}, "keyring")
    items = document["keys"]
    if not isinstance(items, list) or len(items) > MAX_KEYS:
        raise ValueError("Connect entitlement keyring has an invalid key list.")
    keys: dict[str, bytes] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Connect entitlement keyring item must be an object.")
        _exact_keys(
            item, {"key_id", "algorithm", "public_key_base64url"}, "keyring item"
        )
        key_id = item["key_id"]
        if not _valid_identifier(key_id, KEY_ID_PATTERN, 100):
            raise ValueError("Connect entitlement key ID is invalid.")
        if item["algorithm"] != "Ed25519" or key_id in keys:
            raise ValueError("Connect entitlement keyring entry is invalid.")
        public_key = _decode_base64url(item["public_key_base64url"], PUBLIC_KEY_BYTES)
        if len(public_key) != PUBLIC_KEY_BYTES:
            raise ValueError("Connect entitlement public key has an invalid size.")
        keys[key_id] = public_key
    return MappingProxyType(keys)


def _evaluate_entitlement(
    content: bytes,
    keys: Mapping[str, bytes],
    now: datetime,
) -> EntitlementDecision:
    if not content or len(content) > MAX_ENTITLEMENT_BYTES or now.tzinfo is None:
        return EntitlementDecision.INVALID
    try:
        envelope = _strict_json_object(content)
        _exact_keys(
            envelope,
            {"format_version", "key_id", "payload_base64url", "signature_base64url"},
            "entitlement envelope",
        )
        if type(envelope["format_version"]) is not int or envelope["format_version"] != 1:
            raise ValueError("Unsupported entitlement format.")
        key_id = envelope["key_id"]
        if not _valid_identifier(key_id, KEY_ID_PATTERN, 100):
            raise ValueError("Entitlement key ID is invalid.")
        payload_text = envelope["payload_base64url"]
        signature_text = envelope["signature_base64url"]
        if not isinstance(payload_text, str) or not 2 <= len(payload_text) <= 8192:
            raise ValueError("Entitlement payload is invalid.")
        if not isinstance(signature_text, str) or len(signature_text) != 86:
            raise ValueError("Entitlement signature is invalid.")
        payload = _decode_base64url(payload_text, MAX_PAYLOAD_BYTES)
        signature = _decode_base64url(signature_text, SIGNATURE_BYTES)
        if len(signature) != SIGNATURE_BYTES:
            raise ValueError("Entitlement signature has an invalid size.")
        public_key = keys.get(key_id)
        if public_key is None:
            raise ValueError("Entitlement key is not trusted.")
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        claims = _validate_claims(_strict_json_object(payload))
        issued_at = _parse_utc(claims["issued_at"])
        not_before = _parse_utc(claims["not_before"])
        expires_at = _parse_utc(claims["expires_at"])
    except (InvalidSignature, OSError, TypeError, UnicodeDecodeError, ValueError):
        return EntitlementDecision.INVALID

    if issued_at > not_before or not_before >= expires_at:
        return EntitlementDecision.INVALID
    current = now.astimezone(timezone.utc)
    if current < not_before:
        return EntitlementDecision.NOT_YET_VALID
    if current >= expires_at:
        return EntitlementDecision.EXPIRED
    if FEATURE_ID not in claims["features"]:
        return EntitlementDecision.FEATURE_MISSING
    return EntitlementDecision.ACTIVE


def _validate_claims(document: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        document,
        {
            "format_version",
            "entitlement_id",
            "subject",
            "features",
            "issued_at",
            "not_before",
            "expires_at",
        },
        "entitlement claims",
    )
    if type(document["format_version"]) is not int or document["format_version"] != 1:
        raise ValueError("Unsupported entitlement claims format.")
    entitlement_id = document["entitlement_id"]
    if not _valid_uuid4(entitlement_id):
        raise ValueError("Entitlement ID is invalid.")
    subject = document["subject"]
    if not isinstance(subject, str) or not 1 <= len(subject) <= 200:
        raise ValueError("Entitlement subject is invalid.")
    features = document["features"]
    if not isinstance(features, list) or not 1 <= len(features) <= MAX_FEATURES:
        raise ValueError("Entitlement features are invalid.")
    if len(set(features)) != len(features) or any(
        not _valid_identifier(feature, FEATURE_PATTERN, 100) for feature in features
    ):
        raise ValueError("Entitlement features are invalid.")
    for field in ("issued_at", "not_before", "expires_at"):
        value = document[field]
        if not isinstance(value, str) or not UTC_PATTERN.fullmatch(value):
            raise ValueError("Entitlement timestamp is invalid.")
    return document


def _read_private_entitlement(path: Path) -> bytes | None:
    required_flags = ("O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    if os.name != "posix" or not hasattr(os, "geteuid") or any(
        not hasattr(os, flag) for flag in required_flags
    ):
        return None
    try:
        expected_uid = os.geteuid()
        directory = path.parent.lstat()
        candidate = path.lstat()
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != expected_uid
            or directory.st_mode & 0o077
            or not stat.S_ISREG(candidate.st_mode)
            or candidate.st_uid != expected_uid
            or candidate.st_mode & 0o077
            or not 0 < candidate.st_size <= MAX_ENTITLEMENT_BYTES
        ):
            return None
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
    except OSError:
        return None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != expected_uid
            or opened.st_mode & 0o077
            or not 0 < opened.st_size <= MAX_ENTITLEMENT_BYTES
            or (opened.st_dev, opened.st_ino) != (candidate.st_dev, candidate.st_ino)
        ):
            return None
        content = bytearray()
        while len(content) <= MAX_ENTITLEMENT_BYTES:
            chunk = os.read(
                descriptor, min(8192, MAX_ENTITLEMENT_BYTES + 1 - len(content))
            )
            if not chunk:
                break
            content.extend(chunk)
        if not 0 < len(content) <= MAX_ENTITLEMENT_BYTES:
            return None
        return bytes(content)
    except OSError:
        return None
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _strict_json_object(content: bytes) -> dict[str, Any]:
    try:
        document = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_json_constant,
        )
    except RecursionError as exc:
        raise ValueError("Connect entitlement JSON nesting is excessive.") from exc
    if not isinstance(document, dict):
        raise ValueError("Connect entitlement JSON must be an object.")
    return document


def _decode_base64url(value: Any, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise ValueError("base64url value must be canonical and unpadded.")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError("base64url value is invalid.") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if len(decoded) > max_bytes or canonical != value:
        raise ValueError("base64url value is not canonical.")
    return decoded


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Entitlement timestamp must be UTC.")
    return parsed


def _exact_keys(document: dict[str, Any], expected: set[str], label: str) -> None:
    if set(document) != expected:
        raise ValueError(f"Connect {label} fields are invalid.")


def _valid_identifier(value: Any, pattern: re.Pattern[str], maximum: int) -> bool:
    return isinstance(value, str) and len(value) <= maximum and bool(pattern.fullmatch(value))


def _valid_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Unsupported JSON constant: {value}")
