# PR: Ground redesign extraction before source admission

## Why this slice exists

Issue #45 identifies a broken authority boundary in the URL redesign pipeline.
`analyze_site()` JSON-decodes remote model output and returns it directly, while
`enrich_site_json()` applies only a few container checks before merging another
model response. Downstream generation and admission then treat values from that
document as source-owned identity, contact, action URL, image, and content data.
The extraction prompt asks the model not to invent facts, but prompt text is not
verification. A fabricated phone, email, address, link, image, service, team
member, or trust claim can therefore become the evidence against which generated
HTML is admitted.

The same boundary also labels model-derived urgency and layout classifications as
if they were verified facts. The redesign prompt currently permits availability
copy such as same-day or 24/7 based on urgency classification alone, so grounding
the literal extraction fields without removing that inference would leave an
independent fabrication path.

The broken invariant is: only structurally admitted values grounded in the page
that was actually fetched may become source-owned redesign facts; derived design
analysis may control presentation but may not authorize a visible business claim.

## Scope (this PR)

1. Add one canonical local validator for homepage analysis and enrichment output.
   It must enforce bounded JSON structure and reject unknown or wrongly typed
   fields before downstream code reads them.
2. Build normalized evidence from the fetched HTML and effective source URL, then
   ground source-owned text, contacts, action/page URLs, and image URLs before
   admitting them.
3. Keep enumerated classification, design, and layout fields explicitly derived;
   they remain usable for presentation but are not evidence for availability,
   pricing, credentials, geography, or service promises. Reject the unrequested
   model-authored `platform` field because existing code maps it into cost and
   savings metadata.
4. Make homepage analysis fail closed when validation or grounding fails. Preserve
   enrichment's existing best-effort contract by logging and skipping an invalid
   page result rather than merging it.
5. Overwrite enrichment `source_url` with the effective URL selected and fetched
   by code; never accept model-authored provenance. Keep homepage sections free of
   that field because generation uses it as the interior-enrichment discriminator.
   Every secondary page fetch must remain on the requested source-site origin after
   redirects before its body can reach extraction or page generation.
6. Remove redesign-prompt instructions that synthesize availability promises from
   urgency classification or require trust claims when no source-owned signal
   exists, and state the derived-versus-source authority boundary at the
   generation prompt.
7. Verify against exactly the truncated HTML slice sent to the model, not unseen
   trailing source, and add boundary regressions for valid and fabricated source
   facts, malformed and mixed structures, limits, relative/absolute URL evidence,
   code-owned provenance, and invalid enrichment isolation.

### Files touched

- `build.py`
- `lib/site_extraction.py`
- `lib/generation.py`
- `pipeline.py`
- `references/02-redesign-gen-prompt.md`
- `references/04-interior-page-prompt.md`
- `references/06-build-prompt.md`
- `tests/test_generation.py`
- `tests/test_site_extraction.py`
- `requirements.txt`
- `requirements-dev.txt`
- `plans/PR-Ground-Redesign-Extraction.md`

## Finding disposition ledger

