"""From-scratch website build for local-business prospects with no
existing online presence. Sibling pipeline to pipeline.py (which redesigns
existing sites).

Usage:
  python build.py <prospect.json> [--generation-provider local|openrouter]
      [--generation-model MODEL] [--skip-deploy] [--skip-image-gen]
      [--skip-email-draft]

Reads a small prospect JSON, optionally generates a hero image, generates
a single-page site via the explicitly selected provider, writes to
outputs/builds/<slug>/, writes
a pitch email draft to outputs/email_drafts/<slug>.md (siblings -- the
draft is NOT in the Vercel deploy root and never published), and
optionally deploys the site to Vercel. The salesperson sends the pitch
email manually from their own email client AFTER replacing the
[VERCEL_URL_PLACEHOLDER] token in the draft. No automated send path.
"""
import os
import re
import json
import hashlib
import argparse
from datetime import date

from lib.images import fetch_unsplash_hero, generate_image_openrouter
from lib.deploy import deploy_to_vercel
from lib.generation import (
    DEFAULT_DOCUMENT_ACCENT,
    DEFAULT_DOCUMENT_SECONDARY,
    REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES,
    REQUIRED_FOOTER_CLASS_COUNTS,
    DocumentColors,
    PromptPart,
    assemble_generated_html,
    atomic_write_text,
    body_generation_config,
    extract_homepage_class_names,
    extract_interior_only_class_names,
    extract_square_placeholder_tokens,
    generate_text,
    make_html_comment,
    preflight_generation_provider,
    require_complete_text,
    resolve_generation_config,
)
# lib.email.send_pitch_email is intentionally NOT imported here. The
# from-scratch build flow uses the manual email_draft.md workflow
# instead -- the salesperson sends from their own client after
# replacing [VERCEL_URL_PLACEHOLDER]. The Resend-backed auto-send
# path is still used by pipeline.py (the redesign flow).

BUILD_PROMPT_PATH = "references/06-build-prompt.md"
INDUSTRY_DEFAULTS_PATH = "references/07-industry-defaults.md"
BASE_TEMPLATE_PATH = "references/03-base-template.html"
THEMES_CATALOG_PATH = "references/09-themes.md"
SECTION_ORDERS_PATH = "references/10-section-orders.md"
EMAIL_PROMPT_PATH = "references/08-pitch-email-prompt.md"
BUILD_OUTPUT_ROOT = os.path.join("outputs", "builds")
# Email drafts live in a SIBLING directory, never inside BUILD_OUTPUT_ROOT/<slug>/.
# The Vercel deploy uses outputs/builds/<slug>/ as its root; anything in there
# gets published. The pitch email is an internal salesperson handoff and must
# not be reachable at /email_draft.md on the deployed site.
EMAIL_DRAFT_ROOT = os.path.join("outputs", "email_drafts")
BUILD_TEMPERATURE = 0.4
BUILD_USER_TRUNCATE = 200000
BUILD_RESPONSE_BOUNDARY_REMINDER = (
    "RESPONSE BOUNDARY: Begin your response immediately with <body. "
    "End immediately with </body>. Emit no leading comment, preamble, markdown "
    "fence, trailing text, deployment metadata, or HTML head metadata. Do not "
    "emit any unresolved double-curly or square-bracket template token."
)
# Email-draft generation is short, deterministic, and copy-focused.
# Lower temperature than the HTML build to keep the voice tight.
EMAIL_TEMPERATURE = 0.3
DEFAULT_SALESPERSON_FIRST_NAME = "Juan"

BUILD_DEPLOYMENT_COMMENT_MARKERS = (
    "NEW WEBSITE BUILD - - FROM SCRATCH",
    "Prospect:",
    "Trade:",
    "Location:",
    "HOSTING:",
    "LEAD HANDLER:",
    "ONGOING COST:",
    "DEPLOY:",
)

GATED_SERVICE_CLAIMS = {
    "Upfront Flat-Rate": ("flat-rate pricing", "upfront pricing"),
    "Surprise Fees": ("flat-rate pricing", "upfront pricing", "no surprise fees"),
    "Free Estimates": ("free estimates",),
    "Owner Answers": ("owner answers",),
}

FIELD_GATED_CLAIMS = {
    "licensed_and_insured": ("Licensed", "Insured"),
    "family_owned": ("Family Owned",),
    "locally_owned": ("Locally Owned", "Not a Franchise"),
    "has_24_7": ("24/7", "24 Hour Service", "Around the Clock"),
    "same_day_service": ("Same Day",),
    "epa_certified": ("EPA Certified", "EPA Section 608"),
    "master_electrician_license": ("Master Electrician", "Master Licensed"),
    "ibew_local_number": ("IBEW",),
}

FIELD_GATED_PROMISE_EVIDENCE = {
    "has_24_7": ("24/7", "24 hour", "around the clock"),
    "same_day_service": ("same-day", "same day"),
}

BOOLEAN_CLAIM_FIELDS = frozenset(
    {
        "licensed_and_insured",
        "family_owned",
        "locally_owned",
        "has_24_7",
        "same_day_service",
        "epa_certified",
    }
)

BUILD_REQUIRED_CLASS_COUNTS = (
    ("site-nav", 1),
    ("dual-cta-hero", 1),
    ("coverage-band", 1),
    ("services-grid", 1),
    ("service-card", 6),
    ("service-card-name", 6),
    ("service-card-desc", 6),
    ("benefits-grid", 1),
    ("benefit-card", 3),
    ("contact-form-wrap", 1),
    *REQUIRED_FOOTER_CLASS_COUNTS,
)
BUILD_REQUIRED_CHILD_CLASS_SEQUENCES = (
    ("services-grid", ("service-card",) * 6),
    ("service-card", ("service-card-name", "service-card-desc")),
    ("benefits-grid", ("benefit-card",) * 3),
    *REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES,
)


