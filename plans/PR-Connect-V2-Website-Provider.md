# Local Connect v2 website-generation provider

## Why this slice exists

The local-first generation slice gives the Python entry points one validated
JSON-to-HTML seam, but independently installed apps still cannot discover or
invoke it. Local Connect v2 at contract commit
`c5405935bd1354cf6a4c8539425a53dfd7f52949` is the accepted generic capability
authority. This slice implements that existing contract without adding a
broker, consumer-specific UI, or a second generation pipeline.

That pinned contract also requires each provider to enforce the independent
`connect.capability_exchange` entitlement on every live route. The repository
does not currently contain an official issuer public keyring, so this slice
ships the fail-closed verifier and canonical fixture proof; release authority
and license provisioning remain explicitly blocked on issue #27 rather than
using a runtime override or test key in production.

The authenticated HTTP surface, durable idempotency store, worker lifecycle,
and contract-boundary tests form one vertical capability proof. The slice may
exceed the repository's 400-line soft target because separating persistence or
authentication from the endpoint would temporarily advertise a capability
that cannot satisfy the job contract.

### vLLM integration contract

The operator selected standalone vLLM as the only named local runtime. The
stacked core provider now targets vLLM, but this provider's CLI help, retryable
job error, README instructions, and tests still direct the operator to
llama.cpp. Those are active recovery and operator-contract surfaces rather than
cosmetic wording: a failed Connect job would point away from the runtime that
the generator now requires.

This slice must align those surfaces with `scripts/start_vllm_server.sh`, the
default `127.0.0.1:8000/v1` endpoint, and the exact
`qwen/qwen3.8-27b` alias. It must continue to fail before registration when
vLLM is unhealthy or serves a different alias, and a runtime failure must remain
retryable without starting or restarting vLLM. It must not change the
advertised capability, artifact/job schemas, entitlement enforcement, bearer
authentication, durable job transitions, idempotency, generated HTML, or
OpenRouter behavior.

### Review-blocker contract revision

Exact-head review exposed four fail-closed gaps in already-declared Connect
surfaces. `GeneratedBodyError` is a `ValueError` but is absent from the
model-response exception tuple, so rejected model HTML is mislabeled as invalid
prospect input. The shared entitlement JSON decoder lets parser recursion escape
instead of converting it to the existing invalid-entitlement decision. Clean
shutdown also assumes parsed registration and `auth` values are dictionaries,
so a replaced or corrupted registration can abort the remaining cleanup. The
shared prospect preparer also accepts a non-string optional `display_name`, even
though final document assembly consumes a truthy value as text after generation;
that deterministic input failure is therefore mislabeled as retryable provider
failure after spending a model call.

The correct fix must classify `GeneratedBodyError` with other retryable model
response failures, translate excessive nesting once inside the shared
entitlement object decoder, and make registration cleanup treat malformed,
wrong-shaped, non-UTF-8, or excessively nested content as an ownership mismatch.
It must also reject a non-string, non-null `display_name` in shared prospect
preparation before generation, including falsy values that could defeat a
truthiness-based check.
It must add regression coverage for both sides of each boundary. It must not
broaden accepted entitlement/registration shapes, delete an unowned
registration, broadly reclassify internal exceptions as input failures, change
job or error schemas, or alter provider startup order.

### Pre-generation color validation contract

Exact-head review also exposed a deterministic input failure on the expensive
side of the model boundary. Prospect `brand_colors` are resolved only during
final HTML assembly, so a malformed truthy accent, dark accent, or secondary
value can occupy the local model and then surface as a retryable model-response
failure. The root cause is validation order, not worker retry behavior.

The correct fix must keep one document-color validation authority, validate the
fully resolved build palette before any generation request, and make Connect
perform that same validation inside its non-retryable input-preparation block.
Tests must prove malformed supplied colors never call generation and valid
supplied colors still reach it. This must not change deterministic palette
selection, default colors, rendered CSS values, model/provider selection, job
or error schemas, or any capability contract.

### Generated-Unicode classification contract

Exact-head review exposed a classification leak at the shared generated-body
boundary. A syntactically valid model response can decode to text containing an
unpaired Unicode surrogate; the body byte-limit check then raises a raw
`UnicodeEncodeError`. Because that exception is also a `ValueError`, the
Connect worker currently labels model-owned output as non-retryable invalid
prospect input.