| Finding/thread | Affected invariant | Current reproduction | Disposition | Proof |
| --- | --- | --- | --- | --- |
| `PRRT_kwDOTDYaKM6foIrz`: lone wrapped title used literal membership | Complete source identity and a controlled wrapper must use one authority rule from collection through admission. | `og:site_name="Acme Plumbing"` plus `Welcome to Acme Plumbing` now admits the complete wrapped identity. | fixed/superseded | `lib/site_extraction.py:818-838,1143-1148`; `tests/test_site_extraction.py:49-75,963-971` |
| Metadata `Acme Plumbing` plus H1 `Plumbing` | A source-owned identity cannot be shortened to an inner phrase. | The shortened H1 and extracted name are rejected. | fixed/superseded | `lib/site_extraction.py:1163-1187`; `tests/test_site_extraction.py:916-923` |
| Metadata `Acme Plumbing` plus H1 `Best Acme Plumbing` | A source-owned identity cannot be expanded with unsupported wording. | The expanded H1 and extracted name are rejected. | fixed/superseded | `lib/site_extraction.py:1163-1187`; `tests/test_site_extraction.py:925-933` |
| Metadata `Acme Plumbing` plus title `Plumbing \| Repairs` | Multi-component titles cannot promote a partial component; both components must exercise the non-generic branch. | Extracted name `Plumbing` is rejected. | fixed/superseded | `lib/site_extraction.py:1136-1161`; `tests/test_site_extraction.py:935-943` |
| `Home - Acme Plumbing`, exact identity, controlled `Welcome to ...`, and intrinsic `Acme-Plumbing` | Valid complete identities and only controlled wrapper variants must remain admissible. | All four positive boundaries admit their complete identity. | fixed/superseded | `lib/site_extraction.py:818-838,1136-1161`; `tests/test_site_extraction.py:945-971` |
| Ambiguous and conflicting title identity | Independent conflicting or ambiguous identity surfaces must fail closed rather than self-corroborate. | Ambiguous title candidates and the conflicting single-title name are rejected; the explicit metadata identity remains admissible. | fixed/superseded | `lib/site_extraction.py:1150-1187`; `tests/test_site_extraction.py:887-914,992-1004` |
| `PRRT_kwDOTDYaKM6foSbG`: recipient-qualified claims could be shortened | A published claim cannot drop the source clause that limits its recipient, eligibility, purchase, or timing scope. | `Free Estimates` from member/senior/purchase-qualified source text is rejected, each complete qualified claim is admitted, and unrestricted `Call for Free Estimates` remains admitted. | fixed/superseded | `lib/site_extraction.py:470-535`; `tests/test_site_extraction.py:542-595` |
| `PRRT_kwDOTDYaKM6foY7Q`: a preceding recipient subject could survive the first-token scope check | Claim admission must retain a complete preceding recipient/eligibility relationship, not inspect only the first word before the extracted phrase. | `Free Estimates` from `Maintenance-plan members receive Free Estimates` is rejected; direct, passive, and eligibility predicate variants reject the shortened claim while their complete claims and unrestricted `We offer ...` / `Call for ...` variants pass. | fixed/superseded | `lib/site_extraction.py:417-442,516-528,549-570`; `tests/test_site_extraction.py:542-588` |
| `PRRT_kwDOTDYaKM6foSbJ`: `input[type=button]` labels bypassed action admission | Every visible button-like input label must use the same source-label authority; ordinary data inputs must remain outside that guard. | Unsupported button/reset labels are rejected, source-owned labels are admitted, and text inputs remain unaffected. | fixed/superseded | `lib/site_extraction.py:241-248,1062-1068`; `lib/generation.py:2318-2327`; `tests/test_site_extraction.py:599-623`; `tests/test_generation.py:1365-1395` |
| `PRRT_kwDOTDYaKM6foY7S`: generated `aria-labelledby` targets ignored their own ARIA name | The generated action name must follow the same recursive ARIA precedence as source-side action naming before label authority is checked. | A referenced node whose `aria-label` is unsupported now rejects even when its descendant text is neutral; the inverse valid ARIA override remains admitted. | fixed/superseded | `lib/generation.py:2228-2292`; `tests/test_generation.py:1325-1351` |
| `PRRT_kwDOTDYaKM6foSbL`: broad logo container text became identity | A broad brand container may contribute only bounded name surfaces, not its description or unrelated link text. | The WordPress-style `site-identity` header admits `Acme Plumbing`; `Quality work since 1990` and a sole `Call Us` link do not become identity. | fixed/superseded | `lib/site_extraction.py:731-769,1125-1129`; `tests/test_site_extraction.py:973-990` |
| Carried-forward plumber fixture and zero-match claims | Acceptance evidence must prove a fresh artifact from the tested code revision, not reuse historical output. | The clean `c3741e9` retry rewrote the artifact, exited 0, and both required scans found zero matches. | fixed/superseded | Verification block below; `/dev/shm/website-generator-pr47-fixture-c3741e9-run2.log`; `/dev/shm/website-generator-pr47-scans-c3741e9.log` |
| Issue #46 historical URL-redesign stall | A one-token probe or one successful fixture cannot prove the historical runtime stall resolved. | The required full fixture completed, so the stall did not reproduce in this run; no current code defect was established. | separate issue | Issue #46; verification block below |

## Mechanism