def required_build_class_counts(prospect):
    """Return the exact page skeleton valid for the sanitized prospect."""
    if prospect.get("phone"):
        return BUILD_REQUIRED_CLASS_COUNTS
    return tuple(
        (class_name, 0 if class_name == "coverage-band" else expected_count)
        for class_name, expected_count in BUILD_REQUIRED_CLASS_COUNTS
    )


def expected_build_form_action(prospect):
    endpoint = prospect.get("formspree_endpoint")
    if isinstance(endpoint, str) and endpoint.strip():
        return endpoint.strip()
    return "#"


BUILD_SERVICES_RESPONSE_SCAFFOLD = (
    '<div class="page-wrap section-gap">\n'
    '  <div class="sec-hd">\n'
    '    <span class="sec-title"><span class="sec-dot"></span>Services</span>\n'
    '  </div>\n'
    '  <div class="services-grid">\n'
    + "\n".join(
        '    <div class="service-card">\n'
        f'      <div class="service-card-name">[SERVICE_{index}_NAME]</div>\n'
        f'      <p class="service-card-desc">[SERVICE_{index}_DESCRIPTION]</p>\n'
        '    </div>'
        for index in range(1, 7)
    )
    + '\n  </div>\n'
    '</div>'
)

REQUIRED_FIELDS = ("business_name", "trade", "city", "state", "phone")

# Substring markers that indicate a prospect-JSON field was left at its
# template default. Case-insensitive substring match against the value.
PLACEHOLDER_MARKERS = (
    "example.com",
    "REPLACE",
    "YOUR_FORM_ID",
    "(REPLACE)",
    "TODO",
)
# Fields where a placeholder is a credibility / functionality problem --
# warn loudly, don't silently strip. The site will still build, but the
# salesperson needs to fix these before sending the link to a prospect.
PLACEHOLDER_CRITICAL_FIELDS = ("business_name", "formspree_endpoint")
# Fields where a placeholder should be silently nullified so the LLM
# doesn't render it. Safer to omit "owner@example.com" from the footer
# than to render it on a live site.
PLACEHOLDER_NULLIFY_FIELDS = ("owner_email", "owner_first_name", "phone", "address")


def _is_placeholder(value):
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)


def sanitize_placeholders(prospect):
    """Detect prospect-JSON values left at their template defaults. Critical
    fields produce a loud warning; nullifiable fields are silently set to
    None so the LLM omits them from the rendered output."""
    for field in PLACEHOLDER_CRITICAL_FIELDS:
        value = prospect.get(field)
        if _is_placeholder(value):
            print(f"[!] PLACEHOLDER VALUE in prospect.{field}: {value!r}")
            print(f"    The site will render this verbatim. Update before sharing the live URL.")
    for field in PLACEHOLDER_NULLIFY_FIELDS:
        value = prospect.get(field)
        if _is_placeholder(value):
            print(f"[*] Nullifying placeholder prospect.{field}: {value!r}")
            prospect[field] = None


def sanitize_reviews(prospect):
    """Drop entries from prospect.reviews that still contain template
    placeholder markers (EXAMPLE / REPLACE / etc.) in any of their
    visible string fields. The remaining list is what the build will
    actually render."""
    reviews = prospect.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        return
    cleaned = []
    dropped = 0
    for r in reviews:
        if not isinstance(r, dict):
            dropped += 1
            continue
        suspect_fields = ("author", "text", "date", "platform")
        if any(_is_placeholder(r.get(f)) for f in suspect_fields):
            text_preview = (r.get("text") or "")[:60]
            print(f"[*] Dropping placeholder review entry: author={r.get('author')!r}, text={text_preview!r}...")
            dropped += 1
            continue
        cleaned.append(r)
    if dropped:
        prospect["reviews"] = cleaned
        print(f"[*] {dropped} placeholder review(s) removed; {len(cleaned)} real review(s) remain.")


def normalize_years(prospect, build_date):
    """If established_year is set, recompute years_in_business from
    current_year - established_year so a stale JSON doesn't report the
    wrong tenure. Established_year wins over years_in_business when both
    are present."""
    current_year = build_date.year
    established = prospect.get("established_year")
    if isinstance(established, int) and 1900 <= established < current_year:
        computed = current_year - established
        existing = prospect.get("years_in_business")
        if existing != computed:
            print(f"[*] years_in_business recomputed: {existing} -> {computed} (from established_year={established})")
        prospect["years_in_business"] = computed
    return prospect


