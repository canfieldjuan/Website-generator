# 07 -- Industry Defaults (Plumbing)

Knowledge base the from-scratch build pipeline (`build.py`) uses when the
prospect JSON doesn't specify a value. Used by `06-build-prompt.md` to
fill in industry-standard content for a local plumbing business that has
no current online presence.

This is NOT a content database -- it's a defaults book. Prospect-specified
values always win. Use these only to fill gaps.

## Template placeholders (governs ALL trade sections below)

The Tier 1/2/3 subheads, headlines, and `06-build-prompt.md`
form-trust trailers below use named placeholders rather than
literal trust phrases. Each placeholder has a strict
prospect-data-driven expansion. If the underlying prospect field
is missing or false, the placeholder renders as empty -- never
as a default literal. This is how the skill keeps the
fabrication-guard promise from `SKILL.md` at the template level
instead of relying on the LLM to remember a separate rule.

### `[TRUST_TRAILER]`

Expand into a comma-separated, period-terminated sentence built
ONLY from the components verified by prospect data, in this order:

1. `Licensed, insured` -- if `prospect.licensed_and_insured` is
   true.
2. `family-owned` -- if `prospect.family_owned` is true.
3. `locally owned` -- if and only if `prospect.locally_owned`
   is explicitly true. There is no implicit inference from
   `family_owned`, single-location, or any other field. Never
   assert `locally owned` from `prospect.licensed_and_insured`.

Join with commas; close with a single period. **If no component
qualifies, render the placeholder as the empty string** -- the
sentence preceding `[TRUST_TRAILER]` in the template becomes the
subhead's natural end, no extra punctuation. Never substitute a
generic fallback like "Licensed [TRADE] in [CITY]" -- that would
be fabrication. Tenure/since-year claims are NOT part of
[TRUST_TRAILER]; they live in the headline (`[CITY]'s Trusted
[TRADE] Since [YEAR]`) and in form-trust options 2 and 3 in
`06-build-prompt.md`, not in the comma-separated trailer.

Examples:
- `licensed_and_insured: true, family_owned: true`
  -> `Licensed, insured, family-owned.`
- `licensed_and_insured: true` only
  -> `Licensed, insured.`
- No verified components -> placeholder renders empty; nothing
  appended to the prior sentence.

### `[SERVICE_PROMISE]`

Expand into the verified service promises from
`prospect.service_promises` (an array of short, prospect-verified strings),
joined with periods and terminated with a period.

If `prospect.service_promises` is absent, empty, or null, render
the empty string. **Never default-render any scheduling, estimate, pricing,
response-time, fee, or owner-availability promise -- those are operational
claims about a specific prospect's business practices, not generic trade
defaults**. The salesperson supplies verified promises in the prospect JSON;
this skill does not invent them.

### `[YEARS]` and `since [YEAR]` (separate tenure placeholders)

- `[YEARS] years` substitutes `prospect.years_in_business`
  directly. Drop the clause if that field is null.
- `since [YEAR]` substitutes `prospect.established_year`. Drop
  the clause if that field is null.

These are **independent**. A prospect with verified
`years_in_business: 12` but no `established_year` can still
truthfully claim "12 years of ..." in the subhead. Do not strip
one because the other is missing.

### Credential-stripping (Master / specialty licenses)

- Drop "Master Electrician" / "Master-licensed" / similar
  trade-specific certifications if the corresponding
  `prospect.master_electrician_license` /
  `prospect.certifications` / explicit flag is not verified.
- **Falling back to the generic "Licensed" phrasing still
  requires `prospect.licensed_and_insured` to be true.** If the
  Master credential is unverified AND `licensed_and_insured` is
  not true, drop the credential entirely (no generic "Licensed"
  default). The Tier 3 headline rule below handles the
  no-credential case.

### Headline: `Licensed [TRADE] Serving [CITY]` is conditional

Tier 3 default headlines that read `Licensed [TRADE] Serving
[CITY]` (`Licensed Plumber Serving [CITY]`, `Licensed HVAC
Contractor Serving [CITY]`, `Licensed Electrician Serving [CITY]`)
render the leading "Licensed " word **only when
`prospect.licensed_and_insured` is true**. Otherwise the headline
falls back to `[TRADE_DISPLAY] Serving [CITY]` -- no credential
claim. `[TRADE_DISPLAY]` is the human-readable form (`Plumber`,
`HVAC Contractor`, `Electrician`), not the lowercase JSON key.

Operating unlicensed is itself unusual for these trades, and the
salesperson should surface a missing `licensed_and_insured` flag
during prospect intake -- but until that flag is verified, the
generated site will not assert the credential.

**Bottom line:** Never fabricate a credential, ownership claim,
or service promise the prospect data does not support. The
SKILL.md fabrication guards override the defaults below; the
placeholders here implement those guards at the template level
so the LLM doesn't have to remember them every time.

---

## TRADE: plumber

### Buyer / urgency profile

A plumbing prospect's site visitor falls into two segments:

1. **Emergency** (~70% of inbound traffic for plumbers) -- pipe burst,
   water heater failed, sewage backup, no water, no hot water. Decision
   in minutes. They will call the first credible result when a verified phone
   is available; otherwise the request-service form must carry that intent.
2. **Planned** (~30%) -- water heater replacement, repipe quote,
   bathroom remodel rough-in, recurring drain maintenance. Decision in
   days. Form CTA acceptable.

A plumber site MUST serve emergency intent first. When `prospect.phone` is set,
render that exact phone in the nav and hero and keep the form secondary. When
`prospect.phone` is null or empty, do not invent a phone action; make the
request-service form the primary path. Render an "Available 24/7" badge only
when the corresponding prospect field is verified.

### Canonical service catalog

Use these as the default service list when the prospect's JSON doesn't
specify, OR to augment a sparse list. Prospect-specified items win.

| Service                       | One-line description                                                |
|-------------------------------|---------------------------------------------------------------------|
| Emergency Leak Repair         | 24/7 response to burst pipes, slab leaks, and active water damage.  |
| Water Heater Repair & Install | Tank and tankless system repair, replacement, and installation.      |
| Drain Cleaning                | Hydro-jet and snake service for kitchen, bath, and main lines.      |
| Sewer Line Repair             | Camera inspection, spot repair, and trenchless replacement.         |
| Sump Pump Service             | Repair, replacement, and battery backup installation.               |
| Garbage Disposal              | Repair, replacement, and new installation.                          |
| Faucet & Fixture Replacement  | Kitchen, bath, and outdoor fixtures.                                |
| Toilet Repair & Install       | Running toilets, leaks, full replacement.                           |
| Repiping                      | Whole-home replacement for failing galvanized or polybutylene pipe. |
| Gas Line Repair               | Licensed gas line work for ranges, water heaters, and grills.       |

