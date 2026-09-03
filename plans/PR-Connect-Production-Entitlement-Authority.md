# PR: Connect production entitlement authority

## Why this slice exists

The Website Redesign provider already fails closed on every Connect route when
it lacks an active entitlement. Its installation gate, however, only trusts a
keyring embedded in a frozen package and the repository has no release build
that supplies that resource. Therefore source and current release workflows
cannot establish production authority, even when a correctly signed license
exists.

The root cause is the absent build-time trust anchor, not the route gate or the
activation installer. This slice packages the accepted public authority and
proves the existing gate with a real production-signed entitlement.

## Scope (this PR)

1. Add a reproducible PyInstaller release entry point for
   `connect_provider.py`.
2. Require a build-owned entitlement keyring, validate its bounded strict
   shape, reject empty/test authority, and embed it at
   `website_redesign_data/connect-entitlement-keyring.json`.
3. Keep source execution fail-closed; no runtime environment variable may
   replace the packaged authority.
4. Add boundary tests proving missing, malformed, empty, test-shaped, and valid
   release keyrings reach the correct build decision.
5. Build the official executable, install one active production-signed
   `connect.capability_exchange` entitlement through the existing CLI, and
   exercise the packaged deny/allow paths including one real JSON-to-HTML job.

### Files touched

- `.gitignore`
- `requirements-release.txt`
- `scripts/__init__.py`
- `scripts/build_connect_provider.py`
- `tests/test_connect_release_build.py`
- `README.md`
- `plans/PR-Connect-Production-Entitlement-Authority.md`

## Mechanism

The release builder accepts the keyring only through the build process, parses
it with duplicate-key rejection and exact field admission, validates Ed25519
key sizes and production key IDs, then invokes PyInstaller with a fixed data
destination. At runtime the existing verifier continues to read only
`sys._MEIPASS/website_redesign_data/connect-entitlement-keyring.json`; source
runs and packages built without authority remain unavailable.

The resulting executable uses the existing `entitlement status` and
`entitlement install` commands. Acceptance uses isolated XDG directories for
negative cases so it does not mutate the active license while probing failures.

## Intentional

- The public key is not a secret; the private key never enters this repository
  or the package.
- Production authority is supplied at build time, following the established
  Document Summarizer pattern.
- PyInstaller is release-only and does not change normal development or source
  execution.
- Existing entitlement routes, response codes, activation semantics, model
  selection, and generated output remain unchanged.

## Deferred

- Windows/macOS packaging, a general installer, code signing, auto-update, and
  release publishing remain deferred.
- Billing, renewal, revocation, device binding, and account UI remain deferred.
- Email Watcher and Document Summarizer packaging are unchanged.

## Verification

- `python3 -m unittest tests.test_connect_release_build`
- `CONNECT_CONTRACTS_DIR=<current-contracts> python3 -m unittest tests.test_entitlement_activation tests.test_connect_provider.EntitlementTests`
- `CONNECT_CONTRACTS_DIR=<current-contracts> python3 -m unittest`
- `python3 -m ruff check scripts/build_connect_provider.py scripts/__init__.py tests/test_connect_release_build.py`
- `python3 -m ruff format --check scripts/build_connect_provider.py scripts/__init__.py tests/test_connect_release_build.py`
- `bash scripts/local_pr_review.sh`
- Build the frozen executable with the production public keyring.
- Run packaged status/install and the isolated deny-state route matrix.
- Run one authenticated packaged Connect JSON-to-HTML job against local vLLM
  with deployment, email, and image generation disabled.

Results so far:

- The focused activation, route-gate, and release-builder suite passed 28
  tests.
- The complete Website Generator suite passed 232 tests.
- Ruff lint and format checks passed for all new Python files.
- PyInstaller 6.22.2 produced `dist/website-redesign-connect` with the
  production public keyring.
- Packaged `entitlement status` reported `missing` before activation and
  `active` after installing the production-signed license. The source command
  continued to report `authority_unavailable`.
- Isolated packaged probes confirmed missing, malformed, expired,
  not-yet-valid, missing-feature, unknown-key, and bad-signature licenses each
  denied all three Connect routes with `CONNECT_ENTITLEMENT_REQUIRED`.
- The active production entitlement allowed the authenticated packaged
  manifest route.
- The production entitlement was installed through the packaged activation
  command for the current user.
- The final real packaged JSON-to-HTML job remains pending because the currently
  running unrelated vLLM process serves a different alias and is actively using
  the RTX 3090; it was not interrupted by this slice.

## Estimated diff size

Approximately 505 added lines across the release builder, boundary tests,
plan, and documentation. This exceeds the normal soft target only if the
package-boundary tests and acceptance record require it; no generation or
provider refactor is included.
