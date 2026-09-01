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
contract. A controlled real-model fixture remains required before the Connect
slice can merge, and the runtime must be unloaded after its evidence is
captured.

### Exact-head boundary revision

Exact-head review proved that the shared local URL constructor validates scheme,
path, query, and fragment but not the host, so a remote endpoint can receive the
complete prompt while still being labeled `local`. It also proved that body
admission excludes wrappers, style, and script but still admits HTML head
metadata, while one wired prompt contradicts code-owned fonts by asking the model
to paste a font import.

The correct fix must make the URL constructor used by both preflight and
generation admit only `localhost` or literal loopback addresses and reject
credentials, remote/wildcard/lookalike hosts, and malformed ports before any
request. The local HTTP client must also ignore environment proxy configuration
so a loopback URL cannot forward the prompt through `HTTP_PROXY` or
`HTTPS_PROXY`. It must reject `base`, `link`, `meta`, and HTML `title` from the body,
preserve valid SVG accessibility titles, and align every wired prompt with that
boundary. It must not alter OpenRouter, page content/layout, CSS tokens, or the
Connect job contract.

### Exact-model fixture revision

The real local Qwen fixture exposed a second ownership error: the model receives
the complete multi-industry body scaffold and deployment-comment templates even
though most of their placeholders do not apply to the selected prospect. Qwen
can therefore copy unrelated calendar/radio or optional photo-credit tokens into
an otherwise complete local-business body. Rewording individual prompt warnings
does not remove that source of invalid output.

The correct fix must keep the base template authoritative while sending the
model only its code-derived class vocabulary plus the existing page-specific
section patterns. Deployment metadata and optional image credit must be derived,
comment-sanitized, and inserted by trusted code. Body admission must continue to
reject unresolved placeholders, unsupported gated prospect claims, and provider
chatter. This revision must not
change visible page copy/layout rules, prospect facts, provider selection,
OpenRouter behavior, deployment/email/image effects, or the Connect job contract.

### Mobile fixture revision

The exact-model visual fixture exposed a class-ownership leak rather than a CSS
defect: the generic class catalog gives homepage generation interior-only
`.page-body` and `.page-cta-*` components. Qwen combined those valid class names
inside `.footer-bottom`; the trusted footer CSS expects a compact copyright row,
so the three interior wrappers collapsed into unreadably narrow mobile columns.

The correct fix must give homepage generation only the shared/homepage class
vocabulary, while preserving `.page-wrap` and leaving the complete catalog
available to interior-page generation. Homepage admission must reject the
interior-only class set even if a provider invents or recalls one. Both homepage
prompts must define the existing compact `.footer-bottom` structure explicitly.
This revision must not edit the base template CSS, redesign the footer, remove
interior-page components, or otherwise change the intended desktop/mobile
product shape.

### Exact-head review revision

The generated-claim admission gate currently compares denied prospect claims
only with visible character data even though the parser already retains decoded
attribute values. A provider can therefore move the same unsupported promise
into an accessibility label, title, or another attribute and bypass the gate.
The correct fix must compare the denied phrases with both joined visible text
and each decoded and URL-decoded attribute value. It must not broaden the claim
catalog or reject an otherwise clean body.

Trusted document-color assembly also treats a missing trade palette as fatal,
although prospect intake accepts uncatalogued trades and the redesign path
already has a deterministic generic blue/navy fallback. The correct fix must
use that same code-owned fallback only when neither explicit brand colors nor a
trade-specific palette is available. Explicit brand colors, supported-trade
palette selection, theme selection, and the accepted prospect schema must not
change.

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
9. Enforce locality at both local request entry points and exclude head metadata
   from generated bodies while preserving SVG titles; local requests never use
   environment proxies.
10. Remove cross-industry scaffold placeholders and deployment metadata from
    model context; expose the template class catalog and insert sanitized,
    code-owned head comments instead.
11. Keep interior-only component classes out of homepage context and admission,
    while retaining the shared `.page-wrap` class and the full interior-page
    catalog.
12. Apply unsupported-claim admission to decoded attribute values as well as
    visible text.
13. Preserve uncatalogued-trade builds with the existing generic document-color
    fallback while retaining explicit-brand and supported-trade precedence.

### Files touched

- `lib/generation.py`, `lib/clients.py`, `lib/email.py`, `lib/__init__.py`
- `build.py`, `pipeline.py`
- `tests/test_generation.py`, `tests/__init__.py`
- `references/02-redesign-gen-prompt.md`, `references/04-interior-page-prompt.md`,
  `references/06-build-prompt.md`, `references/07-industry-defaults.md`
- `.github/workflows/generator-tests.yml`
- `scripts/start_llama_server.sh`
- `README.md`
- `plans/PR-Local-Generation-Provider.md`

## Mechanism

The CLI resolves a `GenerationConfig` from explicit arguments and environment
configuration. Local is the default, accepts only localhost or literal loopback
endpoints, ignores environment proxy settings, and preflights standalone `llama.cpp`
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
Trusted code extracts its head and body class vocabulary, applies the already
selected theme and palette from the existing catalogs/JSON, and inserts a
generated body fragment only after it passes a body-root/content boundary. The assembled page
then passes the existing complete-document and byte gates. This preserves the
model's content, conditional-section, and layout decisions while bounding model
output to the actual variable page surface.

