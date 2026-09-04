# Desktop operator UI

## Why this slice exists

Issue #38 now has a bounded engine contract, but the Website Generator still
requires an operator to understand JSON, terminals, and output paths. The root
problem is not missing styling; it is the absence of a native workflow that
collects known business facts, invokes the one canonical admitted-generation
path, isolates untrusted generated HTML, and saves the exact admitted artifact.

A correct fix must add a Windows-oriented Tauri 2 host, a human-first form with
lossless JSON import/export, an explicit local-Ollama/OpenRouter session choice,
child-process lifecycle control, a sandboxed preview, and native save dialogs.
It must call the existing `desktop` protocol rather than import Python logic or
create another generation implementation.

This work must not change `build.py`, the HTML admission rules, Local Connect's
HTTP contract or entitlement behavior, deployment, image generation, pitch
email generation, model installation/daemon management, billing, or generated
website semantics.

This vertical slice exceeds the repository's 400-line soft target because the
native host, operator workflow, sandboxed preview, and installable Windows
package must land together to prove one usable path. The measured review
surface is approximately 9,500 added text lines across 76 paths, including two
generated dependency lockfiles and 50 binary icon assets; excluding the
lockfiles leaves approximately 3,000 added text lines. Splitting the native
process boundary or installer from the UI would leave a visual mock rather than
the end-to-end operator slice. The Local Connect lifecycle remains separate.

### Design contract

Subject: a small-business operator's drafting desk. Audience: an operator who
knows the customer but should not need to know the schema. Single job: turn
verified prospect facts into one reviewable, savable website.

- Palette: blueprint ink `#102A33`, cool paper `#F4F7F8`, clean sheet
  `#FCFEFE`, surveyor orange `#F26B38`, status teal `#167C80`, graphite
  `#4C5B61`.
- Type: Bahnschrift/Arial Narrow for compact display labels, Segoe UI Variable
  for working text, and Consolas for machine-facing model or file details. All
  are offline system stacks; the desktop must not fetch fonts.
- Layout: a narrow build-progress rail, a fact sheet, and the generated page
  preview. On narrow windows the fact sheet and preview become explicit tabs;
  controls must never depend on horizontal scrolling.
- Signature: a real four-stage build line -- Facts, Generate, Review, Save --
  whose state reflects the artifact lifecycle rather than acting as decoration.
- Motion: one restrained progress sweep during generation; respect reduced
  motion and use no ambient animation.

The common cream/serif landing-page aesthetic was rejected because this is an
operator tool, not one of the sites it produces. The drafting-desk vocabulary,
condensed labels, and restrained orange registration marks belong to the work
being done without competing with the customer preview.

## Scope (this PR)

1. Scaffold a Tauri 2 application under `desktop/` using plain TypeScript and
   CSS with no frontend framework.
2. Capture required prospect facts and useful optional contact/services fields;
   import and export the full prospect JSON without discarding unknown fields.
3. Default to local Ollama while allowing an explicit OpenRouter model and API
   key for the current in-memory session only.
4. Invoke `website-redesign-connect desktop` through a Rust-owned child process,
   enforce one active generation, bound stdin/stdout, support cancellation, and
   surface stable engine errors.
5. Decode the admitted HTML artifact, render it only in a sandboxed preview,
   and save those exact bytes through a native dialog.
6. Produce and exercise the native Windows installer using the existing Windows
   packaging host and approved public entitlement keyring.

### Files touched

- `desktop/package.json`, TypeScript configuration, and Vite configuration
- `desktop/src/*`
- `desktop/src-tauri/*`
- `.github/workflows/generator-tests.yml`
- `README.md`
- `plans/PR-Desktop-Operator-UI.md`

## Mechanism

The frontend maintains one in-memory prospect document and an explicit set of
known controls the operator has edited. Only those fields are projected back
before validation, generation, or export, preserving exact untouched known
representations and every unknown imported key even when browser controls
normalize their displayed values. Provider credentials live only in JavaScript
memory, are sent inside the private Tauri IPC request, and are cleared when the
provider changes or the window closes.

