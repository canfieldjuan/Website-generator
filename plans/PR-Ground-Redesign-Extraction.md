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
| `PRRT_kwDOTDYaKM6foY7Q`: a preceding recipient subject could survive the first-token scope check | Claim admission must retain a complete preceding relationship instead of enumerating recipient verbs. | `Free Estimates` from both known `members receive ...` and unknown `members redeem ...` predicates is rejected; each complete claim and only explicit meaning-preserving wrappers such as `We offer ...` pass. | fixed/superseded | `lib/site_extraction.py:407-420,474-550,1410-1418`; `tests/test_site_extraction.py:542-592` |
| `PRRT_kwDOTDYaKM6fodmA`: `are eligible for` bypassed recipient-scope admission | Shortening a published assertion must fail closed on unapproved leading clauses while preserving complete qualified claims. | `Free Estimates` from `Maintenance-plan members are eligible for Free Estimates` is rejected; the complete claim and explicit `Call for ...` / `Call to request ...` wrappers pass. | fixed/superseded | `lib/site_extraction.py:407-420,474-550`; `tests/test_site_extraction.py:542-592` |
| `PRRT_kwDOTDYaKM6foSbJ`: `input[type=button]` labels bypassed action admission | Every visible button-like input label must use the same source-label authority; ordinary data inputs must remain outside that guard. | Unsupported button/reset labels are rejected, source-owned labels are admitted, and text inputs remain unaffected. | fixed/superseded | `lib/site_extraction.py:241-248,1062-1068`; `lib/generation.py:2318-2327`; `tests/test_site_extraction.py:599-623`; `tests/test_generation.py:1365-1395` |
| `PRRT_kwDOTDYaKM6foY7S`: generated `aria-labelledby` targets ignored their own ARIA name | The generated action name must follow the same recursive ARIA precedence as source-side action naming before label authority is checked. | A referenced node whose `aria-label` is unsupported now rejects even when its descendant text is neutral; the inverse valid ARIA override remains admitted. | fixed/superseded | `lib/generation.py:2228-2292`; `tests/test_generation.py:1325-1351` |
| `PRRT_kwDOTDYaKM6foSbL`: broad logo container text became identity | A broad brand container may contribute only bounded name surfaces, not its description or unrelated link text. | The WordPress-style `site-identity` header admits `Acme Plumbing`; `Quality work since 1990` and a sole `Call Us` link do not become identity. | fixed/superseded | `lib/site_extraction.py:731-769,1125-1129`; `tests/test_site_extraction.py:973-990` |
| `PRRT_kwDOTDYaKM6fodmD`: a heading record absorbed content from a sibling wrapper with its own heading | Record and section consumers must share heading-boundary detection while retaining their explicit container policy. | A Drain Cleaning record cannot acquire a warranty from a sibling wrapper headed Water Heater Repair; a wrapper without a competing heading remains part of the record, and existing card/list/figure plus single-page boundaries still pass. | fixed/superseded | `lib/site_extraction.py:888-924,927-978`; `tests/test_site_extraction.py:2048-2087` plus existing boundary suite |
| `PRRT_kwDOTDYaKM6fojuq`: nested atomic FAQ records could donate fields across entries | An atomic record can own descendants only when it is the leaf instance of that record type. | The outer `<details>` can no longer pair the first nested question with the second nested answer; a single leaf `<details>` still admits its own question and answer. | fixed/superseded | `lib/site_extraction.py:915-929`; `tests/test_site_extraction.py:2090-2133` |
| `PRRT_kwDOTDYaKM6fojur`: generated ARIA actions bypassed label authority | Source collection and generated-output validation must use one action-identification rule; destination sanitization remains independently mandatory. | `div[role=button]` is recognized by the shared classifier in both consumers: a source-owned label passes and an unsupported generated label rejects. An unlabelled `xlink:href` is still sanitized. | fixed/superseded | `lib/site_extraction.py:752-762,1086-1097`; `lib/generation.py:22-23,2333-2348`; `tests/test_site_extraction.py:594-628`; `tests/test_generation.py:1424-1440` |
| `PRRT_kwDOTDYaKM6fojus`: a main-only H1 page had no admissible enrichment scope | Page-section ownership must admit one H1-owned `<main>` only when no explicit article/section owns the content. | A common `<main><h1>...<div>...` services page admits; a main containing separate explicit sections cannot become a broad scope that recombines them. | fixed/superseded | `lib/site_extraction.py:968-992`; `tests/test_site_extraction.py:1932-1974` |
| `PRRT_kwDOTDYaKM6fokih`: `apply to` escaped recipient-scope detection | Claim preservation must be fail-closed around unknown leading predicates and recipient-bearing `to`, not grow a denylist of English verbs. | Shortened claims from both `apply to ...` and the unseen predicate `members redeem ...` reject without adding either predicate to production code; complete forms and explicit action-infinitive wrappers pass. | fixed/superseded | `lib/site_extraction.py:407-420,474-550`; `tests/test_site_extraction.py:542-592` |
| `PRRT_kwDOTDYaKM6fovtC`: source form endpoints existed only in label/destination pairs | A real source form endpoint must remain usable as a generated form endpoint without becoming link-navigation authority. | A source `<form action="/submit">` now admits the same generated form, while a generated link to `/submit`, a generated form to link-only `/contact`, and contact-derived `tel:`/`mailto:` form actions reject. | fixed/superseded | `pipeline.py:144-237`; `build.py:351-384`; `lib/generation.py:375-428,2301-2404`; `tests/test_site_extraction.py:1720-1798`; `tests/test_generation.py:1194-1263,1563-1592` |
| `PRRT_kwDOTDYaKM6fo4Hb`: a partial FAQ question became an item title | Nonassertive FAQ admission may preserve a complete source question, not promote one inner phrase as a standalone claim. | `Free Estimates` from `Do you offer Free Estimates?` now rejects, while the complete question remains admitted. | fixed/superseded | `lib/site_extraction.py:1398-1433,1601-1637`; `tests/test_site_extraction.py:2134-2167` |
| `PRRT_kwDOTDYaKM6fo4Hc`: `role=link` bypassed action-label authority | Source collection and generated output must share one semantic action classifier for native and ARIA actions. | Source-owned ARIA button/link labels admit and unsupported generated ARIA button/link labels reject; an unroled focusable element remains non-action content. | fixed/superseded | `lib/site_extraction.py:761-771,1095-1106`; `lib/generation.py:2345-2361`; `tests/test_site_extraction.py:594-630`; `tests/test_generation.py:1427-1450` |
| `PRRT_kwDOTDYaKM6fo4Hd`: non-URL image metadata became image authority | Metadata authority must be selected by a bounded resource-URL property set, not by the substring `image`. | Common Open Graph/Twitter image URL properties admit; `og:image:alt`, `og:image:width`, and `og:image:type` cannot become image URLs. | fixed/superseded | `lib/site_extraction.py:238-249,1139-1148`; `tests/test_site_extraction.py:1343-1385` |
| `PRRT_kwDOTDYaKM6fo4He`: form-control ARIA references used raw descendant text | Every ARIA-labelled consumer must use the same recursive accessible-name resolver, including nested references and replacement text. | Image `alt` and target `aria-label` now supply the control name; conflicting raw target text no longer grants field authority. | fixed/superseded | `lib/site_extraction.py:700-739,1222-1261`; `tests/test_site_extraction.py:1245-1341` |
| `PRRT_kwDOTDYaKM6fo8_x`: descendants of ignored source containers became visible evidence | Dormant source containers cannot authorize identity, claims, actions, fields, records, or sections; the explicitly code-owned image inventory must remain available. | A claim, action, and form label found only below `<template>` now reject while their visible equivalents admit. The code-owned image-inventory template still admits its recorded image URL. | fixed/superseded | `lib/site_extraction.py:1043-1090`; `tests/test_site_extraction.py:1386-1465` |
| `PRRT_kwDOTDYaKM6fo8_y`: descendant ARIA names bypassed generated action admission | Source and generated actions must use one recursive accessible-name rule while visible conflicting labels remain independently checked. | A child image whose `aria-label` says `Book Appointment` now rejects even when its `alt` is neutral; a source-owned accessible and visible label admits. | fixed/superseded | `lib/site_extraction.py:689-785`; `lib/generation.py:2238-2254`; `tests/test_generation.py:1427-1477` |
| `PRRT_kwDOTDYaKM6fo8_z`: non-image `src` values became image authority | Image evidence attributes belong only to image-bearing elements; metadata and CSS resources retain their separate bounded paths. | `video[src]` and video `source[src]` reject as image URLs while `picture > source[srcset]` remains admissible. | fixed/superseded | `lib/site_extraction.py:1149-1206`; `tests/test_site_extraction.py:1387-1415` |
| `PRRT_kwDOTDYaKM6fpAf9`: mixed nested record types could donate fields | Atomic records must yield ownership to nested semantic record containers as well as nested instances of their own tag. | A `<details>` wrapping separate `<article>` FAQ records can no longer pair one article's question with another's answer; leaf details and existing nested-list boundaries remain valid. | fixed/superseded | `lib/site_extraction.py:877-980`; `tests/test_site_extraction.py:2316-2377` |
| `PRRT_kwDOTDYaKM6fpAf_`: native labels discarded image replacement text | Every form-label association must use the same replacement-text-aware accessible-name resolver as ARIA references. | `<label for=email><img alt=Email></label>` now admits `Email`; conflicting and partial labels still reject. | fixed/superseded | `lib/site_extraction.py:689-785,1277-1314`; `tests/test_site_extraction.py:1245-1342` |
| `PRRT_kwDOTDYaKM6fpGr5`: explicitly hidden source subtrees became visible evidence | One renderedness rule must exclude browser-inert tags, hidden inputs/attributes, and inline render suppression from every source collector and generated claim scanner. | Claims/actions under `<template>`, `hidden`, `noscript`, and `display:none` now reject; visible equivalents remain admissible. | fixed/superseded | `lib/site_extraction.py:697-707,820-826,1134-1152`; `lib/generation.py:1359-1483`; `tests/test_site_extraction.py:1472-1531,2032-2048` |
| `PRRT_kwDOTDYaKM6fpGr7`: fetchable relative URLs stayed relative | A URL marked fetchable must be the resolved, same-origin HTTP(S) URL that the fetcher can request. | `/services` is admitted as `https://acme.test/services`; same-page fragments and cross-origin destinations remain non-fetchable. | fixed/superseded | `lib/site_extraction.py:648-670,1838-1843`; `tests/test_site_extraction.py:1039-1091` |
| `PRRT_kwDOTDYaKM6fpGr8`: font URLs became image authority through CSS | CSS resources must be admitted by declaration type, and the fetch inventory plus verifier must share that classifier. | `@font-face src: url('/brand.woff2')` rejects as image evidence while `background-image: url('/hero.jpg')` admits. | fixed/superseded | `lib/site_extraction.py:252-267,688-694,1143-1144,1270-1272`; `pipeline.py:495-500`; `tests/test_site_extraction.py:1420-1444` |
| `PRRT_kwDOTDYaKM6fpGr9`: metadata image alt lost its image owner | Bounded Open Graph/Twitter image metadata must preserve ordered URL/alt ownership rather than admit unrelated page-wide text. | `og:image` followed by its `og:image:alt` admits the exact pair; a different alt rejects. | fixed/superseded | `lib/site_extraction.py:241-251,1198-1220`; `tests/test_site_extraction.py:1446-1470` |
| `PRRT_kwDOTDYaKM6fpOBq`: input action `value` bypassed generated label admission | Every independently rendered, accessible, or tooltip label surface on one action must pass the same source-owned or bounded-neutral policy in every consumer. | A submit input whose admitted ARIA label hides an unsupported visible `value` now rejects; when both labels and their destination pairs are source-owned, it admits. | fixed/superseded | `lib/site_extraction.py:742-773,856-876,1253-1271`; `pipeline.py:208-234`; `lib/generation.py:2260-2280,2367-2382`; `tests/test_generation.py:1427-1458`; `tests/test_site_extraction.py:2050-2072` |
| `PRRT_kwDOTDYaKM6fpOBr`: neutral action tokens composed an unsupported review claim | Capability-neutral fallback labels must be bounded complete phrases; token membership cannot authorize a new semantic assertion. | `Read All Reviews` now rejects without source label/pair authority while exact neutral `Contact Us` and `Learn More` labels admit; the same review label admits when source-owned. | fixed/superseded | `lib/generation.py:404-432,2152-2215,2367-2382`; `tests/test_generation.py:1460-1492` |
| `PRRT_kwDOTDYaKM6fpZkx`: unknown trailing claim predicates could be discarded | Asserted fields may omit only an explicit meaning-preserving leading wrapper; every unknown trailing clause remains part of the assertion regardless of its vocabulary. | `Free Estimates` from `Free Estimates require membership` rejects without adding `require` to a denylist; the complete qualified claim admits. Other trailing assertions now follow the same fail-closed rule. | fixed/superseded | `lib/site_extraction.py:557-592,1623-1648`; `tests/test_site_extraction.py:386-462,553-590` |
| `PRRT_kwDOTDYaKM6fpZk0`: conflicting explicit identity metadata independently authorized both names | Identity authority must resolve one uniquely best-supported canonical identity across independent metadata, structured DOM, title, and H1 channels; a tied conflict authorizes neither candidate. | Conflicting `application-name` and `og:site_name` now select the name corroborated by title/H1 and reject the other; without corroboration both reject. | fixed/superseded | `lib/site_extraction.py:1010-1052,1260-1446,1580-1594`; `tests/test_site_extraction.py:1051-1078` |
| Carried-forward plumber fixture and zero-match claims | Acceptance evidence must prove a fresh artifact from the tested code revision, not reuse historical output. | The clean `6ee2c00` invocation rewrote the artifact, exited 0, and both required scans found zero matches; the rewritten bytes were rendered and inspected. | fixed/superseded | Verification block below; `/dev/shm/website-generator-pr47-fixture-6ee2c00.log`; `/dev/shm/website-generator-pr47-browser-render-6ee2c00.png` |
| Issue #46 historical URL-redesign stall | A one-token probe or one successful fixture cannot prove the historical runtime stall resolved. | The required full fixture completed, so the stall did not reproduce in this run; no current code defect was established. | separate issue | Issue #46; verification block below |
| `PRRT_kwDOTDYaKM6fpeiS`: class-based stylesheet suppression is not applied before evidence collection | Raw fetched HTML does not own browser-computed visibility; a correct computed-visibility policy must account for the CSS cascade, media state, viewport, and external stylesheets once at the fetch/render boundary. | The class-hidden claim is present in fetched HTML and is admitted; the equivalent inline-hidden claim rejects. A selector regex here would not establish computed visibility. | separate issue | `lib/site_extraction.py:805-815,1328-1335`; issue #48 |
| `PRRT_kwDOTDYaKM6fpeiT`: an adjacent sibling disclaimer did not scope its claim | Claim ownership must preserve every adjacent paragraph-like assertion owned by the same bounded record without using an English predicate list. | Adjacent paragraph/small runs now form one structural owner occurrence; a shortened claim rejects, the complete owner passes, and a separately contained assertion remains independent. | fixed/superseded | `lib/site_extraction.py:1278-1409,1778-1825`; `tests/test_site_extraction.py:606-647` |
| `PRRT_kwDOTDYaKM6fpeiU`: prompt-declared classifications were plain strings | Every bounded derived classification must be admitted by the executable schema, and the runtime prompt must name the same supported values. | Invalid site/section/image/page/layout/conversion classifications now reject locally; a document exercising valid values passes. Existing code-owned FAQ support was added to the stale prompt enum rather than removed. | fixed/superseded | `lib/site_extraction.py:51-132,156-306`; `references/01-site-analysis-prompt.md:64-164`; `tests/test_site_extraction.py:675-768` |
| `PRRT_kwDOTDYaKM6fplaH`: `Membership required` escaped the first sibling implementation | Sibling ownership must be structural, not dependent on enumerating qualifier vocabulary. | The semantic marker helper was removed. Both `Members only` and `Membership required` are rejected when shortened, and their complete structural owner passes. | fixed/superseded | `lib/site_extraction.py:1355-1409,1778-1825`; `tests/test_site_extraction.py:606-628,642-647` |
| `PRRT_kwDOTDYaKM6fplaI`: normalized claim deduplication lost occurrence ownership | Equal text in different DOM records must retain distinct owners so one scoped occurrence cannot suppress a separate unrestricted occurrence. | Assertion occurrences are no longer deduplicated; a scoped `Free Estimates` card plus a separate unrestricted card admits from the unrestricted occurrence. | fixed/superseded | `lib/site_extraction.py:1280-1283,1355-1409,1778-1825`; `tests/test_site_extraction.py:630-640` |
| `PRRT_kwDOTDYaKM6fplaJ`: contact presentation labels were treated as arbitrary claim prefixes | Schema-known contact fields may omit only their exact field-owned presentation label; the exception must not weaken general claims. | `Location:`, `Address:`, and `Hours:` admit their values through field-local contracts; `Former address:` still rejects. | fixed/superseded | `lib/site_extraction.py:687-695,1778-1825,1979-2005,2074-2087`; `tests/test_site_extraction.py:649-673` |
| `PRRT_kwDOTDYaKM6fprAP`: heading-led cards did not contribute one assertion owner | A page-level claim must preserve adjacent heading and paragraph assertions owned by the same bounded card, independent of heading level or qualifier vocabulary. | Heading-led cards now use one owner across `h2` through `h6`, paragraph, and small-text siblings; shortened claims reject and the complete owned assertion admits. Record/section evidence retains its existing field-local ownership so valid composite enrichment remains supported. | fixed/superseded | `lib/site_extraction.py:1323-1438,1719-1757,1813-1896`; `tests/test_site_extraction.py:606-668` |
| `PRRT_kwDOTDYaKM6fprAQ`: labeled contact fields discarded adjacent correction owners | A schema-owned presentation label may be omitted, but an unlabeled sibling or trailing qualifier in the same owner may not be discarded. Independently labeled contact fields must remain separate facts. | Exact Location/Address/Hours labels partition field records. A same-element label or exact heading label can wrap its value; unlabeled sibling corrections and same-line trailing qualifiers reject, including across sentence punctuation. | fixed/superseded | `lib/site_extraction.py:548-555,695-713,1374-1438,1813-1896,2047-2070`; `tests/test_site_extraction.py:670-728` |
| `PRRT_kwDOTDYaKM6fpyOX`: non-identity H1 cards remained outside assertion ownership | Claim ownership is determined by a heading's structural role, not by its tag number or whether identity is sourced elsewhere. | The shared heading-owner classifier covers `h1` through `h6`; an explicit metadata identity plus a claim-bearing H1 cannot drop its following restriction, while the complete H1-owned claim admits. | fixed/superseded | `lib/site_extraction.py:716-722,1394-1445`; `tests/test_site_extraction.py:649-673` |
| `PRRT_kwDOTDYaKM6fpyOY`: flat heading walks absorbed peer sections | Heading claim ownership must follow the document hierarchy, and paragraph facts must not inherit unrelated heading text. | A heading owns following claim elements only until a same-or-higher peer heading or field boundary. Paragraph/small-text runs remain directional and local, so `Licensed and insured.` under About admits without absorbing the peer Hours section. | fixed/superseded | `lib/site_extraction.py:716-722,1394-1466`; `tests/test_site_extraction.py:675-686` |
| `PRRT_kwDOTDYaKM6fp4hx`: adjacent leaf block claims remained tag-dependent | Assertion ownership must follow actual direct source contexts while preserving explicit independent-record, heading, and field boundaries; the HTML spelling of a leaf block cannot change its owner. | Sibling leaf `<div>` blocks now share their direct parent owner, so `Free Estimates` cannot discard `Members only`; the complete owned assertion admits. Existing independent record containers and peer heading sections remain separate. | fixed/superseded | `lib/site_extraction.py:1394-1484`; `tests/test_site_extraction.py:606-699` |
| `PRRT_kwDOTDYaKM6fp4hy`: validated brand identity and home destination were authorized independently | A code-owned generated navigation action must bind its exact validated label to its exact code-owned destination, just as source actions do. | The redesign action contract carries the exact site name paired with the catalog-owned `/` home route. A linked brand to `/` admits; rebinding that name to another otherwise admitted URL rejects. | fixed/superseded | `pipeline.py:146-247`; `lib/generation.py:2218-2382`; `tests/test_generation.py:4720-4774`; `tests/test_site_extraction.py:2213-2377` |
| `PRRT_kwDOTDYaKM6fp-5p`: list/wrapper restrictions fell outside a heading owner | An assertion owner must include the text-bearing sibling subtree, not only a sibling that is itself the nearest text context, while record and heading boundaries remain intact. | An H3 followed by a `ul/li` restriction now owns the list subtree; the shortened benefit rejects and the complete qualified assertion admits. Nested same-or-higher headings and independent semantic records stop the owner. | fixed/superseded | `lib/site_extraction.py:1394-1514`; `tests/test_site_extraction.py:688-714` |
| `PRRT_kwDOTDYaKM6fp-5q`: content-bearing labels were classified as neutral actions | Neutral fallback wording cannot assert that an About, FAQ, gallery, map, service, team, or work destination exists. Those labels require exact source label/pair authority. | The content/capability category was removed from the bounded neutral set. `Meet Our Team` pointed at an otherwise admitted contact URL rejects; the exact source-owned `Meet Our Team` to `/team` pair admits. Truly generic `Contact Us` and `Learn More` controls remain neutral; `Request Service` requires exact source or code ownership. | fixed/superseded | `lib/generation.py:2152-2200,2350-2366`; `tests/test_generation.py:1460-1528` |
| `PRRT_kwDOTDYaKM6fqEKl`: admitted relative image resources remained relative | Source-relative image and logo evidence must become one usable source-resolved resource before mirroring and generation consume it. | Homepage and enrichment admission now canonicalize every validated `image_url`, `logo_url`, and `images[].url` against that document's source URL. The extraction integration test proves `/hero.jpg` reaches the mirror as `https://acme.test/hero.jpg`, while a relative action URL remains unchanged. | fixed/superseded | `lib/site_extraction.py:2361-2399,2488-2489`; `tests/test_site_extraction.py:78-160,2528-2533` |
| `PRRT_kwDOTDYaKM6fqEKn`: final CTA checklist contradicted action admission | The model prompt and executable action contract must permit the same exact source-owned or bounded-neutral labels. | The checklist no longer forbids `Submit` or `Contact Us`; it repeats the shared exact-source-or-bounded-neutral rule and still prohibits invented capability wording. | fixed/superseded | `references/02-redesign-gen-prompt.md:254-258,601-620`; `tests/test_site_extraction.py:3145-3178`; `lib/generation.py:2152-2200,2350-2366` |
| `PRRT_kwDOTDYaKM6fqME4`: direct rendered text after a claim heading escaped its owner | Claim ownership must follow rendered text nodes as well as element wrappers while retaining record, peer-heading, and schema-field boundaries. | `<h3>Free Estimates</h3>Members only.` now rejects the shortened benefit and admits the complete qualified assertion through the same owner walk used for wrapped sibling content. | fixed/superseded | `lib/site_extraction.py:1415-1525`; `tests/test_site_extraction.py:635-757` |
| `PRRT_kwDOTDYaKM6fqME5`: `Request Service` was globally neutral | A label that asserts a service-request capability must require exact source or code ownership; it cannot be an unrestricted neutral phrase. | An unowned `Request Service` action now rejects. The standalone builder explicitly owns only `Request Service` paired with its generated `#contact` section, and rebinding that label to another destination rejects. | fixed/superseded | `lib/generation.py:2152-2198,2350-2364`; `build.py:94-99,359-370`; `tests/test_generation.py:1488-1529,1615-1661` |
| `PRRT_kwDOTDYaKM6fqME8`: uncorroborated multiple H1 candidates selected the first candidate | Unseeded identity candidates must resolve to one uniquely supported identity; DOM order alone cannot grant authority. | Both names from a two-H1 page now reject, while a single H1 and an independently corroborated H1 identity retain their existing positive paths. | fixed/superseded | `lib/site_extraction.py:1687-1728`; `tests/test_site_extraction.py:1199-1249` |
| `PRRT_kwDOTDYaKM6fqME-`: SVG `xlink:href` actions bypassed label admission | Source extraction and generated-output validation must classify the same link elements, destination attributes, labels, and label/destination pairs. | An unsupported label on `<svg><a xlink:href=...>` now rejects; the exact source-owned SVG label/destination pair admits in both source extraction and generated-output validation. | fixed/superseded | `lib/site_extraction.py:330,1015-1025,1577-1608`; `lib/generation.py:2105-2119,2350-2364`; `tests/test_site_extraction.py:2259-2293`; `tests/test_generation.py:1292-1318` |

