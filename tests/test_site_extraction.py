import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline
from lib.site_extraction import (
    MAX_ITEMS,
    MAX_TEXT_LENGTH,
    SiteExtractionError,
    validate_enrichment_result,
    validate_site_analysis,
)


class _ExtractionClient:
    def __init__(self, document):
        self._document = document
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=json.dumps(self._document))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class SiteAnalysisGroundingTests(unittest.TestCase):
    def test_analyze_site_rejects_phone_absent_from_source(self):
        document = {
            "site": {
                "name": "Acme Cleaning",
                "contact": {"phone": "217-555-9999"},
            }
        }
        html = "<html><body><h1>Acme Cleaning</h1></body></html>"

        with patch.object(
            pipeline,
            "get_openrouter_client",
            return_value=_ExtractionClient(document),
        ):
            with self.assertRaises(ValueError):
                pipeline.analyze_site(html)

    def test_analyze_site_admits_grounded_contacts_images_and_relative_urls(self):
        document = {
            "site": {
                "name": "Acme Cleaning",
                "location": "Effingham, IL",
                "contact": {
                    "phone": "(217) 555-0100",
                    "email": "hello@acme.test",
                    "addresses": ["100 Main Street, Effingham, IL"],
                },
            },
            "nav": [{"label": "Contact", "url": "https://acme.test/contact"}],
            "brand": {"logo_url": "https://acme.test/logo.png"},
            "images": [
                {
                    "url": "https://acme.test/hero.jpg",
                    "alt": "Acme cleaning crew",
                    "context": "hero",
                }
            ],
            "conversion_profile": {
                "urgency_type": "planned",
                "primary_goal": "form",
                "has_emergency_service": False,
                "phone": "217-555-0100",
                "existing_ctas": ["Request a Quote"],
            },
            "homepage_blueprint": {
                "hero_type": "hero-split",
                "above_fold_form": True,
                "section_sequence": ["hero", "inline-form"],
                "footer_layout": "footer-2col",
                "notes": "Derived layout observation",
            },
            "platform": {"detected": "WordPress"},
        }
        html = """
        <html><head><meta property="og:image" content="/logo.png"></head><body>
          <h1>Acme Cleaning</h1><p>Effingham, IL</p>
          <a href="/contact">Contact</a>
          <a href="tel:+12175550100">(217) 555-0100</a>
          <a href="mailto:hello@acme.test">hello@acme.test</a>
          <address>100 Main Street, Effingham, IL</address>
          <button>Request a Quote</button>
          <img src="/hero.jpg" alt="Acme cleaning crew">
        </body></html>
        """
        client = _ExtractionClient(document)

        with patch.object(pipeline, "get_openrouter_client", return_value=client):
            admitted = pipeline.analyze_site(html, source_url="https://acme.test/")

        self.assertEqual(admitted, document)
        supplied_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("SOURCE_URL: https://acme.test/", supplied_prompt)

    def test_homepage_section_provenance_is_owned_by_code(self):
        document = {
            "site": {"name": "Drees Plumbing"},
            "sections": [
                {
                    "type": "services",
                    "headline": "Drain Cleaning",
                    "items": [
                        {
                            "title": "Drain Cleaning",
                            "description": "Clear drains, done right.",
                        }
                    ],
                }
            ],
        }
        html = (
            "<h1>Drees Plumbing</h1><section><h2>Drain Cleaning</h2>"
            "<p>Clear drains, done right.</p></section>"
        )

        admitted = validate_site_analysis(
            document,
            html,
            "https://example.com/home",
        )

        self.assertNotIn("source_url", document["sections"][0])
        self.assertEqual(
            admitted["sections"][0]["source_url"],
            "https://example.com/home",
        )

    def test_site_analysis_rejects_one_fabricated_value_in_mixed_collection(self):
        document = {
            "site": {
                "name": "Acme Cleaning",
                "contact": {
                    "addresses": [
                        "100 Main Street",
                        "999 Fabricated Avenue",
                    ]
                },
            }
        }

        with self.assertRaisesRegex(
            SiteExtractionError, r"site\.contact\.addresses\[1\]"
        ):
            validate_site_analysis(
                document,
                "<h1>Acme Cleaning</h1><address>100 Main Street</address>",
                "https://acme.test/",
            )

    def test_site_analysis_rejects_unknown_and_wrong_typed_fields(self):
        cases = (
            {
                "site": {
                    "name": "Acme Cleaning",
                    "unverified": "unexpected",
                }
            },
            {"site": {"name": "Acme Cleaning"}, "nav": ["Contact"]},
            {
                "site": {"name": "Acme Cleaning"},
                "pages_to_fetch": [
                    {
                        "label": "Contact",
                        "url": "/contact",
                        "page_type": "contact",
                        "priority": 0,
                        "fetchable": True,
                    }
                ],
            },
            {"site": {"name": "   "}},
            {"site": {"name": "Acme Cleaning"}, "sections": 1},
            {
                "site": {"name": "Acme Cleaning"},
                "pages_to_fetch": [
                    {
                        "label": "Contact",
                        "url": "/contact",
                        "page_type": "contact",
                        "priority": True,
                        "fetchable": True,
                    }
                ],
            },
        )
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaisesRegex(SiteExtractionError, "schema"):
                    validate_site_analysis(
                        document,
                        "<h1>Acme Cleaning</h1><a href='/contact'>Contact</a>",
                        "https://acme.test/",
                    )

    def test_schema_limits_accept_the_boundary_and_reject_beyond_it(self):
        html = "<h1>Acme Cleaning</h1>"
        accepted = (
            {
                "site": {"name": "Acme Cleaning"},
                "image_generation_prompt": "x" * MAX_TEXT_LENGTH,
            },
            {
                "site": {"name": "Acme Cleaning"},
                "brand": {"style_notes": ["x"] * MAX_ITEMS},
            },
            {
                "site": {"name": "Acme Cleaning"},
                "pages_to_fetch": [
                    {
                        "label": "Contact",
                        "url": "/contact",
                        "page_type": "contact",
                        "priority": priority,
                        "fetchable": False,
                    }
                    for priority in (1, 3)
                ],
            },
        )
        for document in accepted:
            with self.subTest(boundary="accepted", document=document):
                validate_site_analysis(
                    document, html + "<a href='/contact'>Contact</a>"
                )

        rejected = (
            {
                "site": {"name": "Acme Cleaning"},
                "image_generation_prompt": "x" * (MAX_TEXT_LENGTH + 1),
            },
            {
                "site": {"name": "Acme Cleaning"},
                "brand": {"style_notes": ["x"] * (MAX_ITEMS + 1)},
            },
            {
                "site": {"name": "Acme Cleaning"},
                "brand": {"style_notes": [("💾" * MAX_TEXT_LENGTH)] * 4},
            },
            {
                "site": {"name": "Acme Cleaning"},
                "pages_to_fetch": [
                    {
                        "label": "Contact",
                        "url": "/contact",
                        "page_type": "contact",
                        "priority": 4,
                        "fetchable": False,
                    }
                ],
            },
        )
        for document in rejected:
            with self.subTest(boundary="rejected", document=document):
                with self.assertRaisesRegex(SiteExtractionError, "size limit|schema"):
                    validate_site_analysis(document, html)

    def test_site_analysis_rejects_unobserved_url(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "nav": [{"label": "Contact", "url": "https://attacker.test/contact"}],
        }

        with self.assertRaisesRegex(SiteExtractionError, r"nav\[0\]\.url"):
            validate_site_analysis(
                document,
                "<h1>Acme Cleaning</h1><a href='/contact'>Contact</a>",
                "https://acme.test/",
            )

    def test_analyze_site_cannot_ground_a_fact_beyond_the_prompt_cutoff(self):
        document = {
            "site": {
                "name": "Acme Cleaning",
                "contact": {"phone": "217-555-9999"},
            }
        }
        html = "<h1>Acme Cleaning</h1>" + ("x" * 120_000) + "217-555-9999"

        with patch.object(
            pipeline,
            "get_openrouter_client",
            return_value=_ExtractionClient(document),
        ):
            with self.assertRaisesRegex(SiteExtractionError, "source phone"):
                pipeline.analyze_site(html, source_url="https://acme.test/")


