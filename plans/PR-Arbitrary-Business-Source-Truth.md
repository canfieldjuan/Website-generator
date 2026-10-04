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
9. Make every neutral action label the build prompt offers renderable
   (issue #51). The catalog admits the bare channel labels exactly when that
   channel is supplied, plus the phone label-and-number compositions a split
   `tel:` label produces. The build prompt offers only neutral labels that are
   both catalog entries and backed by an admitted action destination.
10. Give the model a trust-strip structure that the existing composition gate
    already scores per chip (issue #52), without changing the gate.
11. Let the nav brand link to the top of the page under a source-owned
    business name (issue #53): the code-owned display identity or the legal
    name. The link is bound to one same-document destination.

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
meaning. The same fail-closed contract covers the complete WAI-ARIA numeric
collection, hierarchy, grid, and span metadata family, so generated roles
cannot announce invented positions or collection sizes. Canonical review-score
components remain governed by the existing review evidence contract.
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
Default-inline `label`, `output`, and `svg` owners also remain in their parent's
complete visible run, so changing semantic tags cannot split one rendered
phrase into separately admitted fragments. SVG metadata titles remain
accessibility copy rather than visible text and therefore do not get joined to
the SVG's rendered label. Source-owned service-name owners are additionally
checked against the trusted template's complete case-transforming CSS selectors.
The validator matches those selectors against the generated DOM and follows
each service text node's inheritance chain, covering owner, ancestor,
descendant, tag, and combinator selectors without reducing them to class-name
approximations. Valid source spelling such as `eBay Repair` therefore cannot
render as a different-cased offering.
Ordered-list markers also fail closed because their browser-generated copy has
no source-bound owner in this page contract. Finite source-backed compositions,
such as the verified phone beside verified 24/7 status, are admitted explicitly.
The no-radius service-area prompt uses the same exact `Service Area` casing as
the code-owned catalog.

### Channel action labels (issue #51)

The shared action-label instruction offers 39 capability-neutral labels. The
visible-copy catalog admitted only `Call us` and `Contact` of them. So a model
that followed the action contract and labelled a `tel:` action `Call`, with the
number in a sibling node, failed visible-copy admission. That happened even
though the catalog already held the composite `Call <phone>`; its bare part
`Call` was never admissible.

The build catalog now admits `Call` and `Call us` only when a prospect phone
exists, together with the `<label> <phone>` composition each one produces as a
split `tel:` accessible name. The existing `Call <phone> →` coverage-band entry
is unchanged. `Call us` moves out of the always-on fixed copy. Before this
change, a phoneless page could render `Call us` even though the prompt says to
omit every phone surface.

The catalog admits `Email` and `Email us` only when an owner email exists. It
adds no email composition: the action gate accepts an email label only when the
whole label is the address, so `<label> <email>` could never be a link label
and would admit only free text. `Text` and `Text us` stay excluded because SMS
capability is not a source fact.

The channel labels never enter the action contract's `allowed_labels`. If they
did, the source-label branch, which runs before the neutral branch, would
demand an exact pair and bypass the channel-to-scheme binding.

The build passes its visible-copy contract to `action_url_contract_instruction`.
The instruction then offers only neutral labels that are exact catalog entries,
in catalog case. It also drops channel labels whose scheme has no admitted
destination: a phone for `tel`, an owner email for `mailto`, and an exact
`sms:` URL for `sms`. The prompt therefore offers no label that either gate must
reject.

The redesign flow passes no visible-copy contract and keeps its existing
instruction. Behaviour tests bind each build channel label to the shared
authority. A `tel:` or `mailto:` action with that label admits, the same label
on `#contact` raises the channel-specific error, and none of the labels appear
in the build action contract's `allowed_labels`.

### Trust-strip structure (issue #52)

The build never sends the template markup, only its class names, so the model
invents its own trust-strip structure. Its natural `div` or `span` chips are
joined by the layout or inline composition pass and rejected as one phrase.

A design review considered marking `trust-item` as an independent component.
That would also exempt the element from being a layout owner, because
`independent_component_classes` both ends the parent's run and skips the
element's own composition check. Two consequences:
- `<div class="trust-item"><div>Roof</div><div>Repair</div></div>` would be
  admitted;
- the class could be used to split the `dual-cta-row` composition that
  `PRRT_kwDOTDYaKM6fwRBN` guards.

A narrower variant still left the second escape.

The gate therefore does not change. List items already end the parent's run,
while a list item that carries `trust-item` is still a layout owner. So the
structure below admits each catalog entry as its own fragment today, while
anything combined inside one `li` still fails:

```html
<ul class="trust-strip-inner">
  <li class="trust-item">one catalog entry, optionally in one .trust-badge/.trust-text span</li>
</ul>
```

Combinations that still fail inside one `li` include two `div`s, two badges,
or prose such as `Licensed and insured`.

The template CSS keeps that list chip-shaped. The reset zeroes list padding,
and the flex `trust-item` renders no marker. The build prompt's trust-strip
rule now requires this structure, with exactly one catalog entry per item.

### Brand home link (issue #53)

The build action contract never admitted the business name as a link label.
A brand link therefore failed:
- the template's `<a href="/" class="nav-brand">` failed first on `/`, which
  is not an admitted destination;
- a model's `<a href="#main">{name}</a>` failed as a non-neutral label.

The redesign flow already owns a brand pair, `(site_name, "/")`, but `/` is
wrong for a one-page build. The desktop preview loads the page from a `blob:`
URL in a sandboxed iframe, and the artifact is saved as a standalone `.html`
file. In both places `/` leaves the page.

When the prospect has a `business_name`, `expected_build_action_url_contract`
now adds `expected_build_display_name(prospect)` to `allowed_labels`, plus
exactly one pair: `(display identity, "#top")`. `#` fragments are already
admitted destinations, and HTML scrolls `#top` to the top of the document. So
no URL authority is added. The binding works as follows:

- Only the code-owned display identity is admitted, not the legal name. The
  legal name stays confined to the copyright line.
- The label stays bound to `#top`. The brand pointing at `#contact`, `tel:`,
  an external URL, or `/` still fails.
- A prospect without `business_name` (contract-level callers) gets no pair, so
  its tuples are unchanged.

The build prompt's nav rule now says the brand is the exact display identity:
either plain text, or `<a href="#top" class="nav-brand">` showing it once. A
logo inside that link uses `alt=""` when the name is also visible text,
because a logo `alt` plus visible text would form the label `Name Name`.

### Amendment after model verification (issues #51 and #53)

The fixes above were checked by building all five example prospects with the
production Qwen3.5-9B, before and after the change.
- Two prospects that failed before on `Call us <phone>` now build on the first
  attempt.
- Two new failures traced to the same class of gap: parts that are each
  admitted, but whose composition is not.

**Channel label with a verified badge (#51).** The drees fixture labels its
24/7 emergency CTA `Call (217) 857-6642 Available 24/7`. That is a channel
label, the verified phone, and the verified badge. The catalog held the badge
with the phone (in either order) and the label with the phone, but not all
three.

When a verified badge and a phone both exist, the catalog now also admits two
forms for each phone channel label `L`:
- `L <phone> <badge>`
- `<badge> L <phone>`

The label stays attached in front of the number, and the badge sits on either
side of that unit, mirroring the existing either-order badge/phone rule. No
other permutation is admitted. For example, `L <badge> <phone>`, or the label
after the number, still fails.

**Legal name on the brand link (#53).** With the nav rule inviting a brand
link, Althoff labelled it with the legal name `Althoff Plumbing, Inc.` The
visible-copy catalog already admits `business_name` as rendered text, so
binding the legal name to the same single destination makes no new claim. It
only stops the gate depending on which source-owned name the model picks.

When `business_name` exists, the build contract therefore admits both the
display identity and the stripped legal `business_name` as labels. Each gets
exactly one pair to `#top`. They are deduplicated when the two are equal.
Every other destination, near-miss name, and composed brand label still
fails. This supersedes the "display identity only" binding above.

## Latest review finding ledger

| Finding/thread | Affected invariant | Current reproduction | Disposition | Proof |
| --- | --- | --- | --- | --- |
| `PRRT_kwDOTDYaKM6fwRBN` | Layout styling must not recombine separately admitted fragments into a new offering. | `dual-cta-row` with adjacent `div` or `p` owners containing `Roof` and `Repair`. | fixed/superseded | `test_build_generator_rejects_copy_composed_by_layout_class` rejects both boundary forms while admitting native list items. |
| `PRRT_kwDOTDYaKM6fwRBO` | Complete source-backed CTA accessible names must remain admissible. | Badge-first 24/7 and same-day CTA labels followed by the verified phone. | fixed/superseded | `test_build_generator_allows_source_backed_cta_badge_and_phone` admits field-backed 24/7, field-backed same-day, and promise-backed same-day labels. |
| `PRRT_kwDOTDYaKM6fwcB-` | Review claims require source review authority and a validated score owner. | Raw `★★★★★` in an ordinary `div` while review mode is `omit`. | fixed/superseded | `test_build_generator_rejects_reviews_without_source_evidence` rejects the raw glyph; aggregate-review controls preserve canonical scored widgets. |
| `PRRT_kwDOTDYaKM6fwcCA` | Native layout must not bypass complete-phrase admission. | One table row with `Roof` and `Repair` in adjacent cells. | fixed/superseded | `test_build_generator_rejects_copy_composed_by_native_table_row` rejects the combined row and admits the same source values in separate rows. |
| `PRRT_kwDOTDYaKM6fwkA1` | Native inline semantics must not split one rendered phrase into separately admitted fragments. | Adjacent `label`, `output`, or `svg` owners containing `Roof` and `Repair`. | fixed/superseded | `test_build_generator_rejects_copy_composed_by_native_inline_owners` rejects all three combined forms and preserves a source-backed SVG whose accessibility title and rendered text agree. |
| `PRRT_kwDOTDYaKM6fwkA3` | Source-owned service spelling and case must survive rendered CSS. | `eBay Repair` owned by or descended from template class `ft-col-title`. | fixed/superseded | `test_build_generator_rejects_visual_case_transform_on_service_names` rejects both direct and inherited transforms while preserving the canonical service owner. |
| `PRRT_kwDOTDYaKM6fwsni` | The complete service-name ownership subtree must preserve source case. | `ft-col-title` nested below the canonical `service-card-name` owner. | fixed/superseded | `test_build_generator_rejects_visual_case_transform_on_service_names` rejects transforming classes on the owner, its ancestors, and its descendants while preserving canonical markup. |
| `PRRT_kwDOTDYaKM6fwzPq` | CSS authority must preserve the full selector that controls rendered case. | `.nav-links a` applied to an `a.service-card-name` under a `service-card.nav-links` ancestor. | fixed/superseded | `test_build_generator_rejects_visual_case_transform_on_service_names` rejects the complete descendant-selector path; the contract now matches full trusted-template selectors against each source text node's inheritance chain. |
| `PRRT_kwDOTDYaKM6fw7aZ` | Assistive metadata must not create numeric claims without source authority. | `aria-setsize`, `aria-posinset`, `aria-rowcount`, or `aria-colcount` attached to otherwise admitted copy. | fixed/superseded | `test_build_generator_rejects_uncontracted_numeric_semantics` covers all WAI-ARIA numeric collection, hierarchy, grid, span, and value properties while source-owned ordinary numeric text remains admissible. |
| Issue #51 | Every neutral action label the build prompt offers must be renderable, and a source-owned composite must have admissible parts. | A `tel:` action with label `Call` (or `Call us`) and the verified phone in sibling nodes is rejected on `'Call'` (or `'Call us <phone>'`). The prompt offers 39 neutral labels, of which only `Call us` and `Contact` are catalog entries. | fixed | `test_build_generator_admits_split_phone_channel_labels` admits split `Call`/`Call us` tel: labels and rejects `Call Now`, `CALL`, `Text us`, and `Call` composed with other copy; `test_build_channel_copy_requires_its_supplied_channel` rejects every channel label on a page without that channel; `test_build_generator_admits_email_channel_labels_with_owner_email` admits `Email`/`Email us` mailto labels and rejects `Email us <email>` as one label; `test_build_channel_labels_stay_bound_to_their_channel_scheme` rejects each label on `#contact` or the other channel and keeps them out of `allowed_labels`; `test_build_prompt_offers_only_renderable_neutral_action_labels` pins the offered list per channel set and the unchanged redesign instruction. |
| Issue #53 | The nav brand may link home only under the exact code-owned display identity and only to one same-document destination. | `<a href="/" class="nav-brand">` fails on the `/` destination, and `<a href="#main">{name}</a>` fails as a non-neutral label. | fixed | `test_build_action_contract_binds_display_identity_to_page_top` admits the `#top` brand as text, with an `alt=""` logo, and as a logo alone, and rejects the brand on `#contact`, `#main`, `/`, `tel:`, or an external URL, the legal name, a near-miss name, logo `alt` plus visible name, and brand plus `.nav-sub`; it also proves a nameless contract has no `#top` pair; `test_build_generator_admits_brand_link_to_page_top` admits the brand link end to end, rejects `/`, and pins the nav prompt line; the two exact-tuple review tests include the display identity; the redesign brand test is unchanged. |
| Issue #52 | Each trust signal must be scored as its own complete phrase without letting layout recombine admitted fragments (preserves `PRRT_kwDOTDYaKM6fwRBN`). | Model-written `div` or `span` chips holding `Licensed`, `Insured`, and `Established in 2016` are rejected as one joined phrase. | fixed | `test_build_generator_scores_list_trust_strip_items_separately` admits the `ul.trust-strip-inner > li.trust-item` strip and rejects two `div` entries, two badges, or `Licensed and insured` inside one item, plus `dual-cta-row` Roof/Repair with and without `trust-item`; `test_build_prompt_requires_one_catalog_entry_per_trust_list_item` pins the prompt structure under the unverified-claim filter. |
| Issue #51 (amendment) | A verified badge composed with an admitted call label and the verified phone must remain admissible in meaning-preserving orders. | The drees fixture's tel: CTA `Call (217) 857-6642 Available 24/7` is rejected under the production model. | open (contract) | Planned tests: `L <phone> <badge>` and `<badge> L <phone>` admit for 24/7 and same-day evidence and for both labels; `L <badge> <phone>` and the badge without evidence reject. |
| Issue #53 (amendment) | Either source-owned business name may label the one brand home link, and only that link. | Althoff's model links the brand as `Althoff Plumbing, Inc.`, which is rejected as a non-neutral label. | open (contract) | Planned tests: the legal name and the display identity each admit on `#top` and reject on every other destination; a near-miss name and composed brand labels reject; equal names produce one pair. |

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
- Exclude `Text` and `Text us` from the build catalog. They stay in the shared
  neutral list, but SMS capability has no source field.
- Gate `Call us` on a supplied phone, like `Call`. Its only build surface is the
  footer phone label, which the prompt already omits without a phone.
- Change no composition-gate code for #52. Model `div` and `span` chips keep
  failing closed. The prompt supplies the list structure the gate already
  scores per item, rather than a new exemption class that could split other
  layout runs.
- Leave `references/03-base-template.html` unchanged. The build sends only its
  class names, so its sample `Call Now 24/7` label and its `div` chip markup
  never reach the model.
- Bind the build brand to `#top` rather than mirror the redesign flow's `/`.
  `/` is correct for multi-page redesigns, but leaves a one-page build in the
  desktop preview and the saved file.
- Do not special-case a business whose display identity equals a neutral
  label. Admitting it as a source label binds it to `#top`. Any other use of
  that label then fails closed rather than widening.

## Deferred

- A structured, safe admission-error explanation in the desktop UI is a separate
  operability slice.
- A cleaning-specific content/style profile is unnecessary for generic website
  generation and is not introduced here.
- Provider/model behavior, Ollama scheduling, OpenRouter live billing checks,
  redesign/extraction, Connect, packaging, deployment, email, and image
  generation do not change.
- Icon- or role-bearing layout items can still opt out of the layout join.
  That remains issue #54.
- Build-prompt example copy that the catalog rejects remains issue #55. The
  examples are the `<br>`-split footer address, `Licensed and insured.`, the
  industry trust-signal phrasings, and the stale BASE_TEMPLATE input line.
- `main` keeps rejecting brand links until this PR merges. Its build flow has
  no deterministic display identity to bind, because the model derives that
  identity from a prose rule. So issue #53 is fixed here rather than in a
  separate `main` slice.

## Verification

Current implementation evidence is based on commit
`91d2252432cc726368bd0dca1548b80340277d67`. The generated artifact and evidence logs are
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
# 403 passed, 34 skipped, 704 subtests passed in 45.74s

python3 -m pytest -q tests/test_generation.py \
  -k 'visible_copy or aria or accessibility or service_cards or review_cards or layout_catalog or ordered_list or native_table_row or native_inline_owners or visual_case_transform or numeric_semantics or native_control_label or rendered_input_value or aggregate_review_claims or rejects_reviews_without_source_evidence'
# 28 passed, 181 deselected, 57 subtests passed in 10.80s

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

After the final layout, table-row, review-star, native-inline, and visual-case
ownership changes, the same artifact body was
replayed deterministically through the real `generate_build_html()` admission
path without a model call. Admission passed and reproduced 71,838 validated bytes
with SHA-256
`2c16369fd1dc42ed0e79b98f344b1077990e3270aed25060667518e0bb6f2367`.

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
