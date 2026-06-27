# PR: Resolution Audit Truth Bundler

## Why this slice exists

Issue #18 asks the prompt bundler to put current product truth in front of the
model at generation time. Slice #17 made `product-truth.json` source-backed,
but the bundle still only includes prose guides unless an operator opens the
manifest separately.

This slice adds an opt-in manifest include and an explicit precedence line so
the manifest wins when examples or guides drift.

## Scope (this PR)

1. Add an opt-in `--include-product-truth` flag to `bundle_prompt.py`.
2. Render `product-truth.json` into the bundle only when the flag is present.
3. Add an operator instruction saying the manifest is authoritative when it
   conflicts with guides or examples.
4. Keep default bundles unchanged.

Files touched:

- `content-pipeline/resolution-audit/bundle_prompt.py`
- `plans/PR-Resolution-Audit-Truth-Bundler.md`

## Mechanism

The bundler already accepts optional context blocks for Plain Talk, report
shape, angles, and leak evidence. This slice follows that pattern with a
`Product Truth Manifest` rendered section.

The manifest section is inserted after Claims Guard and before optional guides
or examples. The operator instruction is emitted only when the flag is present
and states the precedence rule directly.

## Intentional

- The flag is opt-in. The default command remains unchanged, avoiding the #18
  default-command footgun.
- The manifest is rendered as JSON, not paraphrased, so downstream users see
  the exact fields and claim flags.
- The precedence line does not weaken the claims guard; it clarifies that
  source-backed product facts outrank older examples or guides.

## Deferred

- Presets that always include product truth stay deferred until operators prove
  they need them.
- Evidence freshness remains slice #19.

## Verification

Ran locally:

- `python content-pipeline/resolution-audit/bundle_prompt.py --help`
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin --include-product-truth >/tmp/resolution-audit-product-truth-bundle.md`
- `rg -n "Product Truth Manifest|owner_lane|target_report_fields|The product truth manifest is authoritative" /tmp/resolution-audit-product-truth-bundle.md`
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin >/tmp/resolution-audit-default-bundle.md`
- `! rg -n "Product Truth Manifest|The product truth manifest is authoritative" /tmp/resolution-audit-default-bundle.md`
- `python -m py_compile content-pipeline/resolution-audit/bundle_prompt.py`
- `git diff --check -- content-pipeline/resolution-audit/bundle_prompt.py plans/PR-Resolution-Audit-Truth-Bundler.md`

## Estimated diff size

| Area | Estimated LOC |
| --- | ---: |
| Bundler flag and render path | ~25 |
| Plan doc | ~75 |
| Total | ~100 |

Under the 400 LOC soft cap.
