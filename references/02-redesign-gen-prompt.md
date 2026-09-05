# 02 -- Redesign Generation Prompt

Feed this prompt the JSON from the analysis step plus a theme and any overrides.
Output is a complete, self-contained HTML file.

---

## INPUTS

- SITE_JSON: full JSON object from the analysis prompt
- THEME: one of the 6 layout themes below (controls structure + typography + spacing)
- COLOR_MODE: "brand" to use colors extracted from the site, "override" to specify custom colors
- ACCENT_OVERRIDE: hex color -- only used when COLOR_MODE is "override", otherwise pass "none"
- NOTES: any client-specific instructions, or "none"

---

## COLOR STRATEGY (read this carefully)

The theme controls layout, typography, spacing, and component style.
The brand colors from the JSON control the actual color values.

When COLOR_MODE is "brand":
- Use brand.colors.primary as --accent
- Use brand.colors.secondary as --secondary (or derive one if null)

When COLOR_MODE is "override":
- Use ACCENT_OVERRIDE as --accent and derive the full palette from it

COLOR DERIVATION RULES HAVE BEEN REMOVED TO PREVENT HALLUCINATIONS.
You must NOT try to guess background and text colors.
Instead, you must apply either `class="theme-light"` or `class="theme-dark"` to the `<body>` tag.
- If the original site was dark mode, use `<body class="theme-dark">`.
- If the original site was light mode, use `<body class="theme-light">`.
- The CSS framework handles all text, border, and background scales automatically.

---

## COLOR DISCIPLINE (read this carefully -- this is what separates premium from generic)

The --accent color is the brand's PRIMARY color. It must be used SPARINGLY to create
visual hierarchy and draw the eye to the single most important action on the page.

**Use --accent for MAXIMUM 3–4 elements total:**
1. The single primary CTA button (emergency call or top booking button only)
2. Active nav state / nav CTA button
3. Section indicator dots (`.sec-dot`, `.sb-dot`) -- these are tiny, they don't count as accent-heavy
4. Logo area IF the brand uses it there

**Do NOT use --accent for:**
- The `<em>` in the hero headline (use `#fff` or `rgba(255,255,255,0.85)` instead for fullbleed heroes)
- The secondary CTA button -- use `var(--bg-card2)` / `var(--border-hi)` / white instead
- Badge backgrounds on every card -- use `var(--text-muted)` for most, --accent for one featured item only
- Trust strip text
- Footer elements
- More than one button on any single section

**The rule: if you removed the --accent color, the layout should still be fully functional
and readable. Accent is emphasis, not structure.**

Examples of correct restraint:
- Law firm: green accent ONLY on the "Call Now" button. Everything else is dark navy/charcoal.
- Restaurant: warm amber ONLY on the "Reserve a Table" button. Menu cards are neutral.
- HVAC: red accent ONLY on the emergency call CTA. Service grid cards are white on gray.

---

## FAMILIARITY PRINCIPLE

The owner should look at this redesign and feel "this is still my site, just way better"
not "who made this completely different thing."

Preserve:
- Their color family (even if you refine the specific shades)
- Their content hierarchy (if news was the main focus, it stays the main focus)
- Their logo (always present, prominent, not restyled)
- Their nav structure (same links, same order)

Modernize:
- Layout (grid system, whitespace, component structure)
- Typography (better font choices that match their tone)
- Visual polish (hover states, transitions, image treatments)
- Information density (reduce clutter, improve scannability)

Multi-page consistency: if this homepage is part of a multi-page deliverable,
the nav HTML, footer HTML, and any evidence-backed trust strip must be identical
across every page. Trusted code applies the shared `:root` and font settings.
Interior pages are generated using prompt 04. Never vary nav structure between
pages.

---

## THEME REFERENCE

Themes control layout personality and typography ONLY.
Color values come from the brand JSON, not the theme.

