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
6. Remove redesign-prompt instructions that synthesize availability promises from
   urgency classification or require trust claims when no source-owned signal
   exists, and state the derived-versus-source authority boundary at the
   generation prompt.
7. Verify against exactly the truncated HTML slice sent to the model, not unseen
   trailing source, and add boundary regressions for valid and fabricated source
   facts, malformed and mixed structures, limits, relative/absolute URL evidence,
   code-owned provenance, and invalid enrichment isolation.

### Files touched

- `lib/site_extraction.py`
- `pipeline.py`
- `references/02-redesign-gen-prompt.md`
- `tests/test_site_extraction.py`
- `requirements.txt`
- `requirements-dev.txt`
- `plans/PR-Ground-Redesign-Extraction.md`

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
destinations, preserving these separations after extraction. Flat heading records
stop before sibling structural containers, including list wrappers, so a section
heading cannot turn a collection of independent cards into one evidence record.
Definition-list terms and their owned definitions form individual records.
Definition-list wrappers are also record boundaries, so an enclosing article or
section cannot recombine a term with another term's definition.
Navigation, CTA, footer, and fetch-page labels remain paired with the destination
of the same interactive source element. Phone and email scans operate per local
DOM context rather than concatenating unrelated page nodes. Assertion context
survives commas, parenthetical contrast modifiers, and colons until a real
sentence or contrast boundary; inline links inherit their surrounding prose for
assertion checks while retaining a link-local contact context. Claim-bearing
content fields require assertive evidence, except FAQ questions. Single-page
navigation labels bind to their own anchors, and the section content is validated
inside that exact target container. The code-owned image inventory is emitted as
real prompt-visible image attributes, so the same bounded URLs remain available
to validation even when their original elements fall after HTML truncation.
Claim-bearing section headings, body text, taglines, locations, addresses, and
hours preserve the same assertion context instead of treating an unanswered
question or conditional as an affirmative fact. Form-field evidence comes only
from labels and accessible names attached to actual non-action
`input`/`select`/`textarea` controls. Image alt text remains paired with the exact
source image URL rather than being recombined from page-wide values, including
responsive `<picture><source>` candidates owned by the same fallback image. A
logo URL additionally requires explicit logo semantics on its source image or
owning brand container; merely appearing elsewhere on the page is insufficient.
Fetchability is overwritten by code from the admitted destination and effective source URL:
same-document anchors and same-page URLs are not queued, while a distinct HTTP(S)
page remains fetchable even if the model says otherwise.
Business identity uses assertion evidence. Nested content containers prevent a
broad article from recombining separate cards. Form labels must match a complete
accessible label, duplicate references to the same source label are collapsed,
and labels are assigned one-to-one to distinct controls. Social platform names
are derived from recognized destination hosts; otherwise the name and URL must
belong to the same source action.
Only actual submit inputs contribute input-value CTA evidence; reset, image,
button, and text inputs cannot promote their values into published CTA copy.
Classifications, layout choices, color selections, and image-generation guidance
are admitted as typed derived metadata, not source facts.

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

- Expected-failing-before phone regression: reproduced the original unguarded
  acceptance before implementation; the same case now fails closed.
- `python -m unittest -q tests.test_site_extraction`: 46 tests passed, including
  both-side/mixed/cap/provenance and prompt-visible-source boundaries.
- `python -m unittest discover -s tests -q`: 331 tests passed with 34 skipped on
  the current working tree.
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

The reviewed diff is 3,099 insertions and 72 deletions across seven files. This
exceeds the 400-line soft target because the extraction document has many
independently consumed fact paths: structure admission without provenance checks
still trusts fabricated facts, while provenance checks without shape and resource
admission leave ambiguous traversal and unsafe boundaries. The enforcement and
its both-side proof are one authority change and must ship together.
