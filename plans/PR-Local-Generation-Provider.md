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

### Unicode claim-admission revision

Exact-head review proved that browser-decoded attributes can preserve Unicode
whitespace such as the non-breaking space in `Free&nbsp;Estimates`. The claim
gate case-folds text but compares that non-breaking space directly with the
ordinary space in the denied phrase, so the same unsupported customer-facing
claim can bypass admission through whitespace representation alone.

The correct fix must compatibility-normalize Unicode and collapse every
whitespace run before comparing both denied phrases and all visible, decoded,
and URL-decoded output surfaces. Tests must cover ordinary space, HTML
non-breaking space, another Unicode whitespace code point, and a clean nearby
label. This must not broaden the denied-claim catalog, rewrite generated output,
or change placeholder, provider, assembly, or deployment behavior.

### GPU-runtime revision

The controlled fixture used `LLAMA_CPP_GPU_LAYERS=all`, but the launcher still
defaults that setting to `auto`. On the supported workstation the 27B Qwen GGUF
fits the RTX 3090, and normal app use must request full CUDA layer offload rather
than leave CPU/GPU placement implicit. The launcher must therefore default to
`all` while preserving an explicit `auto` or numeric override for other
installations. This must not auto-start a model during application preflight,
select a cloud provider, hide launch failure, or remove the operator's explicit
runtime override.

### Required-page-structure revision

The GPU-default fixture produced valid balanced HTML but omitted the
`<footer class="site-footer">` wrapper around `.footer-grid` and
`.footer-bottom`. The class catalog exposes available components but does not
state which structural components are mandatory, so prompt-only footer guidance
cannot guarantee that the trusted `.site-footer` border/background rules apply.
After that prompt correction, the next fixture emitted the footer but omitted
the entire services grid even though the prospect supplied eight services and
the build contract requires six cards. The root cause is that all mandatory
page structure is still advisory model prose.

The correct fix must encode the from-scratch build's unconditional skeleton as
exact class counts at shared admission: one nav, hero, coverage band, services
grid, benefits grid, contact form, and footer structure; six service cards; and
three benefit cards. The response-boundary reminder must repeat those counts so
the one allowed generation attempt can satisfy them. Redesign and interior pages
must enforce only the common footer structure because their other sections are
data-dependent. Any missing, partial, or duplicated mandatory structure must
fail before assembly and file write. This must not change the base CSS, visible
copy, generated page ordering, conditional reviews/trust behavior, or introduce
a second component implementation.

### Services-component contract revision

The exact GPU fixture still omitted the required services section after the
response boundary repeated its exact class counts. A reduced, selected-trade
defaults context produced the same failure: the model ended normally after
2,460 generated tokens with no truncation, but returned zero `.services-grid`
and `.service-card` elements. Prompt size and output length are therefore not
the cause. Comparing the emitted page with the build prompt shows that every
rendered structured section has a concrete HTML markup contract, while services
is the only unconditional component described solely in prose.

The correct fix must provide one exact allowed-class services scaffold at the
services rule and repeat that compact scaffold at the final response boundary.
The existing exact-count admission remains the fail-closed enforcement before
write. The unsuccessful selected-trade filtering experiment must not remain in
the diff. This must not move service choice or copy into code, change prospect
service precedence or selection, alter visible design, add retries, change
provider behavior, or affect deployment/email/image or Connect job contracts.

### Exact-head admission contract revision

The shared admission parser currently concatenates visible text nodes without
a separator, counts repeated class tokens within one element more than once,
and applies one unconditional build skeleton even when placeholder sanitation
has removed the phone number that makes the coverage band valid. Those are
three boundary-model errors: browser-rendered denied claims can disappear from
the comparison string, one DOM element can impersonate several required
components, and correct no-phone output can be rejected.

The correct fix must compare both boundary-separated and compact text-node
surfaces for rendered claims while retaining compact split-placeholder checks;
count each required class no more than once per element, including case-folded
duplicates; reject case variants rather than treating them as either the exact
required class or an unrelated class; and require exactly one coverage band
when the sanitized prospect has a phone number and exactly zero otherwise.
Tests must prove each adverse case and its positive opposite.
This must not alter the denied-claim catalog, placeholder sanitation, other
mandatory component counts, prompt copy, visual design, provider selection,
GPU/runtime behavior, or any image, email, deployment, or Connect contract.