| Name           | Layout feel                        | Typography                          | Best for                          |
|----------------|------------------------------------|-------------------------------------|-----------------------------------|
| broadcast      | Dense, editorial, ticker + grid    | Condensed display + serif headlines | Radio, news, sports               |
| editorial      | Newspaper, column-based, refined   | Slab or serif display + serif body  | News, civic, nonprofits           |
| civic          | Bold, structured, high-contrast    | Strong geometric sans               | Government, schools, churches     |
| warm           | Friendly, slightly loose, inviting | Rounded sans + serif body           | Restaurants, retail, services     |
| minimal        | Open, airy, lots of whitespace     | Clean geometric sans throughout     | Portfolio, professional services  |
| brand-forward  | Hero-driven, large imagery         | Display-heavy, modern sans          | Entertainment, gyms, events       |

---

## SYSTEM PROMPT

You are a senior frontend developer and UI designer specializing in website
redesigns for local businesses and community organizations.

You produce the variable `<body>` for clean, modern, production-grade
single-file HTML/CSS.
CRITICAL RULE: DO NOT WRITE CUSTOM CSS. Compose one `<body>...</body>` fragment
from the section patterns below using only the provided allowed-class catalog.
Trusted code owns the doctype, `<html>`, `<head>`, CSS, font import, and `:root`
tokens and assembles them after validating your body.
- Do NOT invent new classes or layout structures.
- Do NOT output `<style>`, `<script>`, `<head>`, `<html>`, or a doctype.
- Do NOT output HTML head metadata (`<base>`, `<link>`, `<meta>`, or a page `<title>`) anywhere in the body; an accessibility `<title>` nested inside `<svg>` is allowed.
- You are an injection engine: map the content to the existing template blocks.
- Uses only real content from the site JSON (no placeholder text, no lorem ipsum)

Output rules:
- Output ONLY one raw `<body>...</body>` fragment. No markdown code fences,
  preamble, trailing commentary, doctype, `<html>`, `<head>`, `<style>`, or
  `<script>`. The first characters must be `<body` and the last characters
  must be `</body>`. No HTML comment may precede the opening `<body>` tag.
- Do not emit any unresolved template token.
- Do not output deployment metadata; trusted code inserts it into the final
  document head.
- Apply the selected theme's layout and semantic classes. Trusted code applies
  its exact colors, fonts, and root tokens.
- IMAGE RULES: Prioritize using any images with context='hero' or 'logo' from the JSON. If the original images are poor but a generated hero image was provided in the JSON, you MUST use the generated hero image for the main hero section.
- All links use real URLs from the JSON
- Image failure behavior is added by trusted code after admission. Do not emit
  event-handler attributes.

---

## USER PROMPT

Using the data below, produce the complete redesigned `<body>` fragment from
the section patterns below and the allowed-class catalog.

THEME: [INSERT THEME]
COLOR_MODE: [brand OR override]
ACCENT_OVERRIDE: [HEX OR none]
NOTES: [INSERT OR none]

SITE JSON:
[PASTE JSON HERE]

SOURCE AUTHORITY BOUNDARY:
- Source-owned identity, contact, navigation, CTA, section, trust-signal, and
  image/link values in SITE JSON have passed local evidence admission. Those
  values may be rendered as business facts.
- `site.type`, brand/style selections, `site_structure`, urgency/goal booleans,
  `booking_platform`, `homepage_blueprint`, and `image_generation_prompt` are
  derived design metadata. Use them only to choose presentation. Never turn
  them into a new availability, pricing, credential, geography, service, or
  performance claim.
- A derived urgency value does NOT prove 24/7 service, same-day availability,
  walk-ins, free consultations, free estimates, or any similar promise. Render
  such a promise only when its exact source-owned wording appears elsewhere in
  SITE JSON.

ALLOWED BODY CLASSES:
[PASTE THE CLASS CATALOG FROM 03-BASE-TEMPLATE.HTML HERE]

Use the catalog's classes for grids, cards, buttons, and layouts. Omit sections
that do not apply. Do not
emit CSS or color declarations; trusted code owns the head and root tokens.

---

## ABOVE THE FOLD FORMULA

Every redesign must satisfy the 3-second rule: a visitor knows what the business
does, where it operates, and what to do next without scrolling.

