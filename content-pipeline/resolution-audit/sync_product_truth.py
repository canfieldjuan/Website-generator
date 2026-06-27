#!/usr/bin/env python3
"""Sync derived Resolution Audit product-truth fields."""

from __future__ import annotations

import argparse
import copy
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

from bundle_prompt import CHANNEL_CONTRACTS


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "product-truth.json"
DEFAULT_PRODUCT_SOURCE = ROOT / "product-truth-sources/atlas-deflection-v1.json"
CHANNEL_SOURCE = "derived:bundle_prompt.CHANNEL_CONTRACTS"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync product-truth.json fields that can be derived from local code.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to product-truth.json.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if derived fields are out of sync instead of rewriting the manifest.",
    )
    parser.add_argument(
        "--product-source",
        type=Path,
        default=DEFAULT_PRODUCT_SOURCE,
        help="Path to the source-backed product facts snapshot.",
    )
    return parser.parse_args(argv)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"manifest must be a JSON object: {path}")
    return data


def load_product_source(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"product source not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"product source must be a JSON object: {path}")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        raise SystemExit("product source fields must be a JSON object")
    return data


def _sync_field(fields: dict[str, Any], name: str, expected: Any) -> bool:
    if fields.get(name) == expected:
        return False
    fields[name] = copy.deepcopy(expected)
    return True


def sync_derived_fields(
    manifest: dict[str, Any],
    product_source: dict[str, Any] | None = None,
) -> bool:
    fields = manifest.setdefault("fields", {})
    if not isinstance(fields, dict):
        raise SystemExit("manifest.fields must be a JSON object")

    expected_channels = sorted(CHANNEL_CONTRACTS)
    channel_field = fields.setdefault("verifier_channels", {})
    if not isinstance(channel_field, dict):
        raise SystemExit("manifest.fields.verifier_channels must be a JSON object")

    changed = False
    if channel_field.get("value") != expected_channels:
        channel_field["value"] = expected_channels
        changed = True
    if channel_field.get("source") != CHANNEL_SOURCE:
        channel_field["source"] = CHANNEL_SOURCE
        changed = True
    if product_source is not None:
        source_fields = product_source["fields"]
        for field_name in ("shipped_report_fields", "target_report_fields", "claims"):
            expected = source_fields.get(field_name)
            if not isinstance(expected, dict):
                raise SystemExit(f"product source field {field_name!r} must be a JSON object")
            changed = _sync_field(fields, field_name, expected) or changed
    if changed:
        manifest["generated_at"] = date.today().isoformat()
    return changed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest = load_manifest(args.manifest)
    product_source = load_product_source(args.product_source)
    changed = sync_derived_fields(manifest, product_source)

    if args.check:
        if changed:
            print(f"{args.manifest}: derived fields are out of sync", file=sys.stderr)
            return 1
        print(f"{args.manifest}: derived fields are in sync")
        return 0

    if changed:
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{args.manifest}: synced derived fields")
    else:
        print(f"{args.manifest}: already in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
