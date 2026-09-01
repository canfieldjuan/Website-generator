# Local Connect v2 website-generation provider

## Why this slice exists

The local-first generation slice gives the Python entry points one validated
JSON-to-HTML seam, but independently installed apps still cannot discover or
invoke it. Local Connect v2 at contract commit
`c5405935bd1354cf6a4c8539425a53dfd7f52949` is the accepted generic capability
authority. This slice implements that existing contract without adding a
broker, consumer-specific UI, or a second generation pipeline.

The authenticated HTTP surface, durable idempotency store, worker lifecycle,
and contract-boundary tests form one vertical capability proof. The slice may
exceed the repository's 400-line soft target because separating persistence or
authentication from the endpoint would temporarily advertise a capability
that cannot satisfy the job contract.

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

### Files touched

- `connect_provider.py`
- `lib/connect_v2.py`, `lib/connect_store.py`
- `tests/test_connect_provider.py`
- `requirements.txt`, `requirements-dev.txt`, `.github/workflows/generator-tests.yml`
- `README.md`
- `plans/PR-Connect-V2-Website-Provider.md`

## Mechanism

`connect_provider.py` preflights the configured local model, starts a FastAPI
server on an ephemeral `127.0.0.1` port, rotates a bearer token, and atomically
writes the v2 registration under the XDG runtime directory. The durable
instance UUID and jobs live in a SQLite database under the XDG state directory.

`POST /v2/jobs` validates the request JSON before accepting the artifact, then
streams and bounds the artifact, verifies declared size and SHA-256, and stores
the complete accepted job in one transaction. Identical job-ID reuse returns
the existing status; different request identity returns 409. One background
worker transitions accepted → processing → completed/failed and stores the
validated HTML artifact. GET routes project stored state into the canonical v2
manifest and job-status shapes.

## Intentional

- Connect invocation is local-Qwen-only and advertises `external: false`; an
  OpenRouter-configured CLI cannot silently change Connect's cost/privacy
  contract.
- No parameters are declared in v1.0. Theme and section choices remain in the
  prospect JSON's existing deterministic contract.
- The provider refuses to register when Qwen is unavailable. It never auto-loads
  a model.
- Accepted jobs survive restart. Jobs interrupted while processing become a
  durable retryable `PROVIDER_INTERRUPTED` failure rather than silently rerun.
- Completed bytes remain provider-owned SQLite state and cross Connect only in
  the bounded canonical output artifact.

## Deferred

- Existing-site analysis, email drafting, images, Vercel deployment, and
  OpenRouter-backed Connect capabilities are not advertised.
- Launch-on-demand, a broker, multi-input jobs, remote transport, large-output
  retrieval, and consumer UI remain deferred by the v2 contract.
- Additional website capabilities require a real consumer use case and their
  own atomic capability versions.

## Verification

- `python3 -m unittest discover -s tests -v`
- `python3 -m compileall -q build.py pipeline.py connect_provider.py lib tests`
- Canonical manifest, registration, job request/status, and HTTP-error schema
  validation against the pinned `connect-contracts` commit.
- Endpoint tests for missing/wrong auth, malformed multipart, size/hash/media
  mismatches, same/conflicting IDs, busy concurrency, completed output, provider
  failure, and interrupted-job restart reconciliation.
- `bash scripts/local_pr_review.sh`
- The controlled real-Qwen proof remains the final cross-surface acceptance run.

## Estimated diff size

Expected 9 files and approximately 1,850–2,100 added lines, split between the
durable provider and its contract/concurrency/restart boundary suite. The
overage is justified above; removing those tests or persistence boundaries
would make the advertised asynchronous capability unproved or non-durable.