`lib/site_extraction.py` owns both structure admission and source grounding. A
bounded JSON Schema accepts only the analysis shape consumed by the pipeline.
Before source admission, the verifier parses the exact cleaned HTML slice supplied
to the extraction model, normalizes browser-equivalent text, gathers link/image
attributes and their source-relative absolute forms, and checks every
source-owned leaf through a field-specific evidence rule. Claim-bearing text uses
DOM-local assertion contexts so inline markup cannot hide negation while separate
elements cannot alter one another's meaning. CTA labels must exactly match an
interactive element. Phone and email fields use canonical comparison against
visible text or the scheme-specific `tel:`/`mailto:` destination, excluding URI
parameters and cross-scheme tokens. Link destinations and image resources are
separate evidence sets: generated links require an observed anchor destination,
not an image resource or form endpoint, and both URL kinds permit only their
deterministic source-relative resolution.
Composite content items must ground all of their populated source fields in one
DOM-local record container; independently present values elsewhere on the page
cannot be recombined. HTML comments are excluded from visible text and contact
evidence. The downstream generation action contract is assembled only from the
schema's action-owned fields plus code-owned enrichment and contact-page source
destinations, preserving these separations after extraction. Every non-neutral
generated action label must exactly match a source-owned label; a bounded neutral
vocabulary permits only presentation, navigation, contact, and the code-owned
generated service-request form. This allow-by-authority rule prevents booking,
quote, commerce, donation, registration, subscription, and ticket claims without
depending on an incomplete capability-verb denylist.
A source-owned label remains bound to the destination on its source action, even
when that wording also belongs to the neutral vocabulary. Accessible action
labels include replacement text from image, area, and image-input controls;
source collection and generated-body admission construct the same complete,
whitespace-normalized label. An admitted phone or email display value remains
bound to its matching contact destination unless that exact source action pair
was observed. Submit buttons and image inputs resolve their effective destination
from `formaction`, an explicitly referenced form, or their owning ancestor form;
source collection and output pair admission use the same resolver. Output URL
sanitization separately checks every declared destination attribute, including an
inert or orphaned `formaction`, without promoting that attribute into source
authority. Pair evidence does not itself grant URL authority: raw form actions can
bind a label to an already admitted destination, but cannot become generated link
destinations.
Flat heading records
stop before sibling structural containers, including list wrappers, so a section
heading cannot turn a collection of independent cards into one evidence record.
Definition-list terms and their owned definitions form individual records.
Definition-list wrappers are also record boundaries, so an enclosing article or
section cannot recombine a term with another term's definition.
Navigation, CTA, footer, and fetch-page labels remain paired with the destination
of the same interactive source element. A top-level CTA must contain both its
source-owned label and URL pair or contain neither; one nullable half cannot be
admitted from page-wide evidence. Phone and email scans operate per local
DOM context rather than concatenating unrelated page nodes. Assertion context
survives commas, parenthetical contrast modifiers, and colons until a real
sentence or contrast boundary; inline links inherit their surrounding prose for
assertion checks while retaining their destination at its original DOM position.
Contact-specific negation recognizes affirmative phrases such as "do not hesitate
to call" without allowing genuinely negated contact details. Claim-bearing
content fields require assertive evidence, except FAQ questions. Single-page
navigation labels bind to their own anchors, and the section content is validated
inside that exact target container. When no anchor exists, the navigation label
must be a real source action and match a heading in the same bounded semantic
section as all submitted content; an unscoped or empty section fails closed. The
code-owned image inventory is emitted as real prompt-visible image attributes, so
the same bounded URLs remain available to validation even when their original
elements fall after HTML truncation.
Claim-bearing section headings, body text, taglines, locations, addresses, and
hours preserve the same assertion context instead of treating an unanswered
question or conditional as an affirmative fact. Form-field evidence comes only
from labels and accessible names attached to actual non-action
`input`/`select`/`textarea` controls. Image alt text remains paired with the exact
source image URL rather than being recombined from page-wide values, including
responsive `<picture><source>` candidates owned by the same fallback image. A
logo URL additionally requires a site-brand-specific marker on its image or
owning brand container; generic `logo` text in an image alt/title is insufficient
because it may describe payment, partner, certification, or sponsor branding.
The same rule applies when `images[].context` would promote an image to the
navigation logo.
Fetchability is overwritten by code from the admitted destination and effective
source URL: same-document anchors, same-page URLs, and external origins are not
queued, while a distinct same-origin HTTP(S) page remains fetchable even if the
model says otherwise. The same source-site boundary is rechecked after fetch
redirects in the shared fetch primitive used by enrichment and interior/contact
page generation, before a secondary page body can reach a model. The enrichment
caller retains an independent effective-URL check as defense against an injected
or substituted fetch result.
Business identity uses assertion evidence. Nested content containers prevent a
broad article from recombining separate cards. Form labels must match a complete
accessible label, duplicate references to the same source label are collapsed,
and labels are assigned one-to-one to distinct controls. Social platform names
are derived from recognized destination hosts; otherwise the name and URL must
belong to the same source action.
Source action evidence uses one effective accessible name: every valid
`aria-labelledby` target is resolved in declaration order, replacement text such
as image `alt` participates, and a missing, duplicate, cyclic, or oversized
reference set fails closed rather than falling back to another label surface.
The same complete name and its effective destination become the generation
contract pair. Identity admission likewise accepts only a complete identity
surface or a small code-owned canonical wrapper variant (for example,
`Welcome to …` or `… logo`); an arbitrary inner phrase cannot become the business
name. Title components and H1 candidates use that same exact canonical agreement
when stronger identity metadata must corroborate them; bidirectional substring
matching cannot promote a partial name. Common spaced ASCII hyphens join the
existing title separators without splitting hyphenated business words. A parent
article or section containing multiple nested semantic containers is excluded
from section evidence so sibling cards cannot be recombined.
Business identity is further limited to title, a single primary H1, site-name
metadata, and explicit brand/logo evidence; on a multiple-H1 page, title,
site-name, or logo evidence corroborates the admitted H1, with only the first
non-generic document H1 used when no corroborating identity exists. Ordinary
subsection
headings and arbitrary footer or body attribution cannot become the prospect
name. Generic page-title components are excluded, and isolated title identity
components require an exact match rather than lending every phrase in the full
document title to business identity. When a title retains multiple non-generic
components, an independent site-name or logo seed must select exactly one; the
page H1 cannot select its own title descriptor, and ambiguity disables the H1
fallback. A lone title component can supply identity only when no stronger
explicit identity exists, or when it agrees exactly with that explicit identity.
Negation and conditional qualifiers are
retained across the complete
owning clause rather than a fixed word window. Figures are atomic content
records. Heading-delimited section fallback stops at sibling `article` and
`section` containers, and an article wrapping nested sections cannot become a
broad content scope. A list item that contains nested list items is likewise not
an atomic record; only its leaf items can authorize a composite extracted item.
When a homepage section
contains both a headline and items, both must validate inside one semantic or
heading-delimited source section before admission.
Only actual submit inputs contribute input-value CTA evidence; reset, image,
button, and text inputs cannot promote their values into published CTA copy.
Classifications, layout choices, color selections, and image-generation guidance
are admitted as typed derived metadata, not source facts.