### Hero copy templates -- selection rule

Apply this decision tree in order. The first matching tier wins.
Substitute `[CITY]`, `[YEAR]`, `[YEARS]`, `[SERVICE_AREA]` from
prospect values. NEVER fabricate a tenure value -- if the field is
absent, fall through to the next tier.

**Tier 1 -- Established (years_in_business >= 8):**

This tier wins even when has_24_7 is true. An 8+ year track record
beats "we're available 24/7" on credibility. When has_24_7 is true,
the 24/7 claim is carried by the `.hero-chip` eyebrow badge above the
headline (see 06-build-prompt.md HERO CHIP rule) -- do NOT duplicate
it in the subhead. Trying to out-emergency Roto-Rooter in the headline
is a losing position for a local plumber; trying to out-trust them on
locality and tenure is winnable.

- Headline: `[CITY]'s Trusted Plumber Since [YEAR]`
- Subhead (any value of has_24_7): `[YEARS] years of plumbing repair, replacement, and installation across [SERVICE_AREA]. [TRUST_TRAILER] [SERVICE_PROMISE]`

**Tier 2 -- Emergency (years_in_business < 8 AND has_24_7 true):**

Newer business that still differentiates on 24/7 availability. Lead
with it because there is no longer-tenure story to tell yet.

- Headline: `Emergency Plumber in [CITY] -- We Answer 24/7`
- Subhead: `Plumbing service across [SERVICE_AREA]. [TRUST_TRAILER] [SERVICE_PROMISE]`

**Tier 3 -- Local (years_in_business < 8 AND has_24_7 false/absent):**

New business without 24/7 service. Lead on credentials, pricing
transparency, and the anti-franchise angle.

- Headline (if `prospect.licensed_and_insured` is true): `Licensed Plumber Serving [CITY]`
- Headline (otherwise): `Plumber Serving [CITY]`
- Subhead: `Local plumbing service across [SERVICE_AREA]. [SERVICE_PROMISE]`

NEVER use mission-statement language ("We believe in honest plumbing",
"Our mission is to..."). NEVER use "dedicated" or "committed to."
NEVER drop the headline tier rule -- a Tier-1 plumber with 24/7
service does NOT get the bare emergency headline; the 24/7 fact goes
into the subhead, not the headline.

### Trust signal priority

Use the highest-tier signal the prospect actually has. Skip lower tiers
if a higher one exists.

1. Third-party review score with platform name (`4.8 from 127 Google Reviews`)
2. Years in business + location (`Serving [CITY] since [YEAR]`)
3. Licensing + insurance + ownership line -- render via `[TRUST_TRAILER]` from intro (composes only verified components; never the literal `Licensed, insured, family-owned` default)
4. Service-radius coverage (`Serving [CITY] and surrounding areas within 25 miles`)

NEVER fabricate review counts. If the prospect didn't provide a review
score, use tier 2 or 3.

### Competitive positioning vs national chains

Local plumbers compete against Roto-Rooter, Mr. Rooter, Benjamin Franklin,
and similar national/franchise brands that dominate paid local-pack ads.
The site should signal *local* without being explicit / defensive about it.

**Positive signals for the Why-Choose-Us section** (see Section order step 6).
Each bullet has a gating rule -- a benefit card may render ONLY when the
named prospect field is verified. The same fabrication-guard discipline
that gates the hero subhead via `[TRUST_TRAILER]` and `[SERVICE_PROMISE]`
applies to the benefits grid: never invent a verified-trust or
service-promise card just to fill the 3rd slot.

**Verified trust signals** (gated by existing `[TRUST_TRAILER]` fields):
- "Family Owned & Operated" -- render only if `prospect.family_owned` is true.
- "Locally Owned, Not a Franchise" -- render only if `prospect.locally_owned` is true. No implicit inference from `family_owned`.
- "Licensed & Insured" -- render only if `prospect.licensed_and_insured` is true.

**Verified service promises** (require a matching entry in `prospect.service_promises`):
- Any pricing or billing benefit requires a close equivalent in `service_promises`.
- Any scheduling or estimate benefit requires a close equivalent in `service_promises`.
- Any owner-availability benefit requires an explicit matching entry and is never inferred from `has_24_7`.