Hero section structure (always in this order):
1. **Full-bleed hero image section** — If the JSON contains ANY image with context='hero' or 'background', you MUST render it using BOTH the `dual-cta-hero` AND `hero-fullbleed` CSS classes on the section element, with the image as an inline `style="background-image: url('[URL]')"`. The `hero-fullbleed` class handles the overlay and min-height automatically — all text will be white. This is NON-NEGOTIABLE — the hero must be a visual, image-driven section.
2. Headline = [Primary Service or Value] + [Location]. Keep it under 8 words.
   Example: "Drain Cleaning in Effingham, IL" when "Drain Cleaning" is a
   source-owned service, or "Acme Plumbing — Effingham, IL" from the grounded
   business name and location.
   The headline is derived. Do NOT use `site.tagline` verbatim as the headline if
   the tagline is a mission statement. Build the headline from the most specific
   grounded service in `sections[]` plus `site.location`. If no grounded service
   exists, use `site.name` plus `site.location`; do not substitute `site.type` as
   a claimed service. The tagline rarely makes a good headline.
3. Subheadline = one concrete outcome statement -- what the visitor GETS, not what
   the business BELIEVES. Must NOT echo the headline's key phrase.
   - CORRECT: Join exact service names and a source-owned location without adding
     a response-time, price, outcome, or availability promise.
   - CORRECT: Reuse one complete source-owned outcome or coverage line verbatim.
   - WRONG: "Working together as a team to provide dedicated advocacy." (this is a mission statement, not a benefit)
   - WRONG: Any tagline that starts with "We believe", "Our mission", or "Committed to"
   - WRONG: Repeating the headline's primary noun phrase. If the headline says
     "Dedicated Advocacy" the subhead must NOT also say "dedicated advocacy".
     Pick a different source-owned angle: outcome, geographic coverage, tenure,
     or specific service scope.

   SUBHEAD SOURCE PRIORITY -- pick the first available:
   a. A specific outcome line found in `conversion_profile.trust_signals.social_proof_lines` that names a service or coverage area.
   b. A concrete service-scope line assembled only from the exact service names
      in `sections[]` items. Add no availability, price, consultation, outcome,
      or geographic qualifier that is absent from those source-owned values.
   c. An exact source-owned availability or geographic coverage line already
      present in `sections[]`, `existing_ctas`, or `social_proof_lines`.
   d. ONLY if none of the above are extractable, the existing `site.tagline` -- but ONLY if it does not match the mission-statement patterns above.
   If nothing usable exists, output NO subhead element rather than a mission statement.
4. Dual CTAs (see below)
5. Trust strip only when SITE JSON contains an evidence-backed trust value (see
   below); otherwise omit it completely

The headline and both CTAs must be visible without scrolling on a 1280px desktop
and a 390px mobile screen.

---

## DUAL CTA ARCHITECTURE

Every local business has two visitor types. The design must serve both.

Read conversion_profile.urgency_type from the JSON and apply the matching pattern:

Urgency controls CTA layout and relative emphasis only. It is not evidence of
hours, response time, same-day service, walk-in availability, or any other
business promise.

**urgency_type = "emergency"**
- Primary CTA: large click-to-call button -- phone number visible in the button,
  accent color. Add a "24/7" or "Same-Day" badge only when that exact promise is
  present in a source-owned field.
- Secondary CTA: form or booking button, lower visual weight
- Sticky header: phone number always visible on scroll

**urgency_type = "planned"**
- Primary CTA: booking, reservation, or form button -- specific label (not "Submit", not "Contact Us")
- Secondary CTA: phone number as text link or smaller button
- No sticky phone required

**urgency_type = "both"**
- Two equal-weight CTAs side by side
- Left: call button (emergency path)
- Right: form/booking button (planned path)
- Label the distinction without inventing urgency copy: "Call Now" vs
  "Schedule a Visit"

CTA COPY RULE: Always use first-person or action-specific labels.
"Request My Quote" not "Submit"
"Book My Appointment" not "Book Appointment"
"Call Now" not "Contact Us"

---

## TRUST STRIP

Include a trust strip only when SITE JSON contains at least one source-owned
review, quantified-experience, credential, award, or credibility value. When
present, it sits directly below the hero CTAs, visible without scrolling.

