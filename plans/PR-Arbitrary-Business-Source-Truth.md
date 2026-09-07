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
6. Make each service card's visible name case-exact and its description
   deterministic from that same source service, so free model prose cannot add
   an unsupported offering.
7. Bring checked-in runnable prospects across the new required-services
   boundary using only evidence already present in each fixture.
8. Remove free-form factual authority from every visible body surface. The
   model may arrange the admitted page components, but each visible text
   fragment must be either exact prospect evidence or finite code-owned page
   copy. Pin the hero, benefits, form-trust line, and footer tagline to exact
   code-owned owners so an unsupported offering cannot move outside the
   service cards and bypass admission.

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
- `examples/althoff-plumbing-effingham.json`
- `examples/olney-heating-air-conditioning.json`

## Mechanism

The Trade select becomes a required Business type text input backed by a
`datalist` of the three existing suggestions. State import accepts any trimmed,
non-empty string instead of enforcing a TypeScript union.

`prepare_prospect()` validates and canonicalizes a non-empty list of non-empty
service strings with Unicode compatibility and browser-whitespace normalization
before duplicate detection. Intake also caps the one-page surface at 12 services,
80 characters per service, and 600 characters total so every accepted list is
representable inside the fixed generation-output budget. The required class-count and child-sequence contracts derive
their service-card count from that normalized list, and the response scaffold
contains one code-owned card per submitted service. Each card uses the exact
source casing and a deterministic `Ask us about <service>` description. The
prompt requires the scaffold verbatim. The shared HTML admission API gains an
optional exact-services contract and verifies both direct fields, so prompt
noncompliance cannot add, omit, duplicate, rename, or smuggle another offering
through free description prose.

Industry-guidance prompt assembly extracts only the universal preamble. The
trade sections remain inputs to deterministic code-owned visual selection, but
their mixed operational assumptions do not enter body generation. Universal
benefit fallbacks describe source facts or page functions rather than assuming
ownership, crew, dispatch, availability, or franchise status. Verified prospect
fields remain the only authority for customer facts.

The two checked-in prospects that previously depended on canonical trade
defaults receive only services evidenced in their own documents: Althoff's
review records sanitary lift-pump replacement, while Olney's verified business
name directly supplies Heating and Air Conditioning. Their comments no longer
claim that an empty list triggers defaults.

The build path also supplies one visible-copy admission contract. It contains
only exact prospect fields, exact source reviews and promises, exact service
names/descriptions, and a finite set of code-owned interface strings. The
validator checks every rendered or accessibility-exposed text fragment against
that contract and separately pins the free-copy owner classes to their exact
expected values. This is the shared authority boundary for hero, benefit,
footer, and any other body surface; it does not attempt to recognize offerings
by enumerating English predicates. `aria-hidden` removes content from the
accessibility tree but does not visually hide it, so it never exempts rendered
copy from this admission boundary. Direct attributes, rendered input values,
and all four supported indirect ARIA reference attributes use the same resolver
and exact catalog. Native control labels and the complete standard set of
text-valued ARIA properties come from one shared enumerator used by claim and
copy admission, including the standards-defined table-header abbreviation.
Ordinary native input values use the same source-owned catalog. Generated
numeric range widgets and ARIA value semantics fail closed because the build
has no generic source contract that can bind their related label/current/min/max
meaning; canonical review-score components remain governed by the existing
review evidence contract.
The same admission pass validates complete inline runs at HTML text owners and
complete accessible names/descriptions at interactive or ARIA-owned elements,
so separately allowed source fragments cannot be recombined into a new claim.
It derives text-composing classes from the trusted template CSS and validates
anonymous child runs at those layout owners as complete phrases. Native action
owners, list items, exact required-text owners, and separately validated
service, benefit, review, and footer-address components remain independent, so
the guard rejects layout-created claims without joining unrelated controls,
cards, list entries, or source-bound footer fields. CTA accessible names admit
only the finite badge-and-phone combinations supported by verified 24/7 or
same-day evidence, in either meaning-preserving visual order.
Native table rows enter that same composition pass even without a CSS class, so
adjacent cells cannot rebuild an unsupported phrase. Five-star glyphs have no
global copy authority: they are admitted only inside review roots or ambient
star components already bound to the verified review score by the review
contract.
Ordered-list markers also fail closed because their browser-generated copy has
no source-bound owner in this page contract. Finite source-backed compositions,
such as the verified phone beside verified 24/7 status, are admitted explicitly.
The no-radius service-area prompt uses the same exact `Service Area` casing as
the code-owned catalog.

## Latest review finding ledger

