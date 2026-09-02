# PR plan: Connect entitlement activation

## Problem-derived contract

### Root cause

The Website Redesign provider enforces the signed `entitlement-v1` decision on
every Local Connect route, but the application has no local operation that can
report that decision or install an acquired entitlement. A user therefore
cannot complete the accepted activation flow from this application; manually
placing the shared file would bypass the activation contract's admission,
locking, permissions, and atomicity requirements. The missing behavior is the
application-local activation boundary, not the provider route gate or the
generation pipeline.

### Correct fix

1. Expose a status operation that evaluates the existing shared verifier and
   returns only its stable state plus an `active` boolean.
2. Expose an install operation that reads a user-selected regular source file
   without following its final symlink, bounds the read, and admits only a
   currently active entitlement under the existing compiled authority.
3. Serialize all participating installers with the contract-owned persistent
   lock, validate the destination directory and any existing lock/license as
   owner-private regular filesystem objects, re-evaluate at commit time, and
   replace the fixed shared entitlement path using a synced same-directory
   temporary file and atomic rename.
4. Preserve the prior entitlement byte-for-byte on all failures before the
   atomic replacement; never claim success after a durability or installed
   verification failure. Return the contract's stable activation error codes.
5. Make these operations reachable through the application's trusted local CLI
   adapter without requiring vLLM or starting the Connect HTTP provider.
6. Add boundary tests for status privacy, missing authority, source type and
   size, invalid and inactive candidates, destination safety, lock contention,
   atomic replacement, unchanged-on-failure behavior, exact-byte installation,
   and immediate visibility to the existing route gate.
7. Document activation and the remaining release requirement for an official
   public keyring and issuer-signed license.

### Must not change

- Do not weaken, bypass, cache, or move the entitlement check on `/v2/manifest`,
  `POST /v2/jobs`, or `GET /v2/jobs/{job_id}`.
- Do not change Local Connect manifests, job/artifact schemas, authentication,
  registration, durable job semantics, or capability identity.
- Do not change JSON-to-HTML generation, provider/model selection, output
  validation, standalone build behavior, image/email/deployment behavior, or
  start vLLM during activation.
- Do not create a signing authority, commit any private key, promote test keys,
  add billing/account flows, or make the public keyring runtime-overridable.
- Do not add a second entitlement format or persistence location. The shared
  ADR-0003 path and existing verifier remain authoritative.
- Do not claim production activation is complete until an official packaged
  public keyring and active issuer-signed license are provisioned under issue
  #27.

## Verification contract

- Focused activation and provider-route tests pass against the pinned canonical
  entitlement fixtures.
- The repository's documented local review and unit commands pass.
- A cold diff audit maps every changed line to this contract and reports any
  unmet requirement, out-of-scope change, or touched protected behavior before
  completion.
