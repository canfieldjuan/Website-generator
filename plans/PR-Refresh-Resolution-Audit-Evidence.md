# PR: Refresh Resolution Audit evidence cards

## Why this slice exists

Issue #57 identifies that all 21 cards in `content-pipeline/resolution-audit/evidence.jsonl` expired on 2026-09-25.
They were last checked on 2026-06-27, against a 90-day `evidence_freshness_days` policy. The required `audit` status
context (`validate_evidence.py --fail-on-stale`) therefore fails on every pull request.

The fix is a source re-check, not a date bump. Each card's `source_url` was re-opened on 2026-10-05, and the card's
summary and numbers were compared with the live page.

## Scope (this PR)

1. Re-verify every public-source card against its live page, and record a verdict with verbatim quotes.
2. Re-date every card to `source_date` = `source_checked_at` = 2026-10-05. That makes `expires_at` = 2027-01-03,
   which is check date + 90 days, as the validator requires.
3. Correct the 8 cards whose live source no longer matches, changing only what the page contradicts.
4. Keep every card `id`, `tag` and `evidence_type`, so router tags, frames and any external references are
   unaffected.

### Files touched

- `content-pipeline/resolution-audit/evidence.jsonl`
- `plans/PR-Refresh-Resolution-Audit-Evidence.md`

## Mechanism

Four read-only agents each fetched one vendor's source pages. They were told to use only the live page, never
memory. Each agent returned, per card, a verdict (CONFIRMED / CHANGED / UNVERIFIABLE), verbatim quotes, and any
corrected values. The results: 12 confirmed, 8 changed, 0 unverifiable. One card has no public source (see
Intentional).

### Confirmed (re-dated only)

- Intercom:
  - `intercom_fin_channel_addons`
  - `intercom_fin_knowledge_sources`
  - `intercom_fin_outcome_reopen_boundary`
- Gorgias:
  - `gorgias_billable_ticket_allowance`
  - `gorgias_false_deflection_boundary`
- Zendesk:
  - `zendesk_ai_agent_resolution`
  - `zendesk_suite_seats`: $55 / $115 per agent per month, paid yearly
  - `zendesk_quality_assurance_addon`
  - `zendesk_workforce_management`
- Help Scout:
  - `helpscout_user_pricing`: $25 / $45 / $75 per user per month
  - `helpscout_ai_answers_resolution`: $0.75 per resolution
- Freshdesk:
  - `freshdesk_false_deflection_boundary`

### Changed (operator review requested)

| Card | What changed | Live source quote |
| --- | --- | --- |
| `intercom_fin_resolution_pricing` | The unit is now an **outcome**, which covers resolutions **and completed Procedures, including handoffs**. The price is unchanged: from $0.99, charged once per conversation. | "Fin is priced at $0.99 per outcome. An outcome is counted when: A customer confirms their issue is resolved, or They don’t ask for more help after Fin responds, or Fin completes a workflow (Procedure), including handoffs" |
| `gorgias_ai_agent_resolved_conversation` | The unit is now an **automated interaction**. The rates are unchanged: $0.90 annual, $1.00 monthly. Overage is stated as **$1.50 per interaction** beyond the plan allowance, instead of "$150 per 100 resolutions". | "AI Agent interactions are priced at $0.90 each on annual plans or $1.00 on monthly plans." / "beyond it, $1.50 per interaction" |
| `gorgias_channels` | **WhatsApp is no longer listed.** Volume bands now extend lower on monthly billing: Voice $1.20 down to $0.14, SMS $0.80 down to $0.38 per ticket. | "Add Voice or SMS to any plan. Pricing scales with your call and text volume" |
| `zendesk_help_center_ai_knowledge` | The URL redirects to `/service/knowledge/`, and the product is now "Zendesk Knowledge". | "Zendesk Knowledge is AI-powered knowledge base software that helps customer service teams create, manage, and share trusted answers across self-service, AI agents, and human support." |
| `zendesk_false_deflection_boundary` | **The mechanism was wrong.** There is no "72-hour no-follow-up window". An LLM verifies the conversation text after a channel-dependent end: email 72 h after the first email, messaging 2 h by default (up to 72 h), voice at hangup. Pass is Verified; fail is Contained. | "When the conversation ends, a verification process is performed by a large language model (LLM) … Conversations that don’t pass this verification are considered a Contained resolution." |
| `helpscout_docs_knowledge` | The source page returns HTTP 404. It is replaced by Help Scout's own Docs article. | "allows you to create a public support website, or knowledge base" |
| `helpscout_false_deflection_boundary` | The unit is made precise: "depending on package" is not on the page, which states one unit at one price on all paid plans. | "$0.75 per resolution" / "A resolution is a single conversation that is resolved by AI Answers without human assistance." |
| `freshdesk_freddy_session_pricing` | The session window is now **channel-specific**: chat 24 h, email 72 h. The pack is unchanged: 100 sessions for $49. | "Email AI Agent: A session spans 72 hours from the customer's first email." |

## Intentional

- **`internal_macro_debt_audit_only` is re-dated without an external check.** Its source is
  `customer_export_required`: it is a method definition, not a public fact. The definition was re-read and is
  unchanged, and it carries no vendor or price claim. This is flagged for operator awareness.
- **Card ids keep the `_2026_06` suffix.** It names the card's origin, not its check date. Renaming would break
  references for no gain.
- **`leak-index.md` and `frames.md` are unchanged.** Their WhatsApp mentions are channel-type lists, and Intercom still
  bills WhatsApp per conversation (confirmed card). No other kit file quotes a price.

## Deferred

- **Two vendor pages contradict themselves.** These values are not cited:
  - Gorgias's compare table lists $0.85 for Advanced, while its tooltip says $0.90.
  - Freshdesk's auto-recharge section says "1 pack = 50 sessions", while elsewhere a pack is 100 sessions for $49.
- The next refresh is due before 2027-01-03.

## Verification

- `python3 content-pipeline/resolution-audit/validate_evidence.py --fail-on-stale` must report 0 expired cards.
- `python3 content-pipeline/resolution-audit/sync_product_truth.py --check` and `audit_content_kit_truth.py` must
  pass.
- `bash scripts/local_pr_review.sh` must pass.
- The required `audit` check must pass on this PR.

## Estimated diff size

Two files: 21 changed JSONL lines and this plan.
