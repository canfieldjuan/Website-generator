# Retire incompatible local runtime launchers

## Root cause

The production generation path now speaks only to operator-managed Ollama, but
the repository still ships `scripts/start_vllm_server.sh` as a working vLLM
launcher and makes `scripts/start_llama_server.sh` direct operators to it. That
runtime cannot satisfy the current Ollama version, tag, model-metadata, and chat
contracts, so the retained scripts are executable misinformation rather than a
supported fallback.

## Correct-fix contract

1. Keep both historical script names as compatibility entry points, but make
   each fail closed without launching a process, loading a model, touching the
   GPU, or attempting a cloud request.
2. Direct operators to install/start Ollama themselves and make the configured
   `qwen3-30b-a3b:latest` model available before running the application.
3. Replace the obsolete vLLM launcher implementation tests with a compact
   boundary contract proving both entry points fail, name Ollama, and contain no
   executable vLLM launch path.
4. Keep workflow enrollment for both filenames so any future change remains
   reviewed.

## Must not change

- `lib/generation.py`, provider selection, model defaults, request/response
  parsing, timeouts, prompts, or HTML admission.
- `build.py`, `pipeline.py`, prospect JSON, generated output, image, email, or
  deploy behavior.
- Local Connect capability schemas, authentication, entitlements, durable jobs,
  registration, or desktop lifecycle/UI.
- Application-managed Ollama startup, automatic model loading/download, CPU or
  cloud fallback, and unrelated launcher/platform cleanup.

## Verification

- Run the focused launcher retirement tests in both pass and fail directions.
- Run the complete Python suite with canonical Connect contracts and compile all
  Python entry points.
- Run `bash -n` on both retained scripts, `git diff --check`, and the repository
  local review wrapper.

Completed evidence:

- `python -m unittest -v
  tests.test_generation.RetiredRuntimeLauncherTests` passed both focused tests.
- With `CONNECT_CONTRACTS_DIR=/home/juan-canfield/Desktop/connect-contracts`,
  `python -m unittest discover -s tests -v` passed 274 tests with 10
  native-Windows skips.
- `python -m compileall -q build.py pipeline.py connect_provider.py lib tests`,
  `bash -n scripts/start_llama_server.sh`,
  `bash -n scripts/start_vllm_server.sh`, and `git diff --check` passed.
