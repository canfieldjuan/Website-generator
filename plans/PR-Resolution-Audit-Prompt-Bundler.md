# PR: Resolution Audit Prompt Bundler

## Why this slice exists

The Resolution Audit kit now has safe source files and channel prompt
contracts, but Open WebUI use still requires manual copy/paste assembly. That
is workable once, but easy to get wrong when drafting quickly: the operator can
forget the source pack, skip the claims guard, miss the Shared Context Block, or
use the wrong channel contract.

This slice adds a small local bundler that assembles the required context into
one pasteable prompt. It keeps the workflow manual and inspectable while
removing the most likely operator mistake.

## Scope (this PR)

1. Add a standard-library CLI for bundling the Resolution Audit source pack,
   claims guard, selected angle, Shared Context Block, and selected channel
   contract.
2. Support stdout output for immediate paste workflows and `--output` for saved
   prompt files.
3. Update the kit README with the bundler command and keep the manual paste
   path as a fallback.

### Files touched

- `plans/PR-Resolution-Audit-Prompt-Bundler.md`
- `content-pipeline/resolution-audit/README.md`
- `content-pipeline/resolution-audit/bundle_prompt.py`

## Mechanism

`bundle_prompt.py` reads the existing Markdown files in
`content-pipeline/resolution-audit/` and extracts sections by heading. The
operator chooses a channel with `--channel`; channels map to a prompt contract
section in `prompt-contracts.md`. The operator may choose an angle with
`--angle`; angles map to sections in `angles.md`.

The output is plain Markdown with clear dividers and an operator instruction
that points back to the selected contract's own Inputs list. It is
intentionally copy/paste-first: no Open WebUI database writes, no API calls,
and no MCP dependency.

## Intentional

- No new dependencies. The CLI uses only Python's standard library.
- No generation or validation logic. The script assembles prompts; Open WebUI
  drafts and the prompt self-check still review content.
- No automatic angle selection. The operator chooses the channel and angle so
  the bundle matches the conversation they are actually entering.

## Deferred

- Structured ATLAS `verify_draft` handoff remains the next verification slice.
- Sanitized example outputs and an outcomes log remain a later workflow slice.

## Verification

- `python content-pipeline/resolution-audit/bundle_prompt.py --help`
- `python content-pipeline/resolution-audit/bundle_prompt.py --help | rg "self-check"; test $? -eq 1`
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin --angle diagnostic-not-dashboard --output /tmp/resolution-audit-linkedin-prompt.md`
- `rg -n "Shared Context Block|Contract 1: LinkedIn POV Post|Angle 6: Diagnostic, Not Dashboard|Resolution Audit Source Pack|Resolution Audit Claims Guard|Operator Instruction" /tmp/resolution-audit-linkedin-prompt.md`
- `rg -n "Operator Inputs|Now draft using the channel contract" /tmp/resolution-audit-linkedin-prompt.md`
  - Expected: no matches; the bundle should point to the selected contract's
    own Inputs list instead of a generic LinkedIn-shaped input block.
- `python -m py_compile content-pipeline/resolution-audit/bundle_prompt.py`
- `rg -n "deflects? ~|~30%|25-35%|real deflection rate|auto-updated|launch a self-service center|keep it current automatically|support hire slides" content-pipeline/resolution-audit --glob '!claims-guard.md'`
  - Expected: no matches; unsupported older promises should only appear inside
    the guard as examples of what not to publish.
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Estimated size: 3 files, about 260 added/changed lines. This stays under the
400 LOC soft cap.
