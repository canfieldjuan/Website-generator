# Report Shape Example

Use this when a model needs to understand the target Resolution Audit
report-shape pattern.

This is a fictional example. Do not present the issue names, counts, costs, or
owner lanes as customer proof. Replace bracketed values with real audit data or
remove them. Do not claim this exact structure has shipped unless current
product code or report output confirms it.

## The Before/Now Shape

The old report answered:

- What repeated?
- What might it cost?
- What FAQ or answer could we draft from resolved tickets?
- What customer wording or search language showed up?
- Which unresolved gaps had no proven answer?

The target report shape keeps that and adds:

- Who may need to review the fix?
- Is this a documentation issue, a product issue, a billing issue, a policy
  issue, a process issue, or a support-ops issue?
- What should happen next: publish, rewrite, route, investigate, or stop
  drafting because the workflow is broken?

Short version:

```text
The old report was a ranked repeat list with cost and content output.
The target report is a ranked action queue with cost, evidence, content output,
unresolved gaps, and probable owner routing.
```

## Snapshot Example

Example only. Replace all bracketed fields with audit data.

| Field | Example |
|---|---|
| Top repeated issue | `[invoice PDF missing tax line]` |
| Repeat signal | `[N] matching closed tickets in [date range]` |
| Estimated cost exposure | `[estimated monthly exposure]` |
| Resolution evidence | `[agent answer exists / no proven answer / mixed]` |
| Customer wording | "`[Why does my invoice not show tax?]`", "`[Where is the tax line on the PDF?]`" |
| Content output | `[review-ready FAQ draft / no draft because evidence is missing]` |
| Probable owner lane | `[Billing Ops / Product Billing / Documentation]` |
| Next review action | `[confirm invoice template behavior before publishing the answer]` |

Plain-language summary:

```text
The top repeat appears to be an invoice-PDF question. The ticket history shows
customers asking for the same missing line in similar words. Agents have a
partial answer, but the root cause may sit with Billing Ops or Product Billing,
not only Support. The Snapshot should route this for review before treating it
as a simple FAQ.
```

## Full Audit Ranked Queue

Example only. Use this shape, not these fictional values.

| Rank | Repeated issue | Evidence | Estimated exposure | Content output | Gap status | Probable owner lane | Next action |
|---:|---|---|---|---|---|---|---|
| 1 | Invoice PDF missing tax line | repeated wording + agent workaround | `[cost exposure]` | draft answer if template behavior is confirmed | partial answer | Billing Ops / Product Billing | route before publishing |
| 2 | Password reset loop | reopen marker + repeated failed steps | `[cost exposure]` | no FAQ yet | no proven answer | Product UX / Engineering | investigate workflow |
| 3 | SSO setup confusion | repeated setup wording + proven agent answer | `[cost exposure]` | review-ready FAQ | answer exists | Documentation / Onboarding | publish or improve doc |
| 4 | Duplicate annual charge | negative CSAT + refund language | `[cost exposure]` | no draft until policy is checked | policy gap | Billing Policy / Success | review policy and refund path |
| 5 | Bot closes shipping-status chat | AI-closed marker + follow-up contact | `[cost exposure]` | no draft yet | false-deflection candidate | Support Ops / Automation | inspect bot answer and fallback |

## Finding Detail Card

Use one card per repeated issue in the full audit.

```text
Issue:
Password reset loop

Why it matters:
Customers repeat the same failed reset steps after the ticket is marked
resolved. This may be repeat resolution spend, support rework, or false
deflection exposure depending on the vendor and ticket markers.

Evidence:
- repeated wording: "[reset link expires]", "[cannot reset password]"
- source-ticket IDs: [redacted IDs or internal references]
- reopen/follow-up marker: [present / absent / unknown]
- resolution evidence: no proven answer in ticket history

Content decision:
Do not draft a public FAQ yet. The tickets do not show a reliable answer.

Probable owner lane:
Product UX / Engineering

Next review action:
Check whether reset-token expiry, email delivery, or account-state logic is
causing the repeat before Support writes another answer.
```

## Owner Routing Map

Use this map to keep owner language practical and non-accusatory.

| Signal in the tickets | Safer owner lane | Plain wording |
|---|---|---|
| Agents answer the same how-to question with a stable answer | Documentation / Content | "This may be ready for a review-ready help article." |
| Customers repeat a broken flow or failed step | Product UX / Engineering | "This may need product review before another article helps." |
| Refund, invoice, renewal, or charge confusion repeats | Billing Ops / Billing Policy | "Billing may need to review the workflow or policy." |
| Agents rewrite the same answer without using a macro | Support Ops | "Support Ops may be able to reduce repeated agent work." |
| Bot closes the chat and customers come back | Support Ops / Automation | "Deflected does not prove resolved; inspect the bot path." |
| Customers ask the same setup question during activation | Onboarding / Documentation | "This may belong in onboarding, docs, or both." |

## Language To Copy

Use:

- "probable owner lane"
- "route for review"
- "may need product, billing, policy, process, or documentation review"
- "content output when the evidence supports it"
- "no proven answer when the ticket history does not show one"
- "estimated cost exposure, not promised savings"

Avoid:

- "Product owns this"
- "Billing caused this"
- "Support failed"
- "This will reduce tickets"
- "Publish this automatically"
- "Every repeated question gets an FAQ"
