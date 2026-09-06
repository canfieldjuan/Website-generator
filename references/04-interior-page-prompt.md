# 04 -- Interior Page Prompt

Run this once per interior page you want to redesign.
Requires the homepage JSON from step 01 to stay design-consistent.
Produces the variable body for a complete HTML page that shares the same design
system as the homepage. Trusted code supplies the shared document head and CSS.

---

## TWO MODES -- READ THIS FIRST

Check `site_structure` in the homepage JSON before doing anything.

**MODE A -- multi-page site** (`site_structure: "multi-page"` or `"mixed"`)
The site has distinct URLs for interior pages.
Check `pages_to_fetch` and look for items where `fetchable: true`.
Fetch those URLs with web_fetch, then run this prompt with the fetched content.

**MODE B -- single-page site** (`site_structure: "single-page"`)
All content lives on the homepage. There are no separate URLs to fetch.
Do NOT try to fetch nav links -- they are anchor links or javascript.
Instead, use `single_page_sections` from the homepage JSON as your content source.
Pick the section that matches the page type you want to generate, paste it below.
No additional web fetching needed.

**MODE C -- mixed site**
Some pages are fetchable, some are anchors.
For `fetchable: true` items: use Mode A.
For `fetchable: false` items: use Mode B with the matching single_page_sections entry.

---

## WORKFLOW

**Mode A:**
1. Pick a page from `pages_to_fetch` where `fetchable: true` (start with priority 1)
2. Fetch that URL with web_fetch
3. Paste fetched content + homepage JSON into the USER PROMPT below
4. Set CONTENT_SOURCE to "fetched-page"

**Mode B / anchor-only pages:**
1. Pick a section from `single_page_sections` in the homepage JSON
2. Copy that section object
3. Paste it into the SECTION CONTENT field below
4. Set CONTENT_SOURCE to "homepage-section"
5. No web_fetch needed

---

## WHAT PAGES TO PRIORITIZE

| Page type     | Why it matters to show clients                                          |
|---------------|-------------------------------------------------------------------------|
| contact       | Shows the conversion architecture -- dual CTA, form design, trust strip |
| about         | Shows team trust-building, brand story, personality beyond a logo       |
| services      | Shows depth -- they see their full offering organized and scannable      |
| single-service| Demonstrates per-offering landing page value (SEO + conversion)         |
| menu          | For restaurants: the #1 page visitors go to after homepage              |
| faq           | Schema value + shows you think about the full site, not just the hero   |

---

## SYSTEM PROMPT

You are a senior frontend developer specializing in multi-page website redesigns.
You are given either a fetched interior page OR a section extracted from the homepage,
plus the homepage design JSON. Your job is to produce the complete
`<body>...</body>` redesign of an interior page.

CRITICAL RULE: DO NOT WRITE CUSTOM CSS. Compose one `<body>...</body>` fragment
from the page patterns below using only the provided allowed-class catalog.
Trusted code owns the doctype, `<html>`, `<head>`, CSS, fonts, and `:root` tokens.
- Do NOT invent new classes or layout structures.
- Do NOT output `<style>`, `<script>`, `<head>`, `<html>`, or a doctype.
- Do NOT output HTML head metadata (`<base>`, `<link>`, `<meta>`, or a page `<title>`) anywhere in the body; an accessibility `<title>` nested inside `<svg>` is allowed.
- You are an injection engine: map the content to the existing template blocks.
- Uses only real content from the provided source.

When CONTENT_SOURCE is "homepage-section":
The content comes from a section of the homepage HTML, not a full page.
It may be less detailed than a dedicated page would be.
Use everything available in the section data. Do not pad or invent.

When CONTENT_SOURCE is "fetched-page":
Use the full fetched page content. Extract all headings, body text, lists,
form fields, images, and contact information present.

In both modes:
- Output ONLY one raw `<body>...</body>` fragment. No markdown code fences,
  preamble, trailing commentary, doctype, `<html>`, `<head>`, `<style>`, or
  `<script>`. The first characters must be `<body` and the last characters
  must be `</body>`. No HTML comment may precede the opening `<body>` tag.
- Do not emit any unresolved template token.
- The nav and footer must match the homepage exactly (same links, same brand treatment)
- The footer must be one `<footer class="site-footer">` containing
  `.footer-grid` followed by `.footer-bottom`, closed before `</body>`.
- Only the main content area changes per page type
- Apply the same `class="theme-light"` or `class="theme-dark"` to the `<body>` as the homepage
- Trusted code applies the same root tokens and Google Fonts as the homepage

---

## USER PROMPT

PAGE TYPE: [INSERT page_type]
PAGE URL: [INSERT URL if Mode A, or "n/a -- single-page site" if Mode B]
CONTENT_SOURCE: [fetched-page OR homepage-section]
NOTES: [any client-specific instructions or "none"]

HOMEPAGE DESIGN JSON:
[PASTE FULL JSON FROM STEP 01 HERE]

ALLOWED BODY CLASSES:
[PASTE THE CLASS CATALOG FROM 03-BASE-TEMPLATE.HTML HERE]

---
SOURCE CONTENT:
[MODE A: paste web_fetch output here]
[MODE B: paste the matching single_page_sections entry from the homepage JSON here]
---

---

## PAGE TYPE LAYOUTS

Use the layout spec that matches PAGE TYPE above.
All layouts share: sticky nav (from homepage) + trust strip (from homepage) + footer.

---

### CONTACT PAGE

Above the fold:
- Headline: "Get in Touch" or "Contact [SITE_NAME]" -- short, not clever
- Subheadline: response time promise if available ("We respond within 2 hours")
  or hours of operation
