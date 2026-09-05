import os
import json
import re
import urllib.parse
import argparse
import requests
from bs4 import BeautifulSoup

from lib.clients import (
    EXTRACTION_MODEL,
    extract_json_object as _extract_json_object,
    get_openrouter_client,
)
from lib.images import generate_image_openrouter
from lib.deploy import deploy_to_vercel
from lib.email import send_pitch_email
from lib.site_extraction import (
    SiteExtractionError,
    same_site_origin,
    validate_enrichment_result,
    validate_site_analysis,
)
from lib.generation import (
    ActionUrlAdmissionContract,
    DEFAULT_DOCUMENT_ACCENT,
    DEFAULT_DOCUMENT_SECONDARY,
    REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES,
    REQUIRED_FOOTER_CLASS_COUNTS,
    DocumentColors,
    ImageAdmissionContract,
    PromptPart,
    SourceContactAdmissionContract,
    action_url_contract_instruction,
    assemble_generated_html,
    atomic_write_text,
    body_generation_config,
    extract_homepage_class_names,
    extract_interior_only_class_names,
    extract_square_placeholder_tokens,
    extract_template_class_names,
    generate_text,
    generate_with_local_admission_retry,
    image_contract_instruction,
    make_html_comment,
    preflight_generation_provider,
    resolve_generation_config,
)

# Enrichment pass: fetches priority-1/2 interior pages identified in the
# homepage analysis and merges their extracted JSON back into site_json so
# the homepage redesign has real content (practice areas, team, contact
# form) to inject -- not just a hero with nothing under it.
ENRICHMENT_TEMPERATURE = 0.1
ANALYSIS_HTML_TRUNCATE = 120000
ENRICHMENT_HTML_TRUNCATE = 120000
ENRICHMENT_PRIORITY_THRESHOLD = 2
ENRICHABLE_PAGE_TYPES = {"services", "single-service", "team", "about", "faq", "contact"}
ENRICHMENT_PROMPT_PATH = "references/05-enrichment-prompt.md"
BASE_TEMPLATE_PATH = "references/03-base-template.html"
THEMES_CATALOG_PATH = "references/09-themes.md"
REDESIGN_DEPLOYMENT_COMMENT_MARKERS = (
    "WEBSITE REDESIGN MOCKUP",
    "Client:",
    "Source URL:",
    "Platform:",
    "Theme applied:",
    "THEIR CURRENT ANNUAL COST:",
    "YOUR MODEL:",
    "5-YEAR SAVINGS:",
    "Hosting:",
    "SALES PITCH:",
    "DEPLOY THIS MOCKUP:",
    "INTERIOR PAGES REMAINING:",
)


def _append_source_value(values, value):
    if isinstance(value, str) and value.strip() and value.strip() not in values:
        values.append(value.strip())


def _redesign_contact_contract(site_json):
    phones = []
    emails = []
    addresses = []
    site = site_json.get("site") if isinstance(site_json.get("site"), dict) else {}
    contact = site.get("contact") if isinstance(site.get("contact"), dict) else {}
    contact_form = (
        site_json.get("contact_form")
        if isinstance(site_json.get("contact_form"), dict)
        else {}
    )
    contact_info = (
        contact_form.get("contact_info")
        if isinstance(contact_form.get("contact_info"), dict)
        else {}
    )
    contact_sources = [contact, contact_info]
    conversion_profile = (
        site_json.get("conversion_profile")
        if isinstance(site_json.get("conversion_profile"), dict)
        else {}
    )
    contact_sources.append(conversion_profile)
    single_page_sections = site_json.get("single_page_sections")
    for section in (
        single_page_sections if isinstance(single_page_sections, list) else ()
    ):
        if not isinstance(section, dict):
            continue
        content = section.get("content")
        if not isinstance(content, dict):
            continue
        section_contact = content.get("contact_info")
        if isinstance(section_contact, dict):
            contact_sources.append(section_contact)
    for source in contact_sources:
        _append_source_value(phones, source.get("phone"))
        _append_source_value(emails, source.get("email"))
        _append_source_value(addresses, source.get("address"))
        source_addresses = source.get("addresses")
        if isinstance(source_addresses, list):
            for address in source_addresses:
                _append_source_value(addresses, address)
    return SourceContactAdmissionContract(
        phones=tuple(phones),
        emails=tuple(emails),
        addresses=tuple(addresses),
    )