## Mechanism

`lib/site_extraction.py` owns both structure admission and source grounding. A
bounded JSON Schema accepts only the analysis shape consumed by the pipeline.
Before source admission, the verifier parses the exact cleaned HTML slice supplied
to the extraction model, normalizes browser-equivalent text, gathers link/image
attributes and their source-relative absolute forms, and checks every
source-owned leaf through a field-specific evidence rule. Claim-bearing text uses
DOM-local assertion contexts so inline markup cannot hide negation while separate
elements cannot alter one another's meaning. Direct text-bearing sibling subtrees
share an owner independently of their HTML wrapper tag, but independent semantic
records, peer heading sections, and schema-known fields remain explicit boundaries. CTA labels must exactly match an
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
depending on an incomplete capability-verb denylist. Content-bearing navigation
labels such as About, FAQ, gallery, services, and team are not neutral: they require
an exact source label and label/destination pair so the fallback cannot fabricate a
destination or misdescribe another admitted URL.
A source-owned label remains bound to the destination on its source action, even
when that wording also belongs to the neutral vocabulary. Accessible action
labels include replacement text from image, area, and image-input controls;
source collection and generated-body admission use one shared action-element
classifier and construct the same complete, whitespace-normalized label.
Destination sanitization remains independent, so a destination-bearing element
cannot escape URL admission merely because it lacks an action label. An admitted
phone or email display value remains
bound to its matching contact destination unless that exact source action pair
was observed. Submit buttons and image inputs resolve their effective destination
from `formaction`, an explicitly referenced form, or their owning ancestor form;
source collection and output pair admission use the same resolver. Link navigation
and form submission use separate destination-authority sets: a source form action
or effective submit override can remain a generated form endpoint but cannot
become a generated link, and a source link cannot become a generated form
endpoint. Output URL sanitization separately checks every declared destination
attribute, including an inert or orphaned `formaction`, without promoting that
attribute into source authority. Pair evidence does not itself grant either kind
of URL authority. The redesign catalog's exact validated business name and its
internal `/` home route are likewise carried as one code-owned action pair; neither
half can authorize rebinding the business identity to another destination.
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
Negation and conditional qualifiers are retained across the complete owning
clause rather than a fixed word window. Published-claim shortening fails closed
when a leading clause exists unless it is one of the explicit
meaning-preserving wrappers, and recipient-bearing `to` clauses fail closed
unless `to` introduces a bounded action infinitive such as `to request`. This
removes dependence on enumerating recipient predicates. Figures are atomic content
records. Heading-delimited section fallback stops at sibling `article` and
`section` containers, and an article wrapping nested sections cannot become a
broad content scope. Every atomic record type uses the same leaf-ownership rule:
an outer instance containing another instance of its own record type cannot
authorize a composite extracted item. A main-only page becomes a content scope
only when exactly one H1 owns it and no explicit article or section supplies a
narrower scope.
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

