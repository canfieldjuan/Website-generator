# PR: Resolution Audit Truth Manifest

## Why this slice exists

Issue #15 starts the truth-spine epic. The content kit has markdown guidance,
skills, evidence cards, and verifier tools, but no single place that states
which facts are product truth versus editorial guidance. That caused channel
drift and target/report-shape drift in earlier slices.

This slice adds the first manifest and a tiny sync check for facts that can be
derived from this repo today.

## Scope (this PR)

1. Add `product-truth.json` with derived verifier channels and curated product
   fact fields.
2. Add `sync_product_truth.py` to keep `verifier_channels` derived from
   `bundle_prompt.CHANNEL_CONTRACTS`.
3. Document the manifest in the README source hierarchy.
4. Keep audits, bundler integration, and server-sourced product facts out of
   this slice.

Files touched:

- `content-pipeline/resolution-audit/product-truth.json`
- `content-pipeline/resolution-audit/sync_product_truth.py`
- `content-pipeline/resolution-audit/README.md`
- `plans/PR-Resolution-Audit-Truth-Manifest.md`

## Mechanism

The manifest separates facts into named fields. `verifier_channels` is derived
from local code and checked by `sync_product_truth.py --check`. Product/report
facts are marked `curated` and include `verify_against` pointers for slice #17.

Shipped and target report fields are positive lists. There is no negative "not
shipped" exclusion list.

## Intentional

- Curated product facts are provisional in this slice. The point is to make
  them visible and sourced, not to pretend they are server-derived yet.
- The sync script only manages same-repo derived fields. It does not audit prose
  or generate product facts.
- No bundler change happens here, so default prompt output is unchanged.

## Deferred

- Add `audit_content_kit_truth.py` and negative drift fixtures in slice #16.
- Source product facts from content-ops or an ATLAS contract in slice #17.
- Inject the manifest into prompt bundles with precedence in slice #18.
- Enforce evidence freshness fields in slice #19.

## Verification

Ran locally:

- `python -m json.tool content-pipeline/resolution-audit/product-truth.json >/tmp/product-truth.json`
- `python content-pipeline/resolution-audit/sync_product_truth.py --check`
- `python -m py_compile content-pipeline/resolution-audit/sync_product_truth.py`
- `python - <<'PY' ... PY`
  - asserted manifest `verifier_channels.value == sorted(CHANNEL_CONTRACTS)`
  - asserted every field has `source`
  - asserted curated fields have `verify_against`
  - asserted shipped and target report field lists are disjoint
- `git diff --check -- content-pipeline/resolution-audit/product-truth.json content-pipeline/resolution-audit/sync_product_truth.py content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Truth-Manifest.md`

## Estimated diff size

4 files, +228 / -8. Under the 400 LOC soft cap.