def _redesign_action_url_contract(
    site_json,
    contact_contract,
    *,
    source_content=None,
    extra_urls=(),
):
    allowed_urls = []
    allowed_labels = []

    site = site_json.get("site")
    if isinstance(site, dict):
        _append_source_value(allowed_labels, site.get("name"))

    def append_field(value, field="url"):
        if isinstance(value, dict):
            _append_source_value(allowed_urls, value.get(field))

    def append_label_field(value, field="label"):
        if isinstance(value, dict):
            _append_source_value(allowed_labels, value.get(field))

    def append_item_urls(items):
        if isinstance(items, list):
            for item in items:
                append_field(item)
                if isinstance(item, dict) and item.get("url") is not None:
                    _append_source_value(allowed_labels, item.get("title"))

    for item in site_json.get("nav") or ():
        append_field(item)
        append_label_field(item)
    cta = site_json.get("cta") or {}
    append_field(cta)
    append_label_field(cta)
    for section in site_json.get("sections") or ():
        if isinstance(section, dict):
            append_field(section, "source_url")
            append_item_urls(section.get("items"))
    append_field(site_json.get("contact_form") or {}, "source_url")
    for item in site_json.get("social") or ():
        append_field(item)
        if isinstance(item, dict):
            _append_source_value(allowed_labels, item.get("platform"))
    for item in site_json.get("footer_links") or ():
        append_field(item)
        append_label_field(item)
    for item in site_json.get("pages_to_fetch") or ():
        append_field(item)
        append_label_field(item)
    for section in site_json.get("single_page_sections") or ():
        if not isinstance(section, dict):
            continue
        append_field(section, "anchor")
        _append_source_value(allowed_labels, section.get("nav_label"))
        content = section.get("content")
        if isinstance(content, dict):
            append_item_urls(content.get("items"))
    conversion_profile = site_json.get("conversion_profile")
    if isinstance(conversion_profile, dict):
        for label in conversion_profile.get("existing_ctas") or ():
            _append_source_value(allowed_labels, label)
    for url in extra_urls:
        _append_source_value(allowed_urls, url)
    if isinstance(source_content, str) and "<" in source_content:
        source_root = BeautifulSoup(source_content, "html.parser")
        for element in source_root.find_all(["a", "area", "button", "input"]):
            if element.name in {"a", "area"}:
                _append_source_value(allowed_urls, element.get("href"))
            if (
                element.name == "input"
                and str(element.get("type") or "").casefold() != "submit"
            ):
                continue
            label = element.get_text(" ", strip=True)
            if element.name == "input":
                label = str(element.get("value") or "")
            if not label:
                label = str(element.get("aria-label") or element.get("title") or "")
            _append_source_value(allowed_labels, label)
    return ActionUrlAdmissionContract(
        allowed_urls=tuple(allowed_urls),
        phones=contact_contract.phones,
        emails=contact_contract.emails,
        allowed_labels=tuple(allowed_labels),
    )


def _redesign_image_contract(site_json):
    allowed_urls = []
    brand = site_json.get("brand") if isinstance(site_json.get("brand"), dict) else {}
    logo_url = brand.get("logo_url")
    _append_source_value(allowed_urls, logo_url)
    images = site_json.get("images")
    for image in images if isinstance(images, list) else ():
        if isinstance(image, dict):
            _append_source_value(allowed_urls, image.get("url"))
            if (
                not isinstance(logo_url, str) or not logo_url.strip()
            ) and image.get("context") == "logo":
                logo_url = image.get("url")

    def collect_named_image_values(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"image_url", "logo_url"}:
                    _append_source_value(allowed_urls, nested)
                collect_named_image_values(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_named_image_values(nested)

    collect_named_image_values(site_json)
    normalized_logo = logo_url.strip() if isinstance(logo_url, str) and logo_url.strip() else None
    return ImageAdmissionContract(tuple(allowed_urls), nav_logo_url=normalized_logo)


def _six_digit_hex(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value)
        else None
    )