This correction must cover both HTML entry points (`build.py` and `pipeline.py`)
and therefore the Connect caller that reuses them. It must not change extraction,
enrichment, image generation, email generation/sending, deployment behavior,
claim/fabrication rules, or explicit OpenRouter selection.

Each response records provider, model, finish reason, content, and usage. Body
admission accepts only a normal `stop` response containing exactly one body root
and no head, head metadata, style, script, doctype, or html wrapper. Trusted code combines that
fragment with the immutable template head. Full-document admission then requires
one ordered doctype, `html`, `head`, and `body` structure within the byte limit.
Writes use a same-directory temporary file plus `os.replace`. Non-whitespace text
and HTML elements outside `head` or `body` are rejected rather than silently
admitted. Required deployment metadata is fully code-owned: callers derive it
from normalized prospect/site data, sanitize it as one valid HTML comment, and
the assembler inserts it into the trusted head exactly once. The model neither
sees nor emits that metadata.

Each caller derives its square-bracket placeholder vocabulary from every trusted
static prompt source it actually sends, including catalogs/defaults, then
supplies that set to body admission. Dynamic prospect/site
data is deliberately excluded so real bracketed customer content remains valid;
static prompt edits cannot add new placeholder syntax that silently leaks into
output. The immutable base template contributes only its extracted class-name
catalog to model context, so unrelated page and industry placeholders cannot be
copied. Admission checks the raw body plus browser-decoded, element-spanning
visible text and decoded attribute values, including percent-decoded attribute
surfaces, so character references or URL encoding cannot hide either
square-bracket or curly-brace placeholders. Homepage callers instead provide
their own code-owned deployment-comment builders; an incidental model comment
cannot impersonate the build or redesign metadata contract.

The from-scratch caller also derives a deny set for prospect-specific pricing,
estimate, and owner-availability claims from `service_promises`. Body admission
checks browser-visible, element-spanning text so known unsupported claims fail
before any write. When the JSON explicitly carries the matching promise, the
claim remains admissible.

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
- Desktop/web UI, model catalogs, automatic model loading, and cloud fallback
  remain outside this milestone.

## Verification

- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m unittest discover -s tests -v`
  — 85 tests passed, including the `llama.cpp` health/model/chat contract,
  browser- and URL-decoded placeholder admission, startup-script boundaries, and both
  HTML entry points' shared assembly. The suite also proves this slice cannot
  reconfigure the pre-existing extraction or image model roles through new
  environment variables, keeps interior-page components out of homepage
  generation, checks claim-bearing attributes, and preserves a deterministic
  document palette for uncatalogued trades.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m compileall -q build.py pipeline.py lib tests`
  — passed.
- `bash -n scripts/start_llama_server.sh` — passed.
- `scripts/start_llama_server.sh --help` — passed without loading a model.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python build.py --help` — passed;
  provider/model and existing skip flags shown.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python pipeline.py --help` — passed;
  provider/model and existing skip flags shown.
- `git diff --check` — passed.
- Exact-head standalone-runtime fixture:
  `LOCAL_GENERATION_BASE_URL=http://127.0.0.1:18081/v1
  GENERATION_TIMEOUT_SECONDS=14400
  /home/juan-canfield/.cache/website-redesign-connect-venv/bin/python build.py
  examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft
  --skip-deploy` completed successfully against `llama.cpp` v0.3.0 at commit
  `c1d0e7a004015f23bc0233470b747b596f29b264`, serving the exact
  `qwen/qwen3.8-27b` alias. The command produced no deployment, email, or image
  side effect. `CUDA_VISIBLE_DEVICES=0` and `LLAMA_CPP_GPU_LAYERS=all` confined
  inference to the RTX 3090; the live server process held 19,898 MiB there.
- The admitted artifact was
  `outputs/builds/drees-plumbing-inc/index.html` (71,864 bytes, SHA-256
  `8a275a80208b1542272846096bfcc954e8396b04ff0d4261ef03ed5e8c488690`).
  The shared HTML validator accepted it; the required unresolved-placeholder
  search returned `0`, and the required fabricated-claim search returned `0`.
- System Chrome screenshots at 1440x900 and 390x844 confirmed the generated
  desktop layout remains coherent and the mobile footer now stacks normally
  with a readable one-line copyright row. The artifact contains no interior
  `.page-body` or `.page-cta-*` class in generated markup.
- The standalone runtime was stopped after validation. The GPU compute-process
  query was empty and RTX 3090 usage returned to 15 MiB.
- Mocked local transport tests prove the configured request reaches the
  `llama.cpp` chat route once, disables thinking, preserves finish status, and
  fails closed on malformed, reasoning, tool, and multi-choice responses.

## Estimated diff size

The provider seam, both callers, lazy clients, body/document guards, prompts,
workflow, plan, and their boundary tests form one vertical slice. It exceeds the
soft target for the indivisibility and boundary-test reasons stated above.
