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
5. Keep the immutable template head/CSS code-owned. The model generates only a
   body fragment using existing template classes; the caller composes and
   validates the complete document.
6. Keep every wired HTML-generation prompt aligned with body-only admission and
   deterministic document composition.
7. Add focused unit tests, CI enrollment, and operator documentation.

### Files touched

- `lib/generation.py`, `lib/clients.py`, `lib/email.py`, `lib/__init__.py`
- `build.py`, `pipeline.py`
- `tests/test_generation.py`, `tests/__init__.py`
- `references/02-redesign-gen-prompt.md`, `references/04-interior-page-prompt.md`,
  `references/06-build-prompt.md`
- `.github/workflows/generator-tests.yml`
- `README.md`
- `plans/PR-Local-Generation-Provider.md`

## Mechanism

The CLI resolves a `GenerationConfig` from explicit arguments and environment
configuration. Local is the default and preflights LM Studio's loaded-model
list; OpenRouter requires the operator to select it and provide a model. Local
generation uses LM Studio's native `/api/v1/chat` contract so the request can
explicitly disable Qwen reasoning and server-side response storage. OpenRouter
keeps the OpenAI-compatible request path and receives cache metadata only when
it was requested by the caller.

Local generation uses a two-hour default request deadline because the exact Qwen
fixture exceeds the former cloud-oriented ten-minute deadline on supported local
hardware. The OpenAI-compatible client disables automatic retries, so one CLI or
Connect generation attempt produces exactly one model request instead of silently
restarting an expensive completion after a read timeout. An explicit
`GENERATION_TIMEOUT_SECONDS` value still overrides either provider default;
OpenRouter keeps the existing ten-minute default.

LM Studio's native response does not expose an OpenAI-style finish reason. The
adapter therefore requires its token statistics, treats an output count at the
configured ceiling as `length`, and admits only one text-message output. Any
reasoning, tool, malformed, or multi-message output fails closed. The existing
complete-document gate remains the final truncation check for HTML.

### Full-template timeout correction

The real exact-Qwen fixture proved that reasoning control alone is insufficient:
the local 27B model did not return the full generated document before the
two-hour read deadline, and no HTML was written. The root cause is the output
contract, not the deadline: the model is asked to reproduce the large immutable
template head and CSS on every build even though only the body varies.

The corrected contract keeps `references/03-base-template.html` authoritative.
Trusted code extracts its head and body scaffold, applies the already selected
theme and palette from the existing catalogs/JSON, and inserts a generated body
fragment only after it passes a body-root/content boundary. The assembled page
then passes the existing complete-document and byte gates. This preserves the
model's content, conditional-section, and layout decisions while bounding model
output to the actual variable page surface.

This correction must cover both HTML entry points (`build.py` and `pipeline.py`)
and therefore the Connect caller that reuses them. It must not change extraction,
enrichment, image generation, email generation/sending, deployment behavior,
claim/fabrication rules, or explicit OpenRouter selection.

Each response records provider, model, finish reason, content, and usage. Body
admission accepts only a normal `stop` response containing exactly one body root
and no head, style, script, doctype, or html wrapper. Trusted code combines that
fragment with the immutable template head. Full-document admission then requires
one ordered doctype, `html`, `head`, and `body` structure within the byte limit.
Writes use a same-directory temporary file plus `os.replace`. Non-whitespace text
and HTML elements outside `head` or `body` are rejected rather than silently
admitted. Required deployment-metadata placement remains code-owned: the model
supplies the existing comment as the body's first child, admission verifies that
boundary, and the assembler moves it into the trusted head exactly once.

Each caller derives its square-bracket placeholder vocabulary from the actual
wired prompt and supplies that set to body admission, so prompt edits cannot add
new placeholder syntax that silently leaks into output. Unrelated bracketed real
content remains admissible. Homepage callers also provide their own required
deployment-comment marker set; an incidental leading comment cannot impersonate
the build or redesign metadata contract.

## Intentional

- The scripts do not auto-load Qwen; a missing model exits with the exact
  `lms load` instruction.
- OpenRouter is never an automatic fallback because it changes cost and data
  locality.
- Provider requests are not retried implicitly. A caller or durable job owner must
  observe the failure before deciding whether to submit new work.
- Local Qwen reasoning is disabled at the provider contract, not with a prompt
  phrase the model could ignore or echo.
- Existing outer Markdown fences remain tolerated, but embedded fences,
  provider chatter, partial body markup, forbidden head/style/script content,
  and length-limited completions fail closed.
- Resend's informational domain check still occurs when email is actually sent,
  not when unrelated modules import.

## Deferred

- Local Connect v2 registration, authenticated routes, durable jobs, and
  conformance tests remain isolated in the dependent Connect-provider slice.
- The controlled real-Qwen fixture must run again at the dependent Connect PR's
  exact head before that slice can merge.
- Desktop/web UI, model catalogs, automatic model loading, and cloud fallback
  remain outside this milestone.

## Verification

- `/tmp/website-redesign-connect-venv/bin/python -m unittest discover -s tests -v`
  — 59 tests passed after body-only generation, both HTML entry points gained
  shared-assembly coverage, and prompt/comment boundaries were reconciled.
- `/tmp/website-redesign-connect-venv/bin/python -m compileall -q build.py pipeline.py lib tests`
  — passed.
- `/tmp/website-redesign-connect-venv/bin/python build.py --help` — passed;
  provider/model and existing skip flags shown.
- `/tmp/website-redesign-connect-venv/bin/python pipeline.py --help` — passed;
  provider/model and existing skip flags shown.
- `git diff --check` — passed.
- An authenticated native LM Studio probe against exact model
  `qwen/qwen3.8-27b` returned one text message with
  `reasoning_output_tokens: 0`, proving that `reasoning: "off"` reaches the
  loaded model without prompt-only control.
- The required fixture command completed against exact model
  `qwen/qwen3.8-27b` through the native LM Studio path and wrote
  `outputs/builds/drees-plumbing-inc/index.html`; the cold request reported
  31,031 prompt tokens.
- Both required artifact searches returned `0`: no unresolved trust/template
  tokens and no unsupported `Upfront Flat-Rate`, `Surprise Fees`,
  `Free Estimates`, or `Owner Answers` claims were emitted.
- Reconstructing the real generated Qwen body/comment in memory and passing it
  through the stricter prompt-placeholder and caller-marker admission returned
  `real artifact stricter-admission probe: PASS`.

## Estimated diff size

The provider seam, both callers, lazy clients, body/document guards, prompts,
workflow, plan, and their boundary tests form one vertical slice. It exceeds the
soft target for the indivisibility and boundary-test reasons stated above.