### Loopback redirect contract revision

Restricting the configured local endpoint and disabling environment proxies is
not sufficient locality enforcement while the HTTP client still follows
redirects. A loopback health, model-discovery, or generation response can point
Requests at a remote target; the generation redirect can replay the complete
prospect prompt even though the selected provider remains labelled local.

The correct fix must disable redirects on every shared local llama.cpp request,
including both preflight requests and the generation POST, and prove the flag at
the request boundary. Redirect responses must surface through the existing
provider-unavailable behavior rather than trigger another request. This must not
change OpenRouter, retry behavior, endpoint validation, payloads, timeouts,
provider labels, GPU/runtime behavior, or Connect capability semantics.

### Structural semantics contract revision

The remaining exact-head findings share one root cause: output admission still
models browser structure as flat token totals and global text joins. That can
miss a denied phrase containing both a rendered line boundary and inline word
markup, count differently cased class tokens even though the trusted CSS will
not select them, and admit required footer or grid components outside the
parent that gives them their layout and styling.

The correct fix must build ordered visual and accessibility exposure streams,
including human-facing replacement content such as image alt text, form values,
placeholders, and accessibility labels at their DOM position. Denied phrases
must be compared in both whitespace-normalized and compact Unicode-alphanumeric
forms so markup and CSS cannot change the admission decision. Required classes
must use exact, case-sensitive membership once per element, and the declared
direct-child shape of the footer, services grid, service cards, and benefits
grid must be validated. Tests must cover mixed/CSS boundaries, replacement and
accessibility text, wrong-case tokens, orphaned children, and valid structures.
Direct accessibility text remains supported, and indirect ARIA text references
must resolve unique in-body IDs in declared attribute order. Missing, duplicate,
or cyclic IDREFs must fail closed so admission cannot construct a different
accessible exposure from the browser.
This must not alter trusted CSS, visible copy, component cardinality, page
ordering, provider/model selection, GPU/runtime behavior, placeholder
sanitation, or image, email, deployment, and Connect job contracts.

### Mandatory output truth and markup contract revision

The final exact-head findings expose two remaining prompt-only assertions. The
build serializes mandatory business-name and phone substitutions for the model,
but does not pass those values into admission. The body parser also tracks only
the root body depth, so balanced-body output can still contain unclosed or
misnested descendants that a browser silently repairs into a different DOM.

