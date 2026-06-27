#!/usr/bin/env python3
"""Validate Resolution Audit leak-router evidence cards."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
        "--as-of",
        type=parse_iso_date,
        default=datetime.now(timezone.utc).date(),
        help="Date to evaluate source freshness against, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--stale-after-days",
        type=int,
        default=90,
        help="Warn when exact-price cards are older than this many days.",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit non-zero when exact-price cards are stale.",
    )
    return parser.parse_args(argv)


def parse_iso_date(value: str) -> date:
    if not ISO_DATE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD date, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD date, got {value!r}") from exc


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

        source_date_value = str(row["source_date"])
        if not ISO_DATE_PATTERN.fullmatch(source_date_value):
            errors.append(f"{path}:{line_number}: source_date must be YYYY-MM-DD")
            continue
        try:
            parsed_source_date = date.fromisoformat(source_date_value)
        except ValueError:
            errors.append(f"{path}:{line_number}: source_date must be a valid calendar date")
            continue

        cards.append(EvidenceCard(line_number=line_number, row=row, source_date=parsed_source_date))

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
        age_days = (args.as_of - card.source_date).days
        if age_days < 0:
            future_cards += 1
            errors.append(
                f"{args.evidence}:{card.line_number}: source_date {card.source_date.isoformat()} "
                f"is after as-of {args.as_of.isoformat()}"
            )
            continue
        if not has_exact_price(card):
            continue
        price_cards += 1
        if age_days > args.stale_after_days:
            stale_cards += 1
            warnings.append(
                f"{args.evidence}:{card.line_number}: WARN stale exact-price card "
                f"{card.card_id} is {age_days} days old; re-open {card.source_url} before citing a dollar figure"
            )

    stats = {
        "cards": len(cards),
        "router_tags": len(leak_tags),
        "frame_sections": len(frames),
        "price_cards": price_cards,
        "stale_cards": stale_cards,
        "future_cards": future_cards,
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
        f"{stats['price_cards']} exact-price cards"
    )

    if errors:
        return 1
    if warnings and args.fail_on_stale:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