### Current revision evidence (2026-09-06)

- Code revision under test: `910fd3629dd21a5b12e38e8d194877a1af7240ec`.
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
- The next exact-head review reproduced an eligibility preposition outside the
  first-token check and a weaker duplicate heading-record loop. Complete-clause
  scope scanning now preserves only the controlled request wrapper, and record
  extraction now uses the shared heading-owned fragment routine with an explicit
  record-container policy. The exact eligible-benefit and sibling-wrapper probes
  now reject.
- The current exact-head review reproduced four distinct paths: nested
  `<details>` recombination, a generated `role=button` label bypass, an
  `apply to` recipient qualifier dropped from a claim, and rejection of a valid
  main-only H1 enrichment page. The final implementation does not enumerate the
  newly reported verb or duplicate action tags. It uses one shared action
  classifier, fail-closed claim-prefix admission with explicit safe wrappers, a
  uniform same-type leaf-record rule, and a bounded main/H1 page-scope rule.
- The next exact-head review reproduced one additional shared-contract defect:
  source form endpoints were retained in label/destination pairs but omitted from
  URL admission. The action contract now carries separate link and form endpoint
  sets through source collection, prompt instructions, build generation, and
  output validation. This admits exact source forms without granting those
  endpoints to links or granting contact-derived schemes to forms.