Restriction context includes explicit exception clauses, so a shortened claim
cannot drop an `except ...` qualifier while the complete qualified source phrase
remains admissible. Visible and `tel:`/`mailto:` contact candidates are screened
in their owning assertion context before becoming publishable contact evidence.
Generated actions validate every distinct accessible, visible, submit-value, and
title label; one neutral ARIA label cannot conceal unsupported visible wording.

`analyze_site()` passes the source URL alongside HTML, validates the decoded model
document, and returns it only after the verifier succeeds. `enrich_site_json()`
validates each decoded page-shaped result against that page's HTML before merging,
sets provenance from the effective fetched URL, and skips only the invalid page
on failure. The generator continues to receive the established `site_json` shape,
so no storage or public API migration is introduced.

The redesign prompt may use derived urgency and blueprint metadata to choose CTA
weight and layout. It may not turn those fields into factual availability or
service promises. Source-owned values remain the only authority for visible
business-specific claims.

## Intentional

- Homepage analysis fails closed instead of silently stripping individual model
  errors. An incomplete source document is not a safe authority for the whole
  redesign.
- Enrichment remains fail-soft because each page is independent and the existing
  pipeline contract already treats enrichment as optional.
- Normalized matching accepts browser-equivalent whitespace, HTML entities,
  canonical phone/email forms, and source-relative URL resolution. It does not use
  a page-wide compact substring for URLs or contacts, and shortened text cannot
  drop nearby source negation before or after the phrase or match inside a larger
  word.
- The enrichment page type selected by code owns the generic `FAQ` presentation
  heading; FAQ questions and answers remain verbatim source-owned content.
- Derived fields remain in the established document shape for design continuity,
  but generation instructions explicitly prevent them from authorizing factual
  copy.
- The validator is local and deterministic. Provider structured-output promises
  are not treated as an enforcement boundary.

## Deferred

- Generated-image semantic truth remains unverified; this slice verifies source
  image URLs but does not judge the factual meaning of generated pixels.
- Protection from a hostile source site intentionally placing misleading content
  in its own HTML remains outside the trust model.