def load_prospect(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Prospect JSON not found: {path}")
    with open(path, "r") as f:
        prospect = json.load(f)
    missing = [k for k in REQUIRED_FIELDS if not prospect.get(k)]
    if missing:
        raise ValueError(f"Prospect JSON missing required field(s): {', '.join(missing)}")
    sanitize_placeholders(prospect)
    sanitize_reviews(prospect)
    build_date = date.today()
    prospect["build_date"] = build_date.isoformat()
    normalize_years(prospect, build_date)
    return prospect


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "prospect"


def build_deployment_comment(prospect):
    """Render deployment metadata from trusted inputs, never model output."""
    lines = [
        "============================================================",
        "NEW WEBSITE BUILD -- FROM SCRATCH",
        "============================================================",
        f"Prospect:        {prospect['business_name']}",
        f"Trade:           {prospect['trade']}",
        f"Location:        {prospect['city']}, {prospect['state']}",
    ]
    if prospect.get("build_date"):
        lines.append(f"Generated:       {prospect['build_date']}")
    lines.extend(
        [
            "",
            "HOSTING:         Vercel (free, static, auto-SSL via Let's Encrypt)",
            "LEAD HANDLER:    Formspree (free tier 50 submissions/mo)",
            "ONGOING COST:    ~$15/yr (domain renewal only)",
        ]
    )

    photos = prospect.get("photos")
    first_photo = (
        photos[0]
        if isinstance(photos, list) and photos and isinstance(photos[0], dict)
        else {}
    )
    if all(first_photo.get(field) for field in ("credit_name", "credit_url", "photo_id")):
        lines.extend(
            [
                "",
                f"HERO PHOTO:      {first_photo['credit_name']} via Unsplash ({first_photo['credit_url']})",
                f"PHOTO ID:        {first_photo['photo_id']}",
                "PHOTO LICENSE:   Unsplash License (free, no on-page attribution required;",
                "                 credited here per Unsplash API terms of service)",
            ]
        )

    site_slug = prospect.get("slug") or slugify(prospect["business_name"])
    lines.extend(
        [
            "",
            "DEPLOY:",
            "1. Confirm prospect.formspree_endpoint is set on the form action.",
            f"2. Run the production Vercel deploy command for project {site_slug}.",
            "3. Custom domain: add it in Vercel dashboard, point DNS.",
            "============================================================",
        ]
    )
    return make_html_comment("\n".join(lines))


def unverified_service_claim_phrases(prospect):
    promises = prospect.get("service_promises")
    normalized_promises = (
        tuple(
            promise.casefold()
            for promise in promises
            if isinstance(promise, str) and promise.strip()
        )
        if isinstance(promises, list)
        else ()
    )
    unsupported_service_claims = tuple(
        claim
        for claim, evidence_phrases in GATED_SERVICE_CLAIMS.items()
        if not any(
            evidence in promise
            for promise in normalized_promises
            for evidence in evidence_phrases
        )
    )
    unsupported_field_claims = tuple(
        claim
        for field, claims in FIELD_GATED_CLAIMS.items()
        if not _field_claim_is_verified(prospect, field, normalized_promises)
        for claim in claims
    )
    return tuple(dict.fromkeys((*unsupported_service_claims, *unsupported_field_claims)))


def _field_claim_is_verified(prospect, field, normalized_promises):
    if field in BOOLEAN_CLAIM_FIELDS and prospect.get(field) is True:
        return True
    evidence_phrases = FIELD_GATED_PROMISE_EVIDENCE.get(field, ())
    if any(
        evidence in promise
        for promise in normalized_promises
        for evidence in evidence_phrases
    ):
        return True
    value = prospect.get(field)
    if field == "master_electrician_license":
        if isinstance(value, str) and value.strip():
            return True
        equivalent_credentials = (
            prospect.get("licenses"),
            prospect.get("certifications"),
        )
        return any(
            phrase in credential.casefold()
            for collection in equivalent_credentials
            if isinstance(collection, list)
            for credential in collection
            if isinstance(credential, str)
            for phrase in ("master electrician", "master-licensed", "master licensed")
        )
    if field == "ibew_local_number":
        return (
            isinstance(value, str)
            and bool(value.strip())
            or isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        )
    return False


# Catalog of theme names recognized by 09-themes.md. The harness validates
# computed_theme against this set so an out-of-band override (e.g. someone
# putting "vintage" in prospect.theme_override) doesn't silently propagate
# into the LLM prompt as an unknown theme. Kept in sync with the per-theme
# sections in references/09-themes.md.
KNOWN_THEMES = frozenset((
    "warm",
    "minimal",
    "civic",
    "broadcast",
    "editorial",
    "brand-forward",
))
DEFAULT_THEME = "warm"


def _extract_trade_allowed_themes(trade):
    # Parse 07's `## TRADE: <trade>` section and return the
    # `allowed_themes: [a, b, c]` list. Returns None when the section,
    # the list line, or any parsed entry is missing -- the caller falls
    # back to [DEFAULT_THEME] in that case so a misconfigured 07 still
    # produces a buildable site rather than a hard crash.
    try:
        with open(INDUSTRY_DEFAULTS_PATH, "r") as f:
            content = f.read()
    except OSError:
        return None

    section_match = re.search(
        r"^## TRADE:\s*" + re.escape(trade) + r"\s*$(.*?)(?=^## TRADE:|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return None

    line_match = re.search(
        r"`allowed_themes:\s*\[([^\]]+)\]`",
        section_match.group(1),
    )
    if not line_match:
        return None

    candidates = [t.strip() for t in line_match.group(1).split(",")]
    valid = [t for t in candidates if t in KNOWN_THEMES]
    return valid or None


# Section-order catalog. Each name corresponds to an entry in
# references/10-section-orders.md. The LLM reads
# prospect._computed_section_order and renders sections in the order
# documented under that catalog entry. Selection is purely an
# ordering choice -- it never overrides per-section render rules
# (reviews three-branch logic, coverage-band-needs-phone, etc.).
# Kept ordered (list, not set) so the [0] element is the canonical
# fallback when select_section_order() can't validate a pick.
KNOWN_SECTION_ORDERS = (
    "default",
    "services-led",
    "reviews-led",
)
DEFAULT_SECTION_ORDER = KNOWN_SECTION_ORDERS[0]


def select_section_order(prospect):
    # Deterministic per-prospect section-order selection. Same
    # business_name -> same ordering. Hash slice md5[16:24] is
    # disjoint from theme [:8] and palette [8:16] so the three
    # variation axes (theme + palette + section order) are
    # statistically independent. Falls back to DEFAULT_SECTION_ORDER
    # when business_name is empty (rare; only on incomplete prospect
    # JSON that already triggered a REQUIRED_FIELDS error earlier).
    business_name = (prospect.get("business_name") or "").strip().lower()
    if not business_name:
        return DEFAULT_SECTION_ORDER
    digest = hashlib.md5(business_name.encode("utf-8")).hexdigest()
    index = int(digest[16:24], 16) % len(KNOWN_SECTION_ORDERS)
    return KNOWN_SECTION_ORDERS[index]


# Hero shape catalog. Each theme in 09-themes.md couples to one hero
# shape -- the layout personality the theme is designed around. Same
# theme always implies the same hero shape, so the coupling adds no new
# hash slice and stays deterministic per prospect. If a future theme
# is added to 09 without an entry here, select_hero_shape() falls back
# to "fullbleed" so the build still produces a hero.
THEME_TO_HERO_SHAPE = {
    "broadcast": "fullbleed",     # urgent, photo-driven
    "editorial": "split",         # newspaper, column-based feel
    "civic": "fullbleed",
    "warm": "fullbleed",
    "minimal": "gradient",        # no-photo layout fits the airy aesthetic
    "brand-forward": "fullbleed", # 09 says "hero photos dominate"
}
KNOWN_HERO_SHAPES = frozenset(("fullbleed", "split", "gradient"))
DEFAULT_HERO_SHAPE = "fullbleed"


def select_hero_shape(prospect):
    # Map the prospect's _computed_theme to a hero shape. No new hash
    # slice -- the coupling is intentional so the visual language of
    # the theme matches the hero layout. Falls back to DEFAULT_HERO_SHAPE
    # when the theme is unknown, _computed_theme is missing, OR when the
    # mapping yields a shape that isn't in KNOWN_HERO_SHAPES. The latter
    # case indicates a desync between THEME_TO_HERO_SHAPE here and the
    # `.hero-*` CSS classes in 03-base-template.html -- warn loudly so
    # the operator notices the configuration drift.
    theme = prospect.get("_computed_theme")
    if not theme:
        return DEFAULT_HERO_SHAPE
    shape = THEME_TO_HERO_SHAPE.get(theme, DEFAULT_HERO_SHAPE)
    if shape not in KNOWN_HERO_SHAPES:
        print(
            f"[!] select_hero_shape: theme {theme!r} maps to unknown shape "
            f"{shape!r}; falling back to {DEFAULT_HERO_SHAPE!r}. Check "
            f"THEME_TO_HERO_SHAPE in build.py vs the .hero-* classes in "
            f"03-base-template.html."
        )
        return DEFAULT_HERO_SHAPE
    return shape


def _extract_trade_palette_variants(trade):
    # Parse 07's `## TRADE: <trade>` -> `### Color defaults` block and
    # return a list of (accent, accent_dark) hex tuples from the
    # `palette_variants:` fenced block. Returns None when the trade
    # section, Color defaults subsection, or variants block can't be
    # found -- the caller falls back to None and the LLM uses 07's
    # documented "historical default" pair (first row of each block).
    try:
        with open(INDUSTRY_DEFAULTS_PATH, "r") as f:
            content = f.read()
    except OSError:
        return None

    section_match = re.search(
        r"^## TRADE:\s*" + re.escape(trade) + r"\s*$(.*?)(?=^## TRADE:|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return None

    color_block = re.search(
        r"^### Color defaults\b(.*?)(?=^### |\Z)",
        section_match.group(1),
        re.MULTILINE | re.DOTALL,
    )
    if not color_block:
        return None

    fenced = re.search(
        r"palette_variants:\s*\n(.*?)\n```",
        color_block.group(1),
        re.DOTALL,
    )
    if not fenced:
        return None

    variants = []
    for line in fenced.group(1).splitlines():
        pair = re.search(
            r'accent:\s*"(#[0-9A-Fa-f]{6})",\s*accent_dark:\s*"(#[0-9A-Fa-f]{6})"',
            line,
        )
        if pair:
            variants.append((pair.group(1), pair.group(2)))
    return variants or None


def _extract_trade_secondary(trade):
    try:
        with open(INDUSTRY_DEFAULTS_PATH, "r") as f:
            content = f.read()
    except OSError:
        return None

    section_match = re.search(
        r"^## TRADE:\s*" + re.escape(trade) + r"\s*$(.*?)(?=^## TRADE:|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return None
    color_block = re.search(
        r"^### Color defaults\b(.*?)(?=^### |\Z)",
        section_match.group(1),
        re.MULTILINE | re.DOTALL,
    )
    if not color_block:
        return None
    secondary_match = re.search(
        r"Secondary:.*?`(#[0-9A-Fa-f]{6})`",
        color_block.group(1),
        re.DOTALL,
    )
    return secondary_match.group(1) if secondary_match else None


def _darken_hex_color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise ValueError("Primary brand color must be a six-digit hex value.")
    channels = [int(value[index : index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{round(channel * 0.75):02X}" for channel in channels)


def _resolve_build_document_colors(prospect):
    brand_colors = prospect.get("brand_colors")
    trade_secondary = _extract_trade_secondary(prospect.get("trade", ""))
    if brand_colors:
        if isinstance(brand_colors, str):
            accent = brand_colors
            accent_dark = None
            secondary = None
        elif isinstance(brand_colors, (list, tuple)):
            accent = brand_colors[0] if brand_colors else None
            accent_dark = None
            secondary = brand_colors[1] if len(brand_colors) > 1 else None
        elif isinstance(brand_colors, dict):
            accent = brand_colors.get("accent") or brand_colors.get("primary")
            accent_dark = brand_colors.get("accent_dark") or brand_colors.get("dark")
            secondary = brand_colors.get("secondary")
        else:
            raise ValueError(
                "brand_colors must be a hex string, a color list, or a palette object."
            )
        if not accent:
            raise ValueError("brand_colors does not contain a primary color.")
        return DocumentColors(
            accent=accent,
            accent_dark=accent_dark or _darken_hex_color(accent),
            secondary=secondary or trade_secondary or DEFAULT_DOCUMENT_SECONDARY,
        )

    palette = prospect.get("_computed_palette")
    if palette is None:
        palette = select_palette(prospect)
    if palette is None:
        return DocumentColors(
            accent=DEFAULT_DOCUMENT_ACCENT,
            accent_dark=_darken_hex_color(DEFAULT_DOCUMENT_ACCENT),
            secondary=DEFAULT_DOCUMENT_SECONDARY,
        )
    if not isinstance(palette, dict):
        raise ValueError("_computed_palette must be a palette object.")
    return DocumentColors(
        accent=palette.get("accent"),
        accent_dark=palette.get("accent_dark"),
        secondary=(
            palette.get("secondary")
            or trade_secondary
            or DEFAULT_DOCUMENT_SECONDARY
        ),
    )


def select_palette(prospect):
    # Deterministic per-prospect palette selection. Same prospect JSON
    # always yields the same palette. Returns a dict with 'accent' and
    # 'accent_dark' hex codes, or None if the prospect already specified
    # brand_colors (the LLM then uses those verbatim via 06's :root
    # rule).
    #
    # Hash slice: select_theme() uses md5[:8]; select_palette() uses
    # md5[8:16]. Same md5(business_name) but disjoint slices, so theme
    # and palette selection are independent -- two prospects can share a
    # theme but get different palettes, or vice versa.
    if prospect.get("brand_colors"):
        return None

    trade = prospect.get("trade", "")
    variants = _extract_trade_palette_variants(trade)
    if not variants:
        return None

    business_name = (prospect.get("business_name") or "").strip().lower()
    if not business_name:
        accent, accent_dark = variants[0]
    else:
        digest = hashlib.md5(business_name.encode("utf-8")).hexdigest()
        index = int(digest[8:16], 16) % len(variants)
        accent, accent_dark = variants[index]

    return {"accent": accent, "accent_dark": accent_dark}


def select_theme(prospect):
    # Deterministic per-prospect theme selection. Same prospect JSON
    # always yields the same theme. Priority order (first match wins):
    #
    # 1. prospect.brand_colors is set (any non-null value) -> brand-forward.
    #    The prospect already has explicit brand identity; the layout
    #    designed to showcase it is brand-forward.
    # 2. prospect.theme_override is set AND names a known theme -> that
    #    theme. Salesperson explicit opt-in. Unknown values are ignored
    #    so a typo doesn't silently propagate as an unrecognized theme.
    # 3. Hash-based pick from the trade's allowed_themes list (from 07).
    #    md5(business_name.lower()) mod len(allowed) is stable across
    #    Python runs (unlike the built-in hash()), so re-builds match.
    # 4. Fallback to DEFAULT_THEME if 07 can't be parsed or the trade
    #    has no allowed_themes entry.
    if prospect.get("brand_colors"):
        return "brand-forward"

    override = prospect.get("theme_override")
    if isinstance(override, str) and override in KNOWN_THEMES:
        return override

    trade = prospect.get("trade", "")
    allowed = _extract_trade_allowed_themes(trade) or [DEFAULT_THEME]

    business_name = (prospect.get("business_name") or "").strip().lower()
    if not business_name:
        return allowed[0]
    digest = hashlib.md5(business_name.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(allowed)
    return allowed[index]


def _extract_trade_hero_prompt(trade):
    # Read 07's `## TRADE: <trade>` section and return the Path 2 Flux
    # prompt template (with [CITY] / [STATE] placeholders intact), or
    # None if the section, the Path 2 marker, or the fenced code block
    # can't be found. The caller substitutes placeholders and falls
    # back to a generic prompt when this returns None.
    try:
        with open(INDUSTRY_DEFAULTS_PATH, "r") as f:
            content = f.read()
    except OSError:
        return None

    section_match = re.search(
        r"^## TRADE:\s*" + re.escape(trade) + r"\s*$(.*?)(?=^## TRADE:|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return None

    block_match = re.search(
        r"\*\*Path 2[^*]*\*\*.*?```(?:\w+)?\s*\n(.*?)\n```",
        section_match.group(1),
        re.DOTALL,
    )
    if not block_match:
        return None
    return block_match.group(1).strip()


def build_hero_prompt(prospect):
    trade = prospect.get("trade", "")
    city = prospect.get("city", "")
    state = prospect.get("state", "")

    template = _extract_trade_hero_prompt(trade) if trade else None
    if template:
        return template.replace("[CITY]", city).replace("[STATE]", state)

    # Trade-agnostic fallback. Fires when the prospect's trade key has
    # no matching `## TRADE:` section in 07, or the Path 2 block is
    # missing / unparseable. Keeps the build resilient if 07 is edited
    # in a way that breaks the regex; the prospect still gets a hero.
    display_trade = trade or "local business"
    return (
        f"Professional photorealistic hero image for a local {display_trade} business in "
        f"{city}, {state}. Wide cinematic crop, golden-hour natural light, depth "
        f"of field. Subject: a clean service van in a residential driveway OR a "
        f"close-up of professional tools in use. NO text, NO logos, NO faces "
        f"clearly visible, no branded apparel from any specific company. "
        f"Generic-but-professional. Avoid stock-photo cliches."
    )


def generate_build_html(prospect, generation_config=None, client=None):
    config = generation_config or resolve_generation_config()
    print(
        f"[*] Generating site for {prospect['business_name']} using "
        f"{config.provider}:{config.model}..."
    )
    with open(BUILD_PROMPT_PATH, "r") as f:
        system_prompt = f.read()
    with open(INDUSTRY_DEFAULTS_PATH, "r") as f:
        industry_defaults = f.read()
    with open(THEMES_CATALOG_PATH, "r") as f:
        themes_catalog = f.read()
    with open(SECTION_ORDERS_PATH, "r") as f:
        section_orders = f.read()
    with open(BASE_TEMPLATE_PATH, "r") as f:
        base_template = f.read()
    homepage_classes = extract_homepage_class_names(base_template)
    class_catalog = "\n".join(homepage_classes)
    interior_only_classes = extract_interior_only_class_names(base_template)

    # Static block -- same bytes for every plumber/HVAC/electrician build.
    # Cache marker on the end of this lets consecutive builds within the
    # 5-minute ephemeral window pay ~0.1x for these tokens instead of full
    # price. The static block deliberately comes BEFORE the variable
    # prospect JSON: prompt caching is a prefix match, so any byte change
    # before the marker invalidates the cache for that breakpoint.
    #
    # THEMES and SECTION ORDERS are inlined so the LLM can actually look
    # up _computed_theme and _computed_section_order in the catalogs.
    # Without this inlining, 06's prose pointers to 09-themes.md and
    # 10-section-orders.md are dangling references -- the LLM never sees
    # the file contents. Slice 3b (PR #19) closed the gap for 10; this
    # closes it for 09 (issue #20). The block order
    # INDUSTRY_DEFAULTS -> THEMES -> SECTION_ORDERS -> CLASS_CATALOG
    # walks the LLM through trade guidance, then typography/layout
    # personality, then section sequence, then the CSS framework.
    static_block = (
        f"INDUSTRY DEFAULTS:\n{industry_defaults}\n\n"
        f"THEMES:\n{themes_catalog}\n\n"
        f"SECTION ORDERS:\n{section_orders}\n\n"
        f"ALLOWED BODY CLASSES:\n{class_catalog}"
    )
    prospect_block = f"PROSPECT JSON:\n{json.dumps(prospect, indent=2)}"
    if len(prospect_block) > BUILD_USER_TRUNCATE:
        prospect_block = prospect_block[:BUILD_USER_TRUNCATE]

    logo_url = prospect.get("logo_url")
    prospect_photos = prospect.get("photos")
    if not isinstance(logo_url, str) or not logo_url.strip():
        logo_url = next(
            (
                candidate
                for photo in (
                    prospect_photos if isinstance(prospect_photos, list) else []
                )
                if isinstance(photo, dict) and photo.get("context") == "logo"
                for candidate in (photo.get("url"), photo.get("src"), photo.get("path"))
                if isinstance(candidate, str) and candidate.strip()
            ),
            None,
        )
    required_substitutions = {
        "business_name": prospect["business_name"],
        "phone": prospect.get("phone"),
    }
    required_class_counts = required_build_class_counts(prospect)
    if logo_url:
        logo_instruction = (
            f"Use this exact logo URL when rendering the nav: {json.dumps(logo_url)}."
        )
    else:
        logo_instruction = (
            "No logo URL was supplied. Omit the nav-logo image entirely, show the "
            "text business name, and do not invent a logo URL."
        )
    response_boundary = (
        f"{BUILD_RESPONSE_BOUNDARY_REMINDER}\n"
        "MANDATORY CLASS COUNTS: "
        f"{json.dumps(dict(required_class_counts), ensure_ascii=False)}\n"
        "MANDATORY SERVICES: At the position required by "
        "prospect._computed_section_order, reproduce the exact scaffold below. "
        "Replace every square-bracket token with the selected prospect or "
        "canonical-trade service content; do not emit the tokens themselves.\n"
        f"{BUILD_SERVICES_RESPONSE_SCAFFOLD}\n"
        "MANDATORY EXACT SUBSTITUTIONS: "
        f"{json.dumps(required_substitutions, ensure_ascii=False)}\n"
        f"{logo_instruction}"
    )

    result = generate_text(
        body_generation_config(config),
        system_prompt=system_prompt,
        user_parts=(
            PromptPart(static_block, cacheable=True),
            PromptPart(prospect_block),
            PromptPart(response_boundary),
        ),
        temperature=BUILD_TEMPERATURE,
        cache_system_prompt=True,
        client=client,
    )

    # Cache observability. OpenRouter passes through both the Anthropic
    # field names (cache_creation_input_tokens / cache_read_input_tokens)
    # and the OpenAI-shape (prompt_tokens_details.cached_tokens). We log
    # whichever surface populated so the operator can verify the cache is
    # actually doing work -- a zero-read counter across consecutive builds
    # signals a silent invalidator in the static block.
    usage = result.usage
    cache_read = (
        usage.get("cache_read_input_tokens")
        or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        or 0
    )
    cache_write = usage.get("cache_creation_input_tokens", 0)
    prompt_total = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    uncached = max(prompt_total - cache_read - cache_write, 0)
    if cache_read or cache_write:
        print(
            f"[*] Cache: read={cache_read} write={cache_write} "
            f"uncached={uncached} total_prompt={prompt_total} tokens"
        )
    else:
        print(f"[*] Cache: no hits (cold or invalidated). total_prompt={prompt_total} tokens")

    return assemble_generated_html(
        result,
        base_template=base_template,
        theme_catalog=themes_catalog,
        theme_name=prospect.get("_computed_theme") or DEFAULT_THEME,
        colors=_resolve_build_document_colors(prospect),
        title=prospect.get("display_name") or prospect["business_name"],
        body_theme="theme-light",
        trusted_head_comment=build_deployment_comment(prospect),
        forbidden_square_placeholders=extract_square_placeholder_tokens(
            system_prompt,
            static_block,
            response_boundary,
        ),
        forbidden_visible_phrases=unverified_service_claim_phrases(prospect),
        forbidden_comment_markers=BUILD_DEPLOYMENT_COMMENT_MARKERS,
        forbidden_class_names=interior_only_classes,
        allowed_class_names=homepage_classes,
        required_exposed_values=tuple(
            (name, value)
            for name, value in required_substitutions.items()
            if isinstance(value, str) and value
        ),
        expected_phone=prospect.get("phone"),
        expected_form_action=expected_build_form_action(prospect),
        required_class_counts=required_class_counts,
        required_child_class_sequences=BUILD_REQUIRED_CHILD_CLASS_SEQUENCES,
    )


def generate_email_draft(prospect, generation_config=None, client=None):
    """Generate the Day-1 pitch email draft for this prospect. Returns the
    markdown content that gets written to email_draft.md alongside the
    site. The VERCEL_URL_PLACEHOLDER token is intentionally left in --
    the salesperson swaps it for the real URL after deployment."""
    salesperson = prospect.get("salesperson_first_name") or DEFAULT_SALESPERSON_FIRST_NAME
    print(f"[*] Generating pitch email draft for {prospect['business_name']}...")
    with open(EMAIL_PROMPT_PATH, "r") as f:
        system_prompt = f.read()

    user_prompt = (
        f"PROSPECT JSON:\n{json.dumps(prospect, indent=2)}\n\n"
        f"SALESPERSON FIRST NAME: {salesperson}\n\n"
        f"Generate the email_draft.md file content per the rules above. "
        f"Output the markdown directly -- no code fences, no preamble. "
        f"Leave the [VERCEL_URL_PLACEHOLDER] token in the body verbatim."
    )

    config = generation_config or resolve_generation_config()
    result = generate_text(
        config,
        system_prompt=system_prompt,
        user_parts=(PromptPart(user_prompt),),
        temperature=EMAIL_TEMPERATURE,
        client=client,
    )

    draft = require_complete_text(result)
    # Strip any markdown fences the LLM might have leaked.
    draft = re.sub(r"^```markdown\n?", "", draft)
    draft = re.sub(r"^```\n?", "", draft)
    draft = re.sub(r"```$", "", draft)
    return draft.strip()


def main(
    prospect_json_path,
    *,
    generation_provider="local",
    generation_model=None,
    skip_deploy=False,
    skip_image_gen=False,
    skip_email_draft=False,
):
    prospect = load_prospect(prospect_json_path)
    generation_config = resolve_generation_config(
        generation_provider,
        generation_model,
    )
    preflight_generation_provider(generation_config)
    slug = prospect.get("slug") or slugify(prospect["business_name"])
    output_dir = os.path.join(BUILD_OUTPUT_ROOT, slug)
    os.makedirs(output_dir, exist_ok=True)

    print(f"[*] Building {prospect['business_name']} ({prospect['trade']}, {prospect['city']}, {prospect['state']})")
    print(f"[*] Output: {output_dir}/")

    # Deterministic theme selection. Setting this on the prospect dict
    # before HTML generation means the LLM reads `_computed_theme` as a
    # fact in the prospect JSON and applies the matching block from
    # references/09-themes.md. Two builds of the same prospect always
    # pick the same theme; different prospects within a trade get
    # different themes from the trade's allowed_themes list in 07.
    prospect["_computed_theme"] = select_theme(prospect)
    print(f"[*] Theme: {prospect['_computed_theme']}")

    # Deterministic palette selection. Independent from theme (different
    # hash slice). When prospect.brand_colors is set this returns None
    # and the LLM uses those colors verbatim per 06's :root rule.
    palette = select_palette(prospect)
    if palette:
        prospect["_computed_palette"] = palette
        print(f"[*] Palette: accent={palette['accent']} accent_dark={palette['accent_dark']}")

    # Hero shape coupled to theme. Same prospect -> same theme ->
    # same hero shape. Couples visual language: editorial themes get
    # split-photo heroes, minimal themes get gradient (no photo),
    # everything else gets the historical fullbleed.
    prospect["_computed_hero_shape"] = select_hero_shape(prospect)
    print(f"[*] Hero shape: {prospect['_computed_hero_shape']}")

    # Section ordering. Independent of theme/palette/hero-shape --
    # uses md5[16:24] slice so it varies even when two prospects
    # collide on the earlier axes. The LLM reads
    # _computed_section_order and renders sections in the order
    # documented in references/10-section-orders.md for that name.
    prospect["_computed_section_order"] = select_section_order(prospect)
    print(f"[*] Section order: {prospect['_computed_section_order']}")

    # Hero image acquisition (unless skipped or prospect already provided one).
    # Path 1 (Unsplash) is tried first when UNSPLASH_ACCESS_KEY is set --
    # it returns real photography for free. Path 2 (Flux via OpenRouter)
    # is the paid fallback when Unsplash has no key, no results, or
    # otherwise fails. Both paths mirror the image locally to
    # output_dir/images/ so the deployed bundle is self-contained.
    if skip_image_gen:
        print("[*] Skipping hero image generation due to --skip-image-gen flag.")
    elif prospect.get("_computed_hero_shape") == "gradient":
        # The harness selected a hero shape that renders no photo
        # (see select_hero_shape() and references/09-themes.md). Skip
        # the Unsplash/Flux fetch entirely -- the photo would only sit
        # unused in the output dir and the deployed bundle. Issue #16.
        print("[*] Skipping hero image generation: _computed_hero_shape='gradient' renders no photo.")
    else:
        existing_hero = any(
            p.get("context") in ("hero", "background")
            for p in prospect.get("photos", []) if isinstance(p, dict)
        )
        if not existing_hero:
            trade = prospect.get("trade", "")
            unsplash_hero = fetch_unsplash_hero(trade, output_dir)
            if unsplash_hero:
                print(f"[*] Unsplash credit: {unsplash_hero['credit_name']} ({unsplash_hero['credit_url']})")
                prospect.setdefault("photos", []).append({
                    "url": unsplash_hero["url"],
                    "alt": f"Hero image for {prospect['business_name']}",
                    "context": "hero",
                    "credit_name": unsplash_hero["credit_name"],
                    "credit_url": unsplash_hero["credit_url"],
                    "photo_id": unsplash_hero["photo_id"],
                    "source": "unsplash",
                })
            else:
                img_prompt = build_hero_prompt(prospect)
                print(f"[*] Hero prompt: {img_prompt[:120]}...")
                generated_url = generate_image_openrouter(img_prompt, output_dir=output_dir)
                if generated_url:
                    prospect.setdefault("photos", []).append({
                        "url": generated_url,
                        "alt": f"Modern hero image for {prospect['business_name']}",
                        "context": "hero",
                        "source": "flux",
                    })

    html = generate_build_html(prospect, generation_config)

    index_path = os.path.join(output_dir, "index.html")
    atomic_write_text(index_path, html)

    print(f"\n[+] Build complete: {index_path}")
    print(f"[+] Review locally before deploying.")

    # Email draft -- written alongside the HTML so the salesperson sees
    # the pitch copy right when they review the site. Skippable; the
    # VERCEL_URL_PLACEHOLDER token gets manually replaced post-deploy.
    # Stale-draft protection: any prior email_draft.md in the reused
    # output_dir is removed whenever the draft is skipped or generation
    # fails. Otherwise a salesperson reviewing the new site could pick
    # up an outdated pitch from a previous build.
    # email_draft.md lives in a SIBLING directory, NOT inside output_dir.
    # output_dir is the Vercel deploy root; anything in there gets published.
    # The pitch draft is internal-only.
    os.makedirs(EMAIL_DRAFT_ROOT, exist_ok=True)
    email_path = os.path.join(EMAIL_DRAFT_ROOT, f"{slug}.md")
    if skip_email_draft:
        print("[*] Skipping pitch email draft due to --skip-email-draft flag.")
        if os.path.isfile(email_path):
            os.remove(email_path)
            print(f"[*] Removed stale draft from prior build: {email_path}")
    else:
        try:
            email_md = generate_email_draft(prospect, generation_config)
            # Verify the [VERCEL_URL_PLACEHOLDER] token survived in the BODY
            # (not just in the "Before sending" checklist, which always
            # contains it because the prompt template instructs the model
            # to include it there). Split on the "Before sending" marker
            # and check the body portion only -- if the body is missing
            # the token, the salesperson has no handoff point for the
            # deployed URL and the draft is unusable.
            body_portion = re.split(r"##\s*Before sending", email_md, maxsplit=1)[0]
            if "[VERCEL_URL_PLACEHOLDER]" not in body_portion:
                raise ValueError(
                    "Generated draft is missing the [VERCEL_URL_PLACEHOLDER] token "
                    "in the email body (the checklist alone does not count). "
                    "Salesperson would have no place to insert the deployed URL."
                )
            atomic_write_text(email_path, email_md)
            print(f"[+] Pitch email draft: {email_path}")
            print(f"[*] Replace [VERCEL_URL_PLACEHOLDER] with the deployed URL before sending.")
        except Exception as e:
            print(f"[!] Email draft generation failed: {e}")
            if os.path.isfile(email_path):
                os.remove(email_path)
                print(f"[*] Removed stale draft from prior build: {email_path}")
            print(f"[*] Site build still complete; rerun with --skip-email-draft if this keeps failing.")

    if skip_deploy:
        print("\n[*] Skipping Vercel deployment due to --skip-deploy flag.")
        return

    deploy_choice = input("\n[?] Deploy to Vercel now? (y/N): ")
    if deploy_choice.lower() != "y":
        print("[*] Deployment cancelled.")
        return

    vercel_url = deploy_to_vercel(slug, {"index.html": html}, output_root=BUILD_OUTPUT_ROOT)
    if not vercel_url:
        return

    print(f"\n[+] Live URL: {vercel_url}")
    email_draft_hint_path = os.path.join(EMAIL_DRAFT_ROOT, f"{slug}.md")
    if os.path.isfile(email_draft_hint_path):
        print(f"[*] Pitch email draft ready: {email_draft_hint_path}")
        print(f"[*] Replace [VERCEL_URL_PLACEHOLDER] with {vercel_url}")
        print(f"[*] Send from your own email client. Do NOT use any automated sender.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate one local-business website from prospect JSON."
    )
    parser.add_argument("prospect_json")
    parser.add_argument(
        "--generation-provider",
        choices=("local", "openrouter"),
        default="local",
    )
    parser.add_argument("--generation-model")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--skip-image-gen", action="store_true")
    parser.add_argument("--skip-email-draft", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    main(
        args.prospect_json,
        generation_provider=args.generation_provider,
        generation_model=args.generation_model,
        skip_deploy=args.skip_deploy,
        skip_image_gen=args.skip_image_gen,
        skip_email_draft=args.skip_email_draft,
    )
