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

### Runtime replacement contract

The local provider must talk directly to a standalone `llama-server`. The
current implementation is coupled to LM Studio's model-list client, native chat
route, request fields, response fields, and startup instructions; changing only
the displayed runtime name would leave the request contract unusable.

The correct change must move local preflight to `llama.cpp` health and
OpenAI-compatible model-list routes, move generation to
`/v1/chat/completions`, preserve the exact `qwen/qwen3.8-27b` alias, disable
thinking at both the request and documented server-start boundaries, and parse
the response shape actually returned by `llama-server`. It must provide one
loopback-only startup path and tests for ready/unready health, exact/missing
model identity, malformed responses, reasoning/tool output, completion status,
and request construction.

This runtime replacement must not change the Qwen model choice, prompt content,
body/document admission, trusted template assembly, explicit OpenRouter path,
email/image/deployment behavior, or the dependent Connect job/authentication
contract. A real-model fixture remains required before the Connect slice can
merge, but it must not be started while the operator has requested that the GPU
remain unloaded.

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
8. Replace the LM Studio transport with direct loopback `llama.cpp` health,
   model-discovery, and chat-completion contracts plus a guarded startup script.

### Files touched

- `lib/generation.py`, `lib/clients.py`, `lib/email.py`, `lib/__init__.py`
- `build.py`, `pipeline.py`
- `tests/test_generation.py`, `tests/__init__.py`
- `references/02-redesign-gen-prompt.md`, `references/04-interior-page-prompt.md`,
  `references/06-build-prompt.md`
- `.github/workflows/generator-tests.yml`
- `scripts/start_llama_server.sh`
- `README.md`
- `plans/PR-Local-Generation-Provider.md`

## Mechanism

The CLI resolves a `GenerationConfig` from explicit arguments and environment
configuration. Local is the default and preflights standalone `llama.cpp`
`/health` and `/v1/models` responses; OpenRouter requires the operator to select
it and provide a model. Local generation uses `llama.cpp`'s OpenAI-compatible
`/v1/chat/completions` contract, sends plain system/user messages, disables Qwen
thinking through chat-template parameters, and rejects any returned reasoning
or tool-call surface. OpenRouter keeps its existing request path and receives
cache metadata only when it was requested by the caller.

Local generation uses a two-hour default request deadline because the exact Qwen
fixture exceeds the former cloud-oriented ten-minute deadline on supported local
hardware. The OpenAI-compatible client disables automatic retries, so one CLI or
Connect generation attempt produces exactly one model request instead of silently
restarting an expensive completion after a read timeout. An explicit
`GENERATION_TIMEOUT_SECONDS` value still overrides either provider default;
OpenRouter keeps the existing ten-minute default.

The `llama.cpp` adapter requires exactly one OpenAI-compatible choice, a string
finish reason, a text message, and an object usage record. Any reasoning, tool,
malformed, or multi-choice output fails closed. The returned finish reason feeds
the existing normal-completion gate, and the complete-document gate remains the
final truncation check for HTML.

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

Each caller derives its square-bracket placeholder vocabulary from every trusted
static prompt source it actually sends, including catalogs/defaults and the base
body scaffold, then supplies that set to body admission. Dynamic prospect/site
data is deliberately excluded so real bracketed customer content remains valid;
static prompt edits cannot add new placeholder syntax that silently leaks into
output. Admission checks the raw body plus browser-decoded, element-spanning
visible text and decoded attribute values, so character references cannot hide
either square-bracket or curly-brace placeholders. Homepage callers also provide
their own required
deployment-comment marker set; an incidental leading comment cannot impersonate
the build or redesign metadata contract.

## Intentional

- Generation commands do not auto-start or silently fall back from
  `llama.cpp`; a missing runtime/model exits with the documented standalone
  startup instruction.
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
  — 71 tests passed, including the `llama.cpp` health/model/chat contract,
  browser-decoded placeholder admission, startup-script boundaries, and both
  HTML entry points' shared assembly.
- `/tmp/website-redesign-connect-venv/bin/python -m compileall -q build.py pipeline.py lib tests`
  — passed.
- `bash -n scripts/start_llama_server.sh` — passed.
- `scripts/start_llama_server.sh --help` — passed without loading a model.
- `/tmp/website-redesign-connect-venv/bin/python build.py --help` — passed;
  provider/model and existing skip flags shown.
- `/tmp/website-redesign-connect-venv/bin/python pipeline.py --help` — passed;
  provider/model and existing skip flags shown.
- `git diff --check` — passed.
- The earlier LM Studio fixture is historical evidence for the Qwen model and
  generated-body contract only; it does not verify the replacement
  `llama.cpp` transport.
- The exact-model `llama.cpp` fixture and both required artifact searches remain
  pending because the operator directed that the GPU stay unloaded during this
  implementation pass.
- Mocked local transport tests prove the configured request reaches the
  `llama.cpp` chat route once, disables thinking, preserves finish status, and
  fails closed on malformed, reasoning, tool, and multi-choice responses.

## Estimated diff size

The provider seam, both callers, lazy clients, body/document guards, prompts,
workflow, plan, and their boundary tests form one vertical slice. It exceeds the
soft target for the indivisibility and boundary-test reasons stated above.
