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
   pricing, credentials, geography, or service promises.
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
source-owned leaf through a field-specific evidence rule. Phone and email fields
use canonical comparison; URL and image fields must match an observed attribute
or its deterministic source-relative resolution. Classifications, layout choices,
color selections, and image-generation guidance are admitted as typed derived
metadata, not source facts.

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
  drop nearby source negation or match inside a larger word.
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
- `python -m unittest -q tests.test_site_extraction`: 18 tests passed, including
  both-side/mixed/cap/provenance and prompt-visible-source boundaries.
- `python -m unittest discover -s tests`: 303 tests passed; 34 skipped.
- `ruff check lib/site_extraction.py tests/test_site_extraction.py`: passed.
- `ruff format --check lib/site_extraction.py tests/test_site_extraction.py`:
  passed.
- `python -m compileall -q pipeline.py lib tests`: passed.
- `git diff --check`: passed.
- Required no-deploy fixture: blocked outside this diff. A one-token Ollama
  `/api/chat` probe passed after restarting `ollama-local.service`, but the
  production-shaped build request then stalled waiting for its HTTP status. One
  bounded run produced a 1200-second read timeout, and the clean-service retry
  reproduced the same full-request stall before artifact persistence. No
  placeholder/claim scan is reported because no new artifact was written. This
  separate runtime defect is tracked in issue #46.
- `bash scripts/local_pr_review.sh`: passed on the committed diff against
  `origin/main`.

## Estimated diff size

The reviewed diff is 1,520 insertions and 46 deletions across seven files. This
exceeds the 400-line soft target because the extraction document has many
independently consumed fact paths: structure admission without provenance checks
still trusts fabricated facts, while provenance checks without shape and resource
admission leave ambiguous traversal and unsafe boundaries. The enforcement and
its both-side proof are one authority change and must ship together.