- Generated inline-style value bounds remain issue #33.
- A generalized provenance ledger with source selectors/spans is deferred unless
  future consumers need audit-display provenance rather than admission-only proof.

## Verification

### Current revision evidence (2026-09-05)

- Code revision under test: `4cc97326e697bdee7c797e14d60017d36f07e662`.
  The worktree was clean when the production-shaped fixture started. The plan
  update that records these results is documentation-only and therefore a
  descendant of this tested code revision.
- The earlier three current-review reproductions first admitted a shortened
  recipient-qualified claim, ignored an unsupported `input[type=button]` label,
  and rejected the correct identity from a WordPress-style `site-identity`
  header. The same probes now reject, reject, and admit respectively.
- The final-head review then reproduced two remaining boundary defects: a
  preceding recipient subject (`Maintenance-plan members receive Free
  Estimates`) could still authorize the shortened benefit, and a referenced
  action-label node's own `aria-label` was ignored in favor of its descendant
  text. The same probes now reject both unsupported outputs.
- Focused both-side regressions: `python -m unittest -q
  tests.test_site_extraction.SiteAnalysisGroundingTests.test_claim_text_preserves_recipient_and_purchase_qualifiers
  tests.test_generation.BodyAssemblyTests.test_body_action_destinations_are_source_owned`:
  2 tests passed. The first preserves complete direct, passive, and eligibility
  relationships plus unrestricted offer/call variants; the second rejects the
  hidden unsupported ARIA override while admitting a valid override.
- Affected modules: `python -m unittest -q tests.test_site_extraction
  tests.test_generation`: 207 tests passed.
- Full suite: `python -m unittest discover -s tests -q`: 349 tests passed with
  34 skipped.
- Scoped static checks passed:
  `ruff check --ignore F401 lib/site_extraction.py lib/generation.py
  tests/test_site_extraction.py tests/test_generation.py`;
  `python -m compileall -q pipeline.py build.py lib tests`; and
  `git diff --check`. The broad formatter check remains historical repository
  formatting noise and was not applied as an unrelated whole-file rewrite.
- The final-revision fixture used
  `PYTHONUNBUFFERED=1 GENERATION_TIMEOUT_SECONDS=1800 python build.py
  examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft
  --skip-deploy` used `local:qwen3-30b-a3b:latest` through Ollama, resident
  100% on the GPU at invocation. It started at
  `2026-09-05T20:56:56-05:00`, ended before the post-run capture at
  `2026-09-05T20:58:31-05:00`, and exited 0. No email or deployment path ran.
  Log: `/dev/shm/website-generator-pr47-fixture-4cc9732.log`.
- The successful invocation rewrote
  `outputs/builds/drees-plumbing-inc/index.html` at
  `2026-09-05 20:58:25.656914662 -0500`; size was 71976 bytes, inode 3320504,
  and SHA-256 was
  `27972c2516927caf34742b21f1ad8ba3dcc554c507a88980cb82f6b6fda9cb1d`.
- Exact required placeholder and case-insensitive forbidden-claim scans both
  returned grep status 1 and zero matches. Logs:
  `/dev/shm/website-generator-pr47-placeholder-scan-4cc9732.log` and
  `/dev/shm/website-generator-pr47-forbidden-scan-4cc9732.log`.
- Rendered spot-check: `wkhtmltoimage` produced a nonblank 1440x3890 styled
  page showing Drees Plumbing identity, phone, hero, service list, and trust
  content. Full render: `/dev/shm/website-generator-pr47-render-4cc9732.png`,
  SHA-256
  `451f81f771ec954b98e62de18d0644685232c595e6002a9e1f0fdd80f9dc14bf`.
- `bash scripts/local_pr_review.sh` is reconciled on the final clean descendant
  after this evidence block is committed; the handoff records that exact result
  rather than claiming a dirty-tree advisory run as final proof.
- Issue #46 was not reproduced: both full requests returned, with the first
  failing admission and the controlled retry completing. The issue remains
  separate and open because a successful run does not resolve its historical
  stall.
- Final-head GitHub checks and the latest review are reconciled from the live PR
  after this evidence block is committed, because another plan-only evidence
  commit would itself create a new head. The final handoff must identify the
  exact head, tested merge revision where applicable, check results, unresolved
  thread count, and review outcome.

### Historical evidence (earlier revisions; not final-head proof)

- Expected-failing-before phone regression: reproduced the original unguarded
  acceptance before implementation; the same case now fails closed.
