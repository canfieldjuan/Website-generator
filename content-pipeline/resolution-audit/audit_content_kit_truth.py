#!/usr/bin/env python3
"""Audit the Resolution Audit content kit against product-truth.json."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


KIT_DIR = Path(__file__).resolve().parent
EXPLICIT_CHANNEL_LINE_RE = re.compile(r"\bchannel\b.*(?:`channel`|such as|linkedin|reddit|reply|blog|feedback)", re.I)
TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_-]*\b", re.I)
CURRENT_RE = re.compile(r"\b(current|shipped|live)\b", re.I)
CURRENT_OUTPUT_SUPPORT_RE = re.compile(
    r"\bcurrent\s+(?:product|report)\s+output\b.*\b(?:support|supports|confirm|confirms)\b|"
    r"\b(?:support|supports|supported|confirm|confirms|confirmed)\b.*\bcurrent\s+(?:product|report)\s+output\b",
    re.I,
)
CURRENT_OUTPUT_GUARD_RE = re.compile(
    r"\b(?:unless|without)\b.*\bcurrent\s+(?:product|report)\s+output\b",
    re.I,
)
TARGET_FIELD_LABELS = {
    "probable_owner_lane": ["probable owner lane", "owner lane", "owner routing"],
}
PASS_SEMANTICS_RE = re.compile(r"\bpassed\s*:\s*true\b|\bpass(?:ed|es)?\b", re.I)
WARN_ONLY_RULES = [
    "RA-HONEST-CTA",
    "RA-OWNER-ROUTING-COVERAGE",
    "RA-ANSWER-EVIDENCE-QUALIFIER",
    "RA-OWNERSHIP-QUALIFIER",
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail on exact content-kit drift from product-truth.json.",
    )
    parser.add_argument(
        "--kit-dir",
        type=Path,
        default=KIT_DIR,
        help="Resolution Audit kit directory.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to product-truth.json. Defaults to KIT_DIR/product-truth.json.",
    )
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid manifest JSON in {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"manifest must be a JSON object: {path}")
    return data


def _channel_contracts(kit_dir: Path) -> list[str]:
    module_path = kit_dir / "bundle_prompt.py"
    spec = importlib.util.spec_from_file_location("bundle_prompt_for_truth_audit", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not import CHANNEL_CONTRACTS from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return sorted(module.CHANNEL_CONTRACTS)


def _text_files(kit_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in kit_dir.rglob("*")
        if path.is_file()
        and path.suffix in {".md", ".py"}
        and "__pycache__" not in path.parts
    )


def _line_id(path: Path, line_number: int, kit_dir: Path) -> str:
    try:
        rel = path.relative_to(kit_dir)
    except ValueError:
        rel = path
    return f"{rel}:{line_number}"


def _blocking(message: str) -> str:
    return f"BLOCKING {message}"


def _warning(message: str) -> str:
    return f"WARNING {message}"


def check_manifest(manifest: dict[str, Any], kit_dir: Path) -> list[str]:
    findings: list[str] = []
    fields = manifest.get("fields")
    if not isinstance(fields, dict):
        return [_blocking("manifest.fields must be an object")]

    for name, field in fields.items():
        if not isinstance(field, dict):
            findings.append(_blocking(f"manifest field {name!r} must be an object"))
            continue
        if not field.get("source"):
            findings.append(_blocking(f"manifest field {name!r} is missing source"))
        if field.get("source") == "curated" and not field.get("verify_against"):
            findings.append(_blocking(f"curated manifest field {name!r} is missing verify_against"))

    channels = fields.get("verifier_channels", {})
    expected_channels = _channel_contracts(kit_dir)
    if channels.get("value") != expected_channels:
        findings.append(
            _blocking(
                "manifest verifier_channels does not match bundle_prompt.CHANNEL_CONTRACTS: "
                f"{channels.get('value')!r} != {expected_channels!r}"
            )
        )

    shipped = set(fields.get("shipped_report_fields", {}).get("value", []))
    target = set(fields.get("target_report_fields", {}).get("value", []))
    overlap = sorted(shipped & target)
    if overlap:
        findings.append(_blocking(f"report fields appear in both shipped and target lists: {overlap}"))
    return findings


def check_channel_lines(kit_dir: Path, allowed_channels: set[str]) -> list[str]:
    findings: list[str] = []
    for path in _text_files(kit_dir):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not EXPLICIT_CHANNEL_LINE_RE.search(line):
                continue
            tokens = {token.lower() for token in TOKEN_RE.findall(line)}
            named_channels = tokens & (allowed_channels | {"sales"})
            extra = sorted(named_channels - allowed_channels)
            if extra:
                findings.append(
                    _blocking(
                        f"{_line_id(path, line_number, kit_dir)} names unsupported verifier channel(s): {extra}"
                    )
                )
    return findings


def check_target_fields_current(kit_dir: Path, target_fields: list[str]) -> list[str]:
    findings: list[str] = []
    for path in _text_files(kit_dir):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, 1):
            if not CURRENT_RE.search(line):
                continue
            logical_line = line
            if line_number > 1 and lines[line_number - 2].startswith("- "):
                logical_line = f"{lines[line_number - 2]} {line.strip()}"
            if line_number < len(lines) and lines[line_number].startswith("  "):
                logical_line = f"{line} {lines[line_number].strip()}"
            if CURRENT_OUTPUT_SUPPORT_RE.search(logical_line) or CURRENT_OUTPUT_GUARD_RE.search(logical_line):
                continue
            lowered = logical_line.lower()
            for field in target_fields:
                labels = TARGET_FIELD_LABELS.get(field, [field.replace("_", " ")])
                if any(label in lowered for label in labels):
                    findings.append(
                        _blocking(
                            f"{_line_id(path, line_number, kit_dir)} presents target field {field!r} as current/shipped"
                        )
                    )
    return findings


def check_pass_semantics(kit_dir: Path) -> list[str]:
    findings: list[str] = []
    for path in _text_files(kit_dir):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not PASS_SEMANTICS_RE.search(line):
                continue
            if any(rule in line for rule in WARN_ONLY_RULES):
                findings.append(
                    _blocking(
                        f"{_line_id(path, line_number, kit_dir)} presents warn-only verifier rule as passable"
                    )
                )
    return findings


def run_audit(kit_dir: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    manifest = _load_json(manifest_path)
    fields = manifest.get("fields", {})
    allowed_channels = set(fields.get("verifier_channels", {}).get("value", []))
    target_fields = list(fields.get("target_report_fields", {}).get("value", []))

    blocking: list[str] = []
    warnings: list[str] = []
    blocking.extend(check_manifest(manifest, kit_dir))
    blocking.extend(check_channel_lines(kit_dir, allowed_channels))
    blocking.extend(check_target_fields_current(kit_dir, target_fields))
    blocking.extend(check_pass_semantics(kit_dir))

    return blocking, warnings


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    kit_dir = args.kit_dir.resolve()
    manifest_path = (args.manifest or kit_dir / "product-truth.json").resolve()
    blocking, warnings = run_audit(kit_dir, manifest_path)

    for finding in warnings:
        print(finding)
    for finding in blocking:
        print(finding, file=sys.stderr)
    if blocking:
        print(f"content-kit truth audit failed: {len(blocking)} blocking finding(s)", file=sys.stderr)
        return 1
    print("content-kit truth audit passed: no exact violations found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
