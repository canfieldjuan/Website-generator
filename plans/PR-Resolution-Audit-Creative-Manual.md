# PR: Resolution Audit Creative Manual

## Why this slice exists

The current Resolution Audit content kit is good at preventing unsupported
claims, but it does not give small or mid-sized models enough creative source
material to produce strong social posts, blog posts, marketing copy, or image
prompts. Open WebUI sessions still depend on sparse prompt contracts and broad
RAG retrieval, which can make outputs safe but flat.

This slice adds a compact creative manual that can be pasted into Open WebUI or
used as Finetune Lab training/evaluation source material. The goal is to give
models a richer product narrative, reusable content primitives, safe metaphors,
channel patterns, and image directions without requiring a large RAG payload.

This slice is over the 400 LOC soft cap because the manual needs to be useful
as a standalone model context document. Splitting channel guidance, model setup,
and image direction into separate PRs would preserve the current problem: the
operator has to assemble too many thin documents before the model has enough
creative material.

## Scope (this PR)

1. Add a standalone Resolution Audit creative manual for multi-format content
   generation.
2. Cover social posts, Reddit analysis posts, blog outlines, marketing copy,
   sales copy, and image prompt direction.
3. Keep the manual grounded in the existing source pack and claims guard rather
   than adding new product promises.
4. Update the content kit README so operators know when to use the manual.

### Files touched

- `plans/PR-Resolution-Audit-Creative-Manual.md`
- `content-pipeline/resolution-audit/creative-manual.md`
- `content-pipeline/resolution-audit/README.md`

## Mechanism

`creative-manual.md` acts as a compact "creative source of truth" for models.
It gives models:

- the product narrative in plain language
- safe tension lines and pattern language
- reusable hooks, titles, transitions, and CTAs
- format-specific guidance for LinkedIn, Reddit, blogs, marketing copy, and
  image prompts
- model behavior rules for small-context Open WebUI sessions and larger
  Finetune Lab/RAG workflows

The manual references the existing source pack and claims guard as authority.
It does not replace the stricter claim review or verifier handoff.

## Intentional

- No code changes. The current prompt bundler stays unchanged so this slice
  stays focused on source material quality.
- No fabricated benchmark library. Pattern examples are phrased as hypotheses
  or operator observations, not universal findings.
- No finished campaign calendar. The manual gives reusable primitives instead
  of prescribing a publishing schedule.
- No new product claims around savings, deflection percentages, automation, or
  certain ownership.

## Deferred

- Add a `--include-creative-manual` flag to `bundle_prompt.py` if the manual
  proves useful in repeated Open WebUI sessions.
- Add sanitized before/after output examples once real generated drafts have
  been reviewed.
- Add a smaller "micro-model card" if local models still struggle with the full
  manual.

## Verification

- `rg -n "will (save|reduce|eliminate)|guarantees? (savings|ticket)|automatically (updates|publishes|answers)|replaces? (agents|support)" content-pipeline/resolution-audit/creative-manual.md`
  - Expected: no matches.
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Actual working diff size: 3 files, +553 / -12. This is over the 400 LOC soft cap
for the safety and standalone-context reason named in **Why this slice exists**.