- `python -m unittest -q tests.test_site_extraction`: 51 tests passed, including
  both-side/mixed/cap/provenance and prompt-visible-source boundaries.
- Latest review-boundary pass: `python -m unittest -q
  tests.test_site_extraction` plus the targeted generation action test passed 55
  tests. These prove redirect
  rejection and apex/www acceptance, ambiguous title rejection with explicit
  site-name recovery, leaf-only nested-list records, `Pay`/`Cart` label rejection,
  contact fetch-origin wiring, complete CTA pairs, site-owned logo semantics, and
  source-owned-or-neutral action labels.
- `python -m unittest tests.test_generation -q`: 143 tests passed, including
  source-owned capability labels, neutral CTA wording, and destination-first
  rejection behavior.
- `python -m unittest discover -s tests -q`: 339 tests passed with 34 skipped
  after the source-owned-or-neutral action-label guard replaced the incomplete
  capability denylist.
- Final affected-path check after moving the Google review label from neutral
  vocabulary into its code-owned build contract: four focused action, aggregate
  review, CTA-pair, and logo-ownership tests passed. A subsequent full-suite run
  hung during teardown without returning a verdict; the exact-head GitHub unit
  gate remains the required final full-suite proof.
- Review-mode action binding check: the focused card-mode and aggregate-mode
  build/admission regressions both passed after their distinct code-owned labels
  were bound to the corresponding review mode.
- Final assertion-ownership boundary pass: 57 focused tests passed, covering
  restricted-versus-complete exception claims, negated visible and linked
  phone/email contacts versus positive links, and accessible-label versus
  visible-action wording.
- Latest paired-authority boundary pass: `python -m unittest -q
  tests.test_site_extraction tests.test_generation` passed 202 tests. It covers
  conflicting versus matching single-title identity, linked and plain-text contact
  negation plus the affirmative "do not hesitate" idiom, image-derived accessible
  labels, valid and swapped source action pairs (including neutral wording), and
  malformed or label-authority-exceeding pair contracts. The final review-boundary
  cases also cover inherited and externally referenced form actions plus an image
  node used directly as an `aria-labelledby` target. An inert or orphaned
  `formaction` remains subject to output URL sanitization but cannot create source
  URL or pair authority.
- Latest source-unit boundary pass: `python -m unittest -q
  tests.test_site_extraction tests.test_generation` passed 203 tests. It covers
  complete multi-target accessible names, image replacement text, fail-closed
  partial references, controlled identity wrappers versus arbitrary name
  substrings, and leaf ownership across sibling nested articles.
- Latest identity-corroboration probe rejects partial H1 and title components
  against a longer explicit site name while accepting a full business component
  from a `Home - Business Name` title. Lone title components use the same
  agreement rule, including a metadata-corroborated `Welcome to Business Name`
  surface.
- `ruff check --ignore F401 lib/site_extraction.py lib/generation.py
  tests/test_site_extraction.py tests/test_generation.py`: passed. The unignored
  scoped run still reports two pre-existing unused contract imports in
  `tests/test_generation.py`; they are outside this correction.
- `ruff check --select F401,F821 pipeline.py build.py` still reports the
  pre-existing unused `generate_text` import in `pipeline.py`; no unrelated cleanup
  is included here.
- `ruff check lib/site_extraction.py tests/test_site_extraction.py`: passed.
- `ruff format --check lib/site_extraction.py tests/test_site_extraction.py`:
  passed.
- `python -m compileall -q pipeline.py lib tests`: passed.
- `git diff --check`: passed.
- `PYTHONUNBUFFERED=1 GENERATION_TIMEOUT_SECONDS=1800 python build.py
  examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft
  --skip-deploy`: passed against local Ollama with the model fully resident on
  the RTX 3090; wrote `outputs/builds/drees-plumbing-inc/index.html`.
- Required placeholder-leak grep: 0 matches.
- Required `Upfront Flat-Rate|Surprise Fees|Free Estimates|Owner Answers`
  fabricated-claim grep: 0 matches.
- `bash scripts/local_pr_review.sh`: passed on the committed diff against
  `origin/main`.

## Estimated diff size

The reviewed diff deliberately exceeds the 400-line soft target because the
extraction document has many
independently consumed fact paths: structure admission without provenance checks
still trusts fabricated facts, while provenance checks without shape and resource
admission leave ambiguous traversal and unsafe boundaries. The enforcement and
its both-side proof are one authority change and must ship together.
