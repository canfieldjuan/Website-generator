# PR: Resolution Audit Prompt Contracts

## Why this slice exists

The merged Resolution Audit content kit gives Open WebUI a safe source pack,
claims guard, and angle library, but it still asks the operator to assemble
prompts by hand. That leaves too much room for each drafting session to skip the
guard, blur the channel, or drift back into older unsupported claims.

This slice turns the kit into copyable prompt contracts for the main jobs the
operator named: blog posts, social posts, social replies, and feedback asks.
The goal is not automation yet. The goal is a repeatable Open WebUI workflow
that keeps each draft tied to the source pack and claim guard.

## Scope (this PR)

1. Add prompt contracts for LinkedIn posts, Reddit-style discussion posts,
   social replies, blog outlines, feedback asks, and a draft self-check.
2. Keep all prompt contracts grounded in the existing source pack and claims
   guard rather than adding new product claims.
3. Update the kit README so operators know when to use the prompt contracts.

### Files touched

- `plans/PR-Resolution-Audit-Prompt-Contracts.md`
- `content-pipeline/resolution-audit/README.md`
- `content-pipeline/resolution-audit/prompt-contracts.md`

## Mechanism

`prompt-contracts.md` gives Open WebUI a stable structure:

- a shared context block to paste before any channel prompt
- input fields the operator fills in before generation
- channel-specific instructions for draft shape, CTA posture, and hard limits
- a final self-check prompt that tests a draft against the claims guard

The file does not replace `source-pack.md`, `claims-guard.md`, or `angles.md`.
It tells the operator to paste those files into the chat first, then use the
relevant contract as the generation instruction.

## Intentional

- No Open WebUI database writes. These are portable Markdown contracts the
  operator can paste manually before later bundler work exists.
- No MCP verifier integration. The ATLAS `verify_draft` handoff remains a later
  slice because the current useful step is repeatable generation, not server
  wiring.
- No finished posts. The contracts produce drafts that still require operator
  review before publishing.

## Deferred

- Slice 3: a local prompt-bundler CLI that assembles source pack, guard, angle,
  and channel contract into one pasteable prompt.
- Slice 4: structured verifier handoff for ATLAS `verify_draft`.
- Slice 5: sanitized examples and an outcomes log for posts that actually get
  used.

## Verification

- `rg -n "deflects? ~|~30%|25-35%|real deflection rate|auto-updated|launch a self-service center|keep it current automatically|support hire slides" content-pipeline/resolution-audit --glob '!claims-guard.md'`
  - Expected: no matches; unsupported older promises should only appear inside
    the guard as examples of what not to publish.
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Estimated size: 3 files, about 300 added/changed lines. This stays under the
400 LOC soft cap.
