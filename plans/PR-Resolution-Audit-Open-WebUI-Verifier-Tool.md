# PR: Resolution Audit Open WebUI Verifier Tool

## Why this slice exists

The verifier currently works from the terminal, but the drafting workflow
happens in Open WebUI. This slice adds a Workspace Tool so drafts can be checked
inside chat before posting.

## Scope (this PR)

1. Add a standalone Open WebUI verifier tool.
2. Document the tool slice and verification.

Files touched:

- `content-pipeline/resolution-audit/open-webui-verifier-tool.py`
- `plans/PR-Resolution-Audit-Open-WebUI-Verifier-Tool.md`

## Mechanism

`open-webui-verifier-tool.py` defines a `Tools` class with
`verify_resolution_audit_draft(...)`. It runs standard-library regex checks for
unsupported promises, missing owner routing, raw contact data, unqualified
answer claims, and certain ownership language. It returns a Markdown verdict
with revision priorities and optional JSON.

## Intentional

- The Open WebUI tool is standalone because Workspace Tools should not depend
  on this repo being importable.
- Regex warnings still require human review.

## Deferred

- Push the tool into Open WebUI through an API instead of copy/paste.
- Generate this tool from shared verifier rules if duplication becomes costly.

## Verification

Ran locally:

- `python -m py_compile content-pipeline/resolution-audit/open-webui-verifier-tool.py`
- Imported the tool by path and asserted a no-owner report draft returns
  `RA-OWNER-ROUTING-COVERAGE` with `Needs human review`.
- Imported the tool by path and asserted a `guarantees savings` draft returns
  `RA-NO-GUARANTEED-OUTCOMES` with `Do not post yet`.
- `! rg -n "sales" content-pipeline/resolution-audit/open-webui-verifier-tool.py`
- `git diff --cached --check -- content-pipeline/resolution-audit/open-webui-verifier-tool.py plans/PR-Resolution-Audit-Open-WebUI-Verifier-Tool.md`

## Estimated diff size

2 files, +268 / -0. Under the 400 LOC soft cap.
