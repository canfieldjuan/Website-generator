# PR plan: Connect entitlement activation

## Why this slice exists

The Website Redesign provider enforces the signed `entitlement-v1` decision on
every Local Connect route, but the application has no local operation that can
report that decision or install an acquired entitlement. A user therefore
cannot complete the accepted ADR-0004 activation flow from this application;
manual placement would omit the contract's admission, locking, permissions,
and atomicity requirements. This closes the application-local implementation
portion of issue #27 without weakening the provider gate.

This slice exceeds the repository's 400-line soft cap because activation is a
single security and data-integrity boundary: source admission, cross-app
serialization, atomic persistence, local command dispatch, and the tests that
prove both sides must land together. Splitting out the tests or publishing only
part of the installer would leave an unproved or unusable activation path.

## Scope (this PR)

1. Expose a status operation that evaluates the existing shared verifier and
   returns only its stable state plus an `active` boolean.
2. Expose an install operation that reads a user-selected regular source file
   without following its final symlink, bounds the read, and admits only a
   currently active entitlement under the existing compiled authority.
3. Serialize installers on the contract-owned persistent lock, validate the
   destination directory and existing lock/license as owner-private regular
   filesystem objects, re-evaluate at commit time, and replace the fixed shared
   path using a synced same-directory temporary file and atomic rename.
4. Preserve the prior entitlement byte-for-byte on pre-replacement failures;
   return stable ADR-0004 errors and never report success after durability or
   installed-verification failures.
5. Route status/install through the trusted local CLI before generation
   preflight so neither command needs vLLM or starts the provider.
6. Add boundary tests and operator documentation.

### Files touched

- `lib/connect_entitlement.py`
- `connect_provider.py`
- `tests/test_entitlement_activation.py`
- `README.md`
- `plans/PR-Connect-Entitlement-Activation.md`

## Mechanism

The existing `EntitlementGate` remains the only signature and claim verifier.
The installer reads a fixed-size snapshot from a no-follow regular-file
descriptor and checks it once before filesystem mutation and again after
acquiring `$XDG_CONFIG_HOME/local-connect/.entitlement-v1.lock`. All destination
operations use an opened owner-private directory descriptor. The exact source
bytes go to an exclusive `0600` temporary file, are flushed and synced, replace
only `entitlement-v1.json`, and are followed by a directory sync and installed
status check while the lock remains held.

`python connect_provider.py entitlement status` emits the privacy-bounded state
document. `python connect_provider.py entitlement install PATH` emits that same
document on success or a stable structured error on failure. Dispatch occurs
before runtime-directory resolution and local-model preflight.

## Intentional

- Source checkouts remain `authority_unavailable`; no runtime key override or
  test authority is added.
- Inactive status is a successful status query with `active: false`, not a CLI
  execution failure.
- The first implementation targets Unix because the accepted activation
  contract specifies Unix ownership, no-follow descriptors, `flock`, and
  directory syncing.
- The wire API is unchanged: activation commands are app-local operations, not
  Connect routes.
- Existing unsafe license and lock paths fail closed instead of being repaired
  or overwritten implicitly.

## Deferred

- Issue #27 still owns official Ed25519 public-keyring packaging and an active
  issuer-signed production license. No production activation claim is made
  until both are provisioned and exercised.
- Billing, account UI, renewal, revocation, device binding, non-Unix placement,
  and private issuer-key custody remain outside this slice.
- Generation, provider/model selection, Connect manifests/jobs/authentication,
  image generation, email, and deployment behavior are unchanged.

## Verification

- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935 /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m unittest tests.test_entitlement_activation tests.test_connect_provider.EntitlementTests`
  - 16 tests passed after the final installer resource-ordering change.
- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935 /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m unittest discover -s tests -v`
  - 220 tests passed at the committed implementation head.
- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m compileall -q build.py pipeline.py connect_provider.py lib tests`
  - Passed.
- `bash scripts/local_pr_review.sh`
  - Passed against `origin/main`.
- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python connect_provider.py entitlement status`
  - Returned `{"active":false,"state":"authority_unavailable"}` without model
    preflight, accurately reflecting the source build.

## Estimated diff size

Five files, approximately 820 additions and 4 deletions. About half is focused
boundary/failure-path coverage; the overage is intentional for the indivisible
activation security contract described above.
