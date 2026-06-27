# PR: Resolution Audit Content Kit

## Why this slice exists

The current repo is still shaped around local-business website redesigns, but
the operator now needs a repeatable Resolution Audit content workflow for Open
WebUI. Useful source material already exists in loose Desktop notes and the
nested portfolio checkout, but it is not repo-owned, curated, or guarded against
unsupported claims.

This slice creates the first repo-owned content kit. It promotes the useful
social angles and reply-flow ideas while removing claims that the current
Resolution Audit offer cannot support, such as fixed deflection percentages,
live self-service-center launches, or guaranteed savings.

This slice is slightly over the 400 LOC soft cap because the source pack, claim
guard, and first angle library are only safe as a set. Shipping angles without
the guard would preserve the exact overclaim risk this slice is meant to
remove.

## Scope (this PR)

1. Add a new `content-pipeline/resolution-audit/` kit without modifying the
   existing website-redesign skill.
2. Capture the current Resolution Audit source of truth, safe claim boundaries,
   and channel angles in Markdown files operators can paste into Open WebUI.
3. Salvage the "public-help-center first, CSV later" reply flow while explicitly
   marking the older percentage and self-service-center claims as unsafe.

### Files touched

- `plans/PR-Resolution-Audit-Content-Kit.md`
- `content-pipeline/resolution-audit/README.md`
- `content-pipeline/resolution-audit/source-pack.md`
- `content-pipeline/resolution-audit/claims-guard.md`
- `content-pipeline/resolution-audit/angles.md`

## Mechanism

The kit is plain Markdown so Open WebUI can use it immediately without database
imports, Docker volume edits, or a new MCP server. The files split the workflow
into stable layers:

- `README.md` explains the operator flow and what is deferred.
- `source-pack.md` states what the Resolution Audit does today.
- `claims-guard.md` defines safe, risky, and forbidden claim posture.
- `angles.md` provides channel-ready content angles and a safer reply flow.

The slice deliberately keeps generation prompts out of scope. Those become the
next slice once the source pack and claim guard are stable.

## Intentional

- No changes to `SKILL.md`, `pipeline.py`, `build.py`, or `references/`. The
  website-redesign pipeline remains untouched.
- No Open WebUI database writes. The current WebUI tables are empty for prompts,
  models, tools, functions, knowledge, and documents, so this slice creates
  portable source files first.
- No ATLAS MCP changes. The existing ATLAS `verify_draft` server remains the
  later verification surface, not this slice's generator.

## Deferred

- Slice 2: Open WebUI prompt contracts for LinkedIn, Reddit, replies, blog
  outlines, and feedback asks.
- Slice 3: a local prompt-bundler CLI.
- Slice 4: structured verifier handoff for ATLAS `verify_draft`.
- Slice 5: sanitized operator examples and workflow checklist.

## Verification

- `rg -n "deflects? ~|~30%|25-35%|real deflection rate|auto-updated|launch a self-service center|keep it current automatically" content-pipeline/resolution-audit --glob '!claims-guard.md'`
  - Expected: no matches; unsupported older promises should only appear inside
    the guard as examples of what not to publish.
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Actual staged size: 5 files, about 510 added lines. This is over the soft cap
for the safety reason named in **Why this slice exists**.
