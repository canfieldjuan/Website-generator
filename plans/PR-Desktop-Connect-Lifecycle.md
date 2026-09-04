# Desktop Local Connect lifecycle

## Why this slice exists

The Website Generator can now work as a standalone desktop application, and
the same packaged engine can serve the Local Connect v2 capability. The
remaining gap is operational ownership: activation and provider startup still
require a terminal, so the native app does not actually make its existing
Connect capability available to an operator.

The root cause is not missing generation behavior or capability discovery.
The provider, signed-entitlement validator, durable job store, registration,
and HTTP contract already exist. The missing seam is a bounded native
lifecycle controller around that exact packaged provider.

A correct fix must let the desktop report the privacy-bounded entitlement
state, select and install an issuer-signed entitlement through the existing
activation adapter, and start/stop one provider child owned by the desktop.
Startup must become successful only after the existing provider has completed
Ollama preflight and published its registration. The child must be stopped and
reaped on operator request or normal desktop shutdown. Standalone generation
must remain available when Connect is inactive.

This work must not change prospect preparation, generated HTML, admission,
Local Connect manifests/routes/job semantics, discovery directories,
entitlement cryptography or authority, the standalone provider CLI default,
Ollama daemon/model management, OpenRouter behavior, deployment, billing, or
any unrelated Connect hardening issue.

This slice exceeds the repository's 400-line soft target because the managed
readiness handshake, the one-child native controller, the operator controls,
and installed-Windows smoke form one end-to-end lifecycle contract. Splitting
any one of them would leave either an unowned provider process, controls with
no packaged implementation, or packaging with no operator-visible proof.

## Scope (this PR)

1. Add an opt-in machine-readable readiness line to the existing provider CLI
   while preserving its no-argument standalone behavior.
2. Add bounded Tauri commands for entitlement status/install and for
   start/status/stop of one desktop-owned provider child.
3. Add a compact Local Connect section to the operator UI. It reports only
   stable entitlement/provider states and never blocks the standalone build
   form.
4. Extend Windows packaging acceptance to install the exact-head NSIS build,
   verify its bundled engine resource, launch the native app, and stop it
   cleanly on the ephemeral runner.

### Files touched

- `.github/workflows/generator-tests.yml`
- `README.md`
- `connect_provider.py`
- `lib/connect_v2.py`
- `desktop/src-tauri/Cargo.toml`
- `desktop/src-tauri/Cargo.lock`
- `desktop/src-tauri/src/lib.rs`
- `desktop/src/engine.ts`
- `desktop/src/main.ts`
- `desktop/src/styles.css`
- `plans/PR-Desktop-Connect-Lifecycle.md`
- `tests/test_connect_provider.py`

## Mechanism

- Entitlement status and install execute the packaged engine's existing
  `entitlement` subcommands. Rust never parses, copies, signs, or persists the
  license itself, and the selected source path is not returned to the UI.
- Provider start first requires the activation adapter to report `active`.
  It then launches the same executable with an explicit desktop-managed serve
  flag. The Python process emits exactly one compact readiness envelope only
  after its loopback listener and owner-private registration are live.
- Rust reads and accepts only the first bounded readiness line, without waiting
  for inherited packaged-process stdout handles to reach EOF, within a bounded
  60-second startup window sized for the three sequential Ollama preflight
  requests plus packaged executable startup. Early exit, a malformed or
  oversized first line, or timeout kills and reaps the child and reports a
  stable error. Python flushes that handshake without closing process stdout,
  then redirects later generator progress to a live sink for the provider
  lifetime. A second start is idempotent; a second provider process is never
  created.
- The child is recorded as starting before Rust waits for readiness and no
  provider mutex is held across that wait. Close/Stop can therefore signal or
  force-reap a slow preflight instead of waiting for the startup deadline.
- A monotonic start attempt, its active state, and the managed child share one
  lifecycle mutex. The native command reserves the attempt before scheduling
  its blocking worker. Stop or Close atomically invalidates that attempt before
  checking for a child, so a cancelled preflight cannot later spawn an
  untracked provider and retry cannot race past an incomplete stop. Failed
  startup cleanup is attempt-scoped and cannot stop a newer provider.