Content priority order (use the highest one available, skip lower if higher exists):
1. Third-party review score: star rating + count + platform (e.g. "4.9 stars -- 312 Google Reviews") -- HIGHEST VALUE
2. Quantified experience: years in business, cases handled, clients served (e.g. "Serving Effingham since 1987", "500+ cases handled")
3. Credentials / certifications / bar membership badges
4. Awards or recognitions (named, specific -- not "award-winning")
5. Exact source-owned credibility line from `social_proof_lines`

NEVER fill the trust strip with the firm's own mission statement or tagline.
A self-authored claim like 'We work hard for our clients' has zero persuasion value.
If none of the source-owned values above exists, omit the trust strip. Never
invent or infer years established, staff counts, geographic coverage, review
scores, credentials, or any substitute trust content just to fill the component.

Design: horizontal band, muted background (one step off --bg), small condensed font,
icons or star glyphs if space allows. Not a section -- a compact strip, 44-52px tall.

TRUST SIGNAL PLACEMENT RULE:
Never isolate all social proof on a single testimonials page.
When evidence-backed trust content exists, place at least one trust signal within
visual proximity of every major CTA on the page. In the content sections, inline
review quotes or certification badges near the section CTA. In the sidebar
action block, repeat the review summary below the primary button. When none
exists, omit these elements rather than generating substitutes.

---

## BLUEPRINT-DRIVEN LAYOUT (read this BEFORE the industry table)

If `homepage_blueprint` is present in the JSON, it is the primary driver of the
homepage's section order, NOT the industry priority table below. The blueprint
captures the original site's information architecture. Preserving it is the
single most important thing the redesign does to feel like "the same site, but
modernized" rather than "a generic theme with this client's logo dropped in."

How to apply the blueprint:

1. **Start with `homepage_blueprint.section_sequence`** as the ordered list of
   section blocks on the homepage. Render each block top-to-bottom in that
   order using the base template's matching component (e.g. `services-grid`
   primitive -> `.services-grid` / `.service-card`; `team-grid` -> `.team-grid`;
   `inline-form` -> `.contact-form-wrap`; `cta-band` -> a full-width call-to-action
   band; `map-block` -> map embed plus address; etc.). Modernize the styling --
   the primitive is preserved, the visual treatment is upgraded.

2. **Honor `hero_type`**:
   - `hero-image` -> full-bleed image hero (already the default; use the hero
     image from `images[]` or the generated hero).
   - `hero-split` -> 50/50 split hero, image on one side, copy + CTAs on the
     other. Do NOT default to full-bleed if the original was a split.
   - `hero-typography` -> text-only hero, big display headline, no background
     image. Use generous whitespace; an accent rule or shape is fine.
   - `hero-video` -> full-bleed; treat the same as `hero-image` for the mockup
     (use a still image as the background).
   - `hero-carousel` -> render the first slide as a static hero. Do not build a
     real carousel for the mockup.
   - `none` -> the page should start directly with the first content section.
     No oversized hero band.

3. **`above_fold_form: true` is non-negotiable.** If the original homepage had
   a contact/inquiry form above the fold, the redesign MUST also have one above
   the fold. Place it in the hero (split layout with form on one side) or as
   the very first section under the hero. Visitors expect to find it; removing
   it kills conversions even if the redesign is prettier.

4. **Layer the industry priority table ON TOP, do not replace.** After laying
   out the blueprint's sections, check the industry table below. If a section
   the industry table requires is missing from the blueprint, ADD it at the
   industry-recommended position. Example: a law firm's original homepage may
   have had only a hero + contact form. The blueprint preserves that, but the
   industry table requires a practice areas grid and attorney bios on legal
   sites -- ADD those (sourced from enriched `sections[]` entries that carry a
   `source_url`) at sensible positions.

5. **`footer_layout` controls the footer column count.** Use 1, 2, 3, or 4
   columns to match. `footer-stack` is a single column on all breakpoints --
   minimal sites do this.

6. **Never remove a section the blueprint listed.** If the blueprint says
   `testimonial-block` is in the sequence, render one. If there are no
   testimonials in the JSON, render the section as a single quoted social-proof
   line from `conversion_profile.trust_signals.social_proof_lines` rather than
   omitting the section.

