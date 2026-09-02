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
   destination directory, any newly created config ancestors, and existing
   lock/license as owner-private filesystem objects, and traverse every config
   path component without following symlinks. Apply created-directory modes
   through opened descriptors and sync both the child metadata and each new
   entry's parent. Re-evaluate at commit time and replace the fixed shared path
   using a synced same-directory temporary file and atomic rename.
4. Preserve the prior entitlement byte-for-byte on pre-replacement failures,
   and restore it (or remove a newly promoted candidate) when durability or
   installed-verification fails after replacement. Final verification reads
   through the pinned directory descriptor and confirms that the configured
   path still identifies that directory. Return stable ADR-0004 errors and
   never report activation success for those failures.
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
status check through that same descriptor while the lock remains held. Before
success, the installer also confirms the configured pathname still identifies
the opened directory by walking it again without following any component
symlinks. Missing config ancestors are created relative to pinned parent
descriptors, opened and identity-checked before descriptor-based mode changes,
and rejected under a non-sticky shared parent. Each created directory and the
parent containing its new entry are synced before traversal advances. This
prevents a restrictive process umask from leaving ancestors inaccessible
without reintroducing path redirection or losing the hierarchy after reported
success. The installer snapshots an existing license before promotion and
restores that snapshot—or removes the candidate when no license existed—if a
post-promotion check fails.

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
  - The suites passed separately after one combined-run teardown stall: 19
    activation boundary tests and 4 existing verifier/route tests passed after
    rollback, restrictive-umask, descriptor-based mode changes, parent syncing,
    no-follow traversal, path-identity, and byte-boundary alignment.
- `CONNECT_CONTRACTS_DIR=/home/juan-canfield/.cache/connect-contracts-c5405935 /home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m unittest discover -s tests -v`
  - 220 tests passed before the post-promotion rollback alignment; GitHub's
    required unit check reruns the complete suite at the published head.
- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python -m compileall -q build.py pipeline.py connect_provider.py lib tests`
  - Passed.
- `bash scripts/local_pr_review.sh`
  - Passed against `origin/main`.
- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python connect_provider.py entitlement status`
  - Returned `{"active":false,"state":"authority_unavailable"}` without model
    preflight, accurately reflecting the source build.
- `/home/juan-canfield/.cache/website-redesign-connect-provider-venv/bin/python build.py examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft --skip-deploy`
  - The pinned local Qwen fixture completed after its one bounded correction;
    no image, email, or deployment effect ran.
- Both required `grep` fabrication/placeholder scans returned `0` against
  `outputs/builds/drees-plumbing-inc/index.html`.
- vLLM was stopped after the fixture; the 3090 reported 460 MiB in use and the
  compute-process query returned no entries.

## Estimated diff size

Five files, approximately 1,010 additions and 4 deletions. About half is focused
boundary/failure-path coverage; the overage is intentional for the indivisible
activation security contract described above.
