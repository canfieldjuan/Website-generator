# PR: Resolution Audit Leak Bundler

## Why this slice exists

The leak router is now source-backed and validated, but operators still have to
manually grep `leak-index.md`, `evidence.jsonl`, and `frames.md` before drafting a
vendor-cost angle in Open WebUI. That manual retrieval step is easy to botch: a
model could receive the frame without the claim boundary, the evidence without
the unsafe-language guard, or rows for the wrong leak tag.

This slice adds a narrow bundler flag so one command can retrieve the matching
leak context and keep the operator inside the same prompt-bundle workflow.

## Scope (this PR)

1. Add `--leak-tag` to `bundle_prompt.py`.
2. Include the selected leak router row, the global claim boundary, matching
   evidence rows, and the matching frame section when a leak tag is selected.
3. Keep leak context optional so non-vendor-cost bundles remain unchanged.
4. Update the README command and operator flow with the new flag.

### Files touched

- `plans/PR-Resolution-Audit-Leak-Bundler.md`
- `content-pipeline/resolution-audit/bundle_prompt.py`
- `content-pipeline/resolution-audit/README.md`

## Mechanism

`bundle_prompt.py` reads available leak tags from `leak-index.md` at argument
parse time. When `--leak-tag` is present, the bundler:

- extracts the matching router table row and `## Claim Boundary` section from
  `leak-index.md`;
- parses `evidence.jsonl` and includes only rows whose `tag` matches the
  selected leak tag;
- extracts the matching `frames.md` section;
- adds an operator instruction that vendor evidence describes billing mechanics,
  not customer waste or guaranteed savings.

The output remains plain Markdown so it stays pasteable into Open WebUI.

## Intentional

- No automatic live-price revalidation inside the bundler. Operators still run
  `validate_evidence.py` and re-open live pages before publishing exact prices.
- No change to existing channel or angle behavior when `--leak-tag` is omitted.
- Evidence rows stay JSONL-shaped so they can be copied back into tools or future
  verification packets without lossy rewriting.

## Deferred

- Add `--include-plain-talk` or other higher-level bundle presets later if the
  manual rewrite steps become too repetitive.
- Add freshness gating directly to the bundler only if operators want bundle
  creation to fail on stale exact prices.

## Verification

- `python content-pipeline/resolution-audit/bundle_prompt.py --help`
  - Result: `--leak-tag` appears with the 10 router tags.
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin --angle diagnostic-not-dashboard --leak-tag repeat_resolution >/tmp/resolution-audit-leak-bundle.md`
- `rg -n "Selected Leak Router|Selected Leak Evidence|Selected Leak Frame|intercom_fin_resolution_pricing_2026_06|Repeat Resolution Spend|Never turn a vendor evidence card" /tmp/resolution-audit-leak-bundle.md`
  - Result: matched the selected router, evidence, frame, Intercom evidence card,
    repeat-resolution label, and claim boundary.
- `! rg -n '"tag":"ai_attempt_waste"' /tmp/resolution-audit-leak-bundle.md`
  - Result: no unrelated `ai_attempt_waste` evidence row was bundled.
- `python -m py_compile content-pipeline/resolution-audit/bundle_prompt.py`
- `git diff --check -- content-pipeline/resolution-audit/bundle_prompt.py content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Leak-Bundler.md`
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Actual working diff size: 3 files, +160 / -5.