The correct fix must enforce every build substitution that affects identity or
the primary contact path. The normalized business name and, when present, phone
must occur in visual or accessibility exposure; a present phone must have at
least one `tel:` target and every `tel:` target must resolve to that same phone;
every exposed phone-like value must resolve to the verified phone, and when no
phone is verified neither phone-like exposure nor a `tel:` target may appear.
Inline display/visibility suppression, including an `!important` priority,
must not satisfy required visual or accessibility exposure.
User-exposed attributes such as `title` and direct accessibility descriptions
must participate in that exposure check, while hidden elements and internal
`data-*` metadata must not. Suppression on the generated body root must apply
to its descendants just as suppression on any nested element does. Each
unsuppressed accessibility node must be evaluated independently even when an
ancestor supplies its own ARIA name. Phone-shape matching must canonicalize
Unicode decimal digits, dash punctuation, and invisible format separators that
do not change what the user perceives as the number. Directional formatting or
isolation controls within phone-shaped data must fail closed because removing
them can change the digits the browser presents. Every phone-shaped value in a
decoded actionable URL attribute must follow the same verified-phone contract,
independent of URI scheme or host; the existing required exact `tel:` action
remains the primary contact-path requirement.
Generated body fragments must not carry an alternate executable action plane:
model-authored event-handler attributes, `srcdoc`, and executable script URI
payloads must fail admission before trusted assembly. This restriction applies
only to the model-produced body and must not rewrite the trusted template.
Image fallback behavior is code-owned: the prompts must not request event
handlers, admission must reject any handler supplied by the model, and trusted
assembly must add only the fixed hide-on-error handler to admitted `img`
elements. Neither prospect data nor model output may influence that handler.
Phone admission must additionally scan browser-visible DOM adjacency before an
accessibility-name override can replace ancestor text. Inline text fragments
must remain adjacent for this scan, while semantic block and line boundaries
must terminate a candidate phone value. Caller-declared deployment metadata
markers must also be rejected inside model-authored comments; the explicit
Formspree setup TODO remains allowed, and trusted head comments remain
code-owned.
Conditional business claims must be denied from a complete field-owned
catalog, not from an issue-specific phrase list. Unsupported trust,
availability, scheduling, and trade-credential fields must contribute their
entire canonical claim family; `service_promises` remains the only authority
for its separate pricing, estimate, billing, and owner-availability families.
Required identity substitutions may match punctuation or markup variants only
as a complete normalized alphanumeric token sequence. A short compact name must
never pass because it appears inside an unrelated longer word elsewhere in the
page.
Conditional claim denials must cover the entire canonical family seeded by the
prompt catalogs, not only one rendered label; an unsupported same-day field,
for example, must reject every `Same Day ...` variant. The build caller must
also declare the exact code-owned contact-form action: the verified
`formspree_endpoint` verbatim when present, otherwise `#`. Admission must bind
that value to the single actual `form.contact-form-wrap`; a matching value on
another element or a different well-formed endpoint cannot satisfy it.
The shared parser must also reject unclosed, unexpectedly closed, or misnested
non-void descendants before BeautifulSoup repair, while accepting standard void
elements and valid self-closing SVG content. Finally, each generator must pass
the exact class catalog it gave the model into admission so build, redesign, and
interior output cannot invent unstyled classes. Tests must prove omissions,
wrong and mixed links, exposed-phone mismatches, no-phone output, unknown
classes on all three callers, both malformed-markup directions, and valid
opposites.

This must not change prospect values, phone presentation, visible copy, trusted
template/CSS, required component counts, provider/model selection, GPU/runtime
behavior, or any image, email, deployment, and Connect job contract.

### Mobile trust-strip fixture revision

The final phone-width browser proof exposed a release-path defect in the
trusted template itself: the mobile trust strip remains fixed-height, its
children do not wrap, and the responsive rule converts overflow into an
unlabelled horizontal scroller. Verified trust signals can therefore render
off-canvas even though the generated document passes admission.

The correct fix must touch only the trusted template's phone-width trust-strip
layout, its focused regression, and this evidence record. At 768px and below,
the strip must preserve every rendered trust signal, wrap them within the
viewport, and grow vertically as needed. Desktop trust-strip behavior, trust
content, model prompts, generation admission, provider selection, runtime,
and all downstream image, email, deployment, and Connect contracts must remain
unchanged.

### Raw-attribute and no-phone contract revision

The exact-head review exposed two remaining model/browser boundary mismatches.
First, the raw HTML parser preserves duplicate attributes while BeautifulSoup
repairs them to one value; validating only the repaired DOM can therefore
approve a different actionable value than a browser uses. Duplicate attributes
are invalid generated HTML and have no supported use here. The correct fix must
reject every case-insensitive duplicate attribute on an element in raw body
admission before the repaired DOM controls claims, links, classes, IDs, or
accessibility semantics.

Second, a sanitized missing business phone changes backend admission and the
coverage-band count, but three static prompt requirements still demand nav and
hero phone actions and a global nav/hero/footer `tel:` checklist. The correct
fix must make every business-phone rendering instruction conditional and add a
final caller-owned no-phone instruction: omit business phone values and phone
actions, omit the emergency/or hero controls, and use the existing `#contact`
request-service action as the sole hero CTA. The visitor phone input inside the
lead form is unrelated and must remain required. The verified-phone path,
contact form routing, trust content, design system, providers, runtime, and all
image, email, deployment, and Connect contracts must remain unchanged.

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
14. Default the standalone llama.cpp launcher to all GPU layers, with explicit
    overrides preserved and no CPU or cloud fallback.
15. Enforce exact class counts for the unconditional from-scratch page skeleton
    and the shared footer structure so prompt omissions cannot ship.
16. Give the mandatory services component an exact markup contract while
    preserving model-owned service selection and code-owned count admission.