Rust owns all filesystem and process effects. Import/export/save commands open
native dialogs, cap reads on the opened file handle, and atomically replace
saved UTF-8/HTML payloads only after a same-directory temporary file is synced.
The generation command
launches the packaged engine with the `desktop` subcommand, writes exactly one
JSON request to stdin, closes stdin, reads bounded stdout/stderr, and accepts
only the versioned response envelope. A shared application-state slot rejects a
second generation and lets cancellation terminate the current child. Debug
builds locate the source checkout and Python entry point; packaged builds use
the bundled engine executable.

The preview receives a Blob URL generated from admitted bytes and uses an iframe
with an empty `sandbox` token set. Generated scripts therefore cannot execute,
navigate the app, submit forms, or inherit the desktop origin. Replacing or
closing a preview revokes its prior Blob URL.

## Intentional

- The form covers the fields an operator can reasonably enter by hand; JSON
  remains the lossless handoff for richer or future schema fields.
- Trade stays limited to the three values already supported by the build
  contract. This UI does not pretend arbitrary trade schemas are accepted.
- Local generation is the default. OpenRouter is an explicit per-session
  choice, never a fallback, and its key is never stored.
- Preview controls do not edit generated HTML. Regeneration is the only path to
  a different artifact, preserving the admitted output as source of truth.
- Installer code signing and an auto-updater are not prerequisites for a local
  Windows acceptance build.

## Deferred

- Email/spec-sheet ingestion and Document Summarizer handoff.
- Deployment, domain setup, image generation, pitch email, and website editing.
- Persistent OpenRouter credentials, model download/daemon management, billing,
  updater, installer signing, macOS/Linux distribution, and telemetry.
- Built-in entitlement activation and managed Local Connect lifecycle; those are
  issue #38 slice 3.

## Verification

- `npm test` from `desktop/`: 1 test file passed, 10 tests passed.
- `npm run build` from `desktop/`: TypeScript and Vite production build passed.
- `cargo test` from `desktop/src-tauri/`: 11 tests passed. The boundary tests
  include cancellation before child registration and reject nested numeric
  tokens that cannot survive the JavaScript round trip exactly during import,
  duplicate keys at the root or nested inside arrays/objects, and imports whose
  canonical export would exceed the admitted size. They also prove bounded
  file reads and atomic replacement of an existing saved artifact. The Windows
  run adds a twelfth process-tree regression proving cancellation also
  terminates a spawned descendant.
- `cargo clippy --all-targets --all-features -- -D warnings` from
  `desktop/src-tauri/`: passed with no warnings.
- `cargo build` from `desktop/src-tauri/`: native debug build passed.
- `xvfb-run -a timeout 3s desktop/src-tauri/target/debug/website-generator`:
  the native app remained running for the smoke window and emitted no stderr.
- Direct `generation.status` desktop-protocol probe with the UI's local payload:
  returned available for provider `local`, model `qwen3-30b-a3b:latest`, and
  the loopback Ollama base URL.
- Canonical plumber fixture build completed through local Ollama with
  `qwen3-30b-a3b:latest`; the required unresolved-placeholder and fabricated-
  claim scans each returned `0` matches.
- Desktop and mobile viewport screenshots: inspected with no horizontal cutoff.
- `bash scripts/local_pr_review.sh`: passed.
- `.github/workflows/generator-tests.yml`: parsed as valid YAML. The
  `windows-connect-package` job supplies the native Windows engine and NSIS
  package proof on the PR head; it is not represented as local VM proof.

## Estimated diff size

Approximately 9,500 added text lines across 76 paths, dominated by generated
dependency lockfiles and binary application-icon assets. Excluding the two
lockfiles leaves approximately 3,000 added text lines of configuration,
documentation, native host, operator UI, and tests.