def _darken_hex_color(value):
    channels = [int(value[index : index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{round(channel * 0.75):02X}" for channel in channels)


def _resolve_site_document_colors(site_json):
    brand = site_json.get("brand") if isinstance(site_json.get("brand"), dict) else {}
    colors = brand.get("colors") if isinstance(brand.get("colors"), dict) else {}
    raw_colors = colors.get("raw") if isinstance(colors.get("raw"), list) else []
    primary = next(
        (
            color
            for color in (
                _six_digit_hex(colors.get("primary")),
                _six_digit_hex(colors.get("button_bg")),
                _six_digit_hex(colors.get("link")),
                *(_six_digit_hex(item) for item in raw_colors),
            )
            if color
        ),
        DEFAULT_DOCUMENT_ACCENT,
    )
    secondary = next(
        (
            color
            for color in (
                _six_digit_hex(colors.get("secondary")),
                _six_digit_hex(colors.get("nav_bg")),
            )
            if color
        ),
        DEFAULT_DOCUMENT_SECONDARY,
    )
    return DocumentColors(
        accent=primary,
        accent_dark=_darken_hex_color(primary),
        secondary=secondary,
    )


def _site_body_theme(site_json):
    brand = site_json.get("brand") if isinstance(site_json.get("brand"), dict) else {}
    return "theme-dark" if brand.get("color_mode") == "dark" else "theme-light"


_PLATFORM_ANNUAL_COSTS = {
    "wix (light)": 219,
    "wix (core)": 363,
    "wix (business)": 483,
    "squarespace": 207,
    "godaddy-builder": 240,
    "traditional-hosting": 350,
    "wordpress-hosted": 180,
}


def redesign_deployment_comment(site_json, *, theme, source_url=None, site_slug=None):
    """Render redesign metadata from extracted facts, never model output."""
    site = site_json.get("site") if isinstance(site_json.get("site"), dict) else {}
    site_name = site.get("name") or "Website"
    platform = site_json.get("platform")
    if isinstance(platform, dict):
        platform_name = platform.get("detected")
    elif isinstance(platform, str):
        platform_name = platform
    else:
        platform_name = None
    platform_name = platform_name.strip() if isinstance(platform_name, str) else "unknown"
    if not platform_name:
        platform_name = "unknown"
    annual_cost = _PLATFORM_ANNUAL_COSTS.get(platform_name.casefold())
    annual_cost_text = f"${annual_cost}" if annual_cost is not None else "unknown"
    savings_text = f"${annual_cost * 5 - 75}" if annual_cost is not None else "unknown"

    resolved_source = source_url or site_json.get("source_url") or "unknown"
    if not site_slug:
        parsed_host = urllib.parse.urlparse(str(resolved_source)).netloc.replace("www.", "")
        site_slug = parsed_host.replace(".", "-") or re.sub(
            r"[^a-z0-9]+", "-", str(site_name).lower()
        ).strip("-") or "website"

    lines = [
        "============================================================",
        "WEBSITE REDESIGN MOCKUP",
        "============================================================",
        f"Client:          {site_name}",
        f"Source URL:      {resolved_source}",
        f"Platform:        {platform_name}",
        f"Theme applied:   {theme}",
        "",
        f"THEIR CURRENT ANNUAL COST: {annual_cost_text}/year" if annual_cost is not None else "THEIR CURRENT ANNUAL COST: unknown",
        "YOUR MODEL:      ~$15/year (domain only) + one-time build fee",
        f"5-YEAR SAVINGS:  {savings_text}" if annual_cost is not None else "5-YEAR SAVINGS:  unknown",
        "Hosting:         Vercel (free, static, auto-SSL via Let's Encrypt)",
        "",
        "SALES PITCH:",
        "Write manually from verified prospect facts; not model-generated.",
        "",
        "DEPLOY THIS MOCKUP:",
        "1. Go to vercel.com/new",
        "2. Drag and drop this HTML file",
        f"3. Assign subdomain: {site_slug}.preview.yourdomain.com",
        "4. Vercel provisions HTTPS automatically -- no SSL config needed",
        "5. Share live URL with prospect before the sales call",
        "",
        "INTERIOR PAGES REMAINING:",
    ]
    pages = site_json.get("pages_to_fetch")
    remaining = []
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            priority = page.get("priority")
            if not isinstance(priority, (int, float)) or priority > 2:
                continue
            label = page.get("label") or page.get("page_type") or "Unnamed page"
            page_type = page.get("page_type") or "other"
            if page.get("fetchable") is True and page.get("url"):
                action = f"fetch {page['url']}"
            else:
                action = "use homepage-section"
            remaining.append(f"- {label} ({page_type}) -- {action}")
    lines.extend(remaining or ["- None"])
    lines.append("============================================================")
    return make_html_comment("\n".join(lines))


def _fetch_with_playwright(url):
    """Headless browser fetch for JS-rendered sites (Squarespace, Wix, Webflow)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] playwright not installed. Run: pip install playwright && playwright install chromium")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            content = page.content()
            effective_url = page.url
            browser.close()
            return content, effective_url
    except Exception as e:
        print(f"[!] Playwright fetch failed: {e}")
        return None

def fetch_and_clean_html(url, *, include_source_url=False, required_origin=None):
    print(f"[*] Fetching URL: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.exceptions.SSLError as ssl_err:
        # Many small-business sites have a cert valid only for the www host
        # (or only for the apex). Auto-toggle the www prefix and retry once.
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        alt_host = host[4:] if host.startswith("www.") else "www." + host
        alt_url = parsed._replace(netloc=alt_host).geturl() if alt_host != host else url
        if alt_url != url:
            print(f"[!] SSL hostname mismatch on {url}: {ssl_err}")
            print(f"[*] Retrying with toggled host: {alt_url}")
            response = requests.get(alt_url, headers=headers, timeout=20)
            response.raise_for_status()
            url = alt_url
        else:
            raise
    effective_url = getattr(response, "url", None) or url
    raw_html = response.text

    # Thin content detection: JS-rendered sites return < 8000 chars of visible text.
    # Upgrade to Playwright automatically when detected.
    visible_text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    if len(visible_text) < 8000:
        print(f"[*] Thin content ({len(visible_text)} chars). Upgrading to headless browser fetch...")
        playwright_result = _fetch_with_playwright(effective_url)
        if isinstance(playwright_result, tuple):
            playwright_html, playwright_url = playwright_result
        else:
            playwright_html, playwright_url = playwright_result, effective_url
        if playwright_html and len(playwright_html) > len(raw_html):
            print("[*] Playwright fetch succeeded -- using richer content.")
            raw_html = playwright_html
            effective_url = playwright_url
        else:
            print("[*] Falling back to static fetch.")

    if required_origin is not None and not same_site_origin(
        required_origin, effective_url
    ):
        raise ValueError("Fetched page left the required source origin.")

    soup = BeautifulSoup(raw_html, 'html.parser')

    # Remove noise elements to reduce token count.
    # Keep style tags -- the analysis prompt extracts brand colors from them.
    for element in soup(["script", "svg", "noscript", "iframe"]):
        element.decompose()

    # Aggressively extract image URLs (including lazy-loaded data-src) and place
    # the bounded code-owned inventory at the top. The same real img attributes
    # are therefore visible to both the model and SourceEvidence after truncation.
    image_urls = set()
    for img in soup.find_all("img"):
        for attr in ["src", "data-src", "data-lazy-src", "data-original"]:
            val = img.get(attr, "")
            if val and val.startswith("http") and any(ext in val.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                image_urls.add(val)
    for style in soup.find_all("style"):
        found = re.findall(r'url\(["\']?(https://[^"\')\s]+)["\']?\)', style.string or "")
        image_urls.update(found)

    inventory = BeautifulSoup("", "html.parser")
    inventory_root = inventory.new_tag("template")
    inventory_root["data-code-owned-image-inventory"] = "true"
    for img_url in sorted(image_urls)[:20]:
        inventory_root.append(inventory.new_tag("img", src=img_url))
    inventory.append(inventory_root)

    cleaned_html = str(inventory) + "\n" + str(soup)
    if include_source_url:
        return cleaned_html, effective_url
    return cleaned_html

def mirror_images_locally(site_json, output_dir):
    """Download CDN images to the output folder so they travel with the Vercel deploy.
    Updates image URLs in site_json to relative paths in-place."""
    img_dir = os.path.join(output_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    mirrored = 0
    for img in site_json.get("images", []):
        src = img.get("url", "")
        if not src or not src.startswith("http"):
            continue
        try:
            resp = requests.get(src, headers=headers, timeout=10)
            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and "image" in content_type:
                ext = src.split(".")[-1].split("?")[0][:4].lower() or "jpg"
                fname = f"{img.get('context', 'img')}_{mirrored}.{ext}"
                with open(os.path.join(img_dir, fname), "wb") as f:
                    f.write(resp.content)
                img["url"] = f"images/{fname}"
                mirrored += 1
        except Exception:
            pass  # Leave the original CDN URL if download fails
    if mirrored:
        print(f"[*] Mirrored {mirrored} image(s) locally to {img_dir}/")
    return site_json

def analyze_site(html_content, source_url=None):
    print(f"[*] Analyzing site content with {EXTRACTION_MODEL}...")
    with open("references/01-site-analysis-prompt.md", "r") as f:
        system_prompt = f.read()
    prompt_html = html_content[:ANALYSIS_HTML_TRUNCATE]

    response = get_openrouter_client().chat.completions.create(
        model=EXTRACTION_MODEL,
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"SOURCE_URL: {source_url or 'not supplied'}\n\n"
                    f"HTML:\n{prompt_html}"
                ),
            },
        ],
        temperature=0.1
    )

    document = _extract_json_object(response.choices[0].message.content)
    return validate_site_analysis(document, prompt_html, source_url)

def enrich_site_json(site_json):
    """Fetch high-priority interior pages and merge extracted JSON chunks
    back into site_json. Mutates and returns site_json. Best-effort: any
    single fetch / LLM / schema failure is logged and skipped."""
    pages = site_json.get("pages_to_fetch") or []

    candidates = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        if p.get("fetchable") is not True:
            continue
        priority = p.get("priority")
        if not isinstance(priority, int) or priority > ENRICHMENT_PRIORITY_THRESHOLD:
            continue
        page_type = p.get("page_type")
        if page_type not in ENRICHABLE_PAGE_TYPES:
            continue
        url = p.get("url")
        if not isinstance(url, str) or not url:
            continue
        candidates.append((priority, page_type, url))

    # Dedupe by page_type: lowest priority number wins. Caps total LLM calls
    # at len(ENRICHABLE_PAGE_TYPES).
    candidates.sort(key=lambda t: t[0])
    seen_types = set()
    deduped = []
    for priority, page_type, url in candidates:
        if page_type in seen_types:
            continue
        seen_types.add(page_type)
        deduped.append((page_type, url))

    if not deduped:
        print("[*] No enrichable pages found; skipping enrichment.")
        return site_json

    print(f"[*] Enrichment pass: {len(deduped)} interior page(s) queued.")

    try:
        with open(ENRICHMENT_PROMPT_PATH, "r") as f:
            system_prompt = f.read()
    except Exception as e:
        print(f"[!] Could not load enrichment prompt at {ENRICHMENT_PROMPT_PATH}: {e}")
        return site_json

    for page_type, url in deduped:
        print(f"[*] Enriching {page_type} from {url}...")
        try:
            page_html, fetched_url = fetch_and_clean_html(
                url,
                include_source_url=True,
                required_origin=url,
            )
        except Exception as e:
            print(f"[!] Enrichment fetch failed for {url}: {e}")
            continue
        if not same_site_origin(url, fetched_url):
            print(
                f"[!] Enrichment redirect left the source site for {url}; skipping."
            )
            continue

        prompt_html = page_html[:ENRICHMENT_HTML_TRUNCATE]
        user_prompt = (
            f"PAGE_TYPE: {page_type}\n"
            f"SOURCE_URL: {fetched_url}\n\n"
            f"HTML:\n{prompt_html}"
        )

        try:
            response = get_openrouter_client().chat.completions.create(
                model=EXTRACTION_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=ENRICHMENT_TEMPERATURE
            )
            result = _extract_json_object(response.choices[0].message.content)
        except Exception as e:
            print(f"[!] Enrichment LLM call failed for {page_type} at {url}: {e}")
            continue

        try:
            result = validate_enrichment_result(
                result,
                page_type=page_type,
                source_html=prompt_html,
                source_url=fetched_url,
            )
        except SiteExtractionError as e:
            print(
                f"[!] Enrichment source validation failed for {page_type} at {url}: {e}"
            )
            continue

        if not isinstance(result, dict) or not result:
            print(f"[*] Enrichment for {page_type} returned empty; skipping.")
            continue

        if page_type == "contact":
            form_fields = result.get("form_fields")
            contact_info = result.get("contact_info") or {}
            has_form = isinstance(form_fields, list) and len(form_fields) > 0
            has_info = any(contact_info.get(k) for k in ("phone", "email", "address", "addresses", "hours"))
            if not (has_form or has_info):
                print(f"[*] Enrichment for contact at {url} had no form or contact info; skipping.")
                continue
            if "contact_form" not in site_json:
                site_json["contact_form"] = result
                summary = f"{len(form_fields) if has_form else 0} form field(s)"
                print(f"[*] Enriched contact from {url}: {summary}")
            else:
                print(f"[*] contact_form already set; leaving as-is for idempotency.")
        else:
            section_type = result.get("type")
            items = result.get("items")
            if not isinstance(section_type, str) or not isinstance(items, list) or len(items) == 0:
                print(f"[*] Enrichment for {page_type} at {url} had no usable items; skipping.")
                continue
            site_json.setdefault("sections", []).append(result)
            print(f"[*] Enriched {page_type} from {url}: {len(items)} item(s)")

    return site_json

def generate_redesign(
    site_json,
    theme="minimal",
    color_mode="brand",
    generation_config=None,
    generation_client=None,
    source_url=None,
    site_slug=None,
):
    config = generation_config or resolve_generation_config()
    print(
        f"[*] Generating modernized HTML with theme '{theme}' using "
        f"{config.provider}:{config.model}..."
    )
    with open("references/02-redesign-gen-prompt.md", "r") as f:
        system_prompt = f.read()

    with open(BASE_TEMPLATE_PATH, "r") as f:
        base_template = f.read()
    with open(THEMES_CATALOG_PATH, "r") as f:
        theme_catalog = f.read()
    homepage_classes = extract_homepage_class_names(base_template)
    class_catalog = "\n".join(homepage_classes)
    interior_only_classes = extract_interior_only_class_names(base_template)
    image_contract = _redesign_image_contract(site_json)
    site_name = site_json.get("site", {}).get("name") or "Website"
    contact_contract = _redesign_contact_contract(site_json)
    action_url_contract = _redesign_action_url_contract(
        site_json,
        contact_contract,
    )

    user_prompt = f"""THEME: {theme}
COLOR_MODE: {color_mode}
ACCENT_OVERRIDE: none
NOTES: none

MANDATORY BUSINESS IDENTITY: Visibly render this exact extracted business name:
{json.dumps(site_name, ensure_ascii=False)}

{action_url_contract_instruction(action_url_contract)}

SITE JSON:
{json.dumps(site_json, indent=2)}

ALLOWED BODY CLASSES:
{class_catalog}

RESPONSE BOUNDARY: Begin immediately with <body and end immediately with
</body>. Emit no leading comment, deployment metadata, markdown fence, trailing
text, HTML head metadata, or unresolved template token.

{image_contract_instruction(image_contract)}
"""

    def admit(candidate):
        return assemble_generated_html(
            candidate,
            base_template=base_template,
            theme_catalog=theme_catalog,
            theme_name=theme,
            colors=_resolve_site_document_colors(site_json),
            title=site_name,
            body_theme=_site_body_theme(site_json),
            trusted_head_comment=redesign_deployment_comment(
                site_json,
                theme=theme,
                source_url=source_url,
                site_slug=site_slug,
            ),
            forbidden_square_placeholders=extract_square_placeholder_tokens(
                system_prompt,
                class_catalog,
            ),
            forbidden_comment_markers=REDESIGN_DEPLOYMENT_COMMENT_MARKERS,
            forbidden_class_names=interior_only_classes,
            allowed_class_names=homepage_classes,
            required_exposed_values=(("site_name", site_name),),
            source_contacts=contact_contract,
            expected_images=image_contract,
            expected_action_urls=action_url_contract,
            required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
            required_child_class_sequences=REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES,
        )

    _result, html = generate_with_local_admission_retry(
        body_generation_config(config),
        system_prompt=system_prompt,
        user_parts=(PromptPart(user_prompt),),
        temperature=0.4,
        admit=admit,
        client=generation_client,
    )
    return html

def generate_interior_page(
    site_json,
    page_type,
    page_url=None,
    source_content=None,
    theme="warm",
    color_mode="brand",
    generation_config=None,
    generation_client=None,
):
    print(f"[*] Generating interior page '{page_type}'...")
    with open("references/04-interior-page-prompt.md", "r") as f:
        system_prompt = f.read()
        
    with open(BASE_TEMPLATE_PATH, "r") as f:
        base_template = f.read()
    with open(THEMES_CATALOG_PATH, "r") as f:
        theme_catalog = f.read()
    template_classes = extract_template_class_names(base_template)
    class_catalog = "\n".join(template_classes)
    image_contract = _redesign_image_contract(site_json)
        
    if source_content is not None:
        if not isinstance(source_content, str):
            raise ValueError("Interior source content must be text.")
        content_source = "fetched-page" if page_url else "provided-source"
    elif page_url:
        print(f"[*] Fetching interior page content from {page_url}...")
        source_content = fetch_and_clean_html(
            page_url,
            required_origin=page_url,
        )
        content_source = "fetched-page"
    else:
        # Try to find a matching single_page_sections entry
        sections = site_json.get("single_page_sections", [])
        matching = [s for s in sections if s.get("page_type") == page_type]
        if matching:
            source_content = json.dumps(matching[0], indent=2)
        else:
            source_content = "{}"
        content_source = "homepage-section"

    site_name = site_json.get("site", {}).get("name") or "Website"
    contact_contract = _redesign_contact_contract(site_json)
    action_url_contract = _redesign_action_url_contract(
        site_json,
        contact_contract,
        source_content=source_content,
        extra_urls=(page_url,),
    )
        
    user_prompt = f"""PAGE TYPE: {page_type}
PAGE URL: {page_url or 'n/a -- single-page site'}
CONTENT_SOURCE: {content_source}
NOTES: none

MANDATORY BUSINESS IDENTITY: Visibly render this exact extracted business name:
{json.dumps(site_name, ensure_ascii=False)}

{action_url_contract_instruction(action_url_contract)}

HOMEPAGE DESIGN JSON:
{json.dumps(site_json, indent=2)}

ALLOWED BODY CLASSES:
{class_catalog}

---
SOURCE CONTENT:
{source_content}
---

{image_contract_instruction(image_contract)}
"""

    config = generation_config or resolve_generation_config()
    page_label = page_type.replace("-", " ").title()

    def admit(candidate):
        return assemble_generated_html(
            candidate,
            base_template=base_template,
            theme_catalog=theme_catalog,
            theme_name=theme,
            colors=_resolve_site_document_colors(site_json),
            title=f"{page_label} | {site_name}",
            body_theme=_site_body_theme(site_json),
            forbidden_square_placeholders=extract_square_placeholder_tokens(
                system_prompt,
                class_catalog,
            ),
            forbidden_comment_markers=REDESIGN_DEPLOYMENT_COMMENT_MARKERS,
            allowed_class_names=template_classes,
            required_exposed_values=(("site_name", site_name),),
            source_contacts=contact_contract,
            expected_images=image_contract,
            expected_action_urls=action_url_contract,
            required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
            required_child_class_sequences=REQUIRED_FOOTER_CHILD_CLASS_SEQUENCES,
        )

    _result, html = generate_with_local_admission_retry(
        body_generation_config(config),
        system_prompt=system_prompt,
        user_parts=(PromptPart(user_prompt[:120000]),),
        temperature=0.1,
        admit=admit,
        client=generation_client,
    )
    return html


def _generate_contact_page(site_json, contact_page, theme, generation_config):
    contact_url = contact_page.get("url")
    if contact_page.get("fetchable") is True and contact_url:
        try:
            contact_source = fetch_and_clean_html(
                contact_url,
                required_origin=contact_url,
            )
        except Exception as error:
            print(f"[!] Contact page fetch failed for {contact_url}: {error}")
            print("[*] Falling back to homepage-section content for contact page.")
        else:
            return generate_interior_page(
                site_json,
                "contact",
                page_url=contact_url,
                source_content=contact_source,
                theme=theme,
                generation_config=generation_config,
            )
    return generate_interior_page(
        site_json,
        "contact",
        theme=theme,
        generation_config=generation_config,
    )


def main(
    url,
    *,
    generation_provider="local",
    generation_model=None,
    skip_deploy=False,
    skip_email=False,
    skip_image_gen=False,
):
    generation_config = resolve_generation_config(
        generation_provider,
        generation_model,
    )
    preflight_generation_provider(generation_config)
    # Determine a slug to use for the output folder and Vercel project
    domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
    if not domain:
        domain = urllib.parse.urlparse("http://" + url).netloc.replace("www.", "")
    site_slug = domain.replace(".", "-")
    
    # 1. Fetch & Clean
    html_content, fetched_url = fetch_and_clean_html(url, include_source_url=True)
    
    # 2. Analyze (Extract Info & JSON)
    site_json = analyze_site(html_content, source_url=fetched_url)

    # 2.1 Enrich with interior page content so the homepage redesign has
    # real services / team / contact data, not just whatever was on the
    # homepage hero.
    site_json = enrich_site_json(site_json)

    site_name = site_json.get("site", {}).get("name", domain)
    contact_email = site_json.get("site", {}).get("contact", {}).get("email")
    print(f"\n--- Extracted Data ---")
    print(f"Site Name: {site_name}")
    print(f"Found Email: {contact_email}")
    print(f"----------------------\n")
    
    output_dir = os.path.join("outputs", site_slug)
    os.makedirs(output_dir, exist_ok=True)

    # 2.2 Mirror CDN images to disk so they don't expire or 404 after deployment.
    site_json = mirror_images_locally(site_json, output_dir)

    # 2.5 Image Generation Check
    # For JS-heavy sites (Squarespace, Wix, Webflow), the scraper often can't get
    # hero images. Force image generation if no good hero image is in the JSON.
    img_prompt = site_json.get("image_generation_prompt")
    hero_images = [img for img in site_json.get("images", []) if img.get("context") in ["hero", "background"]]
    if skip_image_gen:
        print("[*] Skipping hero image generation due to --skip-image-gen flag.")
    elif img_prompt or not hero_images:
        if not img_prompt:
            site_type = site_json.get("site", {}).get("type", "business")
            site_name = site_json.get("site", {}).get("name", "")
            location = site_json.get("site", {}).get("location", "")
            img_prompt = f"A professional, modern, photorealistic hero background image for a {site_type} called '{site_name}' in {location}. Wide cinematic crop, high production value, no text."
        print(f"[*] Generating hero image. Prompt: {img_prompt[:120]}...")
        generated_url = generate_image_openrouter(img_prompt, output_dir=output_dir)
        if generated_url:
            site_json.setdefault("images", []).append({
                "url": generated_url,
                "alt": f"Modern hero image for {site_name}",
                "context": "hero"
            })
            
    # 3. Generate HTML
    # Auto-select theme based on site type
    site_type = site_json.get("site", {}).get("type", "services")
    theme_map = {
        "radio": "broadcast",
        "news": "broadcast",
        "restaurant": "warm",
        "retail": "warm",
        "church": "civic",
        "civic": "civic",
        "nonprofit": "editorial",
        "portfolio": "minimal",
        "services": "minimal",
        "local-business": "warm",
        "ecommerce": "brand-forward",
    }
    theme = theme_map.get(site_type, "minimal")
    print(f"[*] Auto-selected theme '{theme}' for site type '{site_type}'")
    redesign_html = generate_redesign(
        site_json,
        theme=theme,
        generation_config=generation_config,
        source_url=url,
        site_slug=site_slug,
    )
    pages_to_deploy = {"index.html": redesign_html}
    
    # 3.5 Generate Contact Page if available. Fail-soft: if the fetch 404s
    # (extracted URL is wrong, page moved, etc.), fall back to generating the
    # contact page from the homepage JSON alone instead of crashing.
    pages_to_fetch = site_json.get("pages_to_fetch", [])
    contact_pages = [p for p in pages_to_fetch if p.get("page_type") == "contact"]
    if contact_pages:
        contact_html = _generate_contact_page(
            site_json,
            contact_pages[0],
            theme,
            generation_config,
        )
        pages_to_deploy["contact.html"] = contact_html

    # Save files locally first so they can be reviewed
    for filename, html_content in pages_to_deploy.items():
        atomic_write_text(os.path.join(output_dir, filename), html_content)
            
    print(f"\n[+] Redesign generation complete!")
    print(f"[+] Files saved locally to: {output_dir}/")
    print(f"[+] Review them before deploying.")
    
    # Check flags for skipping
    if skip_deploy:
        print("\n[*] Skipping Vercel deployment due to --skip-deploy flag.")
        return
        
    deploy_choice = input("\n[?] Do you want to deploy these files to Vercel now? (y/N): ")
    if deploy_choice.lower() != 'y':
        print("[*] Deployment cancelled.")
        return
        
    # 4. Deploy
    vercel_url = deploy_to_vercel(site_slug, pages_to_deploy)
    
    # 5. Send Email
    if vercel_url:
        if contact_email:
            if skip_email:
                print(f"\n[*] Skipping pitch email to {contact_email} due to --skip-email flag.")
                print(f"[*] You can manually email the business at this link: {vercel_url}")
            else:
                email_choice = input(f"\n[?] Do you want to send the pitch email to {contact_email} right now? (y/N): ")
                if email_choice.lower() == 'y':
                    send_pitch_email(contact_email, site_name, vercel_url)
                else:
                    print("[*] Email sending cancelled.")
                    print(f"[*] You can manually email the business at this link: {vercel_url}")
        else:
            print("\n[!] No email address found on the website. Skipping email step.")
            print(f"[*] You can manually email the business at this link: {vercel_url}")

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyze an existing site and generate a redesigned preview."
    )
    parser.add_argument("url")
    parser.add_argument(
        "--generation-provider",
        choices=("local", "openrouter"),
        default="local",
    )
    parser.add_argument("--generation-model")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--skip-email", action="store_true")
    parser.add_argument("--skip-image-gen", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    main(
        args.url,
        generation_provider=args.generation_provider,
        generation_model=args.generation_model,
        skip_deploy=args.skip_deploy,
        skip_email=args.skip_email,
        skip_image_gen=args.skip_image_gen,
    )
