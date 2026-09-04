# Retire incompatible local runtime launchers

## Why this slice exists

The production generation path speaks only to operator-managed Ollama, but the
repository still ships `scripts/start_vllm_server.sh` as a working vLLM launcher,
makes `scripts/start_llama_server.sh` direct operators to it, and calls that
launcher usable historical tooling in the README. vLLM cannot satisfy the current
Ollama version, tag, model-metadata, and chat contracts, so these surfaces are
executable misinformation rather than a supported fallback.

This diff exceeds the 400-line target because it deletes the 229-line obsolete
launcher and its 496-line implementation-specific test matrix in the same slice
that replaces their public behavior and focused boundary proof. Splitting those
deletions from the fail-closed compatibility contract would leave a reviewed head
that either still advertises the incompatible runtime or removes its safety proof.

## Scope (this PR)

1. Keep both historical script names as compatibility entry points, but make
   each fail closed without launching a process, loading a model, touching the
   GPU, or attempting a cloud request.
2. Direct operators to install/start Ollama themselves and make the configured
   `qwen3-30b-a3b:latest` model available before running the application.
3. Replace the obsolete vLLM launcher implementation tests with a compact
   boundary contract proving both entry points fail, name Ollama, and contain no
   executable vLLM launch path.
4. Correct the README model section so it no longer presents either retired
   launcher as usable tooling.
5. Keep workflow enrollment for both filenames so any future change remains
   reviewed.

### Files touched

- `plans/PR-Retire-Vllm-Launchers.md`
- `scripts/start_llama_server.sh`
- `scripts/start_vllm_server.sh`
- `tests/test_generation.py`
- `README.md`

## Mechanism

Each retained launcher is a seven-line shell compatibility stub. It writes an
operator-managed Ollama instruction to stderr and exits with status 2 before
reading runtime configuration or invoking any process. The focused test supplies
a marker-writing fake `VLLM_BIN`, exercises both no-argument and `--help`
calls, and proves the marker is never created. A static second-side probe rejects
any reintroduced `exec` or `vllm serve` path.

## Intentional

- The historical filenames remain present so existing commands fail with the
  correct migration instruction instead of a context-free missing-file error.
- `--help` also fails because these are no longer supported launchers; returning
  success would continue advertising a callable runtime path.
- The large diff is overwhelmingly deletion of an incompatible launcher and its
  obsolete implementation-detail tests, not new product surface.
- The application still does not start Ollama or load a model automatically.

## Deferred

- Application-managed Ollama startup or model loading, model catalogs, CPU/cloud
  fallback, and unrelated runtime/platform cleanup remain outside this milestone.
- Registration-path object hardening remains tracked by #32.
- Generated inline-style value bounds remain tracked by #33.

## Verification

- `python -m unittest -v
  tests.test_generation.RetiredRuntimeLauncherTests` passed both focused tests.
- With `CONNECT_CONTRACTS_DIR=/home/juan-canfield/Desktop/connect-contracts`,
  `python -m unittest discover -s tests -v` passed 274 tests with 10
  native-Windows skips.
- `python -m compileall -q build.py pipeline.py connect_provider.py lib tests`,
  `bash -n scripts/start_llama_server.sh`,
  `bash -n scripts/start_vllm_server.sh`, and `git diff --check` passed.
- `bash scripts/local_pr_review.sh origin/main` must pass on the committed head
  before push.

## Estimated diff size

Five files and roughly 800 changed lines, with more than 700 lines removed. The
overage is justified by the indivisible retirement and replacement proof above.