class EnrichmentGroundingTests(unittest.TestCase):
    def test_content_enrichment_uses_code_owned_source_url(self):
        document = {
            "type": "services",
            "headline": "Cleaning Services",
            "items": [
                {
                    "title": "Office Cleaning",
                    "url": "https://acme.test/services/office",
                    "image_url": "/office.jpg",
                    "tag": "Commercial",
                    "meta": "Nightly and weekly office cleaning.",
                }
            ],
            "source_url": "https://attacker.test/spoofed",
        }
        source_url = "https://acme.test/services"
        html = """
        <h1>Cleaning Services</h1>
        <article><h2>Office Cleaning</h2><span>Commercial</span>
        <p>Nightly and weekly office cleaning.</p>
        <a href="/services/office">Learn more</a>
        <img src="/office.jpg"></article>
        """

        admitted = validate_enrichment_result(
            document,
            page_type="services",
            source_html=html,
            source_url=source_url,
        )

        self.assertEqual(admitted["source_url"], source_url)
        self.assertEqual(document["source_url"], "https://attacker.test/spoofed")

    def test_content_enrichment_rejects_mixed_fabricated_item(self):
        document = {
            "type": "team",
            "headline": "Our Team",
            "items": [
                {
                    "title": "Jane Doe",
                    "url": None,
                    "image_url": None,
                    "tag": "Manager",
                    "meta": "Leads the cleaning team.",
                },
                {
                    "title": "Invented Person",
                    "url": None,
                    "image_url": None,
                    "tag": "Owner",
                    "meta": None,
                },
            ],
        }

        with self.assertRaisesRegex(SiteExtractionError, r"items\[1\]\.title"):
            validate_enrichment_result(
                document,
                page_type="team",
                source_html=(
                    "<h1>Our Team</h1><h2>Jane Doe</h2><p>Manager</p>"
                    "<p>Leads the cleaning team.</p>"
                ),
                source_url="https://acme.test/team",
            )

    def test_derived_enrichment_tag_must_match_selected_page_type(self):
        document = {
            "type": "misc",
            "headline": "About Us",
            "items": [
                {
                    "title": "Our Story",
                    "url": None,
                    "image_url": None,
                    "tag": "faq",
                    "meta": "We started in Effingham.",
                }
            ],
        }

        with self.assertRaisesRegex(SiteExtractionError, "item tag"):
            validate_enrichment_result(
                document,
                page_type="about",
                source_html=(
                    "<h1>About Us</h1><h2>Our Story</h2><p>We started in Effingham.</p>"
                ),
                source_url="https://acme.test/about",
            )

    def test_pipeline_skips_invalid_enrichment_without_mutating_site_json(self):
        site_json = {
            "pages_to_fetch": [
                {
                    "fetchable": True,
                    "priority": 1,
                    "page_type": "services",
                    "url": "https://acme.test/services",
                }
            ],
            "sections": [],
        }
        fabricated = {
            "type": "services",
            "headline": "Cleaning Services",
            "items": [
                {
                    "title": "Invented Service",
                    "url": None,
                    "image_url": None,
                    "tag": None,
                    "meta": None,
                }
            ],
        }

        with (
            patch.object(
                pipeline,
                "fetch_and_clean_html",
                return_value=(
                    "<h1>Cleaning Services</h1>",
                    "https://acme.test/services",
                ),
            ),
            patch.object(
                pipeline,
                "get_openrouter_client",
                return_value=_ExtractionClient(fabricated),
            ),
        ):
            returned = pipeline.enrich_site_json(site_json)

        self.assertIs(returned, site_json)
        self.assertEqual(site_json["sections"], [])

    def test_pipeline_cannot_ground_enrichment_beyond_the_prompt_cutoff(self):
        site_json = {
            "pages_to_fetch": [
                {
                    "fetchable": True,
                    "priority": 1,
                    "page_type": "services",
                    "url": "https://acme.test/services",
                }
            ],
            "sections": [],
        }
        fabricated = {
            "type": "services",
            "headline": "Cleaning Services",
            "items": [{"title": "Invented Service"}],
        }
        page_html = (
            "<h1>Cleaning Services</h1>" + ("x" * 120_000) + "<h2>Invented Service</h2>"
        )

        with (
            patch.object(
                pipeline,
                "fetch_and_clean_html",
                return_value=(page_html, "https://acme.test/services"),
            ),
            patch.object(
                pipeline,
                "get_openrouter_client",
                return_value=_ExtractionClient(fabricated),
            ),
        ):
            returned = pipeline.enrich_site_json(site_json)

        self.assertIs(returned, site_json)
        self.assertEqual(site_json["sections"], [])

    def test_contact_enrichment_rejects_empty_contact_container(self):
        with self.assertRaisesRegex(SiteExtractionError, "no source content"):
            validate_enrichment_result(
                {"contact_info": {}},
                page_type="contact",
                source_html="<h1>Contact</h1>",
                source_url="https://acme.test/contact",
            )