17. Normalize Unicode whitespace at the unsupported-claim comparison boundary
    so browser-equivalent claim text cannot bypass admission.
18. Preserve text-node boundaries for unsupported-claim matching without
    weakening split-placeholder detection.
19. Count each required class once per element rather than once per repeated
    class token.
20. Derive the exact coverage-band count from the sanitized phone value (`1`
    when present, `0` when absent) while leaving every other count unchanged.
20a. Reject case variants of every required class so zero-count requirements
     cannot be bypassed and positive requirements cannot admit unstyled names.
21. Disable redirects on every shared loopback llama.cpp request so a local
    response cannot replay prompts or preflight traffic to a remote target.
22. Scan ordered visual and accessibility exposure streams in both normalized
    and compact forms so CSS, replacement text, and markup segmentation cannot
    hide denied claims.
23. Match required class names with exact case-sensitive HTML class membership.
24. Enforce the direct-child component shapes that make the required footer,
    service, and benefits structures functional.
25. Resolve indirect ARIA text references in declared order and reject missing,
    duplicate, or cyclic references while retaining direct labels and alt text.
26. Enforce the build's business-name and phone substitutions in rendered
    exposure and exact `tel:` destinations, including the explicit no-phone
    path.
27. Reject unbalanced or misnested generated descendants before browser repair
    while preserving standard void elements and valid SVG self-closing tags.
28. Reject exposed phone-like values that are absent from or conflict with the
    sanitized prospect phone, not only incorrect `tel:` destinations.
29. Enforce each generator's provided allowed-class catalog during shared body
    admission for build, redesign, and interior output.
30. Treat priority-bearing inline display and visibility suppression as hidden
    when validating required generated output exposure.
31. Include user-exposed tooltip and accessibility-description attributes in
    output truth admission, honor body-root suppression, and avoid treating
    hidden or internal metadata as copy.
32. Traverse exposed accessibility descendants independently of an ancestor's
    own accessible name while preserving hidden ID-reference resolution.
33. Canonicalize Unicode digit, dash, and invisible-format variants before
    applying phone-shape admission.
34. Reject bidirectional controls in phone-shaped exposure or action data while
    retaining harmless invisible-separator normalization.
35. Enforce the verified-phone contract on decoded `href`, `action`,
    `formaction`, and SVG `xlink:href` phone-shaped destinations.
36. Reject model-authored event handlers, `srcdoc`, and executable script URI
    attribute payloads before assembly.
37. Remove model-authored image-handler requirements and add the fixed image
    fallback only after body admission in trusted assembly.
38. Scan a DOM-adjacent visual phone surface that preserves inline adjacency
    and terminates at semantic block or line boundaries.
39. Reject caller-declared deployment metadata markers inside model-authored
    comments while preserving the explicit Formspree setup TODO.
40. Derive unsupported conditional claim denials from every field-owned trust,
    availability, scheduling, and trade-credential claim family.
41. Replace page-wide compact substring identity admission with complete
    normalized token-sequence matching.
42. Cover every prompt-seeded same-day wording through one semantic claim
    family rather than one label-specific phrase.
43. Require the exact verified Formspree action, or the explicit `#` fallback,
    on the generated contact form before assembly.
44. Keep every trust-strip child within the phone viewport by wrapping the
    trusted strip and allowing its height to grow at the existing mobile
    breakpoint.
45. Reject duplicate raw attribute names before any repaired DOM can decide
    generated-body admission.
46. Make every business-phone output instruction conditional and give a
    sanitized no-phone prospect one consistent request-service CTA path.
47. Bind review cards, aggregate ratings, counts, and review links to the
    sanitized source data; reject review UI and ambient review claims when no
    source evidence exists.
48. Reject testimonial-shaped semantic tags plus quoted or attributed prose
    outside the canonical source-bound review roots, including ASCII and curly
    single-quote forms.
49. Bind every exposed or actionable business email to the sanitized source,
    including addresses assembled across inline DOM nodes, without joining
    fragments across semantic block boundaries.
50. Require exactly one generated contact form, its exact verified action (or
    the explicit `#` fallback), and no conflicting per-control `formaction`.

### Files touched

