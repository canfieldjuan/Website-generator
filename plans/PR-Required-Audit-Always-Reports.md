# Required audit check always reports

## Why this slice exists

The `main` branch requires the `audit` status context for pull requests, but the
only workflow job that produces that context is filtered to Resolution Audit
paths. A pull request outside those paths never creates the required check and
remains blocked even when every workflow it can trigger succeeds. The required
status and its producer therefore disagree about which pull requests they cover.

## Scope (this PR)

1. Run the existing `audit` job for every pull request so the required status is
   always present.
2. Preserve the existing audit commands, job name, permissions, and pass/fail
   behavior.

### Files touched

- `.github/workflows/content-kit-truth.yml`
- `plans/PR-Required-Audit-Always-Reports.md`

## Mechanism

Remove only the pull-request path filter. GitHub will then create the existing
`audit` job on every pull-request head. The job continues to execute the same
three repository-owned product-truth checks, so a green required context still
means the audit actually ran rather than a synthetic no-op reporting success.

## Intentional

- The existing audit runs on unrelated pull requests. That small CI cost keeps
  the branch-protection invariant honest and avoids hand-created statuses or
  privileged merge bypasses.
- The job remains named `audit` because that is the status context required by
  `main`.

## Deferred

- Changing branch-protection contexts or introducing a generalized monorepo
  change detector is outside this repair.
- The generator `unit` workflow and its path filters remain unchanged.

## Verification

- `python3 content-pipeline/resolution-audit/sync_product_truth.py --check`
  reported that derived fields are in sync.
- `python3 content-pipeline/resolution-audit/validate_evidence.py --fail-on-stale`
  validated 21 evidence cards, 10 router tags, 10 frame sections, 8 exact-price
  cards, and 0 expired cards within the 90-day freshness window.
- `python3 content-pipeline/resolution-audit/audit_content_kit_truth.py` passed
  with no exact violations.
- `git diff --check` passed. `actionlint` was not installed locally; GitHub
  workflow parsing remains part of the pull-request proof.
- Pending `bash scripts/local_pr_review.sh` after commit.
- The pull request must itself receive a successful required `audit` check.

## Estimated diff size

Two files and fewer than 60 changed lines.
