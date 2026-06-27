# PR: Resolution Audit Leak Router

## Why this slice exists

The pasted Leak Index is the right shape for routing content and report
language, but it is still a loose note. It names leak categories and vendors
without the backing files the model workflow needs: a stable router, evidence
cards, safe/unsafe framing language, required inputs, and fallback behavior
when the audit evidence is thin.

This slice turns the Leak Index into a repo-owned Resolution Audit router so
Open WebUI and future Finetune Lab prompts can pick a leak tag, retrieve the
right evidence, and draft sharper content without inventing vendor claims or
customer outcomes.

This slice is over the 400 LOC soft cap because the router, evidence cards, and
frames need to ship together. A router without evidence encourages unsupported
claims; evidence without frames leaves models to improvise the risky language.

## Scope (this PR)

1. Add a `leak-index.md` router with tags, metrics, monetization mechanisms,
   required inputs, claim posture, and fallback language.
2. Add `evidence.jsonl` with source-backed vendor evidence cards for the leak
   tags.
3. Add `frames.md` with safe report labels, social angles, unsafe language, and
   visual prompts for each tag.
4. Update the Resolution Audit README so operators know how to use the leak
   router with Open WebUI or Finetune Lab.

### Files touched

- `plans/PR-Resolution-Audit-Leak-Router.md`
- `content-pipeline/resolution-audit/leak-index.md`
- `content-pipeline/resolution-audit/evidence.jsonl`
- `content-pipeline/resolution-audit/frames.md`
- `content-pipeline/resolution-audit/README.md`

## Mechanism

The router stays plain text and grep-friendly:

- `leak-index.md` is the always-load table. It is compact enough to paste into
  small-context sessions and tells the operator which tag to retrieve next.
- `evidence.jsonl` stores one JSON object per source-backed evidence card with
  `tag`, `vendor`, `evidence_type`, `source_url`, `source_date`, `summary`,
  `numbers`, and `claim_limit`.
- `frames.md` stores the language layer by tag: safe wording, unsafe wording,
  report labels, social angles, fallback behavior, and visual direction.

The files separate vendor pricing/packaging evidence from customer-specific
audit findings. Vendor evidence can show how a platform monetizes a surface; it
cannot prove a specific customer's waste without the customer's ticket export,
plan, and usage inputs.

## Intentional

- No customer examples or invented benchmarks. Evidence cards cite public
  vendor pages and still require customer data before producing cost exposure.
- No code changes to the bundler yet. Operators can paste these files manually
  while the language settles.
- No claim that every vendor has every leak. Missing or weak evidence stays
  explicit.
- No savings or avoided-hire promises. The leak router supports estimated
  exposure and investigation language only.
- Exact vendor prices remain source-date snapshots. The docs tell operators to
  prefer billing-model language and re-check the live source page before citing a
  specific dollar figure.

## Deferred

- Add bundler flags for `--leak-tag` and evidence/frame retrieval once the
  documents prove stable.
- Add a small validation script for JSONL shape and tag coverage.
- Add customer-input worksheets for calculating exposure after real audit
  exports and plan data are available.

## Verification

- `python - <<'PY' ... PY`
  - Expected: parse each JSONL row, confirm every evidence tag exists in
    `leak-index.md`, and confirm every leak-index tag has a frame section.
  - Result: validated 21 evidence cards, 10 router tags, 10 frame sections.
- `rg -n "guaranteed savings|guaranteed ticket|will save|will reduce|avoids? a support hire|proves? waste|deflects? [0-9]+%" content-pipeline/resolution-audit/leak-index.md content-pipeline/resolution-audit/frames.md content-pipeline/resolution-audit/evidence.jsonl`
  - Expected: no matches.
  - Result: no matches.
- `rg -n 'source-date snapshots|re-open the `source_url`|re-check the live source' content-pipeline/resolution-audit/README.md content-pipeline/resolution-audit/leak-index.md`
  - Expected: README and leak-index both instruct operators to verify stale
    exact prices before publishing.
- `git diff --check -- content-pipeline/resolution-audit/leak-index.md content-pipeline/resolution-audit/evidence.jsonl content-pipeline/resolution-audit/frames.md content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Leak-Router.md`
- `bash scripts/local_pr_review.sh --allow-dirty`

Public-source spot-checks were made against the current official Intercom/Fin,
Gorgias, Zendesk, Freshdesk, and Help Scout pages cited in `evidence.jsonl`.
Zendesk and Gorgias cards were tightened where the first draft was too stale or
too specific for the cited page.

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Actual working diff size: 5 files, +551 / -16. This is over the soft cap for
the evidence-plus-frame safety reason named in **Why this slice exists**.