- `lib/generation.py`, `lib/clients.py`, `lib/email.py`, `lib/__init__.py`
- `build.py`, `pipeline.py`
- `tests/test_generation.py`, `tests/__init__.py`
- `references/02-redesign-gen-prompt.md`, `references/04-interior-page-prompt.md`,
  `references/03-base-template.html`, `references/06-build-prompt.md`,
  `references/07-industry-defaults.md`
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

Review admission is source-bound: sanitized review entries own review cards,
the source rating/count/link own aggregate review UI, and a no-review prospect
must not emit canonical review components, ambient score/count claims,
testimonial tags, or quoted/attributed testimonial prose elsewhere in the
document. Business-email admission similarly compares direct text and decoded
attributes with a block-boundary-aware DOM adjacency stream so split inline
addresses cannot bypass the source contract. Its synthetic boundary is invalid
inside both phone and email values. Block elements and actionable contact links
establish semantic boundaries; otherwise unseparated inline nodes are scanned
as one rendered candidate, so an adjacent fabricated prefix cannot hide behind
an expected child-node address. `mailto:` targets must resolve to the same
sanitized email. The generated body must contain one and only one contact form;
trusted code verifies its exact action and rejects a conflicting submit-control
override before assembly.

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
  — 118 tests passed in 1.401 seconds, including the `llama.cpp`
  health/model/chat contract,
  browser- and URL-decoded placeholder admission, startup-script boundaries, and both
  HTML entry points' shared assembly. The suite also proves this slice cannot
  reconfigure the pre-existing extraction or image model roles through new
  environment variables, keeps interior-page components out of homepage
  generation, checks claim-bearing attributes, preserves a deterministic
  document palette for uncatalogued trades, and rejects missing, duplicated, or
  unresolved mandatory page structure. The final suite also covers source-bound
  review cards and aggregate claims, testimonial-shaped prose, direct and
  inline-split business email identity, and single-form action ownership.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m compileall -q build.py pipeline.py lib tests`
  — passed.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m unittest
  tests.test_generation.BodyAssemblyTests.test_mobile_trust_strip_wraps_without_horizontal_scroller`
  — failed against the fixed-height horizontal-scroller rule, then passed
  after the scoped mobile template correction.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m unittest
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_requires_exact_contact_form_action`
  — passed with wrong form action, missing fallback action, and mixed
  verified-form/unverified-button `formaction` cases rejected; exact verified
  form and button actions and the explicit `#` fallback remain accepted.
- The duplicate-attribute and no-phone probes failed against the prior head,
  then `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m
  unittest tests.test_generation.BodyAssemblyTests.test_body_admission_rejects_duplicate_raw_attributes
  tests.test_generation.PromptContractTests.test_build_prompt_conditions_every_business_phone_action
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_requires_coverage_band_only_with_a_phone
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_enforces_identity_and_phone_substitutions`
  passed. The boundary set covers duplicate link, ARIA, and class attributes;
  a distinct valid attribute set; verified and sanitized-missing phone prompt
  branches; and the real caller's conflicting duplicate `href` case.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m unittest tests.test_generation.BodyAssemblyTests.test_body_admission_rejects_gated_claim_in_decoded_attributes`
  — passed after the Unicode-whitespace review correction; covers ordinary,
  non-breaking, em-space, percent-encoded, and clean-label paths.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python -m unittest tests.test_generation.AtomicWriteAndCliTests.test_build_generator_rejects_reviews_without_source_evidence tests.test_generation.AtomicWriteAndCliTests.test_build_generator_binds_every_business_email_to_source tests.test_generation.AtomicWriteAndCliTests.test_build_generator_enforces_identity_and_phone_substitutions -v`
  — 3 tests passed in 0.420 seconds. The boundary set rejects ASCII/curly
  single-quoted testimonial prose and wrong or absent-source email addresses,
  including addresses split across inline nodes; it accepts the verified direct
  and split-inline addresses plus non-address fragments separated by block
  boundaries.
- `bash -n scripts/start_llama_server.sh` — passed.
- `scripts/start_llama_server.sh --help` — passed without loading a model.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python build.py --help` — passed;
  provider/model and existing skip flags shown.
