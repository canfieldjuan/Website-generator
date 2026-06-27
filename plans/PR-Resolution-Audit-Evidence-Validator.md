# PR: Resolution Audit Evidence Validator

## Why this slice exists

The leak router now carries source-backed cards for named vendors. That gives
the content kit sharper vendor-cost angles, but it also makes `source_date`
load-bearing: exact dollar figures can go stale even when the billing model
remains useful.

This slice adds a local validator so operators can check the evidence file before
using it in Open WebUI. The validator turns the prior review note into a repeatable
mechanical check instead of a memory-based caution.

## Scope (this PR)

1. Add a standard-library `validate_evidence.py` script for the Resolution Audit
   evidence files.
2. Validate JSONL shape, required fields, duplicate IDs, ISO `source_date`, router
   tag coverage, evidence tag coverage, and frame-section coverage.
3. Warn when a card with exact vendor-price fields is older than the configured
   freshness window, and add `--fail-on-stale` for strict follow-up use.
4. Update the README with the validator command.

### Files touched

- `plans/PR-Resolution-Audit-Evidence-Validator.md`
- `content-pipeline/resolution-audit/validate_evidence.py`
- `content-pipeline/resolution-audit/README.md`

## Mechanism

`validate_evidence.py` reads the three repo-owned leak files:

- `evidence.jsonl` for card rows.
- `leak-index.md` for router tags.
- `frames.md` for frame sections.

It exits non-zero for structural errors: malformed JSON, missing required fields,
duplicate IDs, invalid dates, evidence tags absent from the router, router tags
with no evidence, or router tags without frame sections.

Freshness is softer by default. The script detects exact-price cards by looking
for price/rate/overage-style keys and dollar-bearing values inside `numbers`,
compares `source_date` to an `--as-of` date, and prints `WARN` rows when exact
prices are older than `--stale-after-days`. Passing `--fail-on-stale` promotes
those warnings to a non-zero exit for future stricter workflows.

Required scalar fields must be non-empty strings, and `source_date` must match
literal `YYYY-MM-DD` shape before parsing. That keeps present-but-empty claim
boundaries, missing source URLs, compact dates, and ISO-week dates from passing
as usable evidence.

## Intentional

- No network requests. The validator checks freshness age and structure; it does
  not claim the live vendor page still matches.
- No CI wiring yet. This is a local operator check first so thresholds and output
  can settle.
- Freshness warnings do not fail by default. The docs still require live-page
  re-checks before publishing exact dollar figures.

## Deferred

- Wire the validator into a fuller local review or CI path after the team sees
  whether the freshness threshold is right.
- Add source URL reachability or content snapshots only if the operator wants a
  heavier evidence-governance layer.

## Verification

- `python content-pipeline/resolution-audit/validate_evidence.py`
  - Result: validated 21 evidence cards, 10 router tags, 10 frame sections, 8
    exact-price cards.
- `python content-pipeline/resolution-audit/validate_evidence.py --as-of 2026-10-01`
  - Result: warned on 8 stale exact-price cards and exited 0.
- `python content-pipeline/resolution-audit/validate_evidence.py --as-of 2026-10-01 --fail-on-stale >/tmp/evidence-validator-stale.txt; test $? -eq 2`
  - Result: warned on the same 8 cards and exited 2.
- `python - <<'PY' ... PY`
  - Result: boundary probes passed for stale `$49` under a neutral
    `plan_examples` key, empty/null required scalar fields, and compact/ISO-week
    source dates.
- `python -m py_compile content-pipeline/resolution-audit/validate_evidence.py`
- `git diff --check -- content-pipeline/resolution-audit/validate_evidence.py content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Evidence-Validator.md`
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Actual working diff size: 3 files, +366 / -2.
