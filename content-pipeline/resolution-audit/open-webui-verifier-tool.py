"""
title: Resolution Audit Draft Verifier
author: Juan Canfield / Codex
version: 0.1.0
description: Checks Resolution Audit drafts for claim risk, missing owner routing, and unsafe report-shape language.
"""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Any


RULES = {
    "outcomes": [
        ("guaranteed-savings", r"\bguaranteed\s+savings\b"),
        ("guarantees-savings", r"\bguarantees?\s+savings\b"),
        ("guaranteed-rankings", r"\bguaranteed\s+rankings\b"),
        ("guaranteed-ticket-volume-reduction", r"\bguaranteed\s+ticket[- ]volume\s+reduction\b"),
        ("fixed-deflection-percent", r"\b\d{1,3}\s*%\s+deflection\b"),
        (
            "fixed-ticket-volume-reduction",
            r"\b(?:cut|cuts|reduce|reduces|lower|lowers|drop|drops|shrink|shrinks)\s+ticket\s+volume\s+by\s+\d{1,3}\s*(?:%|percent)\b",
        ),
        ("fixed-fewer-tickets", r"\b\d{1,3}\s*(?:%|percent)\s+(?:fewer|less)\s+tickets?\b"),
    ],
    "automation": [
        ("live-help-center-publishing", r"\blive\s+help[- ]center\s+publishing\b"),
        ("automatic-help-center-updates", r"\bautomatic\s+help[- ]center\s+updates\b"),
        ("automatic-ticket-answering", r"\bautomatic\s+ticket\s+answering\b"),
        ("auto-published", r"\bauto[- ]published\b"),
        ("automatically-updates-help-center", r"\bautomatically\s+updates?\s+(?:your\s+)?help[- ]center\b"),
        ("answers-tickets-automatically", r"\banswers?\s+tickets?\s+automatically\b"),
    ],
    "replacing_agents": [
        ("replace-agents", r"\breplac(?:e|es|ing)\s+(support\s+)?agents?\b"),
        ("avoid-support-hire", r"\bavoid(?:ing)?\s+(?:a|the|your\s+)?(?:next\s+)?support\s+hire\b"),
        ("next-support-hire-slides-right", r"\byour\s+next\s+support\s+hire\s+slides?\s+right\b"),
    ],
    "privacy_churn": [
        (
            "exact-churn-reasons-from-support-tickets",
            r"\bdiagnos(?:e|es|ing)\s+exact\s+churn\s+reasons?\s+from\s+support\s+tickets?\b",
        ),
        (
            "customer-data-trains-shared-model",
            r"\b(?:use|uses|using)\s+customer\s+data\s+to\s+train\s+(?:a\s+)?shared\s+model\b|\btrain(?:s|ing)?\s+(?:a\s+)?shared\s+model\s+(?:on|with)\s+customer\s+data\b",
        ),
    ],
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b")
ANSWER_RE = re.compile(r"\b(drafted answer|answer|answers)\b|\bresolutions?\b(?!\s+(?:audit|snapshot)\b)", re.I)
ANSWER_QUALIFIER_RE = re.compile(
    r"\b(agent resolution|scoped resolution|when (?:that )?evidence exists|if (?:the )?tickets contain|no proven answer)\b",
    re.I,
)
REPORT_SHAPE_RE = re.compile(
    r"\b(?:resolution\s+audit|resolution\s+snapshot|snapshot|report|audit|action\s+queue|ranked|ranks|drafts?|faqs?|repeated\s+questions?)\b",
    re.I,
)
OWNER_ROUTING_RE = re.compile(
    r"\b(?:owner|owners|ownership|owner\s+lane|routing|route|routes|routed|department|who\s+needs\s+to\s+(?:fix|review)|needs\s+to\s+(?:fix|review)|responsible|for\s+review)\b",
    re.I,
)
OWNERSHIP_RE = re.compile(
    r"\b(?:engineering|product|support|cx|policy|ops|operations|billing|success|content|docs|documentation|legal)\s+(?:owns?|is responsible for|are responsible for|should own|must own)\b|\b(?:owned by|responsible for)\b",
    re.I,
)
OWNERSHIP_QUALIFIER_RE = re.compile(
    r"\b(probable|probably|may|might|could|likely|often|appears|seems|investigate|route|routing|signal)\b",
    re.I,
)


def _is_negated(text: str, start: int) -> bool:
    clause_start = max(text.rfind(mark, 0, start) for mark in ".!?;\n")
    prefix = text[clause_start + 1 : start].lower()
    if re.search(r"\b(?:but|however)\b", prefix):
        prefix = re.split(r"\b(?:but|however)\b", prefix)[-1]
    return bool(re.search(r"\b(no|not|never|without)\b|\bdo(?:es)?\s+not\s+promise\b|\bdoesn't\s+promise\b", prefix))


def _pattern_hits(text: str, rules: list[tuple[str, str]]) -> list[dict[str, str]]:
    hits = []
    for code, pattern in rules:
        for match in re.finditer(pattern, text, re.I):
            if not _is_negated(text, match.start()):
                hits.append({"code": code, "evidence": match.group(0)})
    return hits


def _sentence(text: str, start: int) -> str:
    sentence_start = max(text.rfind(mark, 0, start) for mark in ".!?\n")
    ends = [idx for mark in ".!?\n" if (idx := text.find(mark, start)) != -1]
    sentence_end = min(ends) if ends else len(text)
    return text[sentence_start + 1 : sentence_end].strip()


def _unqualified(text: str, word_re: re.Pattern[str], qualifier_re: re.Pattern[str], code: str) -> list[dict[str, str]]:
    hits = []
    for match in word_re.finditer(text):
        sentence = _sentence(text, match.start())
        if not qualifier_re.search(sentence):
            hits.append({"code": code, "evidence": sentence or match.group(0)})
    return hits


def _row(rule_id: str, status: str, evidence: str) -> dict[str, str]:
    return {"rule_id": rule_id, "status": status, "evidence": evidence}


def _coverage(text: str) -> list[dict[str, str]]:
    outcome_hits = _pattern_hits(text, RULES["outcomes"])
    automation_hits = _pattern_hits(text, RULES["automation"])
    replacing_hits = _pattern_hits(text, RULES["replacing_agents"])
    privacy_churn_hits = _pattern_hits(text, RULES["privacy_churn"])
    contact_hits = [{"code": "email", "evidence": m.group(0)} for m in EMAIL_RE.finditer(text)]
    contact_hits += [{"code": "phone", "evidence": m.group(0)} for m in PHONE_RE.finditer(text)]
    answer_hits = _unqualified(text, ANSWER_RE, ANSWER_QUALIFIER_RE, "unqualified-answer-claim")
    ownership_hits = _unqualified(text, OWNERSHIP_RE, OWNERSHIP_QUALIFIER_RE, "unqualified-ownership-claim")

    report_shape = bool(REPORT_SHAPE_RE.search(text))
    owner_routing = bool(OWNER_ROUTING_RE.search(text))
    if report_shape and owner_routing:
        owner_status = "warning"
        owner_evidence = "Draft mentions ownership, routing, departments, or who should review the fix; confirm it stays probable."
    elif report_shape:
        owner_status = "warning"
        owner_evidence = "Draft explains the report shape but omits owner routing or who should review the fix."
    else:
        owner_status = "not_applicable"
        owner_evidence = "Draft does not appear to explain the report shape."

    answer_status = "warning" if answer_hits else ("pass" if ANSWER_RE.search(text) else "not_applicable")
    answer_evidence = "; ".join(f"{h['code']}: {h['evidence']}" for h in answer_hits)
    if not answer_hits:
        answer_evidence = "Answer/resolution claims are qualified or not present."

    return [
        _row("RA-NO-GUARANTEED-OUTCOMES", "blocker" if outcome_hits else "warning", _format_hits(outcome_hits, "No exact forbidden outcome phrase detected.")),
        _row("RA-NO-AUTO-PUBLISHING", "blocker" if automation_hits else "warning", _format_hits(automation_hits, "No exact forbidden automation phrase detected.")),
        _row("RA-NO-REPLACING-AGENTS", "blocker" if replacing_hits else "warning", _format_hits(replacing_hits, "No replacing-agent or avoided-hire phrase detected.")),
        _row("RA-NO-PRIVACY-CHURN-CLAIMS", "blocker" if privacy_churn_hits else "warning", _format_hits(privacy_churn_hits, "No exact forbidden privacy or churn phrase detected.")),
        _row("RA-NO-RAW-CONTACT-DATA", "blocker" if contact_hits else "pass", _format_hits(contact_hits, "No email addresses or phone-number-shaped strings detected.")),
        _row("RA-ANSWER-EVIDENCE-QUALIFIER", answer_status, answer_evidence),
        _row("RA-OWNER-ROUTING-COVERAGE", owner_status, owner_evidence),
        _row("RA-OWNERSHIP-QUALIFIER", "warning" if ownership_hits else "not_applicable", _format_hits(ownership_hits, "No ownership-certainty sentence detected.")),
        _row("RA-HONEST-CTA", "warning", "Human review required: confirm the CTA matches the channel and offer posture."),
    ]


def _format_hits(hits: list[dict[str, str]], fallback: str) -> str:
    if not hits:
        return fallback
    return "; ".join(f"{hit['code']}: {hit['evidence']}" for hit in hits)


def _verdict(rows: list[dict[str, str]]) -> str:
    if any(row["status"] == "blocker" for row in rows):
        return "Do not post yet"
    if any(row["status"] == "warning" for row in rows):
        return "Needs human review"
    return "No obvious blockers"


def _render(payload: dict[str, Any]) -> str:
    lines = [
        "## Resolution Audit Draft Check",
        "",
        f"Verdict: **{payload['verdict']}**",
        f"Channel: `{payload['channel']}`",
        f"Asset: `{payload['asset_id']}`",
        f"As of: `{payload['as_of']}`",
        "",
        "| Rule | Status | Evidence |",
        "|---|---|---|",
    ]
    for row in payload["coverage"]:
        evidence = row["evidence"].replace("\n", " ").replace("|", "\\|")
        lines.append(f"| `{row['rule_id']}` | {row['status']} | {evidence} |")

    lines.extend(["", "### Next Revision Priorities"])
    if payload["verdict"] == "Do not post yet":
        lines.append("- Remove blocker language before posting.")
    if any(row["rule_id"] == "RA-OWNER-ROUTING-COVERAGE" and row["status"] == "warning" for row in payload["coverage"]):
        lines.append("- Add the probable owner lane if this draft explains the report or Snapshot.")
    if any(row["rule_id"] == "RA-ANSWER-EVIDENCE-QUALIFIER" and row["status"] == "warning" for row in payload["coverage"]):
        lines.append("- Qualify answer/draft claims with evidence language or no-proven-answer wording.")
    if any(row["rule_id"] == "RA-OWNERSHIP-QUALIFIER" and row["status"] == "warning" for row in payload["coverage"]):
        lines.append("- Replace certain ownership with probable, may, appears, route, or investigate language.")
    return "\n".join(lines)


class Tools:
    async def verify_resolution_audit_draft(
        self,
        draft: str,
        channel: str = "linkedin",
        asset_id: str = "chat-draft",
        as_of: str = "",
        include_json: bool = False,
    ) -> str:
        """
        Review a Resolution Audit draft for claim risk and missing owner-routing language.

        :param draft: Full draft text to check.
        :param channel: Draft channel, such as linkedin, reddit, reply, blog, or feedback.
        :param asset_id: Optional label for the draft.
        :param as_of: Optional ISO date. Defaults to today.
        :param include_json: Include structured JSON after the Markdown report.
        """
        if not draft or not draft.strip():
            return "Paste a draft into `draft` before running the verifier."

        rows = _coverage(draft)
        payload = {
            "asset_id": asset_id or "chat-draft",
            "channel": channel or "unknown",
            "as_of": as_of or date.today().isoformat(),
            "coverage": rows,
            "verdict": _verdict(rows),
        }
        report = _render(payload)
        if include_json:
            report += "\n\n```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```"
        return report