- The following exact-head review reproduced four more independent consumers of
  the same extraction-authority contract: partial nonassertive FAQ titles, ARIA
  links, non-URL image metadata fields, and raw form-control ARIA target text.
  They now use complete-context question admission, the shared semantic action
  classifier, a bounded image-resource property set, and the shared recursive
  accessible-name resolver respectively.
- The final exact-head review reproduced one remaining ancestry defect: text
  nested below an ignored source container could still authorize visible output.
  `SourceEvidence.from_html()` now preserves only the bounded code-owned image
  inventory and stylesheet image resources before removing every ignored
  container. All downstream identity, claim, action, form, record, and section
  collectors therefore operate on the same visible evidence tree.
- A complete paginated thread reconciliation then exposed four current paths
  hidden beyond the first 100 review threads: descendant ARIA labels, non-image
  `src` values, mixed-type nested records, and native labels composed from image
  replacement text. These are now enforced by shared recursive accessible/visible
  name functions, image-bearing element ownership, and one semantic nested-record
  ownership rule. The browser-inert predicate is also reused by the downstream
  source-action contract so ignored containers cannot re-enter through a sibling
  consumer.
- The next exact-head review reproduced four more concrete sides of those same
  policies: explicit render suppression, relative fetch URLs, non-image CSS
  resources, and metadata image-alt ownership. Source and generated scanners now
  share one renderedness predicate; fetchability returns and stores the resolved
  request URL; the fetch inventory and verifier share declaration-typed CSS image
  extraction; and ordered Open Graph/Twitter image groups preserve URL/alt pairs.