| Finding/thread | Affected invariant | Current reproduction | Disposition | Proof |
| --- | --- | --- | --- | --- |
| `PRRT_kwDOTDYaKM6fwRBN` | Layout styling must not recombine separately admitted fragments into a new offering. | `dual-cta-row` with adjacent `div` or `p` owners containing `Roof` and `Repair`. | fixed/superseded | `test_build_generator_rejects_copy_composed_by_layout_class` rejects both boundary forms while admitting native list items. |
| `PRRT_kwDOTDYaKM6fwRBO` | Complete source-backed CTA accessible names must remain admissible. | Badge-first 24/7 and same-day CTA labels followed by the verified phone. | fixed/superseded | `test_build_generator_allows_source_backed_cta_badge_and_phone` admits field-backed 24/7, field-backed same-day, and promise-backed same-day labels. |
| `PRRT_kwDOTDYaKM6fwcB-` | Review claims require source review authority and a validated score owner. | Raw `★★★★★` in an ordinary `div` while review mode is `omit`. | fixed/superseded | `test_build_generator_rejects_reviews_without_source_evidence` rejects the raw glyph; aggregate-review controls preserve canonical scored widgets. |
| `PRRT_kwDOTDYaKM6fwcCA` | Native layout must not bypass complete-phrase admission. | One table row with `Roof` and `Repair` in adjacent cells. | fixed/superseded | `test_build_generator_rejects_copy_composed_by_native_table_row` rejects the combined row and admits the same source values in separate rows. |

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

Current implementation evidence is based on commit
`6253691dd31b191f447bd5f43d50ac2e43955ae8`. The generated artifact and evidence logs are
ignored outputs, not source changes. The earlier evidence recorded against
`758626d2df23865449f41b5b185a19cd79fd847b` is historical and superseded by
this block.

Commands and results:

```bash
npm --prefix desktop test
# 1 test file passed; 16 tests passed

npm --prefix desktop run build
# TypeScript check and Vite production build passed

python3 -m pytest -q
# 401 passed, 34 skipped, 688 subtests passed in 48.90s

python3 -m pytest -q tests/test_generation.py \
  -k 'visible_copy or aria or accessibility or service_cards or review_cards or layout_catalog or ordered_list or native_table_row or native_control_label or rendered_input_value or aggregate_review_claims or rejects_reviews_without_source_evidence'
# 25 passed, 182 deselected, 35 subtests passed in 7.27s

python3 -m compileall -q build.py pipeline.py connect_provider.py lib tests
# Exit 0

PYTHONUNBUFFERED=1 GENERATION_TIMEOUT_SECONDS=1800 \
  python3 build.py examples/prospect-plumber-template.json \
  --skip-image-gen --skip-email-draft --skip-deploy
# 2026-09-06T18:08:13-05:00 through 2026-09-06T18:08:57-05:00
# Exit 0; local:qwen3-30b-a3b:latest; no deploy, email, or image generation
```

The final fixture invocation completed without a correction. Its complete log
is `/tmp/pr50-visible-copy-fixture-final3.log` with SHA-256
`c05581a3e9b0155e01d60c2e127b718ca4dbdb046c30d4fa28583ef81dccbcaa`.
The invocation wrote
`outputs/builds/drees-plumbing-inc/index.html` at
`2026-09-06 18:08:57.257109498 -0500`. The artifact is 71,838 bytes with
SHA-256 `2c16369fd1dc42ed0e79b98f344b1077990e3270aed25060667518e0bb6f2367`.
Both the required placeholder pattern and the case-insensitive forbidden-claim
pattern returned zero matches. Parsed artifact inspection confirmed the exact
code-owned hero, benefit, and form-trust copy. A headless Chrome render of these
exact artifact bytes wrote `/tmp/pr50-drees-render-final2.png` with SHA-256
`329482b35d29390c41bb27a67a2380309d9ffcd75cd1e2bbd0b174477dbd25bf`;
Chromium computed-style inspection and direct PNG pixel reads confirmed the
white page, red gradient hero, visible white hero copy, service grid, and
page-function content.

After the final layout, table-row, and review-star ownership changes, the same artifact body was
replayed deterministically through the real `generate_build_html()` admission
path without a model call. Admission passed and produced 70,581 validated bytes
with SHA-256
`a8986d4d0651344dbe20c37f4848d16a98946d30577c9eca58e2e934942903da`.

No live OpenRouter request was made; doing so would spend provider credit and
is unnecessary to prove the provider-independent prompt and admission contract.
`git diff --check` also passed. The final-head
`bash scripts/local_pr_review.sh` result is recorded in the PR verification
block after this evidence note is committed.

## Estimated diff size

The current PR diff is 2,767 changed lines across the 11 declared source files
plus this plan, exceeding the 400-line soft target. It remains one indivisible
source-authority slice: intake must accept the business type and services,
generation must consume exactly those services without trade-profile facts,
and admission must reject any service-list drift. Splitting any one boundary
would temporarily ship a form that still cannot produce an admissible website.
The location correction is the reproduced blocker on that exact path, not a
general validator cleanup. Unrelated provider, runtime, redesign, Connect, and
UI error-reporting work remains excluded.