class FetchEvidenceTests(unittest.TestCase):
    def test_fetch_returns_effective_redirect_url_for_source_admission(self):
        response = SimpleNamespace(
            text="<html><body><p>Source page</p></body></html>",
            url="https://www.acme.test/home",
            raise_for_status=lambda: None,
        )

        with (
            patch.object(pipeline.requests, "get", return_value=response),
            patch.object(pipeline, "_fetch_with_playwright", return_value=None),
        ):
            cleaned, effective_url = pipeline.fetch_and_clean_html(
                "https://acme.test", include_source_url=True
            )

        self.assertIn("Source page", cleaned)
        self.assertEqual(effective_url, "https://www.acme.test/home")


class RedesignPromptAuthorityTests(unittest.TestCase):
    def test_derived_urgency_does_not_authorize_availability_promises(self):
        prompt = Path("references/02-redesign-gen-prompt.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("SOURCE AUTHORITY BOUNDARY", prompt)
        self.assertIn("Urgency controls CTA layout and relative emphasis only", prompt)
        self.assertNotIn("A response-time / availability promise tied", prompt)
        self.assertNotIn('"Call Now -- We Answer 24/7"', prompt)
        self.assertNotIn('"Get My Free Quote"', prompt)
        self.assertNotIn("Build the headline from `site.type`", prompt)
        self.assertIn("do not substitute `site.type` as", prompt)


if __name__ == "__main__":
    unittest.main()