- Stop and normal window close kill and wait for only the child held by this
  application instance. The desktop does not discover or terminate a
  separately launched provider. If graceful shutdown times out, the desktop
  force-reaps its child and asks the packaged engine to remove only this app's
  registration carrying its private desktop-issued bearer. This remains exact
  when a packaged one-file bootloader and its Python worker have different
  process IDs; a replacement or a different provider registration is
  preserved. Terminated-child state is separate from pending registration
  cleanup state, so a failed cleanup remains bearer-bound and retryable from
  Stop, Status, or the next Start until reconciliation succeeds. The hidden
  cleanup command resolves only the owner-private discovery runtime; provider
  database/state availability cannot block dead-registration removal. It scans
  only canonical registration filenames and retries when one cannot be read,
  because an I/O failure cannot safely disprove bearer ownership. Window close
  is vetoed while reconciliation is failing, preserving the in-memory bearer
  and cleanup command for the next close attempt.
- Entitlement-status failure is reported independently from managed-process
  state, so it cannot hide a running child or remove the operator's Stop path.
- Standalone generation may disable activation and provider startup while it
  owns the model, but it cannot disable Stop for an already-running provider.
- A running provider does not disable entitlement replacement, so an
  issuer-signed renewal can take effect through the existing atomic adapter
  without interrupting Connect jobs.
- The UI exposes Stop while startup is pending. Stopping supersedes the
  in-flight start response so late success or failure cannot overwrite the
  authoritative stopped state.
- Window focus refreshes the managed child status, so an unexpected provider
  exit is reconciled before the operator next relies on the displayed state.
- The app never sends an OpenRouter setting or API key into Connect. Connect
  remains local-Ollama-only and still performs its own preflight.

## Intentional

- Local Connect is mandatory as a product capability but not a prerequisite
  for using the standalone Website Generator. An unavailable entitlement is a
  visible Connect state, not a generation failure.
- Activation uses a native file picker because entitlement acquisition and
  issuer operations remain outside this application.
- Lifecycle state is session-owned. The existing provider lock remains the
  cross-process authority if another standalone instance is already running.
- No auto-start is added. Starting a provider is an explicit operator action;
  the app does not unexpectedly reserve the model runtime or advertise a
  capability merely because its window opened.

## Deferred

- Entitlement purchase/issuance, account UI, updater, installer signing, and
  auto-start at login.
- Managing Ollama, downloading models, arbitrary provider discovery UI, job
  history UI, and consumer-specific workflow buttons.
- Connect cleanup/style hardening already tracked outside issue #38.

## Verification

- `python -m pytest -q`: 249 tests passed, 34 platform/fixture tests skipped,
  and 355 subtests passed. The provider lifecycle cases cover explicit managed
  readiness, stop/owner-EOF/invalid control input, and preservation of the
  no-command standalone mode.
- `python -m compileall -q build.py pipeline.py connect_provider.py lib tests`:
  passed.
- `npm test` from `desktop/`: 1 test file passed, 14 tests passed.
- `npm run build` from `desktop/`: TypeScript and Vite production build passed.
- `cargo fmt --check` from `desktop/src-tauri/`: passed.
- `cargo test` from `desktop/src-tauri/`: 25 tests passed. The lifecycle cases
  cover exact/bounded readiness without EOF, inactive entitlement, duplicate
  start, timeout and early-exit cleanup, cancellation before spawn and during
  the readiness wait, attempt-scoped cleanup that preserves a newer provider,
  graceful stop/reap, an ownership-matched registration cleanup after a forced
  fallback, retry after cleanup-command failure, and independent provider state
  when entitlement status is unavailable. The Windows run adds the process-tree
  cancellation regression.
- `cargo clippy --all-targets --all-features -- -D warnings` from
  `desktop/src-tauri/`: passed.
- `python connect_provider.py entitlement status`: returned the expected
  fail-closed source state `authority_unavailable` without starting Ollama or
  the provider.
- `./venv/bin/python build.py examples/prospect-plumber-template.json
  --skip-image-gen --skip-email-draft --skip-deploy`: completed through local
  Ollama with `qwen3-30b-a3b:latest` after one bounded admission correction.
- The prescribed unresolved-placeholder and fabricated-claim `grep` scans of
  `outputs/builds/drees-plumbing-inc/index.html` each printed `0`.
- `.github/workflows/generator-tests.yml`: parsed as valid YAML.
- The Windows package job builds the packaged engine and NSIS installer,
  installs the exact PR head on its ephemeral runner, verifies the installed
  bundled engine can report entitlement status, launches the installed GUI,
  and requests a clean close before using a bounded smoke-only fallback.

## Estimated diff size

The final patch contains 1,898 additions and 35 deletions across 12 files for
the provider readiness adapter, native lifecycle controller, compact UI
surface, tests, and Windows smoke step. The provider HTTP contract and
generation stack are not part of this diff.