The correct fix must make shared generated-body admission translate an
unencodable model body into `GeneratedBodyError`, which the existing Connect
worker classifies as retryable `MODEL_RESPONSE_INVALID`. It must preserve the
strict input decoder's existing non-retryable rejection of unpaired surrogates
in prospect and request JSON, and it must not broadly reclassify arbitrary
worker `ValueError` or `UnicodeEncodeError` exceptions. Tests must drive the
real generated-body validator through the worker and prove both ownership
directions.

### Final input and hero-asset admission contract

Exact-head review exposed two remaining admission-order defects. Shared prospect
preparation accepts a non-string `owner_email`, even though final generated-body
validation treats that value as an exact source-owned string; the deterministic
input defect therefore spends a model call and is mislabeled as a retryable model
response failure. Separately, the Connect-only hero predicate treats any nonempty
HTTP authority or `data:image/` prefix as a usable asset, so malformed authorities,
empty data payloads, and invalid base64 can preserve a photo-dependent layout that
the single-artifact capability cannot actually satisfy.

The correct fix must validate `owner_email` as string-or-null in the shared
pre-generation prospect boundary and retain `INPUT_INVALID` as its non-retryable
Connect outcome. It must admit a remote hero only when an HTTP(S) URL has a valid
host authority, and admit an embedded hero only when its image data payload is
nonempty and decodes according to its data-URL encoding. Boundary tests must prove
both accepted and rejected sides, including falsy optional-field values, malformed
HTTP authorities, empty data, invalid base64, valid absolute URLs, and valid
embedded image data.

This revision must not fetch or inspect remote images, add a second artifact,
change hero selection for valid supplied assets, alter generated HTML or job/error
schemas, broaden model-error classification, or validate unrelated optional
prospect fields. The repository-mandated plumber fixture and both zero-count
content-safety scans must then be rerun on the final combined head using the CUDA
vLLM runtime before the slice is called verified.

### Owner-email syntax admission revision

Exact-head review proved that the prior optional-field correction validates only
the `owner_email` JSON type. Non-email and whitespace-only strings still cross
the expensive generation boundary, then fail the source-owned output validator
as retryable `MODEL_RESPONSE_INVALID`. The root cause is two separate notions of
email validity: prospect preparation checks string-or-null while final body
admission owns the actual mailbox syntax.

The correct fix must expose one shared mailbox canonicalizer from generated-body
admission and use it during `prepare_prospect` before any provider call. Null
remains absent; a valid string is trimmed but otherwise preserved for source
copy; empty, whitespace-only, percent-encoded, or syntactically invalid values
must fail as deterministic input and retain Connect's non-retryable
`INPUT_INVALID` classification. Existing recognized placeholder values must
still be sanitized to null before syntax admission. Final visible and `mailto:`
comparisons must continue using the same canonical mailbox semantics.

Tests must prove invalid type and syntax values never call generation, valid and
trimmed values reach preparation, and downstream email ownership behavior is
unchanged. This correction must not change other prospect fields, capability or
job schemas, provider/runtime behavior, generated copy, or image, deployment,
and email-send effects.

### Address input admission revision

Exact-head review exposed the same validation-order defect for the optional
business address. A truthy non-string value reaches local generation and only
fails when generated-body admission tries to compare it with source evidence,
misclassifying deterministic input as retryable model output.

The correct fix must admit only string-or-null address input during shared
prospect preparation, trim a valid string, and normalize an empty or
whitespace-only string to absence before generation. Connect must retain the
existing non-retryable `INPUT_INVALID` mapping for rejected input, and tests
must prove truthy and falsy non-string values never reach generation. This must
not change address rendering, source-ownership admission, job/error schemas,
or any unrelated prospect field.

## Scope (this PR)

1. Expose `website.generate.single-page` version `1.0` over Local Connect v2,
   accepting one `application/json` artifact up to 200,000 bytes and producing
   one `text/html` artifact up to 2 MiB.
2. Bind only to loopback, require the per-process bearer token, publish an
   owner-private atomic runtime registration, and remove it on clean shutdown.
3. Persist the provider instance identity, request identity, input bytes, job
   states, errors, and completed HTML in SQLite before acknowledging work.
4. Enforce exact request/artifact identity, idempotent same-request replay,
   conflicting-ID rejection, and one active generation worker.
5. Reuse the local Qwen generation seam only; add conformance, endpoint,
   concurrency, restart, and failure-path tests plus operator documentation.
