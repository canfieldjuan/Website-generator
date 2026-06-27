#!/usr/bin/env python3
"""Audit the Resolution Audit content kit against product-truth.json."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


KIT_DIR = Path(__file__).resolve().parent
EXPLICIT_CHANNEL_LINE_RE = re.compile(r"\bchannel\b.*(?:`channel`|such as|linkedin|reddit|reply|blog|feedback)", re.I)
TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_-]*\b", re.I)
CURRENT_RE = re.compile(r"\b(current|currently|shipped|live)\b", re.I)
CURRENT_OUTPUT_SUPPORT_RE = re.compile(
    r"\bcurrent\s+(?:product|report)\s+output\b.*\b(?:support|supports|confirm|confirms)\b|"
    r"\b(?:support|supports|supported|confirm|confirms|confirmed)\b.*\bcurrent\s+(?:product|report)\s+output\b",
    re.I,
)
CURRENT_OUTPUT_GUARD_RE = re.compile(
    r"\b(?:unless|without)\b.*\bcurrent\s+(?:product|report)\s+output\b",
    re.I,
)
NEGATED_CURRENT_CLAIM_RE = re.compile(
    r"\b(?:not|never|no|without)\b[^.!?\n]*\b(?:current|currently|shipped|live)\b|"
    r"\b(?:current|currently|shipped|live)\b[^.!?\n]*\b(?:not|never|yet|target|future)\b",
    re.I,
)
TARGET_FIELD_LABELS = {
    "probable_owner_lane": [
        re.compile(r"\bprobable\s+owner[-\s]+lane\b", re.I),
        re.compile(r"\bowner[-\s]+lane\b", re.I),
        re.compile(r"\bowner\s+routing\b", re.I),
    ],
}
PASS_SEMANTICS_RE = re.compile(r"\bpassed\s*:\s*true\b|\bpass(?:ed|es)?\b", re.I)
NO_PASS_RULES = [
    "RA-HONEST-CTA",
    "RA-OWNER-ROUTING-COVERAGE",
]
CHANNEL_LINE_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "available",
    "bool",
    "channel",
    "channels",
    "contract",
    "contracts",
    "defaults",
    "draft",
    "example",
    "examples",
    "for",
    "full",
    "if",
    "include",
    "is",
    "label",
    "list",
    "or",
    "optional",
    "param",
    "run",
    "self",
    "str",
    "such",
    "the",
    "to",
    "tool",
    "use",
    "uses",
    "using",
    "verifier",
    "with",
}
REQUIRED_LIST_FIELDS = ("verifier_channels", "shipped_report_fields", "target_report_fields")


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


def _list_field_value(fields: dict[str, Any], name: str) -> list[str]:
    field = fields.get(name)
    if not isinstance(field, dict):
        return []
    value = field.get("value")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def check_manifest(manifest: dict[str, Any], kit_dir: Path) -> list[str]:
    findings: list[str] = []
    fields = manifest.get("fields")
    if not isinstance(fields, dict):
        return [_blocking("manifest.fields must be an object")]

    for name, field in fields.items():
        if not isinstance(field, dict):
            findings.append(_blocking(f"manifest field {name!r} must be an object"))
            continue
        source = field.get("source")
        if not isinstance(source, str) or not source:
            findings.append(_blocking(f"manifest field {name!r} is missing source"))
        if isinstance(source, str) and source.startswith("curated") and not field.get("verify_against"):
            findings.append(_blocking(f"curated manifest field {name!r} is missing verify_against"))

    for name in REQUIRED_LIST_FIELDS:
        field = fields.get(name)
        if not isinstance(field, dict):
            findings.append(_blocking(f"manifest field {name!r} is required"))
            continue
        value = field.get("value")
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            findings.append(_blocking(f"manifest field {name!r}.value must be a list of strings"))

    expected_channels = _channel_contracts(kit_dir)
    channels = _list_field_value(fields, "verifier_channels")
    if channels != expected_channels:
        findings.append(
            _blocking(
                "manifest verifier_channels does not match bundle_prompt.CHANNEL_CONTRACTS: "
                f"{channels!r} != {expected_channels!r}"
            )
        )

    shipped = set(_list_field_value(fields, "shipped_report_fields"))
    target = set(_list_field_value(fields, "target_report_fields"))
    overlap = sorted(shipped & target)
    if overlap:
        findings.append(_blocking(f"report fields appear in both shipped and target lists: {overlap}"))
    return findings


def _channel_candidates(line: str, allowed_channels: set[str]) -> set[str]:
    tokens = {token.lower() for token in TOKEN_RE.findall(line)}
    candidates = tokens - CHANNEL_LINE_STOPWORDS
    return {token for token in candidates if token in allowed_channels or token.islower()}


def check_channel_lines(kit_dir: Path, allowed_channels: set[str]) -> list[str]:
    findings: list[str] = []
    for path in _text_files(kit_dir):
        if path.name == "audit_content_kit_truth.py":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not EXPLICIT_CHANNEL_LINE_RE.search(line):
                continue
            named_channels = _channel_candidates(line, allowed_channels)
            extra = sorted(named_channels - allowed_channels)
            if extra:
                findings.append(
                    _blocking(
                        f"{_line_id(path, line_number, kit_dir)} names unsupported verifier channel(s): {extra}"
                    )
                )
    return findings


def _logical_lines(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    logical_lines: list[tuple[int, str]] = []
    for line_number, line in enumerate(lines, 1):
        logical_line = line
        if line_number > 1 and lines[line_number - 2].startswith("- "):
            logical_line = f"{lines[line_number - 2]} {line.strip()}"
        if line_number < len(lines) and lines[line_number].startswith("  "):
            logical_line = f"{line} {lines[line_number].strip()}"
        logical_lines.append((line_number, logical_line))
    return logical_lines


def check_target_fields_current(kit_dir: Path, target_fields: list[str]) -> list[str]:
    warnings: list[str] = []
    for path in _text_files(kit_dir):
        for line_number, line in _logical_lines(path):
            if not CURRENT_RE.search(line):
                continue
            if (
                CURRENT_OUTPUT_SUPPORT_RE.search(line)
                or CURRENT_OUTPUT_GUARD_RE.search(line)
                or NEGATED_CURRENT_CLAIM_RE.search(line)
            ):
                continue
            for field in target_fields:
                patterns = TARGET_FIELD_LABELS.get(field, [re.compile(rf"\b{re.escape(field.replace('_', ' '))}\b", re.I)])
                if any(pattern.search(line) for pattern in patterns):
                    warnings.append(
                        _warning(
                            f"{_line_id(path, line_number, kit_dir)} may present target field {field!r} as current/shipped"
                        )
                    )
    return warnings


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _expr_may_pass(node: ast.AST, pass_names: set[str]) -> bool:
    constant = _constant_string(node)
    if constant == "pass":
        return True
    if isinstance(node, ast.Name) and node.id in pass_names:
        return True
    return any(_constant_string(child) == "pass" for child in ast.walk(node))


def _python_pass_semantics(path: Path, kit_dir: Path) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return findings

    pass_names: set[str] = set()
    for node in ast.walk(tree):
        value: ast.AST | None = None
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            value = node.value
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            targets = [node.target]
        if value is None or not _expr_may_pass(value, set()):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                pass_names.add(target.id)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        rule_id = _constant_string(node.args[0])
        if rule_id not in NO_PASS_RULES:
            continue
        if _expr_may_pass(node.args[1], pass_names):
            findings.append(
                _blocking(
                    f"{_line_id(path, node.lineno, kit_dir)} presents warn-only verifier rule {rule_id!r} as passable"
                )
            )
    return findings


def check_pass_semantics(kit_dir: Path) -> list[str]:
    findings: list[str] = []
    for path in _text_files(kit_dir):
        if path.suffix == ".py":
            findings.extend(_python_pass_semantics(path, kit_dir))
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not PASS_SEMANTICS_RE.search(line):
                continue
            if any(rule in line for rule in NO_PASS_RULES):
                findings.append(
                    _blocking(
                        f"{_line_id(path, line_number, kit_dir)} presents warn-only verifier rule as passable"
                    )
                )
    return findings


def run_audit(kit_dir: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    manifest = _load_json(manifest_path)
    fields = manifest.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}
    allowed_channels = set(_list_field_value(fields, "verifier_channels"))
    target_fields = _list_field_value(fields, "target_report_fields")

    blocking: list[str] = []
    warnings: list[str] = []
    blocking.extend(check_manifest(manifest, kit_dir))
    blocking.extend(check_channel_lines(kit_dir, allowed_channels))
    warnings.extend(check_target_fields_current(kit_dir, target_fields))
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
    "bool",
    "defaults",
    "param",
    "self",
    "str",
