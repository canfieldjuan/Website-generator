# PR: Resolution Audit Evidence Freshness

## Why this slice exists

Issue #19 closes the last truth-spine gap from the Resolution Audit content kit:
vendor evidence can contain exact prices, but the previous validator only warned
from `source_date` and the audit did not fail closed on stale price cards.

Slice #16 made the audit strict about product truth, slice #17 sourced the
manifest, and slice #18 put that manifest into prompt bundles. This slice makes
evidence freshness equally explicit so a stale dollar claim cannot slip through
as trusted proof.

## Scope (this PR)

1. Add `source_checked_at` and `expires_at` to every evidence card.
2. Move the freshness window default to `product-truth.json` by reading
   `fields.evidence_freshness_days.value`.
3. Update `validate_evidence.py` so expired evidence cards warn locally and fail
   when `--fail-on-stale` is used.
4. Wire evidence validation into `audit_content_kit_truth.py` as a blocking CI
   check.
5. Add an explicit workflow step for the evidence validator.

Files touched:

- `content-pipeline/resolution-audit/evidence.jsonl`
- `content-pipeline/resolution-audit/validate_evidence.py`
- `content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `.github/workflows/content-kit-truth.yml`
- `plans/PR-Resolution-Audit-Evidence-Freshness.md`

## Mechanism

Each evidence card now carries three separate dates:

- `source_date`: the source's evidence date.
- `source_checked_at`: when this kit last re-opened or checked the source.
- `expires_at`: the last date this evidence remains fresh.

`validate_evidence.py` loads `evidence_freshness_days` from the manifest when no
CLI override is supplied, validates all three dates, and confirms `expires_at`
matches `source_checked_at + freshness_days`. Exact-price detection continues to
scan nested values, not only price-looking keys.

The standalone validator keeps stale cards as warnings unless
`--fail-on-stale` is present. The content-kit audit calls the validator with
`--fail-on-stale` semantics and converts evidence warnings into blocking audit
findings, which makes CI fail closed.

## Intentional

- Expiration applies to all evidence cards, not only price cards. That is
  stricter than the original stale-price bug, but easier to reason about:
  expired evidence should not pass as current proof.
- `expires_at` is materialized on each card rather than derived only at runtime
  so reviewers and operators can see the deadline without running code.
- The manifest owns the default freshness window. The validator still accepts a
  CLI override for fixture checks and future one-off policy tests.

## Deferred

- Live vendor re-fetching stays deferred. This slice makes stale evidence
  visible and blocking; it does not automate source recapture.
- Vendor-specific freshness windows stay deferred until the kit has evidence
  that some source classes need shorter or longer validity than the default.

## Verification

Ran locally:

- `python content-pipeline/resolution-audit/validate_evidence.py --as-of 2026-06-27`
  - Passed: 21 evidence cards, 8 exact-price cards, 0 expired cards, 90-day freshness window.
- `python content-pipeline/resolution-audit/validate_evidence.py --as-of 2026-06-27 --fail-on-stale`
  - Passed with the same counts.
- `python content-pipeline/resolution-audit/audit_content_kit_truth.py`
  - Passed: no exact violations found.
- `python -m py_compile content-pipeline/resolution-audit/validate_evidence.py content-pipeline/resolution-audit/audit_content_kit_truth.py`
  - Passed.
- Temp negative fixture: a dollar value under neutral `numbers.plan_examples`
  increased the exact-price count from 8 to 9.
- Temp negative fixture: an expired `expires_at` failed under
  `--fail-on-stale`.
- Temp negative fixture: the content-kit audit failed an expired evidence card
  as a blocking finding.
- Temp negative fixture: `source_url: null` failed validation.
- Temp negative fixture: `claim_limit: ""` failed validation.
- Temp negative fixture: changing manifest `evidence_freshness_days.value` from
  90 to 30 failed the card expiry math.
- `python content-pipeline/resolution-audit/sync_product_truth.py --check`
  - Passed: derived fields are in sync.
- `python content-pipeline/resolution-audit/validate_evidence.py --help`
  - Passed; CLI documents `--manifest`, `--stale-after-days`, and `--fail-on-stale`.
- `git diff --check`
  - Passed.
- `bash scripts/local_pr_review.sh`
  - Pending until the slice is committed; the script requires a clean worktree.

## Estimated diff size

| Area | Estimated LOC |
| --- | ---: |
| Evidence metadata | ~21 |
| Validator freshness rules | ~90 |
| Audit and workflow wiring | ~25 |
| Plan doc | ~90 |
| Total | ~226 |

Under the 400 LOC soft cap.
