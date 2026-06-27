# PR: Resolution Audit Truth Audit

## Why this slice exists

Issue #16 depends on the truth manifest from #15. The manifest now exists, but
its structural invariants and the kit's most brittle exact drifts are not
enforced by committed code.

This slice adds the fail-closed audit and CI path for exact violations.

## Scope (this PR)

1. Add `audit_content_kit_truth.py`.
2. Add the first GitHub Actions workflow for the Resolution Audit kit path.
3. Check manifest structure, channel parity, target-field-as-current phrasing,
   and warn-only verifier pass semantics.
4. Keep evidence expiry enforcement out of this slice; slice #19 owns it.

Files touched:

- `content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `.github/workflows/content-kit-truth.yml`
- `plans/PR-Resolution-Audit-Truth-Audit.md`

## Mechanism

The audit loads `product-truth.json`, imports `CHANNEL_CONTRACTS` from
`bundle_prompt.py`, and scans kit Markdown/Python files for exact violations.
Blocking findings exit non-zero. A green run means no exact violation was
found, not that prose is fully clean.

The workflow runs the audit on pull requests touching the Resolution Audit kit,
its plan docs, or the workflow itself.

## Intentional

- Channel scanning is limited to explicit verifier-channel lines, so ordinary
  "sales reply" copy is not treated as a verifier channel.
- Evidence freshness is deferred because #19 revises the evidence schema.
- The audit is exact-match oriented. Broad prose judgment stays with review.

## Deferred

- Add evidence `expires_at` enforcement in slice #19.
- Add generated/server-sourced product facts in slice #17.
- Expand warning-only prose checks after the blocking audit proves stable.

## Verification

Ran locally:

- `python content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `python -m py_compile content-pipeline/resolution-audit/audit_content_kit_truth.py`
- Negative fixture: copied the kit to `/tmp`, added `sales` to the verifier
  channel list, and confirmed the audit exits non-zero.
- Negative fixture: copied the kit to `/tmp`, changed a line to say
  `current probable owner lane`, and confirmed the audit exits non-zero.
- Negative fixture: copied the kit to `/tmp`, removed a curated
  `verify_against`, and confirmed the audit exits non-zero.
- `git diff --check -- content-pipeline/resolution-audit/audit_content_kit_truth.py .github/workflows/content-kit-truth.yml plans/PR-Resolution-Audit-Truth-Audit.md`

## Estimated diff size

| Area | Estimated LOC |
| --- | ---: |
| Audit script | ~232 |
| CI workflow | ~19 |
| Plan doc | ~71 |
| Total | ~322 |

Under the 400 LOC soft cap.