**Safe generic positioning** (true by definition for the skill's target audience -- rural small-town owner-operators with no franchise affiliation, owner-or-tight-crew operations):
- "Local Service, Not a Call-Center Dispatch"
- "Direct Line to the Service Tech, Not a Booking Agent"
- "Serving [CITY] and [SERVICE_AREA]" -- substitute the verified `prospect.service_radius`.

These three are safe to render without per-prospect verification because every skill target prospect IS a local independent by definition. Padding with these when verified trust + service-promise cards yield < 3 is honest framing, not fabrication.

**Selection rule for the EXACTLY 3 cards** (see Section order step 6):
1. Pick all verified-trust cards available.
2. Pick all verified-service-promise cards available.
3. Pad with safe-generic-positioning cards if the running count is < 3.
4. Never fabricate a verified-trust or service-promise card. If the prospect data supports 0 verified cards, all 3 come from safe-generic. If it supports 2 verified, the 3rd comes from safe-generic.
5. Consolidate overlapping verified-trust cards (e.g. family_owned + locally_owned) into a single card per 06's "consolidate overlapping claims" rule -- adjacent cards saying nearly the same thing weakens both.

Do NOT explicitly name competitors ("better than Roto-Rooter"). Looks
defensive and triggers brand-disparagement issues.

### Default service grid selection (plumber)

The services grid renders EXACTLY 6 cards (6 fills a 3-column desktop
grid as 2 clean rows of 3; 7 or 8 leaves an orphan trailing cell).
Prospect-specified services win. If the prospect supplied more than 6,
pick the 6 with highest commercial value (emergency + replacement work
over small-ticket fixture jobs). If the prospect list is sparse, fall
back to the default 6 for a plumber:

- Emergency Leak Repair
- Water Heater Repair & Install
- Drain Cleaning
- Sewer Line Repair
- Sump Pump Service
- Toilet Repair & Install

Faucet & Fixture Replacement and Garbage Disposal stay in the canonical
catalog above for prospects who explicitly ask for them, but don't make
the default 6.

### Service area handling (plumber)

The hero subhead names the service-area cities and the coverage band
asks "Not sure if we cover your area?". Together they cover the
Service Area's textual function. **Do not render a standalone Service
Area section** -- it duplicates both.

### Section render order

Render order comes from `prospect._computed_section_order` only. See
`references/10-section-orders.md` for the three named orderings the
harness picks among. The `default` ordering (trust-strip-first) suits
plumbers given the emergency-CTA priority; `services-led` and
`reviews-led` render correctly for plumbers too.

Omit any section the prospect data can't fill honestly. A plumber site
without a Google review score skips section 7 cleanly -- do not pad
with generic testimonials or fabricated review claims.

### Hours defaults

If prospect didn't specify, use:
- Office: `Monday-Friday 7:00 AM - 6:00 PM, Saturday 8:00 AM - 2:00 PM`
- Emergency: `24/7 emergency service available`

### Service radius defaults

If prospect didn't specify, use a 20-mile radius from the listed city.
Phrase as: `Serving [CITY] and surrounding communities within 20 miles`.

### Hero image source -- two paths

**Path 1 -- Unsplash photo library (preferred; consumed by `build.py`'s `fetch_unsplash_hero()` and the SKILL bash workflow)**

When `UNSPLASH_ACCESS_KEY` is set, `build.py` and the
`local-business-build` Claude Code skill both fetch a hero from
Unsplash using the trade-specific search query below. Free, fast,
real photography. `build.py` falls through to Path 2 (Flux) only
when the key is missing, the API returns no results, or the
network call fails. The skill workflow falls through to the
manual placeholder fallback documented in SKILL.md under the
same conditions. Both consumers read this field per-trade:

```
hero_search_query: "plumbing"
```

**Empirically verified** against the Unsplash search API (May 2026):
this single-word query returns 2,314 results, and the top
landscape-oriented match is a plumber-in-action photo ("a man working
on a pipe in a wall"). Earlier multi-word phrases like "plumber
service truck residential work" returned only 2 results, with the
top match being a snow-covered crane truck -- not plumber-appropriate.

The "fewer words wins" rule for Unsplash search:

- Unsplash search is keyword-based, not phrase-based. Long multi-word
  queries narrow the pool to photos tagged with ALL words; few
  photographers tag with five words. A single specific trade word
  ("plumbing", "roofing", "electrical") usually returns 1000+ results.
- The first result for a single-word trade query is almost always the
  most-favorited photo for that tag, which tends to be a real working
  professional in context -- exactly what we want.
- Do NOT include the business name, city, or any text that would
  appear in the image. Unsplash is a photo library; those words don't
  improve results and can break the query.

When onboarding a new trade, start with the single-word trade name
(e.g. "roofing", "hvac", "landscaping") and only narrow if results
are off-target. Verify the top result is appropriate by inspecting
the API response before committing the query.

**Path 2 -- Flux 2 hero prompt (consumed by `build.py`'s `build_hero_prompt()`)**

`build.py`'s `build_hero_prompt()` reads this template at runtime
via `_extract_trade_hero_prompt(trade)`, substitutes `[CITY]` and
`[STATE]` from the prospect JSON, and sends the result to the
Flux 2 model. If the prospect's trade key doesn't match a
`## TRADE:` section here (or the Path 2 fenced block is missing /
unparseable), `build_hero_prompt()` falls back to a generic
trade-agnostic prompt so the prospect still gets a hero -- just
less trade-specific. Each trade's Path 2 block below is the
single source of truth for that trade's Flux prompt; edit here,
no code change required.

```
Professional photorealistic hero image for a local plumbing business in
[CITY]. Wide cinematic crop, golden-hour natural light, depth of field.
Subject: a plumber's service van parked in a residential driveway, tools
visible but tidy, or a close-up of a clean copper pipe installation
under a sink. NO text, NO logos, NO faces clearly visible, no people
wearing branded apparel from any specific company.
```

Why no faces / branded apparel: the same image gets reused across multiple
prospects in this trade, and we don't want any prospect to feel the photo
is "of someone else's business." Generic-but-professional wins.

The Unsplash path (Path 1) is preferred when available -- it's free,
fast, and produces real photography. The Flux path (Path 2) is the
fallback when no Unsplash key is configured.

### Page set for MVP

Single page (`index.html`) containing all sections above. That's the
shippable product. Multi-page (services subpages, individual service
detail pages, blog) is v2 and lives in a different generation prompt.

### Theme

`allowed_themes: [warm, civic, broadcast, editorial]`

The harness picks among these per the deterministic rule in
`06-build-prompt.md` (see `references/09-themes.md` for the full theme
catalog). When each one shines for a plumber prospect:

- **warm** -- the canonical residential plumber default. Rounded cards,
  friendly typography, serif headlines. Pairs well with family-owned /
  locally-owned signals.
- **civic** -- prospects whose brand reads cool/blue or who lean
  utility / municipal contractor. Less common for rural sole proprietors.
- **broadcast** -- emergency-first prospects with `has_24_7: true`,
  particularly newer businesses (Tier 2 in the headline tier rule).
  Conveys urgency through dense type and grid layout.
- **editorial** -- tenured plumbers (`established_year` set and
  `years_in_business >= 20`). Magazine refinement for the
  heritage-led pitch.

### Color defaults

If prospect provided brand colors, use them. If not, the harness
(`build.py`'s `select_palette()`) picks one of the variants below
deterministically by hash of `business_name` and injects it as
`prospect._computed_palette` (accent + accent_dark hex codes).
Different plumber prospects within the same town get visibly
different reds; the same prospect always gets the same one.

All variants are **WCAG AA-compliant** against white button text
(`.nav-cta`, `.form-submit`, `.cta-emergency`). The shallower
`#D9534F` (Bootstrap red, ~4.0:1) fails AA and is **explicitly
rejected** for accent slots that overlay white text.

```
palette_variants:
- accent: "#B91C1C", accent_dark: "#991B1B"  -- classic emergency red (~6.5:1 / ~8.2:1), Tailwind red-700/800
- accent: "#991B1B", accent_dark: "#7F1D1D"  -- deep red (~8.2:1 / ~10:1), Tailwind red-800/900 -- conveys gravity
- accent: "#C2410C", accent_dark: "#9A3412"  -- orange-red (~5.2:1 / ~7.3:1), Tailwind orange-700/800 -- less aggressive
- accent: "#B7372D", accent_dark: "#8C2E26"  -- warm crimson (~5.9:1 / ~8.3:1), custom -- between red and rust
```

- Secondary: navy (`#1F3A5F`, ~11.5:1) -- trust/professional, constant across variants
- Background: white (light theme)

The four variants all sit inside the "plumber emergency / urgent
service" emotional register but differ enough in hue and weight to
fingerprint two plumbers in the same service area. Variant
selection is independent of theme selection (see 09-themes.md):
two plumber prospects could share a theme and still get different
palette variants, or share a palette and get different themes.

Apply the COLOR DISCIPLINE rule from `02-redesign-gen-prompt.md`: accent
appears on AT MOST 3-4 elements (primary CTA, verified-phone CTA when present,
one badge).

---

## TRADE: hvac

### Buyer / urgency profile

An HVAC prospect's site visitor falls into two segments:

1. **Emergency** (~60% of inbound traffic) -- AC failure in summer,
   no heat in winter, furnace making concerning noises before it
   quits. Decision in hours rather than minutes (unlike a burst
   pipe). They will call the first credible result when a verified phone is
   available; otherwise the request-service form must carry that intent.
2. **Planned** (~40%) -- end-of-life system replacement (15-25 year
   cycle), new-construction install, ductwork upgrade, seasonal
   tune-up, indoor air quality improvements. Decision in days to
   weeks. Form CTA acceptable.

Compared to plumbing, HVAC emergencies have slightly more grace
period and a higher proportion of planned high-ticket work
(~$5-15K full system installs). The site should still serve emergency intent
first. When `prospect.phone` is set, render that exact phone in the nav and
hero; when it is null or empty, do not invent a phone action and make the
request-service form primary. A "24/7" badge still requires the corresponding
verified field. The planned-work pitch carries more weight here than for
plumber.

### Canonical service catalog

Use these as the default service list when the prospect's JSON
doesn't specify, OR to augment a sparse list. Prospect-specified
items always win.

| Service                       | One-line description                                                |
|-------------------------------|---------------------------------------------------------------------|
| AC Repair & Installation      | Window units, central AC, and mini-split repair and installation.         |
| Furnace Repair & Installation | Gas, electric, oil. Repair to full system replacement.              |
| Heat Pump Service             | Installation, repair, and refrigerant service for heat pumps.       |
| Duct Cleaning & Sealing       | Air duct cleaning, sealing leaks, improving system airflow.         |
| Thermostat Installation       | Smart thermostats, programmable thermostats, replacement.           |
| Seasonal Tune-Up              | Annual maintenance: AC in spring, furnace in fall.                  |
| Indoor Air Quality            | Whole-home humidifiers, dehumidifiers, air purifiers, HEPA filters. |
| Refrigerant Service           | EPA Section 608 certified refrigerant recharge and recovery.        |
| Emergency No-Heat / No-AC     | 24/7 response for system failures during extreme weather.           |
| New Construction HVAC         | Full HVAC rough-in and finish for new homes and additions.          |

The default 6 for an HVAC build when the prospect list is sparse:
AC Repair & Installation, Furnace Repair & Installation, Duct
Cleaning & Sealing, Thermostat Installation, Seasonal Tune-Up,
Indoor Air Quality. Heat Pump Service is regional (less common in
the rural Midwest, much more common in the Southeast) -- include
only when the prospect explicitly offers it.

### Hero copy templates -- selection rule

Apply this decision tree in order. The first matching tier wins.
Substitute `[CITY]`, `[YEAR]`, `[YEARS]`, `[SERVICE_AREA]` from
prospect values. NEVER fabricate a tenure value -- if the field is
absent, fall through to the next tier.

**Tier 1 -- Established (years_in_business >= 8):**

This tier wins even when has_24_7 is true. An 8+ year track record
beats "we're available 24/7" on credibility. When has_24_7 is true,
the 24/7 claim is carried by the `.hero-chip` eyebrow badge above
the headline (see 06-build-prompt.md HERO CHIP rule) -- do NOT
duplicate it in the subhead.

- Headline: `[CITY]'s Trusted HVAC Since [YEAR]`
- Subhead (any value of has_24_7): `[YEARS] years of heating, cooling, and indoor-air comfort across [SERVICE_AREA]. [TRUST_TRAILER] [SERVICE_PROMISE]`

**Tier 2 -- Emergency (years_in_business < 8 AND has_24_7 true):**

Newer business that still differentiates on 24/7 availability. Lead
with it because there is no longer-tenure story to tell yet.

- Headline: `Emergency HVAC in [CITY] -- 24/7 No-Heat & No-AC Service`
- Subhead: `Repair for furnace, AC, and heat pump failures across [SERVICE_AREA]. [TRUST_TRAILER] [SERVICE_PROMISE]`

**Tier 3 -- Local (years_in_business < 8 AND has_24_7 false/absent):**

New business without 24/7. Lead on credentials, certifications,
and the anti-franchise angle.

- Headline (if `prospect.licensed_and_insured` is true): `Licensed HVAC Contractor Serving [CITY]`
- Headline (otherwise): `HVAC Contractor Serving [CITY]`
- Subhead: `Local heating, cooling, and indoor-air service across [SERVICE_AREA]. [SERVICE_PROMISE]`

NEVER use mission-statement language ("We believe in honest HVAC",
"Our mission is to..."). NEVER use "dedicated" or "committed to."
NEVER drop the tier rule -- a Tier-1 established HVAC with 24/7
service does NOT get the bare emergency headline; 24/7 moves to
the subhead or hero chip, not the headline.

### Trust signal priority

Use the highest-tier signal the prospect actually has. Skip lower
tiers if a higher one exists.

1. Third-party review score with platform name (`4.8 from 127 Google Reviews`)
2. Years in business + location (`Serving [CITY] since [YEAR]`)
3. **EPA Section 608 / NATE certification** (`EPA-certified, NATE-certified`) -- HVAC-specific, real, verifiable credential
4. Licensing + insurance + ownership line -- render via `[TRUST_TRAILER]` from intro (composes only verified components; never the literal `Licensed, insured, family-owned` default)
5. Service-radius coverage (`Serving [CITY] and surrounding areas within 25 miles`)

EPA Section 608 certification is legally required in the US to
handle refrigerants -- if a prospect is operating, they almost
certainly have it. Worth surfacing as a trust signal because most
homeowners don't know it's mandatory and reading "EPA-certified"
adds credibility. NATE (North American Technician Excellence) is a
voluntary trade-association credential that signals higher
training; only mention if the prospect actually holds it.

NEVER fabricate certifications. If the prospect JSON doesn't
confirm NATE or specific licensing class, drop those claims and
fall back to the generic licensed/insured signal.

### Competitive positioning vs national chains

Local HVAC contractors compete against ARS / Service Experts,
American Home Shield (home-warranty dispatch), Trane Comfort
Specialists, Mr. Cool, Roto-Rooter Heating & Cooling, and similar
national/franchise brands that dominate paid local-pack ads. The
site should signal *local* without being explicit / defensive
about it.

**Positive signals for the Why-Choose-Us section** (see Section order step 6).
Each bullet has a gating rule -- a benefit card may render ONLY when the
named prospect field is verified. The same fabrication-guard discipline
that gates the hero subhead via `[TRUST_TRAILER]` and `[SERVICE_PROMISE]`
applies to the benefits grid: never invent a verified-trust or
service-promise card just to fill the 3rd slot.

**Verified trust signals** (gated by existing `[TRUST_TRAILER]` fields):
- "Family Owned & Operated" -- render only if `prospect.family_owned` is true.
- "Locally Owned, Not a Franchise" -- render only if `prospect.locally_owned` is true.
- "Licensed & Insured" -- render only if `prospect.licensed_and_insured` is true.

**Verified service promises** (require a matching entry in `prospect.service_promises`):
- Any pricing or billing benefit requires a close equivalent in `service_promises`.
- Any scheduling or estimate benefit requires a close equivalent in `service_promises`.
- Any owner-availability benefit requires an explicit matching entry and is never inferred from `has_24_7`.

**Verified trade credential** (gated by an explicit prospect field):
- "EPA-Certified Technicians" -- render only if `prospect.epa_certified` is true. EPA Section 608 cert IS near-universal among professional HVAC techs (legally required for refrigerant handling), but "near-universal" is not "verified" -- the salesperson must confirm during intake before this card renders.

**Safe generic positioning** (true by definition for the skill's target audience -- rural small-town owner-operators with no franchise affiliation, owner-or-tight-crew operations):
- "Local Service, Not a Call-Center Dispatch"
- "Same Crew Installs and Services" -- safe because target prospects are single-crew operations by definition, not the multi-team install/service-split of national franchises.
- "Serving [CITY] and [SERVICE_AREA]" -- substitute the verified `prospect.service_radius`.

**Selection rule for the EXACTLY 3 cards** (see Section order step 6):
1. Pick all verified-trust cards available.
2. Pick the verified-trade-credential card if `prospect.epa_certified` is true.
3. Pick all verified-service-promise cards available.
4. Pad with safe-generic-positioning cards if the running count is < 3.
5. Never fabricate a verified-trust, service-promise, or credential card. If the prospect data supports 0 verified cards, all 3 come from safe-generic.
6. Consolidate overlapping verified-trust cards per 06's "consolidate overlapping claims" rule.

Do NOT explicitly name competitors ("better than ARS"). Same
fabrication guards as plumber section -- looks defensive and
triggers brand-disparagement issues.

### Section render order (HVAC)

Render order comes from `prospect._computed_section_order` only. See
`references/10-section-orders.md` for the three named orderings the
harness picks among. The `default` ordering (trust-strip-first) suits
HVAC given the seasonal-emergency framing; `services-led` and
`reviews-led` render correctly for HVAC too. No HVAC-specific
ordering deviations vs plumber.

### Hours defaults

If prospect didn't specify, use:
- Office: `Monday-Friday 7:00 AM - 6:00 PM, Saturday 8:00 AM - 2:00 PM`
- Emergency: `24/7 emergency service available`
- Seasonal note: HVAC demand is bimodal -- if prospect data
  indicates extended summer/winter hours during peak season,
  surface that fact rather than using the standard week.

### Service radius defaults

If prospect didn't specify, use a 25-mile radius from the listed
city. Phrase as: `Serving [CITY] and surrounding communities
within 25 miles`. HVAC service areas tend to be slightly larger
than plumber because higher-ticket installs justify longer drive
time per call.

### Hero image source -- two paths

**Path 1 -- Unsplash photo library (preferred; consumed by `build.py`'s `fetch_unsplash_hero()` and the SKILL bash workflow; see plumber section for path details)**

```
hero_search_query: "hvac technician"
```

**Multi-word exception to the "fewer words wins" rule** (empirical,
verified 2026-05-18): for HVAC, the single-word `"hvac"` query
maps to commercial-system stock imagery (industrial pipes, exterior
AC units on walls) -- credible but cold, no human presence. The
single-word fallbacks `"furnace"`, `"heating"`, and `"air
conditioning"` produce the same equipment-only failure mode. Only
the multi-word `"hvac technician"` (605 results vs 8000+ for
"heating") returns the **tradesperson-at-work imagery** that
matches the warmth target. Lesson: "fewer words wins" is a
trade-specific heuristic, not universal. Plumber works at one word
because "plumbing" already maps to the human-at-work tag pool;
HVAC does not. When onboarding a new trade, **start with the
single-word trade name AND verify the top result has a human in
it**; if not, escalate to a two-word query that names the person
(`<trade> technician`, `<trade> contractor`, `<trade> worker`).

**Path 2 -- Flux 2 hero prompt (consumed by `build.py`'s `build_hero_prompt()`; see plumber section for the lookup mechanics)**

```
Professional photorealistic hero image for a local HVAC contractor
in [CITY]. Wide cinematic crop, natural light, depth of field.
Subject: a technician in unbranded work uniform servicing an
outdoor AC condenser unit, OR a close-up of a clean high-efficiency
furnace installation. NO text, NO logos, NO faces clearly visible,
no people wearing branded apparel from any specific company.
```

Why no faces / branded apparel: same reasoning as plumber section
-- the same image gets reused across multiple prospects in this
trade, and we don't want any prospect to feel the photo is "of
someone else's business."

### Page set for MVP

Single page (`index.html`) containing all sections above. Same
constraint as plumber. Multi-page (services subpages, individual
service detail pages, blog) is v2.

### Theme

`allowed_themes: [warm, civic, minimal, broadcast]`

The harness picks among these per the deterministic rule in
`06-build-prompt.md` (see `references/09-themes.md` for the full theme
catalog). When each one shines for an HVAC prospect:

- **warm** -- residential default. Friendly, rounded, trust-signal
  serif headlines. The natural pick for the rural homeowner audience.
- **civic** -- prospects whose brand reads cool/blue (HVAC's natural
  industry color) or municipal-contractor flavor.
- **minimal** -- commercial HVAC operations targeting business clients.
  Whitespace and clean geometric sans signal professional services.
- **broadcast** -- newer businesses leading on emergency response
  (`has_24_7: true` and `years_in_business < 8`). The HVAC failure
  modes (no-heat in winter, no-AC in summer) reward urgency framing.

### Color defaults

If prospect provided brand colors, use them. If not, the harness
(`build.py`'s `select_palette()`) picks one of the blue variants
below deterministically by hash of `business_name` and injects it
as `prospect._computed_palette`. All variants are **WCAG AA-
compliant** against white button text.

```
palette_variants:
- accent: "#1E5BB8", accent_dark: "#164B96"  -- HVAC industry blue (~6.4:1 / ~8.3:1), historical default
- accent: "#1E40AF", accent_dark: "#1E3A8A"  -- deep royal blue (~8.7:1 / ~10:1), Tailwind blue-800/900
- accent: "#0E7490", accent_dark: "#155E75"  -- cool teal-blue (~5.4:1 / ~7.5:1), Tailwind cyan-700/800 -- leans toward "cooling/comfort"
- accent: "#1D4ED8", accent_dark: "#1E40AF"  -- bright royal (~6.7:1 / ~8.7:1), Tailwind blue-700/800 -- more energetic
```

- Secondary: **emergency red** (`#B91C1C`, Tailwind red-700, ~6.5:1) -- reserved for "no heat" / "no AC" emergency CTAs only. Constant across variants. Matches plumber accent for visual consistency across the home-services trade family and uses the same WCAG-AA-compliant red the plumber section adopted to replace the shallower `#D9534F` (~4.0:1, fails AA).
- Background: white (light theme)

The blue/red split intentionally parallels the cool/hot duality
of HVAC services (cooling = blue, heating = red). This differs
from the plumber default (red-dominant) because plumber visits
are uniformly urgent while HVAC is split between urgent comfort
failures and planned high-ticket installs. The four blue variants
all preserve the "cool/professional" register but differ enough
in hue and weight to fingerprint two HVAC contractors in the
same service area.

Apply the COLOR DISCIPLINE rule from `02-redesign-gen-prompt.md`:
accent appears on AT MOST 3-4 elements (primary CTA, verified-phone CTA when
present, one badge). The secondary emergency red is reserved for emergency
CTAs only -- not used as a general accent.

---

## TRADE: electrician

### Buyer / urgency profile

An electrician prospect's site visitor falls into two segments:

1. **Emergency** (~50% of inbound traffic) -- sparking outlets,
   smell of burning insulation, breaker that won't reset, partial
   power loss, exposed wiring. Decision in hours rather than
   minutes; the genuine fire-hazard cases call immediately, the
   intermittent issues call within the day.
2. **Planned** (~50%) -- panel upgrades (200A modernization),
   generator installs, EV charger installs, new-construction
   wiring, smart-home retrofits, ceiling fans, recessed lighting.
   Decision in days to weeks. Form CTA acceptable.

Compared to plumber (70% emergency) and HVAC (60% emergency),
electrician has the LOWEST emergency proportion of the three
home-services trades. Most electrical issues have workarounds
(use a different outlet, flip the breaker) and the genuine
emergencies are less time-sensitive than a burst pipe. However,
the planned-work proportion is higher -- and planned electrical
work includes high-ticket installs (panel upgrades $1.5-3K,
generators $5-15K, EV chargers $1-3K, whole-home rewires $8-25K)
that justify research time and form-submit-then-call patterns.

### Canonical service catalog

Use these as the default service list when the prospect's JSON
doesn't specify, OR to augment a sparse list. Prospect-specified
items always win.

| Service                       | One-line description                                                |
|-------------------------------|---------------------------------------------------------------------|
| Electrical Panel Upgrade      | Service-entrance, breaker box, 100A-to-200A modernization.          |
| Outlet & Switch Installation  | New circuits, GFCI/AFCI outlets, USB outlets, dimmer installs.      |
| Lighting Installation         | Interior, exterior, recessed, undercabinet, landscape lighting.     |
| Ceiling Fan Installation      | New fan, replacement, with-light upgrade, smart-fan retrofit.       |
| Generator Installation        | Whole-home standby generators (Generac, Kohler) with auto transfer. |
| EV Charger Installation       | Level 2 home charging (Tesla, ChargePoint, JuiceBox).               |
| Smart Home Wiring             | Nest, Ring, smart switches, mesh Wi-Fi infrastructure.              |
| Wiring Repair                 | Knob-and-tube replacement, aluminum repairs, troubleshooting.       |
| Electrical Inspection         | Pre-purchase home inspection, code compliance, insurance reports.   |
| Emergency Electrical Service  | 24/7 response for fire-hazard wiring and total power loss.          |

The default 6 for an electrician build when the prospect list is
sparse: Electrical Panel Upgrade, Outlet & Switch Installation,
Lighting Installation, Ceiling Fan Installation, Generator
Installation, Wiring Repair. EV chargers and smart-home wiring are
higher-margin "growth" services for prospects targeting younger
homeowners; include in the services array only when the prospect
explicitly supports them.

### Hero copy templates -- selection rule

Apply this decision tree in order. The first matching tier wins.
Substitute `[CITY]`, `[YEAR]`, `[YEARS]`, `[SERVICE_AREA]` from
prospect values. NEVER fabricate a tenure value -- if the field is
absent, fall through to the next tier.

**Tier 1 -- Established (years_in_business >= 8):**

This tier wins even when has_24_7 is true. An 8+ year track record
beats "we're available 24/7" on credibility for electrical work
because most homeowners are evaluating "can I trust this person
with my house's wiring" more than "can they show up at 2am."

- Headline: `[CITY]'s Trusted Electrician Since [YEAR]`
- Subhead (any value of has_24_7): `[YEARS] years of residential and commercial electrical work across [SERVICE_AREA]. [TRUST_TRAILER] [SERVICE_PROMISE]`

**Tier 2 -- Emergency (years_in_business < 8 AND has_24_7 true):**

Newer business that differentiates on 24/7 availability. Lead with
it because there is no longer-tenure story to tell yet.

- Headline: `Emergency Electrician in [CITY] -- 24/7 Response`
- Subhead: `Service for sparks, no-power, breaker failures, and fire-hazard wiring across [SERVICE_AREA]. [TRUST_TRAILER] [SERVICE_PROMISE]`

**Tier 3 -- Local (years_in_business < 8 AND has_24_7 false/absent):**

New business without 24/7. The headline carries the credential
conditionally per the rule at the top of this file: render
`Master Electrician Serving [CITY]` only when
`prospect.master_electrician_license` (or equivalent in
`prospect.licenses` / `prospect.certifications`) is verified,
`Licensed Electrician Serving [CITY]` when only
`prospect.licensed_and_insured` is true, and bare
`Electrician Serving [CITY]` otherwise. Master/Master-licensed
verification is strict -- many states use "Master Electrician"
for the highest residential tier, but not all electricians hold
it, and claiming it falsely violates the SKILL.md fabrication
guards.

- Headline (if Master credential verified per intro rule): `Master Electrician Serving [CITY]`
- Headline (else if `prospect.licensed_and_insured` is true): `Licensed Electrician Serving [CITY]`
- Headline (otherwise): `Electrician Serving [CITY]`
- Subhead: `Local electrical service across [SERVICE_AREA]. [SERVICE_PROMISE]`

NEVER use mission-statement language ("We believe in honest
electrical work", "Our mission is to..."). NEVER use "dedicated"
or "committed to." NEVER drop the tier rule -- a Tier-1 established
electrician with 24/7 service does NOT get the bare emergency
headline; 24/7 moves to the subhead or hero chip, not the headline.

### Trust signal priority

Use the highest-tier signal the prospect actually has. Skip lower
tiers if a higher one exists.

1. Third-party review score with platform name (`4.8 from 87 Google Reviews`)
2. Years in business + location (`Serving [CITY] since [YEAR]`)
3. **State Master Electrician license** (`[STATE] Master Electrician licensed, #[LICENSE_NUMBER]` -- substitute `prospect.state` and the prospect's actual license number; do NOT hard-code Illinois or any other jurisdiction here) -- electrician-specific, real verifiable credential
4. IBEW Local membership (if applicable, e.g. `IBEW Local [NUMBER] member` -- use the prospect's actual local chapter number) -- union signal indicates higher training
5. Licensing + insurance + ownership line -- render via `[TRUST_TRAILER]` from intro (composes only verified components; never the literal `Licensed, insured, family-owned` default)
6. Service-radius coverage (`Serving [CITY] and surrounding areas within 25 miles`)

Master Electrician licensing is common in US states for
residential electrical work above a low threshold, but the exact
name, structure, and even existence of a statewide license vary
by state. Texas and Massachusetts run true statewide Master
Electrician programs (`TX Master Electrician`, `MA Master
Electrician #XXXX`); some states use "Journeyman vs Master,"
others use "Class A/B/C electrician." A meaningful set of
states -- **including Illinois, Indiana, Missouri, and Kansas
among others** -- have **no statewide electrician license** and
delegate licensing entirely to municipalities (Chicago,
Springfield, etc. each issue separately). For prospects in those
states, this trust signal does not apply at all -- skip it and
fall to IBEW Local membership or the generic licensed/insured
line. When the credential *does* apply, **always interpolate from
`prospect.state` rather than hard-coding any specific
jurisdiction** -- a prospect in Indiana or Missouri must not see
their listing claim a Texas license.

IBEW (International Brotherhood of Electrical Workers) is the
major US electrical workers' union; local-chapter membership
signals formal apprenticeship training. Only mention IBEW with
the actual local-chapter number from prospect data.

NEVER fabricate licenses or union memberships. If the prospect
JSON doesn't confirm Master Electrician status or specific IBEW
local, drop those claims and fall back to the generic
licensed/insured signal.

### Competitive positioning vs national chains

Local electricians compete against Mister Sparky, Mr. Electric,
The Electric Connection, ARS / Service Experts (mostly HVAC, do
some electric on the side), and big-box-store installers (Home
Depot's "Pro Referral" network for outlets and fans). The site
should signal *local* without being explicit or defensive.

**Positive signals for the Why-Choose-Us section** (see Section order step 6).
Each bullet has a gating rule -- a benefit card may render ONLY when the
named prospect field is verified. The same fabrication-guard discipline
that gates the hero subhead via `[TRUST_TRAILER]` and `[SERVICE_PROMISE]`
applies to the benefits grid: never invent a verified-trust or
service-promise card just to fill the 3rd slot.

**Verified trust signals** (gated by existing `[TRUST_TRAILER]` fields):
- "Family Owned & Operated" -- render only if `prospect.family_owned` is true.
- "Locally Owned, Not a Franchise" -- render only if `prospect.locally_owned` is true.
- "Licensed & Insured" -- render only if `prospect.licensed_and_insured` is true.

**Verified service promises** (require a matching entry in `prospect.service_promises`):
- Any pricing or billing benefit requires a close equivalent in `service_promises`.
- Any scheduling or estimate benefit requires a close equivalent in `service_promises`.
- Any owner-availability benefit requires an explicit matching entry and is never inferred from `has_24_7`.

**Verified trade credential** (gated by explicit prospect fields):
- "Master Electrician on Staff" -- render only if `prospect.master_electrician_license` (or equivalent in `prospect.licenses` / `prospect.certifications`) is verified. Same gating rule as the Tier 3 headline upgrade in the credential-stripping section above. Not "near-universal" the way EPA-cert is for HVAC -- electrician licensing varies meaningfully by state and not every electrician holds Master; verify before rendering.
- "IBEW Local [NUMBER] Member" -- render only if `prospect.ibew_local_number` is set. Substitute the actual local-chapter number.

**Safe generic positioning** (true by definition for the skill's target audience -- rural small-town owner-operators with no franchise affiliation, owner-or-tight-crew operations):
- "Local Service, Not a Big-Box Referral"
- "Same Crew Installs and Services" -- safe because target prospects are single-crew operations by definition, not the multi-team workflow of national franchises or big-box "pro referral" networks.
- "Serving [CITY] and [SERVICE_AREA]" -- substitute the verified `prospect.service_radius`.

**Selection rule for the EXACTLY 3 cards** (see Section order step 6):
1. Pick all verified-trust cards available.
2. Pick verified-trade-credential cards available (Master Electrician, IBEW Local) -- but consolidate if both apply (one card naming the higher-trust credential).
3. Pick all verified-service-promise cards available.
4. Pad with safe-generic-positioning cards if the running count is < 3.
5. Never fabricate a verified-trust, service-promise, or credential card. If the prospect data supports 0 verified cards, all 3 come from safe-generic.
6. Consolidate overlapping verified-trust cards per 06's "consolidate overlapping claims" rule.

Do NOT explicitly name competitors ("better than Mister Sparky").
Same fabrication guards as plumber and HVAC sections.

### Section render order (electrician)

Render order comes from `prospect._computed_section_order` only. See
`references/10-section-orders.md` for the three named orderings the
harness picks among. No electrician-specific ordering deviations vs
plumber or HVAC.

### Hours defaults

If prospect didn't specify, use:
- Office: `Monday-Friday 7:00 AM - 6:00 PM, Saturday 8:00 AM - 2:00 PM`
- Emergency: `24/7 emergency service available` (only if has_24_7 is true)
- Note: electricians often DON'T do 24/7 even when their plumber
  peers do. Less weather-driven demand than HVAC, fewer
  burst-pipe-equivalent failures than plumbing. Don't default has_24_7
  to true for electrician prospects without verification.

### Service radius defaults

If prospect didn't specify, use a 25-mile radius from the listed
city. Phrase as: `Serving [CITY] and surrounding communities
within 25 miles`. Same as HVAC.

### Hero image source -- two paths

**Path 1 -- Unsplash photo library (preferred; consumed by `build.py`'s `fetch_unsplash_hero()` and the SKILL bash workflow; see plumber section for path details)**

```
hero_search_query: "electrician"
```

Single-word query. **Unlike `"hvac"`** (acronym for systems, returns
commercial-system stock), `"electrician"` is itself a person noun,
so the single-word query typically returns tradesperson-at-work
imagery (man in hard hat with wiring or panel, often a real
electrician on a job). Verify the top result has a human in it
before committing; if it returns power-line-tower-only or
panel-only shots without a person, escalate to
`"electrician working"` or `"electrician technician"` per the
multi-word fallback rule documented in the HVAC section above.

**Path 2 -- Flux 2 hero prompt (consumed by `build.py`'s `build_hero_prompt()`; see plumber section for the lookup mechanics)**

```
Professional photorealistic hero image for a local electrician
in [CITY]. Wide cinematic crop, natural light, depth of field.
Subject: a master electrician in work uniform installing or
inspecting a breaker panel, OR working on visible house wiring
with hand tools. NO text, NO logos, NO faces clearly visible,
no people wearing branded apparel from any specific company.
```

### Page set for MVP

Single page (`index.html`) containing all sections above. Same
constraint as plumber and HVAC. Multi-page (service subpages,
individual installs as detail pages, blog) is v2.

### Theme

`allowed_themes: [warm, minimal, civic, broadcast]`

The harness picks among these per the deterministic rule in
`06-build-prompt.md` (see `references/09-themes.md` for the full theme
catalog). When each one shines for an electrician prospect:

- **warm** -- residential default. The natural pick for rural homeowner
  audiences and family-owned shops.
- **minimal** -- commercial electrical operations, electricians
  targeting business clients, EV-charger or smart-home specialists.
  Whitespace + DM Sans reads sleek and modern.
- **civic** -- prospects whose brand reads utility / clinical /
  municipal-contractor.
- **broadcast** -- emergency-first electricians (sparks, no-power,
  breaker failures) with `has_24_7: true`. Lower hit rate for
  electricians than for plumbers since 24/7 is rarer in this trade,
  but applicable when present.

### Color defaults

If prospect provided brand colors, use them. If not, the harness
(`build.py`'s `select_palette()`) picks one of the amber/orange
variants below deterministically by hash of `business_name` and
injects it as `prospect._computed_palette`. All variants are
**WCAG AA-compliant** against white button text. The shallower
amber-600 (`#D97706`, ~3.4:1) fails AA and is **explicitly
rejected** for accent slots that overlay white text.

```
palette_variants:
- accent: "#B45309", accent_dark: "#92400E"  -- electric amber (~5.0:1 / ~7.0:1), Tailwind amber-700/800, historical default
- accent: "#92400E", accent_dark: "#78350F"  -- deep amber (~7.0:1 / ~9.0:1), Tailwind amber-800/900 -- grounded, less neon
- accent: "#C2410C", accent_dark: "#9A3412"  -- warm orange (~5.2:1 / ~7.3:1), Tailwind orange-700/800 -- echoes voltage-warning palette
- accent: "#A16207", accent_dark: "#854D0E"  -- rich gold-orange (~4.9:1 / ~6.9:1), Tailwind yellow-700/800 -- closer to "caution" yellow without crossing into illegibility
```

- Secondary: navy (`#1F3A5F`, ~11.5:1) -- trust/professional signal for emergency CTAs and panel-upgrade CTAs. Constant across variants.
- Background: white (light theme)

The four variants all echo the industry's electrical caution /
breaker-label / voltage-warning palette without crossing into pure
yellow (which has poor contrast for white text). They stay
distinct from plumber's red and HVAC's blue at a glance while
giving same-trade prospects in the same area visibly different
accents.

Apply the COLOR DISCIPLINE rule from `02-redesign-gen-prompt.md`:
accent appears on AT MOST 3-4 elements (primary CTA, verified-phone CTA when
present, one badge). The secondary navy is reserved for emergency CTAs and
high-ticket-install CTAs (panel upgrade, generator) -- not used
as a general accent.