6. Re-evaluate the signed local Connect entitlement on every route and deny
   manifest, submission, and status access unless it is active.
7. Align provider startup, errors, documentation, and loopback tests with the
   direct standalone vLLM runtime inherited from the core slice.
8. Close the four exact-head review blockers in model-error classification,
   entitlement decoding, registration cleanup, and pre-generation optional-field
   validation without changing schemas.
9. Validate the resolved document palette before generation and classify
   malformed prospect colors as non-retryable input without duplicating color
   rules.
10. Classify unencodable model body text as retryable invalid model response
    while preserving strict non-retryable Unicode rejection on input.
11. Reject malformed `owner_email` and unusable hero-asset references before
    generation while preserving valid remote and embedded hero inputs.
12. Re-run the canonical plumber fixture and both zero-count fabrication scans on
    the final combined head with standalone CUDA vLLM.
13. Reject malformed optional addresses before generation and normalize blank
    address strings to omission.

### Files touched

- `build.py`
- `connect_provider.py`
- `lib/connect_v2.py`, `lib/connect_store.py`, `lib/connect_entitlement.py`
- `lib/generation.py`
- `tests/test_connect_provider.py`, `tests/test_generation.py`
- `requirements.txt`, `requirements-dev.txt`, `.github/workflows/generator-tests.yml`
- `README.md`
- `plans/PR-Connect-V2-Website-Provider.md`

## Mechanism

`connect_provider.py` validates that the configured model endpoint is a literal
loopback and disables environment-proxy discovery for that Connect-only model
client. It then preflights standalone vLLM health and the exact served
model alias, opens a listening socket
on an ephemeral `127.0.0.1` port, rotates a bearer token, and only then
atomically writes the v2 registration under the XDG runtime directory. Uvicorn
consumes that same listening socket. The durable instance UUID and jobs live in
a SQLite database under the XDG state directory.

`POST /v2/jobs` validates the request JSON before accepting the artifact, then
streams and bounds the artifact, verifies declared size and SHA-256, and stores
the complete accepted job in one transaction. Identical job-ID reuse returns
the existing status; different request identity returns 409. One background
worker transitions accepted → processing → completed/failed and stores the
validated HTML artifact. GET routes project stored state into the canonical v2
manifest and job-status shapes.

The reused generator now asks Qwen for only the variable body. Trusted code owns
the base template head/CSS, selected palette and theme, deployment-comment
placement, and final standalone-document admission. Connect therefore persists
and returns the same validated assembled HTML as the CLI without maintaining a
second template or output path.

Before generation, the shared prospect preparer requires each required field to
be a non-empty string and an optional `display_name` to be a string or null. The
Connect adapter also changes a photo-dependent hero
selection to the existing gradient shape when the one accepted input artifact
does not contain a usable `context == "hero"` photo URL. This keeps the advertised
single HTML output self-contained without invoking image acquisition.
The same adapter measures the exact pretty-serialized prospect prompt block and
rejects the input when it would cross the generator's limit, so Connect never
marks a job complete after silently truncating accepted prospect fields.
Request and prospect JSON share one strict decoder that rejects duplicate keys,
non-finite constants and exponent overflows, excessive parser depth, and
unpaired Unicode surrogates before hashing or generation. Integral metadata is
range-checked without converting arbitrary-size JSON integers to floats.
Photo-dependent hero shapes survive only when the actual hero record supplies
an absolute HTTP(S) image URL or an embedded `data:image/` URL; background-only,
relative, and local paths fall back to the existing gradient layout.

The HTTP layer checks bearer authentication first and the independently signed
local entitlement second on every request. Entitlement verification uses an
embedded build-owned public keyring, strict bounded JSON/base64url/claim
validation, Ed25519 signatures, and owner-only no-symlink file reads. Source
builds with no official keyring fail closed as authority-unavailable. Malformed
or non-ASCII bearer credentials fail as the same shaped unauthorized response
as any other invalid token.

## Intentional

- Connect invocation is local-Qwen-only and advertises `external: false`; an
  OpenRouter-configured CLI cannot silently change Connect's cost/privacy
  contract.
- CLI endpoint overrides remain available, but Connect rejects non-loopback,
  wildcard, malformed, and hostname-lookalike generation endpoints and ignores
  environment proxy variables. Normal CLI and explicit OpenRouter clients keep
  their existing proxy behavior.
- No parameters are declared in v1.0. Theme and section choices remain in the
  prospect JSON's existing deterministic contract.
