#!/usr/bin/env python3
"""Bundle Resolution Audit prompt context for Open WebUI."""

from __future__ import annotations

import argparse
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


def render_file(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}"


def build_bundle(channel: str, angle: str | None) -> str:
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

    if angle:
        angles = read_file("angles.md")
        angle_section = extract_section(angles, ANGLE_SECTIONS[angle])
        sections.extend(["", "## Selected Angle", "", angle_section])

    sections.extend(
        [
            "",
            shared_context,
            "",
            channel_contract,
            "",
            "## Operator Instruction",
            "",
            "Fill in the Inputs list inside the selected channel contract above, then draft using that contract.",
            "After drafting, run Contract 6: Draft Self-Check from `prompt-contracts.md` before posting.",
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
        "--output",
        type=Path,
        help="Write the bundle to this file instead of stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    bundle = build_bundle(args.channel, args.angle)

    if args.output:
        args.output.write_text(bundle, encoding="utf-8")
    else:
        sys.stdout.write(bundle)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