If `homepage_blueprint` is absent or empty, fall back to the industry priority
table below as the section order. The industry table is the floor; the
blueprint is the structural ceiling.

---

## INDUSTRY SECTION PRIORITY

Based on site.type from the JSON, use this section order for the primary content area
WHEN no homepage_blueprint is present, OR to fill in sections the blueprint is missing.
Sections not applicable to the site type should be omitted entirely.

| site.type       | Section order (primary content area)                                              |
|-----------------|-----------------------------------------------------------------------------------|
| radio / news    | ticker -> hero promos -> news grid -> sports -> calendar                          |
| restaurant      | dual CTA (reserve + order) -> menu preview -> photo gallery -> hours/location map |
| home-services   | dual CTA hero -> services grid -> trust signals -> service area coverage          |
| legal           | consultation CTA -> practice areas GRID (no rank numerals) -> testimonial -> attorney bios |
| dental/medical  | booking widget -> treatment pages -> before/after gallery -> team bios            |
| real-estate     | search/valuation tool -> featured listings -> neighborhood guides -> agent bio    |
| ecommerce       | featured products -> category grid -> local pickup info -> review highlights      |
| civic           | announcements -> services directory -> events calendar -> contact/hours           |
| church          | service times (prominent) -> upcoming events -> ministries -> giving CTA          |
| nonprofit       | mission statement -> impact numbers -> volunteer/donate dual CTA -> programs      |
| services        | dual CTA hero -> services list -> trust signals -> service area or contact        |
| portfolio       | work samples grid -> skills/process -> client logos -> contact form               |

When site.type is "other" or unclear, default to: dual CTA hero -> services/content -> trust -> contact.

LEGAL SITES SPECIFIC RULE: Practice areas must render as a uniform card grid.
Do NOT use numbered ranked lists (.list-n numerals) for legal, medical, dental, or professional services.
All practice areas are equal entry points -- no service should appear ranked above another.

MULTI-LOCATION RULE: If the JSON contains multiple addresses, render ALL of them.
A visitor from a secondary service area who sees only one address may assume they are out of range.

ENRICHED INTERIOR-PAGE RULE: Sections that carry a `source_url` field were
extracted from a dedicated interior page (not the homepage hero). Render
them on the homepage as preview grids that link to the full interior page:

- `type: "services"` with `source_url` -> render up to 6 items in
  `.services-grid` / `.service-card`. Add a "See all" link or button
  pointing to `source_url`. The link label should be specific
  (e.g. "See all practice areas"), not generic.
- `type: "team"` with `source_url` -> render up to 4 items in
  `.team-grid` / `.team-card`. Use `title` as the name, `tag` as the
  role, `image_url` as the headshot, and `meta`
  as the short bio. Add a "Meet the full team" link to `source_url`.
- `type: "misc"` with `tag: "faq"` on items -> render up to 4 items as
  an FAQ preview. Add a "See all FAQs" link to `source_url`.
- `type: "misc"` with `tag: "about"` on items -> render as a narrative
  block using paragraph styling, no grid. Link a "Learn more" button to
  `source_url` if helpful.

Sections WITHOUT a `source_url` come from the homepage itself -- render
them inline with no "See all" link.

Do NOT invent new layouts. Use the existing `.services-grid`,
`.team-grid`, `.benefits-grid`, and `.faq-list` classes from the base
template.

CONTACT FORM RULE: If `site_json.contact_form` is present, render it
on the homepage in a contact section using `.contact-form-wrap`:
- One input per entry in `contact_form.form_fields`. Pick the appropriate
  `.form-input` / `.form-textarea` / `.form-select` from the base
  template based on the label (e.g. multi-line text for a "Message" or
  "Tell us..." field).
- The submit button label must be specific and action-oriented (e.g.
  "Send My Request"), never "Submit".
- Display `contact_form.contact_info` (phone, email, address, hours)
  next to the form. Use `tel:` and `mailto:` links.
- Link the section heading or a small "Full contact page" link to
  `contact_form.source_url` if present.

If `contact_form` is absent, do not invent a form. Render only what the
JSON contains.

---

## FONT ASSIGNMENTS

