#!/usr/bin/env python3
"""Bundle Resolution Audit prompt context for Open WebUI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent

CHANNEL_CONTRACTS = {
    "linkedin": "Contract 1: LinkedIn POV Post",
    "reddit": "Contract 2: Reddit-Style Discussion Post",
    "reply": "Contract 3: Social Reply",
    "blog": "Contract 4: Blog Outline",
    "feedback": "Contract 5: Feedback Ask",
}

ANGLE_SECTIONS = {
    "ownership-question": "Angle 1: The Ownership Question",
    "invisible-repeat-cost": "Angle 2: The Invisible Repeat Cost",
    "build-in-public": "Angle 3: Build In Public - Report Shape",
    "free-snapshot-ask": "Angle 4: Free Snapshot Ask",
    "pattern-or-finding": "Angle 5: Pattern Or Finding",
    "diagnostic-not-dashboard": "Angle 6: Diagnostic, Not Dashboard",
    "reply-flow": "Reply Flow: Public Context First, CSV Later",
}


def read_file(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8").strip()


def extract_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\n.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    if not match:
        raise SystemExit(f"Could not find section: {heading}")
    return match.group(1).strip()


def leak_tags() -> list[str]:
    leak_index = read_file("leak-index.md")
    return sorted(set(re.findall(r"^\| `([^`]+)` \|", leak_index, re.M)))


def extract_leak_router_row(leak_index: str, tag: str) -> str:
    header_match = re.search(r"^\| tag \|.*\n\|[-| ]+\|", leak_index, re.M)
    row_match = re.search(rf"^\| `{re.escape(tag)}` \|.*$", leak_index, re.M)
    if not header_match or not row_match:
        raise SystemExit(f"Could not find leak router row: {tag}")
    return f"{header_match.group(0)}\n{row_match.group(0)}"


def extract_leak_frame(frames: str, tag: str) -> str:
    pattern = re.compile(
        rf"(^## `{re.escape(tag)}`.*?)(?=^## `|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(frames)
    if not match:
        raise SystemExit(f"Could not find leak frame: {tag}")
    return match.group(1).strip()


def evidence_rows_for_tag(tag: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate((ROOT / "evidence.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid evidence.jsonl row {line_number}: {exc.msg}") from exc
        if row.get("tag") == tag:
            rows.append(row)
    if not rows:
        raise SystemExit(f"Could not find evidence rows for leak tag: {tag}")
    return rows


def render_jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows)


def render_product_truth() -> str:
    manifest = json.loads((ROOT / "product-truth.json").read_text(encoding="utf-8"))
    return json.dumps(manifest, indent=2, sort_keys=True)


def build_leak_context(tag: str) -> str:
    leak_index = read_file("leak-index.md")
    frames = read_file("frames.md")
    claim_boundary = extract_section(leak_index, "Claim Boundary")
    router_row = extract_leak_router_row(leak_index, tag)
    evidence_rows = render_jsonl(evidence_rows_for_tag(tag))
    frame = extract_leak_frame(frames, tag)
    return "\n\n".join(
        [
            "## Selected Leak Context",
            "Use this section only for vendor billing-mechanic evidence. Do not turn it into customer waste, guaranteed savings, or blame language.",
            "## Selected Leak Router",
            f"Selected tag: `{tag}`",
            router_row,
            claim_boundary,
            "## Selected Leak Evidence",
            "```jsonl",
            evidence_rows,
            "```",
            "## Selected Leak Frame",
            frame,
        ]
    )


def render_file(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}"


def build_bundle(
    channel: str,
    angle: str | None,
    leak_tag: str | None,
    include_product_truth: bool,
    include_plain_talk: bool,
    include_report_shape: bool,
) -> str:
    source_pack = read_file("source-pack.md")
    claims_guard = read_file("claims-guard.md")
    prompt_contracts = read_file("prompt-contracts.md")

    shared_context = extract_section(prompt_contracts, "Shared Context Block")
    channel_contract = extract_section(prompt_contracts, CHANNEL_CONTRACTS[channel])

    sections = [
        "# Open WebUI Prompt Bundle: Resolution Audit",
        "",
        "Paste this entire bundle into Open WebUI. Fill in the Inputs list inside the selected channel contract before asking for a draft.",
        "",
        render_file("Source Pack", source_pack),
        "",
        render_file("Claims Guard", claims_guard),
    ]

    if include_product_truth:
        sections.extend(["", render_file("Product Truth Manifest", render_product_truth())])

    if include_plain_talk:
        sections.extend(["", render_file("Plain Talk Guide", read_file("plain-talk.md"))])

    if include_report_shape:
        sections.extend(["", render_file("Report Shape Example", read_file("report-shape-example.md"))])

    if angle:
        angles = read_file("angles.md")
        angle_section = extract_section(angles, ANGLE_SECTIONS[angle])
        sections.extend(["", "## Selected Angle", "", angle_section])

    if leak_tag:
        sections.extend(["", build_leak_context(leak_tag)])

    operator_instructions = [
        "Fill in the Inputs list inside the selected channel contract above, then draft using that contract.",
    ]
    if include_product_truth:
        operator_instructions.append(
            "The product truth manifest is authoritative on product facts, such as which fields exist and whether they are shipped. It does not override the claims guard's wording rules."
        )
    if include_plain_talk:
        operator_instructions.append(
            "Plain Talk is voice guidance. The claims guard still wins if readability, rhythm, or sharper phrasing would weaken a qualifier."
        )
    if include_report_shape:
        operator_instructions.append(
            "Use the Report Shape Example as a structure pattern only. Replace bracketed values with real audit data or omit them."
        )
    if leak_tag:
        operator_instructions.append(
            "Use Selected Leak Context only as vendor billing-mechanic evidence. Do not turn it into customer waste, guaranteed savings, or blame language."
        )
    operator_instructions.append(
        "After drafting, run Contract 6: Draft Self-Check from `prompt-contracts.md` before posting."
    )

    sections.extend(
        [
            "",
            shared_context,
            "",
            channel_contract,
            "",
            "## Operator Instruction",
            "",
            *operator_instructions,
        ]
    )

    return "\n".join(sections).strip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bundle Resolution Audit source, guard, angle, and prompt contract for Open WebUI.",
    )
    parser.add_argument(
        "--channel",
        choices=sorted(CHANNEL_CONTRACTS),
        required=True,
        help="Prompt contract to include.",
    )
    parser.add_argument(
        "--angle",
        choices=sorted(ANGLE_SECTIONS),
        help="Optional angle section to include.",
    )
    parser.add_argument(
        "--leak-tag",
        choices=leak_tags(),
        help="Optional leak-router tag to include with matching evidence and frame context.",
    )
    parser.add_argument(
        "--include-product-truth",
        action="store_true",
        help="Include product-truth.json and an explicit source-precedence instruction.",
    )
    parser.add_argument(
        "--include-plain-talk",
        action="store_true",
        help="Include the Plain Talk voice and readability guide.",
    )
    parser.add_argument(
        "--include-report-shape",
        action="store_true",
        help="Include the fictional report-shape example for Snapshot, report-shape, or build-in-public drafts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the bundle to this file instead of stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    bundle = build_bundle(
        args.channel,
        args.angle,
        args.leak_tag,
        args.include_product_truth,
        args.include_plain_talk,
        args.include_report_shape,
    )

    if args.output:
        args.output.write_text(bundle, encoding="utf-8")
    else:
        sys.stdout.write(bundle)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
