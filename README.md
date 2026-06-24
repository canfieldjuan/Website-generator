# Local Business Site Builder

Two parallel implementations of the same pipeline: fetch a small-business website, extract its brand and content with an LLM, generate a modernised HTML mockup, and optionally deploy it to Vercel as a live sales demo.

---

## What's in the box

| Implementation | Entry point | When to use |
|---|---|---|
| **Redesign pipeline** | `pipeline.py` | Client already has a website — you're pitching a modernised version |
| **From-scratch build** | `build.py` | No existing site — you fill a prospect JSON and generate one cold |
| **Claude skill** | `SKILL.md` + `references/*.md` | Running inside a Claude skill host (no Python at runtime) |

All three share the same prompt files in `references/`. The skill and the scripts are two UIs on top of the same LLM prompts.

---

## Pipeline architecture

### Redesign pipeline (`pipeline.py`)

```
URL → fetch_and_clean_html → analyze_site → enrich_site_json
    → mirror_images_locally → hero image (Unsplash / Flux fallback)
    → generate_redesign (homepage) → generate_interior_page (contact)
    → save locally → [deploy to Vercel] → [send pitch email via Resend]
```

1. **Fetch** — `requests` first; auto-upgrades to headless Playwright Chromium when visible text is < 8 000 chars (JS-rendered sites like Squarespace/Wix/Webflow). Strips `<script>/<svg>/<noscript>/<iframe>` but **keeps `<style>`** so the analysis prompt can extract brand colors. Embeds an `<!-- EXTRACTED IMAGE URLS -->` comment harvesting `src`, `data-src`, `data-lazy-src`, `data-original`, and CSS `url(...)` values.

2. **Analyze** — sends cleaned HTML to `EXTRACTION_MODEL` (`claude-haiku-4.5` via OpenRouter) with `references/01-site-analysis-prompt.md` as the system prompt, `response_format=json_object`, temperature 0.1. Produces a site JSON with `site`, `images`, `pages_to_fetch`, `single_page_sections`, `conversion_profile`, `platform`, and `image_generation_prompt` fields.

3. **Enrich** — fetches up to one page per type from `pages_to_fetch` where `fetchable: true` and `priority ≤ 2` (types: `services`, `single-service`, `team`, `about`, `faq`, `contact`). Merges extracted JSON back into `site_json` so the homepage redesign has real services/team/contact data.

4. **Mirror images** — downloads CDN URLs into `outputs/<slug>/images/` and rewrites site JSON to relative paths so the deployed Vercel bundle is self-contained.

5. **Hero image** — Flux-only via `generate_image_openrouter` (OpenRouter, `black-forest-labs/flux.2-max`). Fires when analysis JSON contains `image_generation_prompt` or when no hero/background image was extracted. `UNSPLASH_ACCESS_KEY` has no effect here — the Unsplash-first path is `build.py`-only. Base64 responses are decoded to disk to avoid blowing up the LLM context on the next call.

6. **Generate HTML** — `GENERATION_MODEL` (`claude-sonnet-4.5`) with `references/02-redesign-gen-prompt.md` + full `references/03-base-template.html` (the CSS component library). Theme is auto-selected in `pipeline.py` via a `site.type → theme` map. Contact page generated separately using `references/04-interior-page-prompt.md`.

7. **Deploy** — `vercel --prod --yes --name <slug>` in the output directory. Runs `vercel whoami` as a preflight; returns the `*.vercel.app` URL parsed from stdout/stderr.

8. **Email** — Resend-backed auto-send (`lib/email.py`). The `from` address (`onboarding@resend.dev`) only reaches your own Resend account unless you verify a domain at resend.com/domains.

### From-scratch build (`build.py`)

```
prospect.json → load_prospect (validate + sanitize) → select_theme
              → select_palette → select_hero_shape → select_section_order
              → hero image (Unsplash → Flux) → generate_build_html
              → outputs/builds/<slug>/index.html
              → outputs/email_drafts/<slug>.md   ← internal, not deployed
              → [deploy to Vercel]
```