- A supplied, accessible hero photo preserves the deterministic photo layout;
  absent, background-only, partial, or unrelated photo metadata uses the
  existing photo-free gradient layout because this capability does not produce
  image artifacts.
- The provider refuses to register when standalone vLLM or the exact
  Qwen alias is unavailable. It never auto-starts a runtime or model.
- Accepted jobs survive restart. Jobs interrupted while processing become a
  durable retryable `PROVIDER_INTERRUPTED` failure rather than silently rerun.
- Completed bytes remain provider-owned SQLite state and cross Connect only in
  the bounded canonical output artifact.
- Canonical entitlement fixture keys are test-only. Production cannot select a
  keyring with an environment variable.

## Deferred

- Existing-site analysis, email drafting, images, Vercel deployment, and
  OpenRouter-backed Connect capabilities are not advertised.
- Launch-on-demand, a broker, multi-input jobs, remote transport, large-output
  retrieval, and consumer UI remain deferred by the v2 contract.
- Additional website capabilities require a real consumer use case and their
  own atomic capability versions.
- Official entitlement authority and license provisioning are release
  operations tracked by #27; the provider must remain unavailable until both
  exist.

## Verification

- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935
  /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python
  -m unittest -v tests.test_connect_provider.GenerationSeamTests` — 22 tests
  passed in 2.844 seconds on the combined head. The suite includes truthy and
  falsy malformed address rejection before generation, blank-address omission,
  exact local-Qwen selection, literal-loopback enforcement, photo-free hero
  fallback, input/model error ownership, and registration-after-listener order.
- Current recovery evidence does not permit another live fixture:
  `nvidia-smi -L` enumerates only the NVIDIA GeForce RTX 4060 Ti, while `lsblk`
  shows the `Dev-Drive` partition with no mountpoint. The previously used vLLM
  binary and 27B model paths are therefore unavailable, and the RTX 3090 is not
  currently enumerated. No model was started on the display GPU.
- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935
  /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python
  -m unittest -v
  tests.test_connect_provider.GenerationSeamTests.test_optional_owner_email_must_be_string_or_null
  tests.test_connect_provider.GenerationSeamTests.test_malformed_owner_email_is_nonretryable_before_generation
  tests.test_connect_provider.GenerationSeamTests.test_in_memory_preparation_matches_file_loading_without_mutating_input
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_binds_every_business_email_to_source`
  passed: 4 tests in 1.400 seconds. Invalid type, empty, whitespace,
  malformed-domain, and percent-encoded mailbox inputs fail before generation;
  valid/trimmed and placeholder-null paths plus final source ownership pass.

- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m unittest -v
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_uses_shared_admission_gate
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_enforces_identity_and_phone_substitutions
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_gates_field_owned_claim_families
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_binds_footer_address_to_source
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_binds_tenure_claims_to_source_values
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_binds_ibew_claim_to_exact_local
  tests.test_generation.BodyAssemblyTests.test_body_admission_restricts_inline_styles_to_declared_properties
  tests.test_generation.VllmStartupScriptTests.test_generator_workflow_tracks_the_active_vllm_launcher
  tests.test_connect_provider.GenerationSeamTests`
  passed: 28 current-head core/Connect seam tests in 4.421 seconds. This proves
  the stacked provider reuses the source-bound build preparation and local
  generation boundary after the tenure, inline-style, and workflow corrections.

- `PYTHONWARNINGS=error::ResourceWarning CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935 /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m unittest tests.test_generation.GenerationConfigTests tests.test_generation.VllmStartupScriptTests tests.test_generation.ProviderBoundaryTests tests.test_connect_provider.ConcurrencyAndFailureTests.test_invalid_input_and_model_unavailability_have_distinct_failures tests.test_connect_provider.GenerationSeamTests.test_connect_client_bypasses_environment_proxies`
  passed: 42 affected runtime/Connect tests in 1.329 seconds, including the
  empty-body vLLM health contract and the retryable vLLM recovery instruction.
- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935 /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python connect_provider.py --help`
  passed and names standalone vLLM plus the exact local model alias.
- The combined suite and CUDA llama.cpp evidence below predate the vLLM
  replacement. They remain historical regression evidence but do not verify
  the current runtime or satisfy the final CUDA vLLM fixture requirement.

