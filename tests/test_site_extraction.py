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

    def test_homepage_section_does_not_gain_enrichment_provenance(self):
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
        self.assertNotIn("source_url", admitted["sections"][0])

        document["sections"][0]["source_url"] = "https://attacker.test/spoofed"
        with self.assertRaisesRegex(SiteExtractionError, "schema"):
            validate_site_analysis(
                document,
                html,
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
                "platform": {"detected": "WordPress"},
            },
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

    def test_claim_text_cannot_drop_source_negation(self):
        cases = (
            (
                "<h1>Acme Cleaning</h1><p>No Free Estimates</p>",
                {"existing_ctas": ["Free Estimates"]},
            ),
            (
                "<h1>Acme Cleaning</h1><p>Not BBB Accredited</p>",
                {"trust_signals": {"certifications": ["BBB Accredited"]}},
            ),
            (
                ('<h1>Acme Cleaning</h1><p>Not <a href="/bbb">BBB Accredited</a></p>'),
                {"trust_signals": {"certifications": ["BBB Accredited"]}},
            ),
            (
                "<h1>Acme Cleaning</h1><p>Unlicensed subcontractors prohibited</p>",
                {"trust_signals": {"certifications": ["Licensed"]}},
            ),
            (
                "<h1>Acme Cleaning</h1><p>Free Estimates are not available</p>",
                {"existing_ctas": ["Free Estimates"]},
            ),
            (
                (
                    "<h1>Acme Cleaning</h1>"
                    "<p>Free Estimates, however, are not available.</p>"
                ),
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
        )
        for html, conversion_profile in cases:
            with (
                self.subTest(html=html),
                self.assertRaisesRegex(
                    SiteExtractionError, "grounded|assertion context"
                ),
            ):
                validate_site_analysis(
                    {
                        "site": {"name": "Acme Cleaning"},
                        "conversion_profile": conversion_profile,
                    },
                    html,
                )

    def test_complete_negated_claim_and_separate_positive_occurrence_are_admitted(self):
        complete_claim = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {"existing_ctas": ["No Surprise Fees"]},
        }
        self.assertEqual(
            validate_site_analysis(
                complete_claim,
                "<h1>Acme Cleaning</h1><button>No Surprise Fees</button>",
            ),
            complete_claim,
        )

        positive_claim = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {"existing_ctas": ["Free Estimates"]},
        }
        self.assertEqual(
            validate_site_analysis(
                positive_claim,
                (
                    "<h1>Acme Cleaning</h1><p>No Free Estimates for repairs.</p>"
                    '<a href="/estimates">Free Estimates</a>'
                ),
            ),
            positive_claim,
        )

        rhetorical_positive = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {
                "trust_signals": {"certifications": ["BBB Accredited"]}
            },
        }
        self.assertEqual(
            validate_site_analysis(
                rhetorical_positive,
                (
                    "<h1>Acme Cleaning</h1>"
                    "<p>Not only BBB Accredited but locally owned.</p>"
                ),
            ),
            rhetorical_positive,
        )

        postposed_positive = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {
                "trust_signals": {"social_proof_lines": ["Free Estimates"]}
            },
        }
        for source_text in (
            "Free Estimates are not only available but easy to request",
            "Free Estimates are available without obligation",
            "Free Estimates are available, however financing is not",
        ):
            with self.subTest(source_text=source_text):
                self.assertEqual(
                    validate_site_analysis(
                        postposed_positive,
                        f"<h1>Acme Cleaning</h1><p>{source_text}</p>",
                    ),
                    postposed_positive,
                )

    def test_claim_text_rejects_questions_conditionals_and_inline_negation(self):
        cases = (
            (
                "<p>Do you offer <strong>Free Estimates</strong>?</p>",
                {"existing_ctas": ["Free Estimates"]},
            ),
            (
                "<p>If eligible, <strong>Free Estimates</strong> are available.</p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
            (
                "<p><span>No</span> <strong>Free Estimates</strong></p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
            (
                "<p><strong>Free Estimates</strong> <span>are not available</span></p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
            (
                "<p><strong>Free Estimates</strong>: Are they available?</p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
        )
        for source, conversion_profile in cases:
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(
                    SiteExtractionError, "action label|assertion context"
                ),
            ):
                validate_site_analysis(
                    {
                        "site": {"name": "Acme Cleaning"},
                        "conversion_profile": conversion_profile,
                    },
                    f"<h1>Acme Cleaning</h1>{source}",
                )

    def test_existing_cta_requires_an_exact_source_action_label(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {"existing_ctas": ["Free Estimates"]},
        }
        self.assertEqual(
            validate_site_analysis(
                document,
                "<h1>Acme Cleaning</h1><button><strong>Free Estimates</strong></button>",
            ),
            document,
        )

    def test_existing_cta_accepts_submit_input_but_not_other_input_types(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {"existing_ctas": ["Free Estimates"]},
        }
        self.assertEqual(
            validate_site_analysis(
                document,
                '<h1>Acme Cleaning</h1><input type="submit" value="Free Estimates">',
            ),
            document,
        )

        for input_type in ("button", "image", "reset", "text"):
            with (
                self.subTest(input_type=input_type),
                self.assertRaisesRegex(SiteExtractionError, "action label"),
            ):
                validate_site_analysis(
                    document,
                    (
                        "<h1>Acme Cleaning</h1>"
                        f'<input type="{input_type}" value="Free Estimates">'
                    ),
                )

    def test_navigation_label_and_url_must_share_one_source_action(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "nav": [
                {"label": "Contact", "url": "https://acme.test/about"},
                {"label": "About", "url": "https://acme.test/contact"},
            ],
        }

        with self.assertRaisesRegex(SiteExtractionError, "one source action"):
            validate_site_analysis(
                document,
                (
                    "<h1>Acme Cleaning</h1>"
                    '<a href="/contact">Contact</a>'
                    '<a href="/about">About</a>'
                ),
                "https://acme.test/",
            )

    def test_phone_evidence_is_local_but_combines_inline_parts(self):
        document = {
            "site": {
                "name": "Acme Cleaning",
                "contact": {"phone": "217-555-0100"},
            }
        }

        with self.assertRaisesRegex(SiteExtractionError, "source phone"):
            validate_site_analysis(
                document,
                ("<h1>Acme Cleaning</h1><div>217</div><div>555</div><div>0100</div>"),
            )

        self.assertEqual(
            validate_site_analysis(
                document,
                (
                    "<h1>Acme Cleaning</h1>"
                    "<p><span>217</span> <span>555</span> <span>0100</span></p>"
                ),
            ),
            document,
        )

    def test_claim_bearing_service_item_rejects_question_only_evidence(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {
                    "type": "services",
                    "items": [{"title": "Free Estimates"}],
                }
            ],
        }

        with self.assertRaisesRegex(SiteExtractionError, "assertion context"):
            validate_site_analysis(
                document,
                "<h1>Acme Cleaning</h1><p>Do you offer Free Estimates?</p>",
            )

    def test_single_page_section_binds_navigation_and_scopes_content(self):
        source = (
            "<h1>Acme Cleaning</h1><nav>"
            '<a href="#about">About</a><a href="#contact">Contact</a></nav>'
            '<section id="about"><h2>About Us</h2><p>Family owned.</p></section>'
            '<section id="contact"><h2>Contact Us</h2><p>Call today.</p></section>'
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "single_page_sections": [
                {
                    "nav_label": "About",
                    "anchor": "#about",
                    "page_type": "about",
                    "content": {"headline": "About Us", "body_text": "Family owned."},
                }
            ],
        }
        self.assertEqual(validate_site_analysis(valid, source), valid)

        swapped_target = {
            **valid,
            "single_page_sections": [
                {**valid["single_page_sections"][0], "anchor": "#contact"}
            ],
        }
        with self.assertRaisesRegex(SiteExtractionError, "one source action"):
            validate_site_analysis(swapped_target, source)

        cross_section_content = {
            **valid,
            "single_page_sections": [
                {
                    **valid["single_page_sections"][0],
                    "content": {"headline": "Contact Us", "body_text": "Call today."},
                }
            ],
        }
        with self.assertRaisesRegex(SiteExtractionError, "source text"):
            validate_site_analysis(cross_section_content, source)

    def test_contact_uri_parameters_do_not_become_contact_evidence(self):
        cases = (
            (
                {"phone": "217-555-0100"},
                '<a href="mailto:real@acme.test?body=Call%20217-555-0100">Email</a>',
                "source phone",
            ),
            (
                {"email": "billing@acme.test"},
                '<a href="tel:217-555-0100?note=billing@acme.test">Call</a>',
                "source email",
            ),
            (
                {"phone": "217-555-0100"},
                '<a href="mailto:2175550100@acme.test">Email</a>',
                "source phone",
            ),
            (
                {"email": "billing@acme.test"},
                '<a href="tel:billing@acme.test">Call</a>',
                "source email",
            ),
        )
        for contact, link, error in cases:
            with (
                self.subTest(contact=contact),
                self.assertRaisesRegex(SiteExtractionError, error),
            ):
                validate_site_analysis(
                    {"site": {"name": "Acme Cleaning", "contact": contact}},
                    f"<h1>Acme Cleaning</h1>{link}",
                    "https://acme.test/",
                )

    def test_image_resources_cannot_be_repurposed_as_action_urls(self):
        with self.assertRaisesRegex(SiteExtractionError, r"cta\.url"):
            validate_site_analysis(
                {
                    "site": {"name": "Acme Cleaning"},
                    "cta": {"label": "Contact", "url": "https://acme.test/hero.jpg"},
                },
                (
                    "<h1>Acme Cleaning</h1>"
                    '<a href="/contact">Contact</a>'
                    '<link rel="preload" as="image" href="/hero.jpg">'
                    '<img src="/hero.jpg" alt="Crew">'
                ),
                "https://acme.test/",
            )

    def test_generation_action_contract_keeps_only_action_owned_urls(self):
        contract = pipeline._redesign_action_url_contract(
            {
                "site": {"name": "Acme Cleaning"},
                "brand": {"logo_url": "/logo.png"},
                "nav": [{"label": "Contact", "url": "/contact"}],
                "cta": {"label": "Book", "url": "/book"},
                "sections": [
                    {
                        "items": [
                            {
                                "title": "Office",
                                "url": "/services/office",
                                "image_url": "/office.jpg",
                            }
                        ],
                        "source_url": "/services",
                    }
                ],
                "contact_form": {"source_url": "/contact-source"},
                "images": [{"url": "/hero.jpg", "context": "hero"}],
                "social": [{"platform": "Facebook", "url": "/facebook"}],
                "footer_links": [{"label": "Privacy", "url": "/privacy"}],
                "pages_to_fetch": [{"label": "About", "url": "/about"}],
                "single_page_sections": [
                    {
                        "anchor": "#team",
                        "content": {"items": [{"title": "Jane", "url": "/jane"}]},
                    }
                ],
            },
            pipeline._redesign_contact_contract({}),
            source_content=(
                '<a href="/source-link">Source</a><form action="/submit"></form>'
                '<img src="/source-image.jpg">'
            ),
            extra_urls=("/current-page",),
        )

        self.assertEqual(
            contract.allowed_urls,
            (
                "/contact",
                "/book",
                "/services",
                "/services/office",
                "/contact-source",
                "/facebook",
                "/privacy",
                "/about",
                "#team",
                "/jane",
                "/current-page",
                "/source-link",
            ),
        )

    def test_form_endpoint_cannot_be_repurposed_as_link_destination(self):
        with self.assertRaisesRegex(SiteExtractionError, r"cta\.url"):
            validate_site_analysis(
                {
                    "site": {"name": "Acme Cleaning"},
                    "cta": {"label": "Contact", "url": "https://acme.test/submit"},
                },
                (
                    "<h1>Acme Cleaning</h1><button>Contact</button>"
                    '<form action="/submit"><input name="email"></form>'
                ),
                "https://acme.test/",
            )

    def test_resource_urls_do_not_become_contact_evidence(self):
        cases = (
            (
                {"phone": "217-555-0100"},
                '<img src="/images/217-555-0100.jpg" alt="Crew">',
                "source phone",
            ),
            (
                {"email": "billing@acme.test"},
                '<form action="/route/billing@acme.test"><button>Send</button></form>',
                "source email",
            ),
            (
                {"phone": "217-555-0100"},
                '<img src="/crew.jpg" alt="217-555-0100">',
                "source phone",
            ),
            (
                {"email": "billing@acme.test"},
                '<input placeholder="billing@acme.test">',
                "source email",
            ),
            (
                {"phone": "217-555-0100"},
                "<!-- https://cdn.test/217-555-0100.jpg -->",
                "source phone",
            ),
            (
                {"email": "billing@acme.test"},
                "<!-- billing@acme.test -->",
                "source email",
            ),
        )
        for contact, resource, error in cases:
            with (
                self.subTest(contact=contact),
                self.assertRaisesRegex(SiteExtractionError, error),
            ):
                validate_site_analysis(
                    {"site": {"name": "Acme Cleaning", "contact": contact}},
                    f"<h1>Acme Cleaning</h1>{resource}",
                    "https://acme.test/",
                )


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

        with self.assertRaisesRegex(
            SiteExtractionError, r"items\[1\].*one source container"
        ):
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

    def test_faq_enrichment_uses_code_owned_derived_headline(self):
        document = {
            "type": "misc",
            "headline": "FAQ",
            "items": [
                {
                    "title": "Do you offer recurring cleaning?",
                    "url": None,
                    "image_url": None,
                    "tag": "faq",
                    "meta": "Yes, weekly and biweekly service is available.",
                }
            ],
        }

        admitted = validate_enrichment_result(
            document,
            page_type="faq",
            source_html=(
                "<h1>Frequently Asked Questions</h1>"
                "<h2>Do you offer recurring cleaning?</h2>"
                "<p>Yes, weekly and biweekly service is available.</p>"
            ),
            source_url="https://acme.test/questions",
        )

        self.assertEqual(admitted["headline"], "FAQ")

    def test_composite_item_fields_must_share_one_source_container(self):
        document = {
            "type": "misc",
            "headline": "FAQ",
            "items": [
                {
                    "title": "Do you offer free estimates?",
                    "url": None,
                    "image_url": None,
                    "tag": "faq",
                    "meta": "Yes.",
                }
            ],
        }
        html = """
        <h1>Frequently Asked Questions</h1>
        <div class="faq-item"><h2>Do you offer free estimates?</h2><p>No.</p></div>
        <div class="faq-item"><h3>Do you offer recurring service?</h3><p>Yes.</p></div>
        """

        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_enrichment_result(
                document,
                page_type="faq",
                source_html=html,
                source_url="https://acme.test/questions",
            )

    def test_section_heading_record_cannot_span_sibling_cards(self):
        document = {
            "type": "misc",
            "headline": "FAQ",
            "items": [
                {
                    "title": "Do you offer free estimates?",
                    "url": None,
                    "image_url": None,
                    "tag": "faq",
                    "meta": "Yes.",
                }
            ],
        }
        html = """
        <h2>Frequently Asked Questions</h2>
        <div class="faq-item"><h3>Do you offer free estimates?</h3><p>No.</p></div>
        <div class="faq-item"><h3>Do you offer recurring service?</h3><p>Yes.</p></div>
        """

        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_enrichment_result(
                document,
                page_type="faq",
                source_html=html,
                source_url="https://acme.test/questions",
            )

    def test_section_heading_record_cannot_span_list_records(self):
        document = {
            "type": "misc",
            "headline": "FAQ",
            "items": [
                {
                    "title": "Do you offer free estimates?",
                    "url": None,
                    "image_url": None,
                    "tag": "faq",
                    "meta": "Yes.",
                }
            ],
        }
        sources = (
            (
                "ul",
                "<ul><li><h3>Do you offer free estimates?</h3><p>No.</p></li>"
                "<li><h3>Do you offer recurring service?</h3><p>Yes.</p></li></ul>",
            ),
            (
                "ol",
                "<ol><li><h3>Do you offer free estimates?</h3><p>No.</p></li>"
                "<li><h3>Do you offer recurring service?</h3><p>Yes.</p></li></ol>",
            ),
            (
                "dl",
                "<dl><dt>Do you offer free estimates?</dt><dd>No.</dd>"
                "<dt>Do you offer recurring service?</dt><dd>Yes.</dd></dl>",
            ),
        )

        for wrapper, source in sources:
            with (
                self.subTest(wrapper=wrapper),
                self.assertRaisesRegex(SiteExtractionError, "one source container"),
            ):
                validate_enrichment_result(
                    document,
                    page_type="faq",
                    source_html=f"<h2>Questions</h2>{source}",
                    source_url="https://acme.test/questions",
                )

        valid = {
            **document,
            "items": [{**document["items"][0], "meta": "Yes."}],
        }
        self.assertEqual(
            validate_enrichment_result(
                valid,
                page_type="faq",
                source_html=(
                    "<h2>Questions</h2><dl>"
                    "<dt>Do you offer free estimates?</dt><dd>Yes.</dd></dl>"
                ),
                source_url="https://acme.test/questions",
            )["items"],
            valid["items"],
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

    def test_late_image_inventory_is_shared_by_prompt_and_validation(self):
        image_url = "https://cdn.acme.test/late-hero.jpg"
        response = SimpleNamespace(
            text=(
                "<html><body><h1>Acme Cleaning</h1>"
                + ("x" * pipeline.ANALYSIS_HTML_TRUNCATE)
                + f'<img src="{image_url}"></body></html>'
            ),
            url="https://acme.test/",
            raise_for_status=lambda: None,
        )
        document = {
            "site": {"name": "Acme Cleaning"},
            "images": [{"url": image_url, "alt": None, "context": "hero"}],
        }

        with patch.object(pipeline.requests, "get", return_value=response):
            cleaned = pipeline.fetch_and_clean_html("https://acme.test/")

        client = _ExtractionClient(document)
        with patch.object(pipeline, "get_openrouter_client", return_value=client):
            admitted = pipeline.analyze_site(cleaned, source_url="https://acme.test/")

        self.assertEqual(admitted, document)
        prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("data-code-owned-image-inventory", prompt)
        self.assertIn(image_url, prompt)


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
        self.assertNotIn("Every redesign includes a trust strip", prompt)
        self.assertIn("If none of the source-owned values above exists, omit", prompt)


if __name__ == "__main__":
    unittest.main()
