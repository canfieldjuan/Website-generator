# Local-first generation provider

## Why this slice exists

`origin/main` routes extraction, HTML generation, and pitch-draft generation
through one eager OpenRouter client and a hard-coded cloud model. Importing the
client module can also contact Resend before email is requested. Generated HTML
is fence-stripped and written without checking the provider finish reason or
whether the document actually closed.

The accepted product direction is local-first generation with
`qwen/qwen3.8-27b`, explicit per-run OpenRouter selection, and a shared safe
generation seam that the next Local Connect provider slice can invoke. The
provider abstraction, its two CLI callers, the HTML admission gate, and the
negative tests are one indivisible behavior change. This exceeds the 400-line
soft target primarily because the new tests cover both sides of every provider
and output boundary; splitting those tests from the guard would ship an
unproved admission rule.

## Scope (this PR)

1. Add a provider-neutral generation module with a local Qwen default and
   explicit OpenRouter configuration.
2. Make third-party clients lazy so local-only use has no import-time network
   activity.
3. Route both Python entry points through the shared provider and add explicit
   provider/model flags without changing their existing skip/deploy behavior.
4. Require normal completion and a complete standalone HTML document before
   atomically writing or deploying generated output.
5. Add focused unit tests, CI enrollment, and operator documentation.

### Files touched

- `lib/generation.py`, `lib/clients.py`, `lib/email.py`, `lib/__init__.py`
- `build.py`, `pipeline.py`
- `tests/test_generation.py`, `tests/__init__.py`
- `references/02-redesign-gen-prompt.md`, `references/06-build-prompt.md`
- `.github/workflows/generator-tests.yml`
- `README.md`
- `plans/PR-Local-Generation-Provider.md`

## Mechanism

The CLI resolves a `GenerationConfig` from explicit arguments and environment
configuration. Local is the default and preflights LM Studio's loaded-model
list; OpenRouter requires the operator to select it and provide a model. The
shared request adapter sends plain content to local OpenAI-compatible servers
and adds cache metadata only for OpenRouter.

Each response records provider, model, finish reason, content, and usage. HTML
admission accepts only a normal `stop` response containing one ordered doctype,
`html`, `head`, and `body` structure within the byte limit. Writes use a
same-directory temporary file plus `os.replace`. Non-whitespace text and HTML
elements outside `head` or `body` are rejected rather than silently admitted.
Both generation prompts place their required deployment metadata comment inside
`head`, preserving that metadata without contradicting the doctype-first gate.

## Intentional

- The scripts do not auto-load Qwen; a missing model exits with the exact
  `lms load` instruction.
- OpenRouter is never an automatic fallback because it changes cost and data
  locality.
- Existing outer Markdown fences remain tolerated, but embedded fences,
  provider chatter, partial markup, and length-limited completions fail closed.
- Resend's informational domain check still occurs when email is actually sent,
  not when unrelated modules import.

## Deferred

- Local Connect v2 registration, authenticated routes, durable jobs, and
  conformance tests land in the dependent Connect-provider slice.
- A controlled real-Qwen fixture generation runs after the Connect provider can
  prove the same HTML through both CLI and Connect surfaces.
- Desktop/web UI, model catalogs, automatic model loading, and cloud fallback
  remain outside this milestone.

## Verification

- `/tmp/website-redesign-connect-venv/bin/python -m unittest discover -s tests -v`
  — 36 tests passed.
- `python3 -m compileall -q build.py pipeline.py lib tests` — passed.
- `python3 build.py --help` — passed; provider/model and existing skip flags shown.
- `python3 pipeline.py --help` — passed; provider/model and existing skip flags shown.
- `git diff --check` — passed.
- The required real fixture build is not complete. An authenticated replacement
  server on loopback port 1235 loaded exact model `qwen/qwen3.8-27b` on the CPU
  runtime with a 131,072-token context, and the build passed exact-model
  preflight and began generation. During prompt ingestion, LM Studio attempted
  to restore its server setting to port 1234; a stale LM Studio listener already
  owned that port, so the restart failed, disconnected the request, and produced
  no admitted HTML. The proof model was unloaded and the original NVIDIA runtime
  restored. The stale server conflict and viable inference performance remain
  acceptance blockers, not passing proof.

## Estimated diff size

Approximately 11 files and 1,100 added/changed lines. The slice exceeds the
soft target for the indivisibility and boundary-test reasons stated above.
