# PR: Connect registration cleanup hardening

## Why this slice exists

Issue #32 identifies a POSIX cleanup boundary that can block or consume an
unbounded file. `remove_registration_if_owned()` reads the published path with
`Path.read_text()`, while `remove_registration_for_token()` performs a pathname
`lstat()` and then reopens the path with `Path.read_bytes()`. A same-user path
replacement can therefore substitute a symlink, FIFO, device, oversized file,
or different regular file between validation and use. Cleanup must treat those
objects as unowned without delaying release of the provider's listener, queue,
and locks.

The broken invariant is: registration cleanup may parse and unlink only the
same bounded regular file that it opened without following a final symlink.

## Scope (this PR)

1. Add one POSIX descriptor-based registration reader that opens nonblocking,
   does not follow the final symlink, bounds bytes before parsing, and verifies
   stable descriptor/path identity.
2. Route direct provider cleanup and desktop token-scan cleanup through the
   same admitted-byte path.
3. Treat non-regular, symlinked, oversized, disappeared, or replaced paths as
   unowned while retaining existing optional propagation for genuine I/O
   failures on a canonical regular registration.
4. Serialize external token cleanup on every platform with the same per-instance
   lock a live provider holds before publication, so stale cleanup cannot unlink
   a replacement owned by a restarted provider.
5. Add boundary tests for valid owned registration, symlink, FIFO/non-regular,
   oversized file, and replacement during validation, including the Windows
   pre-unlink and live-provider ownership boundaries.

### Files touched

- `lib/connect_v2.py`
- `tests/test_connect_provider.py`
- `tests/test_connect_windows.py`
- `plans/PR-Connect-Registration-Cleanup-Hardening.md`

## Mechanism

On POSIX, cleanup opens the registration's parent directory and then opens the
filename relative to that descriptor with `O_NOFOLLOW`, `O_NONBLOCK`, and
`O_CLOEXEC`. It admits only a regular file no larger than the existing
registration limit, reads at most that limit plus one byte, and compares the
opened descriptor before/after the read and against the still-visible pathname.
The parent-directory open preserves supported symlinked runtime-directory
overrides; only the final registration entry is no-follow. Only admitted bytes
reach JSON and token validation. Windows keeps its existing ACL-aware bounded
reader and repeats that bounded read immediately before unlink, requiring the
same registration bytes. External token cleanup on both platforms also acquires
the candidate's per-instance ownership lock before validation and holds it
through unlink. Since providers acquire that lock before publication and retain
it for their lifetime, stale cleanup skips a registration owned by a live
restart. POSIX stores this advisory lock inside the runtime directory so
symlinked aliases converge on the same lock inode; Windows retains its existing
private per-instance lock path.

## Intentional

- Unsafe filesystem objects are not errors and are never removed; cleanup
  treats them as registrations it does not own.
- The bearer token remains the ownership decision after filesystem admission.
- A real I/O failure on a stable regular file still propagates only when the
  existing `raise_on_io_error` contract requests it.
- The implementation does not claim to exclude another hostile process running
  as the same OS user; it prevents that process from turning cleanup into a
  blocking or unbounded read and rejects observed identity replacement.

## Deferred

- Generated inline-style value admission remains issue #33.
- Registration schema changes, cryptographic package identity, and protection
  from a hostile same-user process remain outside this slice.

## Verification

- The three pre-fix boundary probes failed on `origin/main`: cleanup followed
  and removed a final symlink, removed an oversized registration, and blocked
  while opening a FIFO.
- `python -m unittest -v tests.test_connect_provider.RegistrationTests` passed
  20 tests, including exact-size/max-plus-one, mixed valid/unsafe candidates,
  stable I/O failure propagation, replacement-before-unlink boundaries, and
  both cleanup paths through a symlinked runtime-directory override. A
  platform-neutral Windows-path probe proves changed registration bytes prevent
  unlink, another proves busy instance ownership prevents token cleanup, and a
  real POSIX handoff proves cleanup waits for provider ownership.
- `tests/test_connect_windows.py` extends the native Windows package gate to
  prove a held provider lock blocks cleanup, release permits cleanup, and the
  cleanup lock is itself released for the next provider. That exact platform
  result is pending GitHub's Windows job on the pushed head.
- With `CONNECT_CONTRACTS_DIR=/home/juan-canfield/Desktop/connect-contracts`,
  `python -m unittest -q tests.test_connect_provider` passed 76 tests on the
  current change.
- Before the review fixes, the same contract directory and
  `python -m unittest discover -s tests` passed 279 tests with 10
  native-Windows skips; the exact pushed head is covered by GitHub's unit and
  Windows jobs.
- `python -m compileall -q connect_provider.py lib tests` and
  `git diff --check` passed.
- The required no-effect local fixture used the already-installed
  `qwen3-30b-a3b:latest` through Ollama `0.24.0`; no model was loaded before the
  run. The first candidate failed closed on `Not a Franchise`, one bounded
  correction passed, and image generation, pitch-email drafting, and Vercel
  deployment were skipped.
- The admitted HTML remained 71,878 bytes with SHA-256
  `65f5dbe48d6cc53c9139df1a77255b4c5b8c302815bd7bb1019516ba62c5b641`.
  Current structural admission passed, and both required placeholder and
  fabricated-claim scans returned zero matches.
- Ollama returned `done_reason=unload`; `/api/ps` then reported no loaded models
  and `nvidia-smi` reported no compute process.
- `bash scripts/local_pr_review.sh` passed on the committed diff.

## Estimated diff size

The current diff contains 642 added lines and 71 removed lines across the reader,
ownership coordination, their boundary matrix, and this plan. This exceeds the
400-line soft target because the guard and its pass/fail, mixed-object,
numeric-boundary, blocking, and race
probes are one indivisible safety change; splitting the tests would publish an
unproved cleanup guard.