Use these entries only to choose semantic theme classes. Do not paste font
imports or font assignments; trusted code applies them in the head and CSS.
Color values in these specs are placeholders -- replace with derived brand colors.

### broadcast
```
Google Fonts: Barlow+Condensed:wght@600;700;800;900&family=Barlow:wght@400;500;600&family=Playfair+Display:wght@700;900
--font-display: 'Barlow Condensed', sans-serif;
--font-body: 'Barlow', sans-serif;
--font-serif: 'Playfair Display', Georgia, serif;
--nav-height: 64px;
--sidebar-width: 360px;
--card-radius: 2px;
--card-style: flush-grid      /* cards sit flush, gap is the border */
--headline-style: serif       /* news headlines use --font-serif */
--badge-style: tight          /* small all-caps badges */
```

### editorial
```
Google Fonts: Oswald:wght@500;600;700&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=Playfair+Display:wght@700;900
--font-display: 'Oswald', sans-serif;
--font-body: 'Source Serif 4', Georgia, serif;
--font-serif: 'Playfair Display', Georgia, serif;
--nav-height: 60px;
--sidebar-width: 340px;
--card-radius: 0px;
--card-style: bordered        /* cards have explicit borders */
--headline-style: serif
--badge-style: underline      /* category as colored underline, not pill */
```

### civic
```
Google Fonts: Fjalla+One&family=Noto+Sans:wght@400;500;600&family=Merriweather:ital,wght@0,700;1,400
--font-display: 'Fjalla One', sans-serif;
--font-body: 'Noto Sans', sans-serif;
--font-serif: 'Merriweather', Georgia, serif;
--nav-height: 64px;
--sidebar-width: 340px;
--card-radius: 4px;
--card-style: elevated        /* cards have subtle shadow or strong border */
--headline-style: display     /* headlines use --font-display */
--badge-style: filled
```

### warm
```
Google Fonts: Lexend:wght@500;600;700;800&family=Lato:wght@400;700&family=Lora:ital,wght@0,400;0,700;1,400
--font-display: 'Lexend', sans-serif;
--font-body: 'Lato', sans-serif;
--font-serif: 'Lora', Georgia, serif;
--nav-height: 68px;
--sidebar-width: 340px;
--card-radius: 8px;
--card-style: rounded
--headline-style: serif
--badge-style: pill
```

### minimal
```
Google Fonts: DM+Sans:wght@400;500;600;700&family=DM+Serif+Display:ital@0;1
--font-display: 'DM Sans', sans-serif;
--font-body: 'DM Sans', sans-serif;
--font-serif: 'DM Serif Display', Georgia, serif;
--nav-height: 60px;
--sidebar-width: 320px;
--card-radius: 8px;
--card-style: ghost           /* minimal borders, whitespace does the work */
--headline-style: serif
--badge-style: dot            /* colored dot + label instead of pill */
```

### brand-forward
```
Google Fonts: Syne:wght@700;800&family=Manrope:wght@400;500;600
--font-display: 'Syne', sans-serif;
--font-body: 'Manrope', sans-serif;
--font-serif: 'Syne', sans-serif;
--nav-height: 68px;
--sidebar-width: 360px;
--card-radius: 6px;
--card-style: image-forward   /* hero images dominate, text overlays */
--headline-style: display
--badge-style: filled
```

---

## LAYOUT MODE (read before building the body)

Not every site uses the sidebar layout. Use this table to decide:

| Theme / Site Type                              | Layout to use                                      |
|------------------------------------------------|----------------------------------------------------|
| broadcast, editorial                           | Two-column: `.layout` with `.primary` + `.sidebar` |
| minimal, brand-forward                         | Full-width single column — DO NOT use `.layout` grid or `.sidebar`. Build sections as full-width `<section>` blocks with `.page-wrap` inner containers. |
| civic, warm                                    | Two-column sidebar OR single column — match the industry. Restaurants/services: single column. Civic/gov: sidebar OK. |
| site.type = legal, portfolio, services, nonprofit | ALWAYS single column. No sidebar.              |
| site.type = radio, news, sports                | ALWAYS two-column with sidebar.                    |

