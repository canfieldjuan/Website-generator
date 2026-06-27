#!/usr/bin/env python3
"""Prepare an ATLAS verify_draft payload for a saved Resolution Audit draft."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Any

from bundle_prompt import CHANNEL_CONTRACTS


OUTCOME_PATTERNS = [
    ("guaranteed-savings", re.compile(r"\bguaranteed\s+savings\b", re.I)),
    ("guaranteed-rankings", re.compile(r"\bguaranteed\s+rankings\b", re.I)),
    (
        "guaranteed-ticket-volume-reduction",
        re.compile(r"\bguaranteed\s+ticket[- ]volume\s+reduction\b", re.I),
    ),
    ("fixed-deflection-percent", re.compile(r"\b\d{1,3}\s*%\s+deflection\b", re.I)),
    (
        "fixed-ticket-volume-reduction",
        re.compile(
            r"\b(?:cut|cuts|reduce|reduces|lower|lowers|drop|drops|shrink|shrinks)\s+ticket\s+volume\s+by\s+\d{1,3}\s*(?:%|percent)\b",
            re.I,
        ),
    ),
    (
        "fixed-fewer-tickets",
        re.compile(r"\b\d{1,3}\s*(?:%|percent)\s+(?:fewer|less)\s+tickets?\b", re.I),
    ),
]

AUTOMATION_PATTERNS = [
    ("live-help-center-publishing", re.compile(r"\blive\s+help[- ]center\s+publishing\b", re.I)),
    ("automatic-help-center-updates", re.compile(r"\bautomatic\s+help[- ]center\s+updates\b", re.I)),
    ("automatic-ticket-answering", re.compile(r"\bautomatic\s+ticket\s+answering\b", re.I)),
    ("auto-published", re.compile(r"\bauto[- ]published\b", re.I)),
    (
        "automatically-updates-help-center",
        re.compile(r"\bautomatically\s+updates?\s+(?:your\s+)?help[- ]center\b", re.I),
    ),
    (
        "answers-tickets-automatically",
        re.compile(r"\banswers?\s+tickets?\s+automatically\b", re.I),
    ),
]

REPLACING_AGENT_PATTERNS = [
    ("replace-agents", re.compile(r"\breplac(?:e|es|ing)\s+(support\s+)?agents?\b", re.I)),
    ("avoid-support-hire", re.compile(r"\bavoid\s+a\s+support\s+hire\b", re.I)),
]

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b")
ANSWER_WORD_PATTERN = re.compile(r"\b(answer|answers|resolution|resolutions|drafted answer)\b", re.I)
ANSWER_QUALIFIER_PATTERN = re.compile(
    r"\b(agent resolution|scoped resolution|when (?:that )?evidence exists|if (?:the )?tickets contain|no proven answer)\b",
    re.I,
)
OWNERSHIP_WORD_PATTERN = re.compile(
    r"\b(?:engineering|product|support|cx|policy|ops|operations|billing|success|content|docs|documentation|legal)\s+(?:owns?|is responsible for|are responsible for|should own|must own)\b|\b(?:owned by|responsible for)\b",
    re.I,
)
OWNERSHIP_QUALIFIER_PATTERN = re.compile(
    r"\b(probable|probably|may|might|could|likely|often|appears|seems|investigate|route|routing|signal)\b",
    re.I,
)


def _is_negated_context(text: str, start: int) -> bool:
    clause_start = max(text.rfind(mark, 0, start) for mark in ".!?;\n")
    prefix = text[clause_start + 1 : start].lower()
    if re.search(r"\b(?:but|however)\b", prefix):
        prefix = re.split(r"\b(?:but|however)\b", prefix)[-1]
    return bool(
        re.search(
            r"(?:\bno\b|\bnot\b|\bnever\b|\bwithout\b|\bdo\s+not\s+promise\b|\bdoes\s+not\s+promise\b|\bdoesn't\s+promise\b)",
            prefix,
        )
    )


def _sentence_bounds(text: str, start: int) -> tuple[int, int]:
    sentence_start = max(text.rfind(mark, 0, start) for mark in ".!?\n")
    sentence_end_candidates = [idx for mark in ".!?\n" if (idx := text.find(mark, start)) != -1]
    sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
    return sentence_start + 1, sentence_end


def _sentence_for_match(text: str, start: int) -> str:
    sentence_start, sentence_end = _sentence_bounds(text, start)
    return text[sentence_start:sentence_end]


def _unqualified_matches(
    text: str,
    word_pattern: re.Pattern[str],
    qualifier_pattern: re.Pattern[str],
    *,
    code: str,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for match in word_pattern.finditer(text):
        sentence = _sentence_for_match(text, match.start())
        if not qualifier_pattern.search(sentence):
            findings.append({"code": code, "evidence": sentence.strip() or match.group(0)})
    return findings


def _matches(
    text: str,
    patterns: list[tuple[str, re.Pattern[str]]],
    *,
    skip_negated: bool = True,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for code, pattern in patterns:
        for match in pattern.finditer(text):
            if skip_negated and _is_negated_context(text, match.start()):
                continue
            findings.append({"code": code, "evidence": match.group(0)})
    return findings


def _coverage_row(rule_id: str, requirement: str, status: str, evidence: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "requirement": requirement,
        "required": True,
        "status": status,
        "evidence": evidence,
    }


def _quality_finding(code: str, message: str, severity: str, field_name: str) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "field_name": field_name,
    }


def build_packet(*, draft_text: str, draft_path: Path, channel: str, asset_id: str, as_of: str) -> dict[str, Any]:
    outcome_hits = _matches(draft_text, OUTCOME_PATTERNS)
    automation_hits = _matches(draft_text, AUTOMATION_PATTERNS)
    replacing_hits = _matches(draft_text, REPLACING_AGENT_PATTERNS)
    contact_hits = [{"code": "email", "evidence": item.group(0)} for item in EMAIL_PATTERN.finditer(draft_text)]
    contact_hits.extend({"code": "phone", "evidence": item.group(0)} for item in PHONE_PATTERN.finditer(draft_text))

    answer_mentions = bool(ANSWER_WORD_PATTERN.search(draft_text))
    unqualified_answer_hits = _unqualified_matches(
        draft_text,
        ANSWER_WORD_PATTERN,
        ANSWER_QUALIFIER_PATTERN,
        code="unqualified-answer-claim",
    )
    ownership_hits = _unqualified_matches(
        draft_text,
        OWNERSHIP_WORD_PATTERN,
        OWNERSHIP_QUALIFIER_PATTERN,
        code="unqualified-ownership-claim",
    )
    answer_status = "not_applicable"
    answer_evidence = "Draft does not make answer or resolution claims."
    if unqualified_answer_hits:
        answer_status = "unresolved"
        answer_evidence = "; ".join(
            f"{hit['code']}: {hit['evidence']}" for hit in unqualified_answer_hits
        )
    elif answer_mentions:
        answer_status = "pass"
        answer_evidence = "Each detected answer/resolution sentence includes agent/scoped resolution evidence or no-proven-answer language."

    coverage = [
        _coverage_row(
            "RA-NO-GUARANTEED-OUTCOMES",
            "Draft avoids guaranteed savings, guaranteed rankings, guaranteed ticket-volume reduction, and fixed deflection percentages.",
            "fail" if outcome_hits else "unresolved",
            "; ".join(f"{hit['code']}: {hit['evidence']}" for hit in outcome_hits)
            if outcome_hits
            else "No exact forbidden outcome phrase detected; human review still required for paraphrased savings, ranking, or volume claims.",
        ),
        _coverage_row(
            "RA-NO-AUTO-PUBLISHING",
            "Draft avoids live publishing, automatic help-center updates, and automatic ticket answering claims.",
            "fail" if automation_hits else "unresolved",
            "; ".join(f"{hit['code']}: {hit['evidence']}" for hit in automation_hits)
            if automation_hits
            else "No exact forbidden automation phrase detected; human review still required for automation paraphrases.",
        ),
        _coverage_row(
            "RA-NO-REPLACING-AGENTS",
            "Draft avoids replacing-agent and avoided-hire promises.",
            "fail" if replacing_hits else "unresolved",
            "; ".join(f"{hit['code']}: {hit['evidence']}" for hit in replacing_hits)
            if replacing_hits
            else "No exact replacing-agent or avoided-hire phrase detected; human review still required for role-impact claims.",
        ),
        _coverage_row(
            "RA-NO-RAW-CONTACT-DATA",
            "Draft avoids raw contact identifiers in public examples.",
            "fail" if contact_hits else "pass",
            "; ".join(f"{hit['code']}: {hit['evidence']}" for hit in contact_hits)
            if contact_hits
            else "No email addresses or phone-number-shaped strings detected.",
        ),
        _coverage_row(
            "RA-ANSWER-EVIDENCE-QUALIFIER",
            "Draft qualifies answer claims with agent/scoped resolution evidence or no-proven-answer language.",
            answer_status,
            answer_evidence,
        ),
        _coverage_row(
            "RA-OWNERSHIP-QUALIFIER",
            "Draft avoids certainty that a specific team owns a repeated issue unless framed as probable or investigatory.",
            "unresolved" if ownership_hits else "not_applicable",
            "; ".join(f"{hit['code']}: {hit['evidence']}" for hit in ownership_hits)
            if ownership_hits
            else "No ownership-certainty sentence detected.",
        ),
        _coverage_row(
            "RA-HONEST-CTA",
            "CTA is honest about the next step and does not imply guaranteed savings, guaranteed rankings, or resolution lift.",
            "unresolved",
            "Human review required: confirm the CTA matches the channel and offer posture.",
        ),
    ]

    findings = []
    for row in coverage:
        if row["status"] == "fail":
            findings.append(
                _quality_finding(
                    code=row["rule_id"],
                    message=row["requirement"],
                    severity="blocker",
                    field_name="draft",
                )
            )
        elif row["status"] == "unresolved":
            findings.append(
                _quality_finding(
                    code=row["rule_id"],
                    message=row["evidence"],
                    severity="warning",
                    field_name="draft",
                )
            )

    return {
        "asset_id": asset_id,
        "rule_packet": {
            "brief": "content-pipeline/resolution-audit/source-pack.md",
            "brand_voice": "content-pipeline/resolution-audit/source-pack.md#voice",
            "claim_registry": "content-pipeline/resolution-audit/claims-guard.md",
            "compliance": "content-pipeline/resolution-audit/claims-guard.md#required-review-questions",
            "channel_schema": f"content-pipeline/resolution-audit/prompt-contracts.md#{CHANNEL_CONTRACTS[channel]}",
        },
        "coverage": coverage,
        "extracted_claims": [],
        "quality_reports": [
            {
                "passed": not any(row["status"] in {"fail", "unresolved"} for row in coverage),
                "findings": findings,
            }
        ],
        "brand_voice_payload": {
            "passed": True,
            "warnings": [],
            "banned_terms": [],
        },
        "comments": [
            {
                "category": "editorial_judgment",
                "message": "Local handoff packet prepared. Fill extracted_claims and unresolved evidence before calling ATLAS verify_draft.",
                "evidence": str(draft_path),
                "blocking": False,
            }
        ],
        "adversarial_passes": [],
        "calibration_library": [],
        "as_of": as_of,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a structured ATLAS verify_draft JSON packet from a saved Resolution Audit draft.",
    )
    parser.add_argument("--draft", type=Path, required=True, help="Path to the draft text or Markdown file.")
    parser.add_argument("--channel", choices=sorted(CHANNEL_CONTRACTS), required=True)
    parser.add_argument("--asset-id", help="Stable asset id. Defaults to the draft filename stem.")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="ISO review date for registry checks.")
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    draft_text = args.draft.read_text(encoding="utf-8")
    packet = build_packet(
        draft_text=draft_text,
        draft_path=args.draft,
        channel=args.channel,
        asset_id=args.asset_id or args.draft.stem,
        as_of=args.as_of,
    )
    payload = json.dumps(packet, indent=2, sort_keys=True) + "\n"

    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
