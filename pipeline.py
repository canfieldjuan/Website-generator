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
from lib.generation import (
    PromptPart,
    atomic_write_text,
    generate_text,
    preflight_generation_provider,
    resolve_generation_config,
    validate_generated_html,
)

# Enrichment pass: fetches priority-1/2 interior pages identified in the
# homepage analysis and merges their extracted JSON back into site_json so
# the homepage redesign has real content (practice areas, team, contact
# form) to inject -- not just a hero with nothing under it.
ENRICHMENT_TEMPERATURE = 0.1
ENRICHMENT_HTML_TRUNCATE = 120000
ENRICHMENT_PRIORITY_THRESHOLD = 2
ENRICHABLE_PAGE_TYPES = {"services", "single-service", "team", "about", "faq", "contact"}
ENRICHMENT_PROMPT_PATH = "references/05-enrichment-prompt.md"

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
            browser.close()
            return content
    except Exception as e:
        print(f"[!] Playwright fetch failed: {e}")
        return None

def fetch_and_clean_html(url):
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
    raw_html = response.text

    # Thin content detection: JS-rendered sites return < 8000 chars of visible text.
    # Upgrade to Playwright automatically when detected.
    visible_text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    if len(visible_text) < 8000:
        print(f"[*] Thin content ({len(visible_text)} chars). Upgrading to headless browser fetch...")
        playwright_html = _fetch_with_playwright(url)
        if playwright_html and len(playwright_html) > len(raw_html):
            print("[*] Playwright fetch succeeded -- using richer content.")
            raw_html = playwright_html
        else:
            print("[*] Falling back to static fetch.")

    soup = BeautifulSoup(raw_html, 'html.parser')

    # Remove noise elements to reduce token count.
    # Keep style tags -- the analysis prompt extracts brand colors from them.
    for element in soup(["script", "svg", "noscript", "iframe"]):
        element.decompose()

    # Aggressively extract ALL image src URLs (including lazy-loaded data-src)
    # and embed as a comment at the top so the LLM can always find them.
    image_urls = set()
    for img in soup.find_all("img"):
        for attr in ["src", "data-src", "data-lazy-src", "data-original"]:
            val = img.get(attr, "")
            if val and val.startswith("http") and any(ext in val.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                image_urls.add(val)
    for style in soup.find_all("style"):
        found = re.findall(r'url\(["\']?(https://[^"\')\s]+)["\']?\)', style.string or "")
        image_urls.update(found)

    image_comment = "\n<!-- EXTRACTED IMAGE URLS (use these in the redesign):\n"
    for img_url in list(image_urls)[:20]:
        image_comment += f"  {img_url}\n"
    image_comment += "-->"

    return image_comment + "\n" + str(soup)

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

def analyze_site(html_content):
    print(f"[*] Analyzing site content with {EXTRACTION_MODEL}...")
    with open("references/01-site-analysis-prompt.md", "r") as f:
        system_prompt = f.read()

    response = get_openrouter_client().chat.completions.create(
        model=EXTRACTION_MODEL,
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": html_content[:120000]} # Truncate to avoid context window limits
        ],
        temperature=0.1
    )

    return _extract_json_object(response.choices[0].message.content)

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
            page_html = fetch_and_clean_html(url)
        except Exception as e:
            print(f"[!] Enrichment fetch failed for {url}: {e}")
            continue

        user_prompt = (
            f"PAGE_TYPE: {page_type}\n"
            f"SOURCE_URL: {url}\n\n"
            f"HTML:\n{page_html[:ENRICHMENT_HTML_TRUNCATE]}"
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

        if not isinstance(result, dict) or not result:
            print(f"[*] Enrichment for {page_type} returned empty; skipping.")
            continue

        if page_type == "contact":
            form_fields = result.get("form_fields")
            contact_info = result.get("contact_info") or {}
            has_form = isinstance(form_fields, list) and len(form_fields) > 0
            has_info = any(contact_info.get(k) for k in ("phone", "email", "address", "hours"))
            if not (has_form or has_info):
                print(f"[*] Enrichment for contact at {url} had no form or contact info; skipping.")
                continue
            result.setdefault("source_url", url)
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
            result.setdefault("source_url", url)
            site_json.setdefault("sections", []).append(result)
            print(f"[*] Enriched {page_type} from {url}: {len(items)} item(s)")

    return site_json

def generate_redesign(
    site_json,
    theme="minimal",
    color_mode="brand",
    generation_config=None,
    generation_client=None,
):
    config = generation_config or resolve_generation_config()
    print(
        f"[*] Generating modernized HTML with theme '{theme}' using "
        f"{config.provider}:{config.model}..."
    )
    with open("references/02-redesign-gen-prompt.md", "r") as f:
        system_prompt = f.read()

    with open("references/03-base-template.html", "r") as f:
        base_template = f.read()

    user_prompt = f"""THEME: {theme}
COLOR_MODE: {color_mode}
ACCENT_OVERRIDE: none
NOTES: none

SITE JSON:
{json.dumps(site_json, indent=2)}

BASE TEMPLATE:
{base_template}
"""

    result = generate_text(
        config,
        system_prompt=system_prompt,
        user_parts=(PromptPart(user_prompt),),
        temperature=0.4,
        client=generation_client,
    )

    return validate_generated_html(result)

def generate_interior_page(
    site_json,
    page_type,
    page_url=None,
    theme="warm",
    color_mode="brand",
    generation_config=None,
    generation_client=None,
):
    print(f"[*] Generating interior page '{page_type}'...")
    with open("references/04-interior-page-prompt.md", "r") as f:
        system_prompt = f.read()
        
    with open("references/03-base-template.html", "r") as f:
        base_template = f.read()
        
    if page_url:
        print(f"[*] Fetching interior page content from {page_url}...")
        source_content = fetch_and_clean_html(page_url)
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
        
    user_prompt = f"""PAGE TYPE: {page_type}
PAGE URL: {page_url or 'n/a -- single-page site'}
CONTENT_SOURCE: {content_source}
NOTES: none

HOMEPAGE DESIGN JSON:
{json.dumps(site_json, indent=2)}

BASE TEMPLATE:
{base_template}

---
SOURCE CONTENT:
{source_content}
---
"""

    config = generation_config or resolve_generation_config()
    result = generate_text(
        config,
        system_prompt=system_prompt,
        user_parts=(PromptPart(user_prompt[:120000]),),
        temperature=0.1,
        client=generation_client,
    )

    return validate_generated_html(result)


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
    html_content = fetch_and_clean_html(url)
    
    # 2. Analyze (Extract Info & JSON)
    site_json = analyze_site(html_content)

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
    )
    pages_to_deploy = {"index.html": redesign_html}
    
    # 3.5 Generate Contact Page if available. Fail-soft: if the fetch 404s
    # (extracted URL is wrong, page moved, etc.), fall back to generating the
    # contact page from the homepage JSON alone instead of crashing.
    pages_to_fetch = site_json.get("pages_to_fetch", [])
    contact_pages = [p for p in pages_to_fetch if p.get("page_type") == "contact"]
    if contact_pages:
        contact_url = contact_pages[0].get("url")
        contact_fetchable = contact_pages[0].get("fetchable", False)
        contact_html = None
        if contact_fetchable and contact_url:
            try:
                contact_html = generate_interior_page(
                    site_json,
                    "contact",
                    page_url=contact_url,
                    theme=theme,
                    generation_config=generation_config,
                )
            except Exception as e:
                print(f"[!] Contact page fetch/generation failed for {contact_url}: {e}")
                print("[*] Falling back to homepage-section content for contact page.")
        if contact_html is None:
            contact_html = generate_interior_page(
                site_json,
                "contact",
                theme=theme,
                generation_config=generation_config,
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