- `/home/juan-canfield/.cache/website-redesign-connect-venv/bin/python pipeline.py --help` — passed;
  provider/model and existing skip flags shown.
- `git diff --check` — passed.
- Last admitted standalone-runtime fixture at generator code head
  `731289ccdea34acb416cc854a00e0f1551b38db4`:
  `LOCAL_GENERATION_BASE_URL=http://127.0.0.1:18081/v1
  GENERATION_TIMEOUT_SECONDS=14400
  /home/juan-canfield/.cache/website-redesign-connect-venv/bin/python build.py
  examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft
  --skip-deploy` completed successfully against the `llama.cpp` v0.3.0 build at
  commit `c1d0e7a004015f23bc0233470b747b596f29b264`, serving the exact
  `qwen/qwen3.8-27b` alias. The command produced no deployment, email, or image
  side effect. `CUDA_VISIBLE_DEVICES=0` and the launcher's default
  `LLAMA_CPP_GPU_LAYERS=all` confined inference to the RTX 3090; the live server
  process held 19,898 MiB there. The server recorded 27,955 prompt tokens and
  2,850 generated tokens at 67.23 tokens/second, with 53,792.27 ms total task
  time.
- The admitted artifact was
  `outputs/builds/drees-plumbing-inc/index.html` (71,870 bytes, SHA-256
  `7fbedc85221654541b5f6bec447f3730be4732d246e18c6499cbad1bc53c6e1d`).
  The shared HTML validator accepted it. Its generated body contains zero
  unresolved curly placeholders and zero same-day claims; the one whole-file
  `{{TOKEN}}` occurrence is the immutable base-template documentation comment,
  not model output. It contains exactly one contact form with the verified
  prospect endpoint.
  It contains one services grid, six service cards, six service names, six
  service descriptions, and every other mandatory class at its exact count.
- The saved GPU artifact was re-admitted through the final executable-attribute,
  deployment-comment, conditional-claim, complete-token identity,
  DOM-adjacent phone, exposed-phone, and allowed-class gates in this PR; the
  current build caller returned
  `saved-gpu-artifact-final-admission: PASS` without another model request. The
  fixture contains no `img` element, so the fixed post-admission image handler
  is proven separately by the focused trusted-assembly regression rather than
  overstated as fixture evidence.
- The original system-Chrome proof exposed the second trust badge off-canvas
  at 390x844. The saved, admitted GPU body was then re-admitted through the
  final validator and deterministically assembled with the corrected trusted
  template (72,170 bytes). A fresh 390x844 system-Chrome screenshot
  (`final-mobile.png`, 85,974 bytes) shows both trust signals wrapped within
  the viewport and the strip growing to contain them. The responsive override
  is confined to the existing 768px breakpoint, so the desktop layout remains
  controlled by the unchanged base rules.
- A second CUDA-backed generation request after the template correction
  completed model inference but was rejected before output because that sample
  omitted the single required `form.contact-form-wrap` action owner. This is
  retained as fail-closed evidence, not reported as a successful fixture and
  not retried merely to obtain a passing sample.
- A final CUDA-backed request after the duplicate-attribute and no-phone prompt
  corrections also completed inference but was rejected before output because
  Qwen emitted the unsupported `Not a Franchise` claim. The server recorded
  28,263 prompt tokens and 2,833 generated tokens at 66.81 tokens/second, with
  53,722.82 ms total task time. The prior admitted GPU body still passes the
  final executable parser and prompt-caller path (`saved-gpu-body-final-admission:
  PASS`, 72,170 bytes). The two rejected samples establish that one-shot local
  generation is not reliably admissible; a bounded retry policy remains a
  separate product decision because the OpenRouter path can incur cost.
- The standalone runtime was stopped after validation. The GPU compute-process
  query was empty.
- Mocked local transport tests prove the configured request reaches the
  `llama.cpp` chat route once, disables thinking, preserves finish status, and
  fails closed on malformed, reasoning, tool, and multi-choice responses.

## Estimated diff size

The provider seam, both callers, lazy clients, body/document guards, prompts,
workflow, plan, and their boundary tests form one vertical slice. It exceeds the
soft target for the indivisibility and boundary-test reasons stated above.