For **single-column layouts**: replace the `.layout` grid entirely. Build each content section as:
```html
<section style="padding: 4rem 0;">
  <div class="page-wrap">
    <!-- section content using template card classes -->
  </div>
</section>
```

---

## COMPONENT BEHAVIOR RULES

### Ticker
Include only if site has news, alerts, or announcements.
Use --accent as ticker background.
Label pill on left uses a darkened version of --accent.

### Nav
Logo image first with adjacent text fallback; trusted code hides an unavailable
image.
Links: condensed font, uppercase, 12-13px, spaced tracking.
CTA button uses --accent, right-aligned.
Sticky, z-index 100.

### Hero / Promo Strip
If promo images exist in JSON: full-bleed image cards, 16:9 aspect ratio,
gradient overlay linear-gradient(to top, rgba(0,0,0,0.88), transparent 60%),
text and tag overlaid at bottom.
If no promo images: typographic cards with left accent-border treatment.
Include only if site has featured promos or contests.

### Primary Content Grid
Two column: flexible main area + fixed sidebar (--sidebar-width).
Main area: top 3 items as featured grid (1 full-width + 2 half), remaining as ranked list.
Featured headline: --font-serif, 20-22px.
Ranked list: --font-serif, 14px, numbered index.
Category badge: small, uppercase, accent background.

### Sidebar Order
1. Primary action block (stream/CTA) -- always first
2. Calendar/events -- if present in JSON
3. Quick links grid -- 2-col, 6 max
4. Social links -- if present in JSON

### Images
Always set explicit aspect-ratio on containers.
Always object-fit: cover.
Never emit event-handler attributes. Trusted code adds the fixed image-failure
behavior after admission.
Gradient overlays only when text is placed over images.

### Footer
Wrap the entire footer in exactly one `<footer class="site-footer">`. Place the
`.footer-grid` first and `.footer-bottom` second inside that wrapper, then close
the footer before `</body>`.
3-col: brand+contact | nav links | secondary/misc links.
Brand name in --font-display at large size (36-42px).
All real contact data from JSON.
Close the footer with one compact `.footer-bottom` containing only a copyright
`<p>` and, when the JSON supplies one, an `.ft-aux-link`. Never put
`.page-body`, `.page-cta-block`, or any `.page-cta-*` component inside the
footer; those are interior-page components and are unavailable to homepage
generation.

---

## QUALITY CHECKLIST

Before outputting, verify:
- [ ] All nav link URLs are real (from JSON nav array)
- [ ] All content headlines are verbatim from JSON
- [ ] All image src values are real URLs from JSON; trusted code owns failure behavior
- [ ] No CSS, doctype, `<html>`, `<head>`, `<style>`, or `<script>` output
- [ ] No lorem ipsum or placeholder text
- [ ] Mobile collapses correctly at 768px
- [ ] Ticker present only if site has news/alerts content
- [ ] Logo visible in nav (with text fallback)
- [ ] Brand colors are recognizable from the original site
- [ ] Above-the-fold shows headline (service + location) and dual CTAs; an
      evidence-backed trust strip is also visible there when one exists
- [ ] Dual CTA pattern matches conversion_profile.urgency_type
- [ ] CTA labels are specific and action-oriented (no "Submit" or "Contact Us")
- [ ] Phone number is in the sticky nav if urgency_type is emergency or both
- [ ] Trust strip is omitted when SITE JSON has no source-owned trust value
- [ ] When source-owned trust exists, at least one trust signal appears near every major CTA
- [ ] Section order matches the industry priority table for this site.type
- [ ] If homepage_blueprint is present: section_sequence is preserved in the output, no listed primitive is missing, and additions follow the blueprint > industry-table layering rule
- [ ] If homepage_blueprint.above_fold_form is true: an inline form is rendered above the fold in the redesign
- [ ] homepage_blueprint.hero_type is honored (split, typography, image, etc. -- not always defaulted to full-bleed)
- [ ] Footer column count matches homepage_blueprint.footer_layout when present

---

## DEPLOYMENT METADATA

Trusted code derives, sanitizes, and inserts deployment metadata into the final
document head. Do not output a deployment comment or recreate those notes in
the generated body.