- `PYTHONWARNINGS=error::ResourceWarning CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935 /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m unittest discover -s tests`
  passed: 176 tests in 8.757 seconds on the updated combined tree, including
  the then-current direct `llama.cpp` preflight, loopback proxy bypass, startup boundaries, and
  the Connect retryable runtime instruction plus the exact-head review
  regressions, including truthy and falsy malformed optional display names.
- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/pip check` passed with no broken
  requirements.
- Canonical manifest, registration, job request/status, and HTTP-error schema
  validation against the pinned `connect-contracts` commit.
- Endpoint tests for missing/wrong/non-ASCII auth, malformed multipart,
  size/hash/media mismatches, same/conflicting IDs, busy concurrency, completed
  output, provider failure, and interrupted-job restart reconciliation.
- `bash scripts/local_pr_review.sh origin/codex/pr-local-generation-provider`
  passed, including the committed diff check and provider plan presence.
- Exact-head CUDA runtime acceptance: standalone `llama.cpp` from
  `/home/juan-canfield/.local/build/llama.cpp-v0.3.0-cuda/bin/llama-server`
  served the exact `qwen/qwen3.8-27b` alias on
  `http://127.0.0.1:18080/v1`. The process held 19,898 MiB on the NVIDIA
  GeForce RTX 3090 before inference and reached 96% utilization during the
  request; the RTX 4060 Ti did not host the model.
- A direct `generate_website_artifact` invocation used the real Connect input
  adapter and generated an admitted in-memory artifact from
  `examples/robert-niebrugge-sons-plumbing-dieterich.json`. llama.cpp processed
  28,068 prompt tokens and generated 2,314 tokens at 67.89 tokens per second;
  total model time was 45,225.64 ms. The returned artifact was
  `robert-niebrugge-sons-plumbing-homepage.html` (70,403 bytes, SHA-256
  `f89e4f5caff78fc4dac36f294d80a6f0975f872212d89badbf6144a900187be3`)
  and began with the required doctype. The acceptance command performed no
  deployment, email, image, or file-write side effect.
- The llama.cpp server was stopped after acceptance; the post-run GPU query
  reported 15 MiB used and 0% utilization on the RTX 3090.
- The first post-replacement Connect attempt proved the pinned upstream adapter
  could load the exact Qwen3.8 GGUF as `Qwen3_5ForCausalLM` under standalone
  vLLM and make the loopback API healthy. The real Connect generation request
  then killed the engine during prompt prefill with `CUDA error: unspecified
  launch failure`; no artifact or content-safety scan result was produced.
  The current combined head contains later address admission and pinned-adapter
  preflight commits, so that failed attempt is diagnostic evidence rather than
  final-head acceptance. The canonical fixture and both zero-count scans remain
  pending; no CPU, cloud, deployment, email, or image fallback was used.
- After the GPU returned, the canonical
  `examples/prospect-plumber-template.json` standalone build completed against
  `local:qwen/qwen3.8-27b` with image generation, email drafting, and deployment
  disabled. Its 73,121-byte artifact had SHA-256
  `e9ff4c2827b62be4a1b7f24f26169de39b4f6d68f96b7606cfd3a454a853ddf8`;
  the unresolved-placeholder and fabricated-claim scans each returned `0`.
- Two subsequent controlled `ProviderRuntime` jobs exercised the real durable
  Connect queue, canonical JSON adapter, local generator, admission boundary,
  and terminal persistence in temporary state. The first candidate invented
  the uncatalogued `nav-phone-wrap` class; the second candidate failed location
  admission. Each used the one bounded local correction and then persisted
  `status=failed`, `error_code=MODEL_RESPONSE_INVALID`, with zero output bytes.
  No repository, deployment, email, or image output was written. These runs
  prove fail-closed behavior, not successful Connect artifact delivery; the
  required successful terminal Connect fixture remains pending.
- The vLLM server was stopped after the bounded attempts. The post-stop compute
  process query was empty; the RTX 3090 reported 247 MiB used.
- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935
  /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python
  -m unittest
  tests.test_generation.AtomicWriteAndCliTests.test_build_generator_binds_location_and_radius_claims_to_source
  tests.test_connect_provider.GenerationSeamTests` passed 23 focused location
  and Connect adapter tests in 3.174 seconds on the merged branch.

## Final diff size

Measured against the current provider base: 13 files changed, with 3,851
insertions and 55 deletions across the durable provider and its contract,
concurrency, and restart boundary suite. Removing those tests or persistence
boundaries would make the advertised asynchronous capability unproved.
