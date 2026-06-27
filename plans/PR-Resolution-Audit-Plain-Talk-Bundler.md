# PR: Resolution Audit Plain Talk Bundler

## Why this slice exists

The Plain Talk guide and readability scorer exist, but the prompt bundler still
does not offer a way to include the guide in a pasteable Open WebUI bundle. That
keeps the operator in a manual second copy step whenever a model needs the voice
and readability rules before drafting.

This slice adds an optional `--include-plain-talk` flag so the style guide can
travel with the prompt bundle when useful, without changing default bundles.

## Scope (this PR)

1. Add `--include-plain-talk` to `bundle_prompt.py`.
2. Include `plain-talk.md` as a rendered section only when the flag is present.
3. Add a short operator instruction that Plain Talk improves voice but never
   outranks the claims guard.
4. Update the README command flow with the optional flag.

### Files touched

- `plans/PR-Resolution-Audit-Plain-Talk-Bundler.md`
- `content-pipeline/resolution-audit/bundle_prompt.py`
- `content-pipeline/resolution-audit/README.md`

## Mechanism

The bundler already has optional sections for selected angles and leak context.
This slice follows that pattern: `--include-plain-talk` reads `plain-talk.md` and
adds it after Claims Guard, before optional angle or leak context. The operator
instruction only mentions Plain Talk when the flag is present.

## Intentional

- Default bundles stay unchanged so ordinary drafting prompts do not grow.
- Plain Talk stays optional because some quick replies need the channel contract
  and claims guard more than the full voice guide.
- The instruction explicitly says claims safety wins over readability or tone.

## Deferred

- Add higher-level presets only if operators repeatedly use the same combination
  of angle, leak tag, and Plain Talk guide.
- Add scored sample outputs and an outcomes log in a separate workflow slice.

## Verification

- `python content-pipeline/resolution-audit/bundle_prompt.py --help`
  - Result: `--include-plain-talk` appears in help.
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin --include-plain-talk >/tmp/resolution-audit-plain-talk-bundle.md`
- `rg -n "Plain Talk Guide|The claims guard still wins|Plain Talk is voice guidance" /tmp/resolution-audit-plain-talk-bundle.md`
  - Result: matched the rendered guide section, guide claim-safety rule, and
    operator instruction.
- `python content-pipeline/resolution-audit/bundle_prompt.py --channel linkedin >/tmp/resolution-audit-default-bundle.md`
- `! rg -n "Plain Talk Guide|The claims guard still wins|Plain Talk is voice guidance" /tmp/resolution-audit-default-bundle.md`
  - Result: default bundle stayed Plain-Talk-free.
- `python -m py_compile content-pipeline/resolution-audit/bundle_prompt.py`
- `git diff --check -- content-pipeline/resolution-audit/bundle_prompt.py content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Plain-Talk-Bundler.md`
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated diff size

Actual working diff size: 3 files, +96 / -10.
