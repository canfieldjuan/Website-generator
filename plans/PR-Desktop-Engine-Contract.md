# Desktop engine contract

## Why this slice exists

Issue #38 needs a private desktop boundary before a UI can call the existing
Website Generator safely. Today generation is reachable through the interactive
CLI and Local Connect HTTP provider, but neither is an appropriate desktop
sidecar contract. Adding UI calls directly to `build.py` would create a second
generation path and let the packaged application drift from Connect.

Root cause: generation preparation and output admission exist, but there is no
bounded, machine-readable desktop protocol or shared site-artifact service.

### Contract revision: Ollama local runtime

New evidence: the operator selected Ollama instead of vLLM. The live model
supports a 262,144-token context, but Ollama had loaded it with an 8,192-token
context while the build contract exceeded 100,000 characters before prospect
data. An Ollama sizing probe measured the fixture request at 28,811 prompt
tokens. The resulting contract truncation caused real fixture responses to
invent classes that the fail-closed HTML admission correctly rejected.

Revised root cause: the missing desktop boundary is compounded by a local
runtime path that identifies Ollama but still uses its OpenAI-compatibility
surface without provisioning enough context for this repository's prompt.

Revised required surface: `lib/generation.py`, Connect error text,
`connect_provider.py`, README runtime instructions, and their tests must use
Ollama's native loopback API, default port, installed model, disabled-thinking
mode, and an explicit context large enough for the build contract plus output.

Revised non-scope: the legacy vLLM launcher remains untouched historical manual
tooling and is no longer an application configuration fallback. This slice does
not delete it, manage the Ollama daemon, pull models, or weaken model-generated
output admission.

Revised verification: add Ollama readiness-shape boundary tests and run one live
status plus fixture generation against the already-running local Ollama model.

## Scope (this PR)

1. Extract the single-page site preparation/generation seam used by Local
   Connect into a shared service.
2. Add a strict, one-request/one-response desktop JSON protocol for prospect
   validation, generation status, and site generation.
3. Add a `desktop` subcommand to the existing packaged executable while
   preserving its default provider behavior and entitlement commands.
4. Prove malformed, partial, oversized, non-loopback, and credential-bearing
   requests fail closed without leaking credentials to stdout or errors.
5. Replace the local vLLM transport with native loopback Ollama requests and
   give the model only the review branch the admission contract permits.

### Files touched

- `connect_provider.py`
- `lib/connect_v2.py`
- `lib/desktop_protocol.py`
- `lib/generation.py`
- `lib/site_artifact.py`
- `README.md`
- `build.py`
- `references/06-build-prompt.md`
- `tests/test_connect_provider.py`
- `tests/test_desktop_protocol.py`
- `tests/test_generation.py`
- `plans/PR-Desktop-Engine-Contract.md`

## Mechanism

The new shared service accepts an already-decoded prospect object, applies the
same normalization and deterministic design selection used by Connect, forces
a self-contained hero fallback when required, enforces the existing prompt and
HTML limits, and returns the admitted HTML bytes plus display name.

The desktop executable accepts exactly one bounded UTF-8 JSON object on stdin:

```json
{"protocol":1,"operation":"prospect.validate","payload":{"prospect":{}}}
```

It emits exactly one compact JSON envelope on stdout. Successful envelopes use
`{"ok":true,"data":...}`; failures use a stable code and safe message under
`{"ok":false,"error":...}`. `site.generate` base64-encodes the admitted HTML.
Local endpoints must be literal loopback. Native Ollama requests pin the
required context and disable thinking. OpenRouter uses its fixed endpoint
and requires a session-supplied model and API key. The API key is never written
to disk, command-line arguments, stdout, or error text.

The Ollama request uses a stable seed and a 40,960-token context. That context
was selected from the measured 28,811-token fixture prompt plus the existing
8,192-token body limit, while remaining fully resident on the current GPU. The
build prompt is filtered to its code-derived review mode before dispatch so the
model is not asked to reason across mutually exclusive markup contracts.

## Intentional

- One process handles one request. This keeps cancellation and secret lifetime
  bounded and lets the future Tauri host own process containment.
- `generation.status` performs the local Ollama preflight. OpenRouter is
  configuration-validated but not probed, avoiding a paid cloud request.
- Desktop generation is standalone and may explicitly use OpenRouter; Local
  Connect remains pinned to local Ollama and cannot fall back to cloud.
- Existing prospect fields are preserved by deep-copy normalization. Computed
  fields remain an internal generation concern.
- The default model is the Ollama-installed `qwen3-30b-a3b:latest`, but the
  desktop contract remains model-configurable. No Qwen 3.8 Ollama artifact was
  found, so this slice does not claim that earlier model target was migrated.

## Deferred

- Tauri UI, native save/import dialogs, preview sandbox, cancellation, and the
  Windows installer are the next issue #38 slice.
- Entitlement installation and managed Local Connect lifecycle are the final
  issue #38 slice.
- Connect cleanup hardening #32 and generated-style hardening #33 remain
  separate work.

## Verification

- `python -m unittest tests.test_desktop_protocol` -- 21 passed.
- `python -m unittest tests.test_connect_provider` -- 60 passed, 5 skipped.
- Exact Linux CI shape with `CONNECT_CONTRACTS_DIR` pinned to `c5405935...`:
  279 passed, 10 skipped.
- `python -m compileall -q build.py pipeline.py connect_provider.py lib tests`
  and `git diff --check` -- passed.
- Required source fixture build through live Ollama -- completed; placeholder
  leaks and forbidden fabricated-claim matches both zero.
- PyInstaller release build with the approved public entitlement keyring --
  completed; the packaged binary passed validation and live model status.
- Packaged `site.generate` through live Ollama -- completed; declared and
  decoded artifact sizes matched, with both content guard counts at zero.
- `bash scripts/local_pr_review.sh` after the commit, as its clean-tree check
  requires committed changes.

## Estimated diff size

This exceeds the soft 400-line target because the executable contract, shared
generation seam, Ollama cutover, and their fail-closed proof form the one
desktop-engine prerequisite. The cold audit measured 12 files with 1,354
additions and 298 deletions; the Tauri UI and Connect lifecycle remain separate.