Takes a small JSON (see `examples/prospect-plumber-template.json`) instead of scraping. All four variation axes are deterministic — same `business_name` always produces the same theme, palette, hero shape, and section order:

| Axis | Source | md5 slice |
|---|---|---|
| Theme | `allowed_themes` list in `references/07-industry-defaults.md` for the prospect's `trade` | `[:8]` |
| Palette | `palette_variants` block in 07 | `[8:16]` |
| Section order | `KNOWN_SECTION_ORDERS` (`default`, `services-led`, `reviews-led`) | `[16:24]` |
| Hero shape | Coupled to theme — no new hash slice | — |

The pitch email is generated as a Markdown draft with `[VERCEL_URL_PLACEHOLDER]` left in. The salesperson replaces it manually after deployment and sends from their own email client. There is no automated send path in `build.py`.

---

## Quick start

### Prerequisites

```bash
# Python deps
pip install -r requirements.txt

# Headless browser (only needed for JS-rendered sites in pipeline.py)
playwright install chromium

# Vercel CLI (only needed for deployment)
npm install -g vercel && vercel login
```

### `.env` required keys

```
OPENROUTER_API_KEY=...   # Required — all LLM and image calls route through OpenRouter
RESEND_API_KEY=...       # Required for pipeline.py email send; optional for build.py
UNSPLASH_ACCESS_KEY=...  # Optional — free hero photos; falls back to Flux generation
```

### Redesign an existing site

```bash
python pipeline.py https://example-plumber.com
python pipeline.py https://example-plumber.com --skip-deploy
python pipeline.py https://example-plumber.com --skip-deploy --skip-email
python pipeline.py https://example-plumber.com --skip-deploy --skip-image-gen
```

Output lands in `outputs/<site-slug>/`.

### Build from scratch (prospect JSON)

```bash
# Copy the template, fill in real values
cp examples/prospect-plumber-template.json examples/my-prospect.json
# Edit my-prospect.json: business_name, trade, city, state, phone are required

python build.py examples/my-prospect.json
python build.py examples/my-prospect.json --skip-deploy
python build.py examples/my-prospect.json --skip-deploy --skip-image-gen --skip-email-draft
```

Output site: `outputs/builds/<slug>/index.html`
Pitch email draft: `outputs/email_drafts/<slug>.md` (never published to Vercel)

---

## Prospect JSON

Required fields: `business_name`, `trade`, `city`, `state`, `phone`.

Optional fields that gate specific rendered content:

| Field | Effect |
|---|---|
| `established_year` | Recomputed to `years_in_business = current_year - established_year` at build time |
| `family_owned`, `licensed_and_insured`, `has_24_7`, `locally_owned`, `same_day_service` | Gate trust-signal phrases per `references/07-industry-defaults.md` |
| `service_promises` | Array of verified service commitments shown in Why-Choose-Us cards |
| `epa_certified`, `master_electrician_license`, `ibew_local_number` | Trade-specific credentials (HVAC, electrician) |
| `google_review_score`, `google_review_count` | Aggregate review widget |
| `reviews` | Array of real reviews (3+ → card grid; 1–2 → aggregate widget only) |
| `brand_colors` | Forces `brand-forward` theme; LLM uses these colors verbatim |
| `theme_override` | Override deterministic theme selection (must be a known theme name) |
| `formspree_endpoint` | Contact form action URL |
| `salesperson_first_name` | Sign-off name in the pitch email draft |

Template placeholder values (`example.com`, `REPLACE`, `TODO`, etc.) in `owner_email`, `owner_first_name`, `phone`, and `address` are silently nullified before the LLM sees them. Placeholders in `business_name` and `formspree_endpoint` produce a loud warning but do not block the build.

---

## Themes

Six themes are defined in `references/09-themes.md` and `references/02-redesign-gen-prompt.md`:

| Theme | Default hero shape | Typical trades |
|---|---|---|
| `warm` | fullbleed | restaurant, retail, local-business, HVAC, plumber |
| `minimal` | gradient (no photo) | portfolio, services |
| `civic` | fullbleed | church, civic, nonprofit |
| `broadcast` | fullbleed | radio, news, home-services |
| `editorial` | split | legal, medical |
| `brand-forward` | fullbleed | ecommerce, entertainment; auto-selected when `brand_colors` is set |

`COLOR_MODE` defaults to `brand` — extracted/supplied hex values are used, not theme defaults.

---

## Reference files

| File | Purpose |
|---|---|
| `references/01-site-analysis-prompt.md` | System prompt for extracting structured JSON from fetched HTML (pipeline.py step 1) |
| `references/02-redesign-gen-prompt.md` | Homepage generation prompt — theme specs, conversion rules, deployment comment block |
| `references/03-base-template.html` | CSS component library (~2000 lines) injected into every generation call |
| `references/04-interior-page-prompt.md` | Interior page generation (contact, about, services, FAQ, menu) |
| `references/05-enrichment-prompt.md` | Interior-page enrichment extraction (pipeline.py only) |
| `references/06-build-prompt.md` | From-scratch HTML generation system prompt (build.py) |
| `references/07-industry-defaults.md` | Trade defaults: allowed themes, palette variants, hero image queries, trust-signal rules |
| `references/08-pitch-email-prompt.md` | Pitch email draft generation prompt (build.py) |
| `references/09-themes.md` | Theme catalog — typography, hero shape coupling, personality |
| `references/10-section-orders.md` | Section order variants catalog |

---

## Models

Both scripts call OpenRouter using the OpenAI-compatible client:

| Role | Model constant | Current value |
|---|---|---|
| Extraction / enrichment | `EXTRACTION_MODEL` | `anthropic/claude-haiku-4.5` |
| HTML generation / email draft | `GENERATION_MODEL` | `anthropic/claude-sonnet-4.5` |
| Hero image (Flux) | `IMAGE_MODEL` | `black-forest-labs/flux.2-max` |

Constants live in `lib/clients.py`. Prompt caching (`cache_control: ephemeral`) is enabled in `build.py` for the large static context block (industry defaults + themes + section orders + base template). Cache hit/miss counts are logged to stdout.

---

## Outputs

```
outputs/
  <site-slug>/              # pipeline.py redesign output
    index.html
    contact.html
    images/
      <context>_0.jpg       # mirrored CDN images
      hero.<ext>            # Unsplash or Flux generated hero

  builds/
    <slug>/                 # build.py from-scratch output (Vercel deploy root)
      index.html
      images/
        hero.<ext>

  email_drafts/             # build.py pitch email drafts (never deployed)
    <slug>.md
```

---

## Fabrication discipline

The defining constraint of this repo is **never fabricate prospect facts**. Every claim in the generated HTML — headline, benefit card, trust signal, review — must trace back to a verified field in the prospect JSON or to a safe-generic entry in `references/07-industry-defaults.md`.

`build.py` enforces this at the harness level:
- Template placeholder values are stripped before the LLM sees them.
- Review entries containing placeholder markers are dropped before generation.
- The pitch email draft is validated to contain `[VERCEL_URL_PLACEHOLDER]` in the body before being written to disk.

See `AGENTS.md` for the full verification commands and pre-push checklist.

---

## Workflow and contributing

This repo follows the PR shape defined in `AGENTS.md`:

- One plan doc per PR (`plans/PR-<Slice-Name>.md`) written before any code.
- Changes to LLM behavior go in `references/*.md`, not in `pipeline.py` or `build.py`.
- If the analysis JSON schema changes (`01-site-analysis-prompt.md`), audit every `site_json.get(...)` in `pipeline.py` and every placeholder in `02-` and `04-`.
- No test suite — each PR's plan doc names the specific build + grep + visual spot-check sequence that verifies the change.

```bash
# Pre-push mechanical check
bash scripts/local_pr_review.sh
```