- The following exact-head review reproduced two action-label paths: a submit
  input's visible `value` could hide behind an admitted ARIA label, and arbitrary
  combinations of neutral tokens could spell an unsupported review claim. Source
  evidence, source contract construction, and generated validation now share one
  multi-surface action-label extractor. Capability-neutral fallbacks are bounded
  complete phrases, while any review wording requires exact source label/pair
  authority.
- The next exact-head review reproduced two remaining root-policy gaps. Asserted
  text now rejects every unknown trailing clause instead of trying to enumerate
  predicates that might restrict it; only explicit meaning-preserving leading
  wrappers may be omitted. Identity candidates now compete by support from
  independent metadata, structured DOM, title, and H1 channels, and tied
  conflicts grant no identity authority.
- The latest exact-head review produced three findings, but only two belong to
  this raw-extraction authority slice. Adjacent qualifier siblings now create a
  bounded owner scope shared by every asserted-text consumer, and every
  explicitly enumerated derived classification is enforced by the executable
  schema. Class-based computed visibility is tracked in issue #48 because a
  raw-HTML selector patch cannot establish cascade, media, viewport, or external
  stylesheet behavior.
- The follow-up exact-head review proved that the first sibling implementation
  still encoded qualifier vocabulary and collapsed equal strings across DOM
  records. That mechanism was replaced: structural paragraph-like runs now own
  ordered assertion occurrences, and validation evaluates each occurrence
  independently. Schema-known contact presentation labels use a separate
  field-local wrapper contract, so they do not weaken general claim admission.
