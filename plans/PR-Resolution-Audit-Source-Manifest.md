# PR: Resolution Audit Source Manifest

## Why this slice exists

Issue #17 asks the truth spine to stop hand-maintaining product facts that have
real sources. Slice #15 created `product-truth.json`, and slice #16 made the
audit fail closed, but shipped report fields and claim flags still used
placeholder `verify_against` prose.

This slice makes the manifest source-backed: local verifier channels are still
derived from code, and product facts now come from a committed ATLAS
`deflection.v1` contract snapshot.

## Scope (this PR)

1. Add an ATLAS deflection contract snapshot for source-backed product facts.
2. Extend `sync_product_truth.py` so it syncs both code-derived channels and
   product-source fields.
3. Make `audit_content_kit_truth.py` block when `product-truth.json` is stale
   versus its code/source inputs.
4. Run the sync check explicitly in the content-kit truth workflow.
5. Update `product-truth.json` from the new source.

Files touched:

- `content-pipeline/resolution-audit/product-truth-sources/atlas-deflection-v1.json`
- `content-pipeline/resolution-audit/sync_product_truth.py`
- `content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `content-pipeline/resolution-audit/product-truth.json`
- `.github/workflows/content-kit-truth.yml`
- `plans/PR-Resolution-Audit-Source-Manifest.md`

## Mechanism

`product-truth-sources/atlas-deflection-v1.json` records a distilled ATLAS
contract snapshot with provenance: the ATLAS commit, files, and functions used
to capture the report-shape and feature facts.

`sync_product_truth.py` now loads that source and copies
`shipped_report_fields`, `target_report_fields`, and `claims` into
`product-truth.json`. It still derives `verifier_channels` from
`bundle_prompt.CHANNEL_CONTRACTS`. In `--check` mode, any drift exits non-zero.

The truth audit deep-copies the manifest, runs the same sync logic in memory,
and blocks if the copy would change. CI runs both `sync_product_truth.py
--check` and the audit.

## Intentional

- The ATLAS contract is a committed snapshot, not a live MCP call. That keeps
  CI deterministic and avoids faking a server dependency that is not always
  available in this repo.
- The PII claim is narrowed to backend report-payload scrubbing because this
  source is ATLAS. Browser-side scrubbing lives outside this repo/source path.
- `owner_lane`, `routing_signals`, and `product_gap_summary` are now shipped
  fields because the current ATLAS `deflection.v1` report projection exposes
  them. Ownership wording still stays probable in copy.

## Deferred

- Live content-ops MCP/server ingestion remains a later source upgrade if we
  want the manifest to refresh from a running service instead of a committed
  snapshot.
- Evidence freshness remains slice #19.
- Bundler injection remains slice #18.

## Verification

Ran locally:

- `python content-pipeline/resolution-audit/sync_product_truth.py`
- `python content-pipeline/resolution-audit/sync_product_truth.py --check`
- `python content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `python -m py_compile content-pipeline/resolution-audit/sync_product_truth.py content-pipeline/resolution-audit/audit_content_kit_truth.py`
- Negative fixture: copied the kit to `/tmp`, changed `claims.owner_routing`
  in `product-truth.json`, and confirmed the audit exits non-zero.
- Negative fixture: copied the kit to `/tmp`, added a stale verifier channel
  in `product-truth.json`, and confirmed `sync_product_truth.py --check` exits
  non-zero.
- `git diff --check -- .github/workflows/content-kit-truth.yml content-pipeline/resolution-audit/audit_content_kit_truth.py content-pipeline/resolution-audit/sync_product_truth.py content-pipeline/resolution-audit/product-truth.json content-pipeline/resolution-audit/product-truth-sources/atlas-deflection-v1.json plans/PR-Resolution-Audit-Source-Manifest.md`

## Estimated diff size

| Area | Estimated LOC |
| --- | ---: |
| ATLAS source snapshot | ~50 |
| Sync script | ~45 |
| Audit stale-source check | ~13 |
| Manifest update | ~29 |
| Workflow | ~2 |
| Plan doc | ~94 |
| Total | ~233 |

Under the 400 LOC soft cap.
