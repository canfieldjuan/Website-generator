#!/usr/bin/env python3
"""Build the official Website Redesign Connect provider executable."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
KEYRING_ENV = "LOCAL_CONNECT_ENTITLEMENT_KEYRING_FILE"
BINARY_NAME = "website-redesign-connect"
BUNDLE_DIRECTORY = "website_redesign_data"
BUNDLE_FILENAME = "connect-entitlement-keyring.json"
CONNECT_REFERENCE_FILES = (
    Path("references/03-base-template.html"),
    Path("references/06-build-prompt.md"),
    Path("references/07-industry-defaults.md"),
    Path("references/09-themes.md"),
    Path("references/10-section-orders.md"),
)
MAX_KEYRING_BYTES = 64 * 1024
MAX_KEYS = 16
KEY_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
NON_PRODUCTION_KEY_TOKENS = frozenset(("dev", "example", "fixture", "test"))
APPROVED_RELEASE_AUTHORITIES = frozenset(
    {
        (
            "local-connect-prod-2026-01",
            "gN8pJj9W2H89LBsIJqk5ydmlxNCrbSXxAbBDYQf1fa0",
        )
    }
)
REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class ReleaseBuildError(RuntimeError):
    """A stable release-build admission failure."""


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT_ATTRIBUTE
    )


def _reject_reparse_ancestors(path: Path) -> None:
    """Reject indirection in every directory leading to a release input."""
    for ancestor in path.parents:
        metadata = ancestor.lstat()
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise ReleaseBuildError(
                "Connect entitlement keyring has an unsafe path ancestor"
            )


def binary_filename(platform_name: str | None = None) -> str:
    selected = os.name if platform_name is None else platform_name
    return f"{BINARY_NAME}.exe" if selected == "nt" else BINARY_NAME


def _strict_json_object(content: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseBuildError(f"duplicate JSON member: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ReleaseBuildError("Connect entitlement keyring is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseBuildError("Connect entitlement keyring must be an object")
    return value


def _decode_base64url(value: object) -> bytes:
    if not isinstance(value, str) or "=" in value or len(value) != 43:
        raise ReleaseBuildError("Connect entitlement public key is invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise ReleaseBuildError("Connect entitlement public key is invalid") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value or len(decoded) != 32:
        raise ReleaseBuildError("Connect entitlement public key is invalid")
    return decoded


def _read_keyring(path: Path) -> bytes:
    if not path.is_absolute():
        raise ReleaseBuildError(f"{KEYRING_ENV} must be an absolute path")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_BINARY", 0)
    )
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        _reject_reparse_ancestors(path)
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_reparse(before)
            or not 0 < before.st_size <= MAX_KEYRING_BYTES
        ):
            raise ReleaseBuildError(
                "Connect entitlement keyring must be a bounded regular file"
            )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or _is_reparse(opened)
                or not 0 < opened.st_size <= MAX_KEYRING_BYTES
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (before.st_dev, before.st_ino, before.st_size)
            ):
                raise ReleaseBuildError(
                    "Connect entitlement keyring must be a bounded regular file"
                )
            chunks: list[bytes] = []
            remaining = MAX_KEYRING_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 8192))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                len(content) != before.st_size
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            ):
                raise ReleaseBuildError(
                    "Connect entitlement keyring changed while being read"
                )
        finally:
            os.close(descriptor)
    except ReleaseBuildError:
        raise
    except OSError as exc:
        raise ReleaseBuildError(
            "Connect entitlement keyring is unavailable or unsafe"
        ) from exc
    if not content or len(content) > MAX_KEYRING_BYTES:
        raise ReleaseBuildError("Connect entitlement keyring is empty or oversized")
    return content


def validate_release_keyring(path: Path) -> bytes:
    content = _read_keyring(path)
    document = _strict_json_object(content)
    if set(document) != {"keys"}:
        raise ReleaseBuildError("Connect entitlement keyring fields are invalid")
    keys = document["keys"]
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS:
        raise ReleaseBuildError(
            "Official packages require at least one bounded issuer key"
        )
    observed: set[str] = set()
    observed_authorities: set[tuple[str, str]] = set()
    for item in keys:
        if not isinstance(item, dict) or set(item) != {
            "key_id",
            "algorithm",
            "public_key_base64url",
        }:
            raise ReleaseBuildError("Connect entitlement keyring entry is invalid")
        key_id = item["key_id"]
        if (
            not isinstance(key_id, str)
            or not 1 <= len(key_id) <= 100
            or not KEY_ID_PATTERN.fullmatch(key_id)
            or key_id in observed
        ):
            raise ReleaseBuildError(
                "Connect entitlement key ID is invalid or duplicated"
            )
        tokens = frozenset(re.split(r"[.-]", key_id))
        if "prod" not in tokens or tokens & NON_PRODUCTION_KEY_TOKENS:
            raise ReleaseBuildError(
                "Official packages refuse non-production issuer key IDs"
            )
        if item["algorithm"] != "Ed25519":
            raise ReleaseBuildError("Official packages require Ed25519 issuer keys")
        public_key = item["public_key_base64url"]
        _decode_base64url(public_key)
        observed.add(key_id)
        observed_authorities.add((key_id, public_key))
    if observed_authorities != APPROVED_RELEASE_AUTHORITIES:
        raise ReleaseBuildError(
            "Connect entitlement keyring does not match the approved production authority"
        )
    return content


def build_release(
    *,
    keyring_path: Path,
    dist_dir: Path,
    work_dir: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    content = validate_release_keyring(keyring_path)
    dist_dir = dist_dir.resolve()
    work_dir = work_dir.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".website-redesign-release-", dir=dist_dir
    ) as temporary:
        temporary_root = Path(temporary)
        staged = temporary_root / BUNDLE_FILENAME
        staged_dist = temporary_root / "dist"
        staged.write_bytes(content)
        command: list[str] = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            BINARY_NAME,
            "--distpath",
            str(staged_dist),
            "--workpath",
            str(work_dir),
            "--specpath",
            str(work_dir),
            "--add-data",
            f"{staged}{os.pathsep}{BUNDLE_DIRECTORY}",
        ]
        for relative_path in CONNECT_REFERENCE_FILES:
            source = ROOT / relative_path
            if not source.is_file():
                raise ReleaseBuildError(
                    f"Required Connect package resource is unavailable: {relative_path}"
                )
            command.extend(
                (
                    "--add-data",
                    f"{source}{os.pathsep}{BUNDLE_DIRECTORY}/references",
                )
            )
        command.append(str(ROOT / "connect_provider.py"))
        runner(command, cwd=ROOT, check=True)
        produced = staged_dist / binary_filename()
        if not produced.is_file():
            raise ReleaseBuildError(
                "PyInstaller completed without producing the expected executable"
            )
        executable = dist_dir / binary_filename()
        os.replace(produced, executable)

    return executable


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--work-dir", type=Path, default=ROOT / "build" / "connect-provider"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configured = os.environ.get(KEYRING_ENV)
    if not configured:
        print(f"Release build failed: {KEYRING_ENV} is required", file=sys.stderr)
        return 2
    try:
        executable = build_release(
            keyring_path=Path(configured),
            dist_dir=args.dist_dir,
            work_dir=args.work_dir,
        )
    except (ReleaseBuildError, subprocess.CalledProcessError, OSError) as exc:
        print(f"Release build failed: {exc}", file=sys.stderr)
        return 2
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
