#!/usr/bin/env python3
"""Validate Resolution Audit leak-router evidence cards."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent
REQUIRED_FIELDS = {
    "id",
    "tag",
    "vendor",
    "evidence_type",
    "source_url",
    "source_date",
    "source_checked_at",
    "expires_at",
    "summary",
    "numbers",
    "claim_limit",
}
REQUIRED_SCALAR_FIELDS = REQUIRED_FIELDS - {"numbers"}
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRICE_KEY_PATTERN = re.compile(r"(?:price|rate|overage|usd|cost|listed_|allowance)", re.I)
PRICE_VALUE_PATTERN = re.compile(r"(?:\$\s*\d|\b\d+(?:\.\d+)?\s*(?:usd|dollars?)\b)", re.I)


@dataclass
class EvidenceCard:
    line_number: int
    row: dict[str, Any]
    source_date: date
    source_checked_at: date
    expires_at: date

    @property
    def card_id(self) -> str:
        return str(self.row["id"])

    @property
    def tag(self) -> str:
        return str(self.row["tag"])

    @property
    def source_url(self) -> str:
        return str(self.row["source_url"])


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Resolution Audit evidence JSONL, router tags, frame sections, and price freshness.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "evidence.jsonl",
        help="Evidence JSONL file.",
    )
    parser.add_argument(
        "--leak-index",
        type=Path,
        default=ROOT / "leak-index.md",
        help="Leak router Markdown file.",
    )
    parser.add_argument(
        "--frames",
        type=Path,
        default=ROOT / "frames.md",
        help="Leak frames Markdown file.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "product-truth.json",
        help="Product truth manifest containing fields.evidence_freshness_days.value.",
    )
    parser.add_argument(
        "--as-of",
        type=parse_iso_date,
        default=datetime.now(timezone.utc).date(),
        help="Date to evaluate source freshness against, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--stale-after-days",
        type=int,
        help="Override manifest freshness window in days.",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit non-zero when evidence cards are expired.",
    )
    return parser.parse_args(argv)


def parse_iso_date(value: str) -> date:
    if not ISO_DATE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD date, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD date, got {value!r}") from exc


def load_freshness_days(path: Path) -> int:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid manifest JSON in {path}: {exc.msg}") from exc

    if not isinstance(manifest, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    fields = manifest.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("manifest.fields must be an object")
    freshness = fields.get("evidence_freshness_days")
    if not isinstance(freshness, dict):
        raise ValueError("manifest is missing fields.evidence_freshness_days")
    value = freshness.get("value")
    if not isinstance(value, int) or value <= 0:
        raise ValueError("fields.evidence_freshness_days.value must be a positive integer")
    return value


def router_tags(markdown: str) -> set[str]:
    return set(re.findall(r"^\| `([^`]+)` \|", markdown, re.M))


def frame_tags(markdown: str) -> set[str]:
    return set(re.findall(r"^## `([^`]+)`", markdown, re.M))


def parse_cards(path: Path) -> tuple[list[EvidenceCard], list[str]]:
    cards: list[EvidenceCard] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_number}: invalid JSON: {exc.msg}")
            continue

        if not isinstance(row, dict):
            errors.append(f"{path}:{line_number}: row must be a JSON object")
            continue

        missing = REQUIRED_FIELDS - set(row)
        if missing:
            errors.append(f"{path}:{line_number}: missing required fields: {', '.join(sorted(missing))}")
            continue

        empty_fields = [
            field
            for field in sorted(REQUIRED_SCALAR_FIELDS)
            if not isinstance(row[field], str) or not row[field].strip()
        ]
        if empty_fields:
            errors.append(
                f"{path}:{line_number}: required fields must be non-empty strings: "
                f"{', '.join(empty_fields)}"
            )

        card_id = str(row["id"])
        if card_id in seen_ids:
            errors.append(f"{path}:{line_number}: duplicate id: {card_id}")
        seen_ids.add(card_id)

        if not isinstance(row["numbers"], dict):
            errors.append(f"{path}:{line_number}: numbers must be a JSON object")

        parsed_dates: dict[str, date] = {}
        for field in ("source_date", "source_checked_at", "expires_at"):
            value = row[field]
            if not isinstance(value, str) or not ISO_DATE_PATTERN.fullmatch(value):
                errors.append(f"{path}:{line_number}: {field} must be YYYY-MM-DD")
                continue
            try:
                parsed_dates[field] = date.fromisoformat(value)
            except ValueError:
                errors.append(f"{path}:{line_number}: {field} must be a valid calendar date")
                continue

        if set(parsed_dates) != {"source_date", "source_checked_at", "expires_at"}:
            continue

        cards.append(
            EvidenceCard(
                line_number=line_number,
                row=row,
                source_date=parsed_dates["source_date"],
                source_checked_at=parsed_dates["source_checked_at"],
                expires_at=parsed_dates["expires_at"],
            )
        )

    return cards, errors


def value_has_exact_price(value: Any) -> bool:
    if isinstance(value, str):
        return bool(PRICE_VALUE_PATTERN.search(value))
    if isinstance(value, dict):
        return any(value_has_exact_price(item) for item in value.values())
    if isinstance(value, list):
        return any(value_has_exact_price(item) for item in value)
    return False


def has_exact_price(card: EvidenceCard) -> bool:
    numbers = card.row.get("numbers", {})
    if not isinstance(numbers, dict):
        return False
    return any(PRICE_KEY_PATTERN.search(str(key)) for key in numbers) or value_has_exact_price(numbers)


def validate(args: argparse.Namespace) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []
    freshness_days = args.stale_after_days
    if freshness_days is None:
        try:
            freshness_days = load_freshness_days(args.manifest)
        except ValueError as exc:
            errors.append(str(exc))
            freshness_days = 0
    elif freshness_days <= 0:
        errors.append("--stale-after-days must be a positive integer")

    cards, card_errors = parse_cards(args.evidence)
    errors.extend(card_errors)

    leak_tags = router_tags(args.leak_index.read_text(encoding="utf-8"))
    frames = frame_tags(args.frames.read_text(encoding="utf-8"))
    evidence_tags = {card.tag for card in cards}

    missing_from_router = evidence_tags - leak_tags
    router_without_evidence = leak_tags - evidence_tags
    missing_frames = leak_tags - frames

    if missing_from_router:
        errors.append(f"evidence tags missing from leak-index: {', '.join(sorted(missing_from_router))}")
    if router_without_evidence:
        errors.append(f"leak-index tags with no evidence cards: {', '.join(sorted(router_without_evidence))}")
    if missing_frames:
        errors.append(f"leak-index tags missing frame sections: {', '.join(sorted(missing_frames))}")

    stale_cards = 0
    future_cards = 0
    price_cards = 0
    for card in cards:
        expected_expires_at = card.source_checked_at + timedelta(days=freshness_days)
        if card.expires_at != expected_expires_at:
            errors.append(
                f"{args.evidence}:{card.line_number}: expires_at {card.expires_at.isoformat()} "
                f"must equal source_checked_at + {freshness_days} days "
                f"({expected_expires_at.isoformat()})"
            )
        if card.expires_at < card.source_checked_at:
            errors.append(
                f"{args.evidence}:{card.line_number}: expires_at {card.expires_at.isoformat()} "
                f"is before source_checked_at {card.source_checked_at.isoformat()}"
            )
        if card.source_date > args.as_of:
            future_cards += 1
            errors.append(
                f"{args.evidence}:{card.line_number}: source_date {card.source_date.isoformat()} "
                f"is after as-of {args.as_of.isoformat()}"
            )
        if card.source_checked_at > args.as_of:
            future_cards += 1
            errors.append(
                f"{args.evidence}:{card.line_number}: source_checked_at {card.source_checked_at.isoformat()} "
                f"is after as-of {args.as_of.isoformat()}"
            )
        if args.as_of > card.expires_at:
            stale_cards += 1
            warnings.append(
                f"{args.evidence}:{card.line_number}: WARN expired evidence card "
                f"{card.card_id} expired on {card.expires_at.isoformat()}; re-open {card.source_url} before citing it"
            )
        if has_exact_price(card):
            price_cards += 1

    stats = {
        "cards": len(cards),
        "router_tags": len(leak_tags),
        "frame_sections": len(frames),
        "price_cards": price_cards,
        "stale_cards": stale_cards,
        "future_cards": future_cards,
        "freshness_days": freshness_days,
    }
    return errors, warnings, stats


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    errors, warnings, stats = validate(args)

    for warning in warnings:
        print(warning)
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)

    print(
        "validated "
        f"{stats['cards']} evidence cards, "
        f"{stats['router_tags']} router tags, "
        f"{stats['frame_sections']} frame sections, "
        f"{stats['price_cards']} exact-price cards, "
        f"{stats['stale_cards']} expired cards, "
        f"{stats['freshness_days']}-day freshness window"
    )

    if errors:
        return 1
    if warnings and args.fail_on_stale:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
