# PR: Resolution Audit Verifier Handoff

## Why this slice exists

The Resolution Audit content workflow can now build Open WebUI prompt bundles,
but the verification step is still manual. The existing ATLAS
`verify_draft` MCP is the right later verifier, but it expects structured
evidence fields instead of a raw draft. Because the OAuth-facing MCP route is
not the reliable dependency in this repo yet, this slice should prepare the
payload shape without wiring a live server call.

This slice adds a local handoff command that turns a draft file into a
`verify_draft` JSON packet. It catches obvious forbidden claims locally and
leaves explicit unresolved rows for the human/operator evidence that still
needs to be filled before calling ATLAS.

## Scope (this PR)

1. Add a standard-library CLI that reads a draft and emits a JSON payload using
   the real ATLAS `verify_draft` argument names.
2. Include deterministic local checks for forbidden outcome claims,
   auto-publishing/ticket-answering claims, replacing-agent claims, contact
   identifiers, ownership certainty, and weak answer-evidence qualifiers.
3. Update the kit README with the verifier handoff command and make clear that
   the script prepares a packet; it does not call MCP.

### Files touched

- `plans/PR-Resolution-Audit-Verifier-Handoff.md`
- `content-pipeline/resolution-audit/README.md`
- `content-pipeline/resolution-audit/prepare_verifier_packet.py`

## Mechanism

`prepare_verifier_packet.py` reads a local draft file and produces JSON with
these ATLAS `verify_draft` fields: `asset_id`, `rule_packet`, `coverage`,
`extracted_claims`, `quality_reports`, `brand_voice_payload`, `comments`,
`adversarial_passes`, `calibration_library`, and `as_of`.

The coverage rows are intentionally conservative. Clear forbidden phrases
become `fail` rows and blocker quality findings. Rows that a deterministic
regex cannot prove stay `unresolved` instead of being marked green. The
operator can then add extracted claims and evidence before submitting the
packet to the ATLAS MCP when that server is available.

## Intentional

- No MCP network call. The content ops verifier endpoint can be restored in a
  later infrastructure slice; this repo only prepares the payload.
- No claim extraction model. Extracted claims remain an explicit fill-in list so
  the handoff does not invent registry mappings.
- No live Open WebUI integration. The command works on a saved draft file.

## Deferred

- Restore durable ATLAS content-ops verifier OAuth services when that lane is
  active again.
- Add sanitized sample drafts and expected verifier packets once real generated
  outputs exist.

## Verification

- `python content-pipeline/resolution-audit/prepare_verifier_packet.py --help`
- `printf 'No guaranteed savings. The answer is backed by agent resolution evidence when it exists. Email me at test@example.com.' >/tmp/resolution-audit-draft.txt`
- `python content-pipeline/resolution-audit/prepare_verifier_packet.py --draft /tmp/resolution-audit-draft.txt --channel linkedin --asset-id smoke --as-of 2026-06-27 --output /tmp/resolution-audit-verify-packet.json`
- `python -m json.tool /tmp/resolution-audit-verify-packet.json >/tmp/resolution-audit-verify-packet.pretty.json`
- `rg -n '"asset_id": "smoke"|"rule_packet"|"coverage"|"quality_reports"|"extracted_claims"|"as_of": "2026-06-27"|"status": "fail"' /tmp/resolution-audit-verify-packet.pretty.json`
- Boundary probes:
  - required disclaimer: `does not promise savings, guaranteed rankings, or ticket-volume reduction` returns `RA-NO-GUARANTEED-OUTCOMES` as `unresolved`, not `fail`
  - ownership certainty: `Engineering owns this repeated issue` returns `RA-OWNERSHIP-QUALIFIER` as `unresolved`
  - volume and automation: `cut ticket volume by 30 percent and automatically update your help center` returns `fail`
  - global answer qualifier miss: `writes answers for every repeated question` returns `RA-ANSWER-EVIDENCE-QUALIFIER` as `unresolved`
  - unseparated phone number: `3125550142` returns `RA-NO-RAW-CONTACT-DATA` as `fail`
- `python -m py_compile content-pipeline/resolution-audit/prepare_verifier_packet.py`
- `rg -n "deflects? ~|~30%|25-35%|real deflection rate|auto-updated|launch a self-service center|keep it current automatically|support hire slides" content-pipeline/resolution-audit --glob '!claims-guard.md'`
  - Expected: no matches; unsupported older promises should only appear inside
    the guard as examples of what not to publish.
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Estimated size: 3 files, about 280 added/changed lines. This stays under the
400 LOC soft cap.