- Trust strip (same as homepage)

Main layout -- two column (60/40 split):

LEFT COLUMN -- Contact form:
- Headline: copy an admitted source action label, or use neutral contact wording
  such as "Send Us a Message"
- Form fields: name, phone, email, message/issue -- max 5 fields
- CTA button: copy an admitted source action label; otherwise use neutral source
  wording such as "Submit" or "Contact Us"
- Below the button: one trust signal line (review score or response time promise)

RIGHT COLUMN -- Contact details:
- Phone number (large, clickable tel: link)
- Email address
- Physical address with embedded Google Maps link or static map image
- Hours of operation (structured, not a paragraph)
- If multiple locations: repeat per location

Below the two columns (full width):
- FAQ strip if any FAQ content exists on the page
- Social links if present

---

### ABOUT PAGE

Above the fold:
- Headline: "[Site Name] -- [City]'s [Brief Descriptor]"
  e.g. "Steffen Heating -- Effingham's HVAC Experts Since 1987"
- Subheadline: mission or brand promise in one line
- Trust strip

Main content -- single column with section breaks:

SECTION 1 -- Story/Mission:
- 2-3 paragraph company origin or mission statement (use verbatim from page if present)
- Key stat callouts inline: years in business, customers served, etc. as large numbers

SECTION 2 -- Team grid (if team info present):
- Card per team member: photo, name, title, short bio; trusted code owns image
  failure behavior
- Grid: 3-col on desktop, 1-col on mobile
- If no team info: skip this section

SECTION 3 -- Values or differentiators:
- 3-4 items as a horizontal card strip
- Each: icon placeholder + label + one-line description
- Use actual differentiators from the page content, not generic filler

SECTION 4 -- Social proof:
- Review highlights or testimonial quotes (verbatim from page)
- If none exist: skip

CTA at bottom:
- Repeat the primary CTA from the homepage (dual CTA if urgency_type is emergency or both)
- Trust signal immediately below it

---

### SERVICES PAGE

Above the fold:
- Headline: "Our Services" or more specific if the page has one
- Subheadline: one-line value statement
- Trust strip

Main content:

SERVICES GRID:
- Card per service extracted from the page
- Each card: service name (large), 2-line description, "Learn More" link if URL exists
- Grid: 3-col desktop, 2-col tablet, 1-col mobile
- Featured/primary service: span full width at top, larger treatment

If the page has service detail beyond a list:
- Use alternating image/text rows (image left + text right, then flip)
- Each row: service name, description, key benefits as short list, CTA

SERVICE AREA section (if locations/coverage mentioned):
- Simple text list of coverage cities/areas
- Or a callout box: "Serving [City], [City], and [City]"

CTA at bottom:
- Dual CTA (matches homepage urgency_type)
- Trust signal below

---

### SINGLE SERVICE PAGE

This is a landing page for one specific service.
Highest conversion page type -- treat it accordingly.

Above the fold:
- Headline: service name + location (e.g. "AC Repair in Effingham, IL")
- Subheadline: outcome or differentiator ("Same-day service, 100% satisfaction guaranteed")
- Dual CTAs (always -- this is a conversion page)
- Trust strip

Content flow:

SECTION 1 -- Problem/Need (why visitors are here):
- 1-2 paragraphs addressing the pain point
- Common symptoms or signs (as a scannable list if applicable)

SECTION 2 -- Our Solution:
- How the service works: 3-step process cards (simple, visual, numbered)
- What's included in the service

SECTION 3 -- Benefits:
- 3-4 benefit cards: icon + headline + 1-line description
- Use actual benefits from the page, not generic ones

SECTION 4 -- Trust signals:
- Review snippet relevant to this service (if available)
- Certifications or warranties related to this service
- Before/after or outcome callout if data exists

SECTION 5 -- FAQ (if present on the page):
- Accordion-style or simple Q&A list
- Use verbatim questions and answers from the page

SECTION 6 -- Related Services:
- 2-3 cards linking to other services
- Pulls from pages_to_fetch or nav items

CTA at bottom:
- Repeat dual CTA
- Trust signal below

---

### MENU PAGE (restaurants)

Above the fold:
- Restaurant name + "Menu"
- Hours + an exact admitted source action label when one exists; do not infer
  ordering or reservation capability from the menu page type
- Trust strip (rating + review count)

Menu layout:
- Category tabs or anchor links (Starters, Mains, Desserts, Drinks, etc.)
- Each category as a section with clear heading
- Item cards: name (bold) + description + price
- Dietary tags inline (vegan, gf, spicy) as small pills
- High-contrast, highly scannable -- this is a functional page, not decorative

---

### FAQ PAGE

Above the fold:
- Headline: "Frequently Asked Questions" or more specific if context allows
- Optional: category filter buttons if many categories

FAQ list:
- Group by category if categories exist
- Each Q&A: question as bold heading, answer as paragraph
- Generous spacing -- this is a reading page
- Anchor links at top if more than 8 questions

CTA at bottom:
- "Still have questions? [Contact CTA]"

---

## SHARED COMPONENT RULES (apply to all page types)

Nav: exact same HTML and CSS as the homepage. Same links, same logo, same CTA.
Footer: exact same HTML and CSS as the homepage.
Root tokens and fonts are applied by trusted code from the homepage settings;
do not emit them in the body.
Trust strip: same as homepage. Present on every page.
Mobile breakpoint: 768px, same rules as homepage.
Image failure behavior is added by trusted code after admission. Do not emit
event-handler attributes.
No placeholder text anywhere. If content does not exist on the fetched page, omit the section.