- The subsequent exact-head review found the two remaining sides of that one
  ownership model. Page-level claim owners now include heading-led cards across
  every supported subheading level. Schema-known field labels form explicit
  field boundaries, while unlabeled siblings stay attached; only an exact local
  label or exact heading label may be omitted from the admitted field value.
  Nested record and section evidence keeps field-local ownership because those
  consumers already require populated fields to share one bounded source record.
- The next exact-head review exposed the limits of the flat heading set and
  forward sibling walk. Assertion ownership is now directional and hierarchical:
  claim-bearing H1 through H6 headings own following content only until a
  same-or-higher peer, while ordinary paragraph facts remain in paragraph runs
  and do not absorb a preceding heading. The same field-label boundary continues
  to separate independently labeled contact facts.
- The final paginated reconciliation exposed two more independently reproduced
  contract gaps. Leaf assertion ownership still depended on `p`/`small`/heading
  tag names, and the redesign catalog's business-name label was not bound to its
  internal home route. Direct source contexts now define claim owners within the
  existing record/heading/field boundaries, and the action contract carries the
  exact validated site name plus `/` as one code-owned pair.
- The next exact-head review proved both policies still had a category boundary,
  not a missing example. Heading owners now include adjacent text-bearing wrapper
  subtrees such as lists until an independent record, schema field, or
  same-or-higher heading. The neutral-action fallback no longer contains labels
  that assert About, FAQ, gallery, map, service, team, or work content; those
  require an exact source-owned label/destination pair.
