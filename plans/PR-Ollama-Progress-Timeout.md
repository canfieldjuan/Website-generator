# PR: Bound Ollama queue stalls without capping active generation

## Why this slice exists

Issue #46 records a local generation request that completed its one-token prompt
accounting probe and then received no HTTP status from the full Ollama request
until the client read timeout expired. The live runtime is configured with
`OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1`. A controlled probe on
2026-09-06 preloaded `qwen3-30b-a3b:latest`, occupied that single slot with a
second request, and reproduced a `ReadTimeout` after 5.005 seconds on the next
request while the contender was still running.

Ollama's queue is shared by every local client. An application-specific lock
would not protect against Document Summarizer, model tests, or any other client
that does not honor that lock. The broken boundary is instead in the local
transport: Website Generator sends both the prompt-accounting probe and the full
generation as non-streaming requests and gives each one the same 7,200-second
socket inactivity timeout. Queueing, prompt evaluation, active generation, and a
dead provider are therefore indistinguishable.

The required invariant is: waiting for Ollama to start or resume a request must
have a production-usable no-progress bound, while a healthy long generation may
continue beyond that interval when Ollama is actively streaming response chunks.
The existing total generation ceiling remains independent and authoritative.

## Scope (this PR)

1. Add a bounded local no-progress timeout with a safe default and an explicit
   positive environment override.
2. Apply that bound to the one-token prompt probe and to starting/reading the
   full local request.
3. Request the full Ollama response as NDJSON streaming output, assemble its
   content and terminal token accounting deterministically, and preserve all
   existing response/admission checks.
4. Translate a no-progress timeout into an actionable local-provider error that
   explains another local model request may be occupying Ollama.
5. Add focused regressions for configuration boundaries, stream assembly,
   terminal/error frames, and both probe/full-request timeout paths.
6. Prove the production-shaped no-deploy plumber fixture still persists an
   admitted artifact when Ollama is uncontended, then repeat a bounded
   contention probe without making application or production writes.

### Files touched

- `lib/generation.py`
- `tests/test_generation.py`
- `README.md`
- `plans/PR-Ollama-Progress-Timeout.md`

## Mechanism

`GenerationConfig` carries a local no-progress timeout separate from the
existing generation timeout. Local config resolution accepts
`LOCAL_GENERATION_NO_PROGRESS_TIMEOUT_SECONDS`; direct callers receive the same
default. The prompt probe stays a one-token non-streaming request because its
entire response is itself the progress unit. Its socket read is bounded by the
smaller of the remaining generation ceiling and the no-progress timeout.

The full native `/api/chat` request uses `stream: true`. The adapter consumes
newline-delimited JSON frames, joins only assistant content, retains the terminal
`done_reason` and token counts, and rejects malformed, error, reasoning, tool,
oversized, duplicate-terminal, or incomplete streams through the existing error
types. The socket read timeout becomes an inactivity bound between progress
frames rather than a limit on the whole generation. Elapsed wall time is checked
against the existing generation timeout so continuous output cannot silently
remove that ceiling.

No runtime-residency check is used as authority. `/api/ps` can show a loaded
model but cannot prove whether the queue is free, and checking it would retain a
check-then-act race. No cross-application file lock is added because unrelated
Ollama clients cannot be required to participate.

## Intentional

- Local Ollama remains the default and no cloud/provider fallback is added.
- Contention is reported as recoverable provider unavailability; requests are
  not retried automatically because another retry would join the same queue and
  could duplicate an ambiguously completed generation.
- The model, context size, deterministic seed, prompt accounting, and output
  token reserve do not change.
- Document Summarizer is evidence for shared-runtime contention, not part of this
  repository's change surface.

## Deferred

- Changing Ollama daemon settings such as `OLLAMA_MAX_QUEUE`,
  `OLLAMA_MAX_LOADED_MODELS`, or `OLLAMA_NUM_PARALLEL` remains operator-owned.
- A machine-wide scheduler for arbitrary local-AI applications is a separate
  product/architecture decision and is not required for bounded failure here.
- User-interface progress rendering is separate; this slice makes the provider
  transport progress-aware and bounded.

## Verification

Current local evidence, recorded 2026-09-06 against base
`826f0c8919615d4ed2849ebed8fb511bc6bc994b` plus only the four declared working
files:

- A controlled baseline preloaded `qwen3-30b-a3b:latest` in 6.851 seconds,
  occupied the sole Ollama slot with another request, and reproduced a
  `ReadTimeout` after 5.005 seconds while the contender remained active.
- The same boundary applied to the changed adapter allowed its prompt probe to
  complete, introduced the contender before the full request, and returned
  `GenerationProviderUnavailable` after 5.591 seconds with the actionable
  no-generation-progress message. A separate uncontended two-token request
  completed and preserved the terminal usage response.
- During investigation, the independent Document Summarizer process was
  observed running its live Ollama Office acceptance test against the same
  host. No Website Generator lock or `/api/ps` check could make that shared
  runtime exclusive.
- The production-shaped fixture ran from `2026-09-06T10:22:14-05:00` through
  `2026-09-06T10:23:09-05:00` with exit status 0:

  ```text
  PYTHONUNBUFFERED=1 GENERATION_TIMEOUT_SECONDS=1800 LOCAL_GENERATION_NO_PROGRESS_TIMEOUT_SECONDS=300 python build.py examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft --skip-deploy
  ```

  `outputs/builds/drees-plumbing-inc/index.html` did not exist before the run.
  The new 71,983-byte artifact has SHA-256
  `1d1f424e35b274b9f1e1973fcd3b21784110bbc38f15885f4360cc48d507ea22`.
  The fixture log is `/dev/shm/website-generator-pr46-fixture.log`.
- The required placeholder and case-insensitive forbidden-claim scans each
  returned status 1 (zero matches). Headless Chrome rendered the generated page
  at 1440x1200; the header, phone/CTA, hero, coverage prompt, and service cards
  were visible without raw placeholders or an obvious broken layout. The local
  screenshot is `/dev/shm/website-generator-pr46-fixture.png`.
- Focused timeout and exact byte-boundary regressions passed: 3 tests, 0
  failures. An earlier complete generation-module run passed 150 tests. After
  the effective-deadline correction, the full repository suite passed: 294
  tests, 34 skipped, 0 failures; log:
  `/dev/shm/website-generator-pr46-full-tests.log`.
- `python -m ruff check lib/generation.py tests/test_generation.py --ignore F401`,
  `python -m compileall -q lib/generation.py tests/test_generation.py`, and
  `git diff --check` passed. `F401` is scoped out because the test module already
  contains two unrelated unused admission-contract imports on `origin/main`.

Pending before publish: run `bash scripts/local_pr_review.sh origin/main` on the
clean committed worktree, then reconcile the exact remote head with GitHub CI
and review.

## Estimated diff size

Target: exactly the four declared files. The stream decoder and its negative-path
tests are indivisible because streaming changes the trusted response boundary;
the final line count is secondary to keeping that transport boundary and its
negative cases together.
