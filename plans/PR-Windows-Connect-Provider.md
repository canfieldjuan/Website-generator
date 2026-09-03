# PR: Windows Local Connect provider package

## Why this slice exists

The release builder can only produce a usable Linux provider. On Windows the
runtime imports `fcntl` unconditionally, requires XDG paths, rejects entitlement
storage and reads outside POSIX, applies Unix modes, and looks for a suffixless
PyInstaller output. A Windows build host alone therefore produces no usable
Connect provider.

The root cause is that platform-specific storage, locking, and executable naming
are embedded in otherwise platform-neutral provider and entitlement code.

This exceeds the repository's 400-line target because a Windows executable that
cannot safely authorize, persist durable jobs, publish discovery, and run the
same native boundary tests is not a usable vertical slice. Splitting the
filesystem adapter, SQLite admission, entitlement path, provider wiring, or
package proof would intentionally publish an executable with a missing
load-bearing runtime stage.

## Scope (this PR)

1. Add a small Windows filesystem adapter for Local AppData roots, effective
   DACL and reparse-point refusal, bounded regular-file reads, atomic
   replacement with bounded sharing-violation retry, and non-blocking process
   locks over byte offset `0`, length `1`.
2. Use the accepted Windows Connect paths for runtime registration,
   application-private state, and the shared entitlement while preserving all
   existing Linux paths and checks.
3. Make provider ownership, registration publication/cleanup, and entitlement
   status/install work on Windows without changing the HTTP or JSON contracts;
   admit the SQLite database plus journal/WAL/SHM files against the same private
   file and ancestor boundary.
4. Make the PyInstaller release builder locate and publish the platform's real
   executable name.
5. Add native-Windows tests and a Windows package job that builds the official
   public authority into the executable and proves packaged status execution.
6. Document the Windows package and its local model-runtime requirement.

### Files touched

- `.github/workflows/generator-tests.yml`
- `README.md`
- `connect_provider.py`
- `lib/connect_entitlement.py`
- `lib/connect_store.py`
- `lib/connect_v2.py`
- `lib/connect_windows.py`
- `scripts/build_connect_provider.py`
- `tests/test_connect_release_build.py`
- `tests/test_connect_windows.py`
- `plans/PR-Windows-Connect-Provider.md`

## Mechanism

Windows derives shared Connect files from `%LOCALAPPDATA%\LocalConnect` and
private Website Redesign state from `%LOCALAPPDATA%\website-redesign\state`.
The adapter admits only absolute per-user roots, establishes a protected
current-user/SYSTEM/Administrators DACL on each newly created directory,
verifies the owner and effective DACL on every trusted root/descendant, rejects broad content or mutation grants,
Connect-owned reparse points, and non-regular files, accepts OWNER RIGHTS only
as the already-validated owner, bounds every read, writes through a flushed
same-directory temporary file, retries transient Windows sharing violations for
a bounded interval, publishes one fixed path per durable v2 provider instance,
validates existing and newly-created SQLite state files, and uses `msvcrt`
byte-range locks for cross-process exclusion. Linux continues through the
existing descriptor, ownership, mode, `flock`, and directory-`fsync` paths.

The release builder chooses `.exe` only on Windows. CI builds on a native
Windows runner because PyInstaller is not a cross-compiler, then executes the
packaged entitlement status adapter. The local VM supplies the final package
and cross-app acceptance host.

## Intentional

- The provider remains exact-loopback HTTP with the same rotating bearer token,
  capability, routes, payloads, durable job identity, and generation output.
- The bundled authority remains the public production keyring; no private key
  or entitlement is committed or uploaded by CI.
- Connect still requires the pinned local model through an OpenAI-compatible
  loopback vLLM endpoint.
- Missing or unsafe Windows storage fails Connect closed; it does not disable
  standalone generation.

## Deferred

- Email Watcher discovery and cross-app Windows acceptance are the next slice.
- Named pipes, a broker, auto-launch, installer UI, code signing, auto-update,
  remote inference, OpenRouter fallback for Connect, and macOS packaging.
- General portal/UI work and unrelated generation behavior.

## Verification

- `CONNECT_CONTRACTS_DIR=../connect-contracts python -m unittest -v
  tests.test_connect_provider tests.test_entitlement_activation` passed all 76
  focused provider and entitlement tests.
- `python -m unittest -v tests.test_connect_windows
  tests.test_connect_release_build` passed the release-builder checks on Linux;
  the eight native-Windows storage tests skipped as designed.
- `python -m compileall -q connect_provider.py lib tests
  scripts/build_connect_provider.py` passed.
- A real local vLLM fixture build completed with the already-local
  `Qwen3-30B-A3B-Instruct-2507` GGUF, and both required placeholder/fabrication
  scans returned zero. This proves the unchanged generator admission path
  without substituting OpenRouter or LM Studio; Qwen3.8 remains the product
  target.
- The same platform-relevant tests on native Windows.
- Native replacement after a short-lived reader releases its handle, plus
  crash/restart publication to the same durable registration path.
- Native PyInstaller build using the committed production public keyring.
- Packaged `entitlement status` before activation and packaged status/install
  with a production-signed entitlement on the local Windows VM.
- Provider registration, authentication, and one deterministic packaged job on
  the local Windows VM; actual model quality remains covered by the existing
  Linux real-generation acceptance.

## Estimated diff size

11 files, 1,403 additions, 20 deletions. The Windows storage adapter, provider
wiring, entitlement lifecycle, state admission, and native package proof are one
vertical slice: splitting them would knowingly publish an executable that
cannot authorize, persist, or advertise its capability.
