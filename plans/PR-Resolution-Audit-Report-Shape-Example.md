# PR: Resolution Audit Report Shape Example

## Why this slice exists

The source pack now explains the new Resolution Audit shape, but models still
benefit from one concrete artifact to imitate. Without a sample structure, they
can drift back to generic language about ranked questions, costs, and FAQ
drafts while treating the owner lane as optional.

This slice adds a sanitized report-shape example and a bundler flag so Open
WebUI prompts can include the example when drafting report-shape, Snapshot,
marketing, or build-in-public content.

## Scope (this PR)

1. Add a `report-shape-example.md` file with a fictional, non-customer mock
   Snapshot and full-audit section.
2. Add `--include-report-shape` to `bundle_prompt.py`.
3. Update the README with when to include the report-shape example.
4. Keep default bundles unchanged unless the new flag is passed.

Files touched:

- `content-pipeline/resolution-audit/report-shape-example.md`
- `content-pipeline/resolution-audit/bundle_prompt.py`
- `content-pipeline/resolution-audit/README.md`
- `plans/PR-Resolution-Audit-Report-Shape-Example.md`

## Mechanism

The new Markdown file acts as a safe pattern library. It uses fictional issue
names and bracketed placeholders instead of real customer numbers. It shows the
columns and language models should copy:

- repeated issue
- estimated cost exposure
- resolution evidence
- customer wording
- content output
- unresolved/no-proven-answer gap
- probable owner lane
- next review action

The bundler flag adds this file as an optional section after the claims guard.
Default bundles stay the same so small-context workflows do not grow unless the
operator asks for the sample.

## Intentional

- The sample uses placeholders and explicit "example only" language to avoid
  fake customer proof.
- The owner lane remains probable and review-oriented, not a certain
  assignment.
- No visual screenshot is added in this slice. The goal is prompt behavior, not
  design polish.

## Deferred

- Add an actual report UI mock or image prompt once the report visual language
  is ready.
- Add golden generated examples that compare outputs with and without the
  report-shape example.

## Verification

Ran locally:

- `python content-pipeline/resolution-audit/bundle_prompt.py --help`
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin --angle build-in-public --include-report-shape >/tmp/resolution-audit-report-shape-bundle.md`
- `rg -n "Report Shape Example|Owner Routing Map|Probable owner lane|Example only" /tmp/resolution-audit-report-shape-bundle.md`
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin --angle build-in-public >/tmp/resolution-audit-default-report-shape-bundle.md`
- `! rg -n "Report Shape Example|Owner Routing Map|Example only" /tmp/resolution-audit-default-report-shape-bundle.md`
- `python -m py_compile content-pipeline/resolution-audit/bundle_prompt.py`
- `git diff --cached --check -- content-pipeline/resolution-audit/report-shape-example.md content-pipeline/resolution-audit/bundle_prompt.py content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Report-Shape-Example.md`

## Estimated diff size

4 files, +265 / -21. Over the initial 250 LOC target because the fictional
report-shape example is the deliverable, but still under the 400 LOC soft cap.