- The final exact-head review exposed two consumer-boundary inconsistencies rather
  than more vocabulary exceptions. Image admission accepted relative and resolved
  forms as equivalent but returned the relative form to downstream consumers; all
  admitted image-resource fields now resolve once against their source document.
  The final CTA checklist also contradicted the executable action rule; it now
  states the same exact-source-or-bounded-neutral contract as generation admission.
- The latest paginated review exposed four independently reproducible paths through
  shared policies, not four words to add to denylists. Assertion ownership now
  includes direct rendered text nodes; unseeded H1 candidates use the same unique
  identity arbitration as every other channel; source and output action consumers
  share `href` plus `xlink:href`; and `Request Service` moved from global neutral
  vocabulary to the standalone builder's exact label/destination contract.
- Focused claim, identity, SVG-action, and builder-action boundary probes passed:
  `python -m unittest -q
  tests.test_site_extraction.SiteAnalysisGroundingTests.test_claim_text_preserves_adjacent_owned_disclaimers
  tests.test_site_extraction.SiteAnalysisGroundingTests.test_business_name_requires_assertive_identity_evidence
  tests.test_site_extraction.SiteAnalysisGroundingTests.test_cta_requires_a_complete_source_action_pair
  tests.test_generation.BodyAssemblyTests.test_body_action_destinations_are_source_owned
  tests.test_generation.BodyAssemblyTests.test_neutral_action_labels_are_bounded_complete_phrases
  tests.test_generation.BodyAssemblyTests.test_build_action_contract_binds_canonical_form_labels`:
  6 tests passed.
  Their negative sides cover dropped direct-text qualifications, both candidates
  from an ambiguous two-H1 page, an unsupported SVG action label, an unowned
  service-request capability, and destination rebinding. Their positive sides
  preserve the complete qualified claim, a single/corroborated H1, an exact
  source-owned SVG pair, and the builder-owned `Request Service` to `#contact`
  pair.
