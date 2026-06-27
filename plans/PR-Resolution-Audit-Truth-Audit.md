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
4. Keep target-field prose suspicion in the warning tier while exact structural
   and verifier-contract violations block.
5. Keep evidence expiry enforcement out of this slice; slice #19 owns it.

Files touched:

- `content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `content-pipeline/resolution-audit/open-webui-verifier-tool.py`
- `.github/workflows/content-kit-truth.yml`
- `plans/PR-Resolution-Audit-Truth-Audit.md`

## Mechanism

The audit loads `product-truth.json`, imports `CHANNEL_CONTRACTS` from
`bundle_prompt.py`, and scans kit Markdown/Python files for exact violations.
Required manifest lists must exist and be lists of strings, curated and
`curated:*` fields must carry `verify_against`, and verifier channel lines are
checked as allowlist diffs rather than one-off denied words.

Blocking findings exit non-zero. Target-field currentness is a warning because
it is prose-adjacent and can be a correct anti-claim. A green run means no exact
blocking violation was found, not that prose is fully clean.

The verifier tool now treats owner-routing coverage as a human-review warning
instead of a pass. The audit parses Python calls to catch warn-only verifier
rules routed through pass-capable status variables.

The workflow runs the audit on pull requests touching the Resolution Audit kit,
its plan docs, or the workflow itself.

## Intentional

- Channel scanning is limited to explicit verifier-channel lines, so ordinary
  "sales reply" copy is not treated as a verifier channel.
- Evidence freshness is deferred because #19 revises the evidence schema.
- Target-field currentness emits warnings instead of blocking because it is a
  prose signal; required manifest shape, channel drift, and pass semantics block.
- The audit is exact-match oriented. Broad prose judgment stays with review.

## Deferred

- Add evidence `expires_at` enforcement in slice #19.
- Add generated/server-sourced product facts in slice #17.
- Expand warning-only prose checks after the blocking audit proves stable.

## Verification

Ran locally:

- `python content-pipeline/resolution-audit/audit_content_kit_truth.py`
- `python -m py_compile content-pipeline/resolution-audit/audit_content_kit_truth.py content-pipeline/resolution-audit/open-webui-verifier-tool.py`
- Negative fixture: copied the kit to `/tmp`, added `telegram` to the verifier
  channel list, and confirmed the audit exits non-zero.
- Negative fixture: copied the kit to `/tmp`, removed
  `target_report_fields.value`, added a current owner-lane claim, and confirmed
  the audit exits non-zero.
- Negative fixture: copied the kit to `/tmp`, changed a curated source to
  `curated:atlas`, removed `verify_against`, and confirmed the audit exits
  non-zero.
- Negative fixture: copied the kit to `/tmp`, changed the verifier owner-routing
  status back to `pass`, and confirmed the audit exits non-zero.
- Warning fixture: copied the kit to `/tmp`, added a current owner-lane claim,
  and confirmed the audit emits a warning while exiting zero.
- Warning fixture: copied the kit to `/tmp`, added `The report currently
  includes a probable owner lane.`, and confirmed the audit warns.
- Warning fixture: copied the kit to `/tmp`, added support-team wording around
  current report output, and confirmed the audit warns.
- Negation fixture: copied the kit to `/tmp`, added `The probable owner lane is
  not shipped yet.`, and confirmed the audit does not warn.
- `git diff --check -- content-pipeline/resolution-audit/audit_content_kit_truth.py content-pipeline/resolution-audit/open-webui-verifier-tool.py .github/workflows/content-kit-truth.yml plans/PR-Resolution-Audit-Truth-Audit.md`

## Estimated diff size

| Area | Estimated LOC |
| --- | ---: |
| Audit script | ~378 |
| Verifier status adjustment | ~4 |
| CI workflow | ~19 |
| Plan doc | ~99 |
| Total | ~500 |

Over the 400 LOC soft cap because the review fix expands the audit from
single-instance checks to class-level checks.
