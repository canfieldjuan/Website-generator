# Arbitrary business types and source-owned services

## Why this slice exists

The desktop intake treats `trade` as a closed plumber/HVAC/electrician enum even
though the build backend accepts any non-empty string. That forces an operator
building a cleaning site to submit false HVAC data. The prompt then fills absent
hours, service radius, and service names from trade defaults while the admission
boundary correctly rejects unsupported location claims. The fixed six-card
service scaffold also makes a five-service brief depend on invented catalog
entries. The result is a structurally valid brief that cannot reliably produce
an admissible website.

The governing invariant is that customer-specific facts and offered services
come from the prospect document. Industry guidance may shape presentation and
generic explanatory copy, but it may not create operational facts or offerings.

This slice exceeds the 400-line soft budget because that invariant must hold at
intake, prompt/scaffold construction, and final HTML admission together. A split
would temporarily ship either an arbitrary-business form that still fails
generation or generation that can silently change the submitted service list.
Most added lines are focused regressions and required fixtures for the newly
mandatory `services` field; unrelated cleanup remains excluded.

## Scope (this PR)

1. Accept any non-empty business type in desktop intake and JSON import while
   retaining the existing `trade` key and known-trade suggestions.
2. Require at least one prospect-supplied service and render exactly the supplied
   service list without padding or silent omission.
3. Give body generation only universal source-gating guidance. Preserve known
   trade styling through the existing deterministic theme, palette, and hero
   selectors rather than exposing mixed-authority trade prose to the model.
4. Remove unsourced hours, emergency availability, service-radius, and canonical
   service fallback instructions from generation context.
5. Add deterministic regressions for arbitrary business types, variable service
   counts, universal-only generation guidance, unsupported location rejection,
   and the EOM cleaning brief.

### Files touched

- `desktop/src/main.ts`
- `desktop/src/state.ts`
- `desktop/src/state.test.ts`
- `build.py`
- `lib/generation.py`
- `references/06-build-prompt.md`
- `references/07-industry-defaults.md`
- `tests/test_generation.py`
- `tests/test_connect_provider.py`

## Mechanism

The Trade select becomes a required Business type text input backed by a
`datalist` of the three existing suggestions. State import accepts any trimmed,
non-empty string instead of enforcing a TypeScript union.

`prepare_prospect()` validates and normalizes a non-empty list of non-empty
service strings. The required class-count and child-sequence contracts derive
their service-card count from that normalized list, and the response scaffold
contains one tokenized card per submitted service. The prompt requires every
card name to correspond to the supplied list and forbids adding or dropping
entries. The shared HTML admission API gains an optional exact-services
contract and verifies the direct name owned by each service card, so prompt
noncompliance cannot add, omit, or duplicate an offered service.

Industry-guidance prompt assembly extracts only the universal preamble. The
trade sections remain inputs to deterministic code-owned visual selection, but
their mixed operational assumptions do not enter body generation. Universal
benefit fallbacks describe source facts or page functions rather than assuming
ownership, crew, dispatch, availability, or franchise status. Verified prospect
fields remain the only authority for customer facts.

## Intentional

- Keep the JSON field named `trade` for compatibility with existing files and
  integrations.
- Keep existing known-trade theme, palette, and hero behavior.
- Require the operator to provide services rather than guessing what a business
  offers.
- Preserve strict generated-output admission, including unsupported-location
  rejection.
- Keep the exact-services admission argument optional so unrelated redesign and
  generic assembly callers retain their existing behavior.

## Deferred

- A structured, safe admission-error explanation in the desktop UI is a separate
  operability slice.
- A cleaning-specific content/style profile is unnecessary for generic website
  generation and is not introduced here.
- Provider/model behavior, Ollama scheduling, OpenRouter live billing checks,
  redesign/extraction, Connect, packaging, deployment, email, and image
  generation do not change.

## Verification

Final working-tree evidence is based on commit
`758626d2df23865449f41b5b185a19cd79fd847b` with only the files listed in
this plan modified. The generated artifact is ignored output, not a source
change.

Commands and results:

```bash
npm --prefix desktop test
# 1 test file passed; 16 tests passed

npm --prefix desktop run build
# TypeScript check and Vite production build passed

python3 -m pytest -q
# 370 passed, 34 skipped, 647 subtests passed

PYTHONUNBUFFERED=1 GENERATION_TIMEOUT_SECONDS=1800 \
  python3 build.py examples/prospect-plumber-template.json \
  --skip-image-gen --skip-email-draft --skip-deploy
# Exit 0; local:qwen3-30b-a3b:latest; no deploy, email, or image generation
```

The final fixture invocation rejected one unsupported service-location claim,
used the existing single bounded correction, and then wrote
`outputs/builds/drees-plumbing-inc/index.html` at
`2026-09-06 15:05:46.720175865 -0500`. The artifact is 72,516 bytes with
SHA-256 `917e7a7837700f3949eeed7bc83cd3ec91efaa0a8ff3577530f9116514110b3d`.
Both the required placeholder pattern and the case-insensitive forbidden-claim
pattern returned zero matches. A headless Chrome render wrote
`/tmp/website-generator-drees-slice1-final.png` (346,749 bytes), and visual
inspection confirmed a rendered hero, verified contact/service-area content,
and the source service-card grid.

The production-shaped desktop request used the EOM form values, the local
provider, and the real `execute_desktop_request()` path. It returned an admitted
`effingham-office-maids-homepage.html` artifact of 69,145 bytes with SHA-256
`5ada2e34e9fb43e8cad38a18c2f3302e08db1f3be6f97497d732bbcb9efb78b8`.
Before the shared location-boundary correction, that same request was rejected
because the city/state scanner parsed adjacent UI text such as `Serving` as part
of the city. The focused regression now passes together with 14 negative/edge
subtests, including unsupported `Springfield, IL`.

No live OpenRouter request was made; doing so would spend provider credit and
is unnecessary to prove the provider-independent prompt and admission contract.
After the implementation commit, `bash scripts/local_pr_review.sh` passed its
diff-check and plan-presence gates against merge base
`758626d2df23865449f41b5b185a19cd79fd847b`. The bundle is rerun after this
verification note is committed so its clean-worktree evidence applies to the
final revision.

## Estimated diff size

The tracked implementation/test diff is 485 changed lines before this plan is
counted, exceeding the 400-line soft target. It remains one indivisible
source-authority slice: intake must accept the business type and services,
generation must consume exactly those services without trade-profile facts,
and admission must reject any service-list drift. Splitting any one boundary
would temporarily ship a form that still cannot produce an admissible website.
The location correction is the reproduced blocker on that exact path, not a
general validator cleanup. Unrelated provider, runtime, redesign, Connect, and
UI error-reporting work remains excluded.