- Current affected modules: `python -m unittest -q tests.test_site_extraction
  tests.test_generation`: 226 tests passed. These modules cover the new direct-text,
  identity arbitration, SVG action, capability label, and exact builder-pair
  boundaries alongside the existing image, ownership, and prompt contracts.
- Full suite on code revision `300e135f0939bbef454a61a2f715255ee8557c3f`:
  `python -m unittest discover -s tests -q`: 368 tests passed with 34 skipped.
- Scoped static checks passed:
  `ruff check --ignore F401,F541 build.py lib/site_extraction.py
  lib/generation.py tests/test_site_extraction.py tests/test_generation.py`;
  `python -m compileall -q build.py lib/site_extraction.py lib/generation.py
  tests/test_site_extraction.py tests/test_generation.py`; and `git diff --check`.
- The final code revision `300e135f0939bbef454a61a2f715255ee8557c3f`
  used
  `PYTHONUNBUFFERED=1 GENERATION_TIMEOUT_SECONDS=1800 python build.py
  examples/prospect-plumber-template.json --skip-image-gen --skip-email-draft
  --skip-deploy` with `local:qwen3-30b-a3b:latest` through Ollama. The clean
  invocation began after the `2026-09-06T03:08:27-05:00` capture with no model
  resident and exited 0 before the `2026-09-06T03:09:57-05:00` post-run capture;
  the configured model was then resident 100% on the GPU. No email or deployment
  path ran. The first generated body was correctly rejected for unsupported `Not
  a Franchise` wording; the bounded correction passed full admission. Log:
  `/dev/shm/website-generator-pr47-fixture-300e135.log`.
- The successful invocation rewrote
  `outputs/builds/drees-plumbing-inc/index.html`; size was 72027 bytes, inode
  3311297, mtime was `2026-09-06 03:09:52.789210998 -0500`, and SHA-256 was
  `2728fda49162dae9477be2acbad5f97e299382eddf3f2837424e51e686c23796`.
- Exact required placeholder and case-insensitive forbidden-claim scans both
  returned grep status 1 and zero matches. Logs:
  `/dev/shm/website-generator-pr47-placeholder-scan-300e135.log` and
  `/dev/shm/website-generator-pr47-forbidden-scan-300e135.log`.
- Rendered spot-check: a loopback server returned HTTP 200 and headless Chrome
  produced a nonblank 1440x3180 styled page showing Drees Plumbing identity,
  phone, navigation, `Request Service` CTA, hero, service grid, trust content,
  and customer reviews. The current
  artifact was served directly from this invocation's output. Full render:
  `/dev/shm/website-generator-pr47-browser-render-300e135.png`,
  SHA-256
  `12cdb4df66e4cdd750eed2ff64ff8364b1e472b6ea177be0ddbfddefc076e99a`.
- `bash scripts/local_pr_review.sh` is reconciled on the final clean descendant
  after this evidence block is committed; the handoff records that exact result
  rather than claiming a dirty-tree advisory run as final proof.
- Issue #46 was not reproduced: the full request returned and completed. The issue
  remains separate and open because a successful run does not resolve its
  historical stall.
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
