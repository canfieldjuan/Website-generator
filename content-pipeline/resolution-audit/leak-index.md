# Leak Index

Always load this file first when drafting vendor-cost or leak-based Resolution
Audit content. It is the router. Pick one leak tag, then retrieve matching
rows from `evidence.jsonl` and the matching section from `frames.md`.

Vendor evidence shows how the platform monetizes a surface. It does not prove
customer waste by itself. Customer waste requires the customer's export, plan,
usage, and audit findings.

| tag | metric | what the platform monetizes | vendors with evidence cards | required customer inputs | safe claim posture | fallback when thin |
|---|---|---|---|---|---|---|
| `repeat_resolution` | Repeat Resolution Spend | same AI outcome charged again | intercom, gorgias, zendesk, helpscout | repeated question count, AI-resolved count, per-resolution price, reopen marker if available | estimated exposure from repeat outcomes | show as vendor-meter risk, do not estimate |
| `ai_attempt_waste` | Paid Attempts vs Resolutions | sessions billed even when they do not solve | freshdesk | AI sessions used, resolved sessions, unresolved/escalated sessions, session-pack price | estimated paid attempts not proven resolved | label as session-meter exposure only |
| `ticket_overage` | Preventable Overage Cost | volume above plan limits | gorgias | included ticket allowance, actual billable tickets, overage rate, repeat-ticket count | estimated overage exposure from repeats above plan | report plan-limit risk, no dollar estimate |
| `seat_pressure` | Avoidable Seat Pressure | per-agent seats and AI add-ons | zendesk, helpscout | seat count, agent plan, add-ons, repeat workload hours, staffing threshold | pressure indicator, not avoided-hire proof | say repeats may contribute to staffing pressure |
| `qa_waste` | QA Waste on Preventable | paying to score every interaction | zendesk | QA add-on status, interaction count, repeat/preventable count, QA coverage rule | estimated QA review surface tied to repeats | mark as QA review scope, no waste claim |
| `wfm_forecast` | Forecast Pollution | staffing forecast built on total volume | zendesk | WFM usage, forecast input volume, repeat volume, removable-repeat hypothesis | repeat demand may pollute staffing forecast | say forecast impact requires WFM data |
| `channel_tax` | Multi-Channel Repeat Demand | SMS, WhatsApp, phone, or email usage | intercom, gorgias | channel mix, channel surcharge, repeated issue count per channel, customer contact paths | estimated channel-cost exposure | label as channel concentration only |
| `knowledge_gap` | Knowledge Gap Cost | KB, search, and AI tooling upsells | zendesk, intercom, helpscout | repeated question, KB coverage, AI source coverage, search/no-answer logs | knowledge gap candidate, not proof the KB caused the issue | mark as "needs content/source review" |
| `macro_debt` | Macro Debt | agents rewriting the same answer | internal / audit-only | repeated answer text, macro usage, handle-time sample, draftability evidence | operational debt in agent work | no estimate; show repeated wording examples |
| `false_deflection` | False Deflection | bot closes, customer comes back | intercom, gorgias, zendesk, helpscout, freshdesk | AI-closed/resolved marker, reopen marker, follow-up contact, negative CSAT if available | investigatory false-deflection candidate | say deflected does not equal resolved; do not accuse |

## Retrieval Pattern

```bash
tag=repeat_resolution
rg -n "\"tag\":\"$tag\"" content-pipeline/resolution-audit/evidence.jsonl
rg -n "^## .*\\`$tag\\`" content-pipeline/resolution-audit/frames.md
```

## Claim Boundary

Use vendor evidence for:

- pricing model
- billable unit
- plan-limit or add-on mechanics
- why a leak category is plausible

Use customer audit evidence for:

- actual repeated-question count
- actual cost exposure
- probable owner lane
- whether the issue is documentation, product, billing, policy, process, or
  unresolved

Never turn a vendor evidence card into a customer outcome claim.
