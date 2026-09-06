import copy
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
    same_site_origin,
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

    def test_analyze_site_propagates_identity_authority(self):
        wrapped = {"site": {"name": "Welcome to Acme Plumbing"}}
        wrapped_html = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            "<title>Welcome to Acme Plumbing</title><h1>Services</h1>"
        )
        with patch.object(
            pipeline,
            "get_openrouter_client",
            return_value=_ExtractionClient(wrapped),
        ):
            self.assertEqual(pipeline.analyze_site(wrapped_html), wrapped)

        expanded = {"site": {"name": "Best Acme Plumbing"}}
        expanded_html = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            "<h1>Best Acme Plumbing</h1>"
        )
        with (
            patch.object(
                pipeline,
                "get_openrouter_client",
                return_value=_ExtractionClient(expanded),
            ),
            self.assertRaisesRegex(SiteExtractionError, "identity"),
        ):
            pipeline.analyze_site(expanded_html)

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
          <a class="navbar-brand"><img src="/logo.png" alt="Acme Cleaning"></a>
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
            (
                (
                    "<h1>Acme Cleaning</h1><p>We do not under any circumstances "
                    "at this time offer Free Estimates.</p>"
                ),
                {"existing_ctas": ["Free Estimates"]},
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
            "Free Estimates are not exclusively available to members",
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
                (
                    "<p>If you are a member of our premium annual maintenance club, "
                    "<strong>Free Estimates</strong> are available.</p>"
                ),
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
            (
                "<p><strong>Free Estimates</strong> are available for premium "
                "members only.</p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
            (
                "<p><strong>Free Estimates</strong> are available when you join "
                "the maintenance plan.</p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
            (
                "<p><strong>Free Estimates</strong> are available exclusively to "
                "maintenance-plan members.</p>",
                {"trust_signals": {"social_proof_lines": ["Free Estimates"]}},
            ),
            (
                "<p><strong>Free Estimates</strong> are limited to members.</p>",
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

    def test_claim_text_preserves_except_restrictions(self):
        shortened = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {
                "trust_signals": {"social_proof_lines": ["Free Estimates"]}
            },
        }
        source = (
            "<h1>Acme Cleaning</h1>"
            "<p>Free Estimates are available except to non-members.</p>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "assertion context"):
            validate_site_analysis(shortened, source)

        complete = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {
                "trust_signals": {
                    "social_proof_lines": [
                        "Free Estimates are available except to non-members"
                    ]
                }
            },
        }
        self.assertEqual(validate_site_analysis(complete, source), complete)

    def test_claim_text_preserves_recipient_and_purchase_qualifiers(self):
        shortened = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {
                "trust_signals": {"social_proof_lines": ["Free Estimates"]}
            },
        }
        for complete_claim in (
            "Free Estimates for maintenance-plan members",
            "Free Estimates for seniors",
            "Free Estimates with purchase",
            "Free Estimates are available to members",
            "Free Estimates as part of membership",
            "For seniors, Free Estimates",
            "Maintenance-plan members receive Free Estimates",
            "Seniors get Free Estimates",
            "Members qualify for Free Estimates",
            "Members are offered Free Estimates",
            "Maintenance-plan members are eligible for Free Estimates",
            "Free Estimates apply to maintenance-plan members",
            "Maintenance-plan members redeem Free Estimates",
        ):
            source = f"<h1>Acme Cleaning</h1><p>{complete_claim}.</p>"
            with (
                self.subTest(complete_claim=complete_claim),
                self.assertRaisesRegex(SiteExtractionError, "assertion context"),
            ):
                validate_site_analysis(shortened, source)

            complete = {
                "site": {"name": "Acme Cleaning"},
                "conversion_profile": {
                    "trust_signals": {"social_proof_lines": [complete_claim]}
                },
            }
            self.assertEqual(validate_site_analysis(complete, source), complete)

        for unrestricted_source in (
            "We offer Free Estimates",
            "Call for Free Estimates",
            "Call to request Free Estimates",
            "Free Estimates are easy to request",
        ):
            with self.subTest(unrestricted_source=unrestricted_source):
                self.assertEqual(
                    validate_site_analysis(
                        shortened,
                        f"<h1>Acme Cleaning</h1><p>{unrestricted_source}.</p>",
                    ),
                    shortened,
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

        aria_action = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {"existing_ctas": ["Book Appointment"]},
        }
        for role in ("button", "link"):
            with self.subTest(role=role):
                self.assertEqual(
                    validate_site_analysis(
                        aria_action,
                        (
                            "<h1>Acme Cleaning</h1>"
                            f'<div role="{role}" tabindex="0">Book Appointment</div>'
                        ),
                    ),
                    aria_action,
                )
        with self.assertRaisesRegex(SiteExtractionError, "action label"):
            validate_site_analysis(
                aria_action,
                (
                    "<h1>Acme Cleaning</h1>"
                    '<div tabindex="0">Book Appointment</div>'
                ),
            )

    def test_existing_cta_accepts_button_inputs_but_not_data_inputs(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "conversion_profile": {"existing_ctas": ["Free Estimates"]},
        }
        for input_type in ("button", "image", "reset", "submit"):
            source = (
                "<h1>Acme Cleaning</h1>"
                f'<input type="{input_type}" value="Free Estimates">'
            )
            with self.subTest(input_type=input_type):
                self.assertEqual(validate_site_analysis(document, source), document)

        for input_type in ("hidden", "text"):
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

    def test_action_labels_use_complete_accessible_names_and_replacement_text(self):
        image_action = {
            "site": {"name": "Acme Cleaning"},
            "nav": [{"label": "Contact Us", "url": "/contact"}],
        }
        image_source = (
            '<h1>Acme Cleaning</h1><a href="/contact"><img alt="Contact Us"></a>'
        )
        self.assertEqual(
            validate_site_analysis(image_action, image_source),
            image_action,
        )

        split_name_source = (
            "<h1>Acme Cleaning</h1>"
            '<span id="members">Members Only</span>'
            '<span id="booking">Book Appointment</span>'
            '<a href="/book" aria-labelledby="members booking"></a>'
        )
        incomplete = {
            "site": {"name": "Acme Cleaning"},
            "nav": [{"label": "Book Appointment", "url": "/book"}],
        }
        with self.assertRaisesRegex(SiteExtractionError, "one source action"):
            validate_site_analysis(incomplete, split_name_source)

        complete = copy.deepcopy(incomplete)
        complete["nav"][0]["label"] = "Members Only Book Appointment"
        self.assertEqual(
            validate_site_analysis(complete, split_name_source),
            complete,
        )

        partial_reference_source = (
            "<h1>Acme Cleaning</h1>"
            '<span id="booking">Book Appointment</span>'
            '<a href="/book" aria-labelledby="booking missing" '
            'title="Book Appointment"></a>'
        )
        with self.assertRaisesRegex(SiteExtractionError, "one source action"):
            validate_site_analysis(incomplete, partial_reference_source)

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

    def test_contact_evidence_preserves_assertion_context(self):
        contacts = (
            ("phone", "217-555-0100", "Do not call 217-555-0100"),
            (
                "phone",
                "217-555-0100",
                (
                    'Do not call <a href="tel:217-555-0100">this number</a>. '
                    "Use our main line instead."
                ),
            ),
            ("email", "billing@acme.test", "Do not email billing@acme.test"),
            (
                "email",
                "billing@acme.test",
                'Do not email <a href="mailto:billing@acme.test">this address</a>',
            ),
        )
        for field, value, source_contact in contacts:
            document = {
                "site": {
                    "name": "Acme Cleaning",
                    "contact": {field: value},
                }
            }
            with (
                self.subTest(field=field, source_contact=source_contact),
                self.assertRaisesRegex(SiteExtractionError, f"source {field}"),
            ):
                validate_site_analysis(
                    document,
                    f"<h1>Acme Cleaning</h1><p>{source_contact}</p>",
                )

        positive = {
            "site": {
                "name": "Acme Cleaning",
                "contact": {
                    "phone": "217-555-0100",
                    "email": "billing@acme.test",
                },
            }
        }
        positive_source = (
            "<h1>Acme Cleaning</h1><p>"
            '<a href="tel:217-555-0100">Call us</a> or '
            '<a href="mailto:billing@acme.test">email us</a>.'
            "</p>"
        )
        self.assertEqual(validate_site_analysis(positive, positive_source), positive)

        idiom_source = (
            "<h1>Acme Cleaning</h1><p>Please do not hesitate to call "
            "217-555-0100 or email billing@acme.test.</p>"
        )
        self.assertEqual(validate_site_analysis(positive, idiom_source), positive)

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

    def test_claim_bearing_headline_rejects_question_only_evidence(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "sections": [{"type": "services", "headline": "Free Estimates"}],
        }

        with self.assertRaisesRegex(SiteExtractionError, "assertion context"):
            validate_site_analysis(
                document,
                "<h1>Acme Cleaning</h1><p>Do you offer Free Estimates?</p>",
            )

        full_question = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {"type": "services", "headline": "Do you offer Free Estimates?"}
            ],
        }
        self.assertEqual(
            validate_site_analysis(
                full_question,
                "<h1>Acme Cleaning</h1><p>Do you offer Free Estimates?</p>",
            ),
            full_question,
        )

    def test_source_claim_fields_preserve_nonassertive_context(self):
        cases = (
            (
                {"site": {"name": "Acme Cleaning", "tagline": "Free Estimates"}},
                "<p>Do you offer Free Estimates?</p>",
            ),
            (
                {"site": {"name": "Acme Cleaning", "location": "Effingham"}},
                "<p>Do you serve Effingham?</p>",
            ),
            (
                {
                    "site": {
                        "name": "Acme Cleaning",
                        "contact": {"hours": "Open weekends"},
                    }
                },
                "<p>Are you Open weekends?</p>",
            ),
        )
        for document, source in cases:
            with (
                self.subTest(document=document),
                self.assertRaisesRegex(SiteExtractionError, "assertion context"),
            ):
                validate_site_analysis(
                    document,
                    f"<h1>Acme Cleaning</h1>{source}",
                )

    def test_business_name_requires_assertive_identity_evidence(self):
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Acme Cleaning"}},
                "<p>Are you Acme Cleaning?</p>",
            )

        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Acme Web Design"}},
                ("<h1>Acme Cleaning</h1><footer>Website by Acme Web Design</footer>"),
            )

        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Acme Web Design"}},
                (
                    "<h1>Acme Cleaning</h1><section><h2>Acme Web Design</h2>"
                    "<p>Our website partner.</p></section>"
                ),
            )

        multiple_h1_source = (
            "<title>Acme Cleaning | Home</title><h1>Premium Maintenance Club</h1>"
            "<article><h1>Welcome to Acme Cleaning</h1></article>"
        )
        valid = {"site": {"name": "Acme Cleaning"}}
        self.assertEqual(validate_site_analysis(valid, multiple_h1_source), valid)
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Premium Maintenance Club"}},
                multiple_h1_source,
            )

        page_title_source = "<title>Services | Acme Cleaning</title><h1>Services</h1>"
        self.assertEqual(
            validate_site_analysis(valid, page_title_source),
            valid,
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Services"}},
                page_title_source,
            )

        ambiguous_page_title_source = (
            "<title>Residential Plumbing | Acme Plumbing</title>"
            "<h1>Residential Plumbing</h1>"
        )
        for unverified_name in ("Residential Plumbing", "Acme Plumbing"):
            with (
                self.subTest(unverified_name=unverified_name),
                self.assertRaisesRegex(SiteExtractionError, "identity"),
            ):
                validate_site_analysis(
                    {"site": {"name": unverified_name}},
                    ambiguous_page_title_source,
                )

        explicit_identity_source = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            + ambiguous_page_title_source
        )
        verified_identity = {"site": {"name": "Acme Plumbing"}}
        self.assertEqual(
            validate_site_analysis(verified_identity, explicit_identity_source),
            verified_identity,
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Plumbing"}},
                explicit_identity_source,
            )

        partial_h1_source = (
            '<meta property="og:site_name" content="Acme Plumbing"><h1>Plumbing</h1>'
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Plumbing"}},
                partial_h1_source,
            )

        expanded_h1_source = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            "<h1>Best Acme Plumbing</h1>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Best Acme Plumbing"}},
                expanded_h1_source,
            )

        partial_title_source = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            "<title>Plumbing | Repairs</title><h1>Acme Plumbing</h1>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Plumbing"}},
                partial_title_source,
            )

        canonical_wrapper_source = "<h1>Welcome to Acme Cleaning</h1>"
        self.assertEqual(
            validate_site_analysis(valid, canonical_wrapper_source),
            valid,
        )

        intrinsic_hyphen = {"site": {"name": "Acme-Plumbing"}}
        self.assertEqual(
            validate_site_analysis(intrinsic_hyphen, "<h1>Acme-Plumbing</h1>"),
            intrinsic_hyphen,
        )

        spaced_hyphen_title = "<title>Home - Acme Plumbing</title><h1>Services</h1>"
        self.assertEqual(
            validate_site_analysis(verified_identity, spaced_hyphen_title),
            verified_identity,
        )

        corroborated_wrapper_title = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            "<title>Welcome to Acme Plumbing</title><h1>Services</h1>"
        )
        wrapped_identity = {"site": {"name": "Welcome to Acme Plumbing"}}
        self.assertEqual(
            validate_site_analysis(wrapped_identity, corroborated_wrapper_title),
            wrapped_identity,
        )

        wordpress_identity_source = (
            "<title>Acme Plumbing</title>"
            '<header class="site-identity">'
            "<h1>Acme Plumbing</h1><p>Quality work since 1990</p>"
            "</header>"
        )
        self.assertEqual(
            validate_site_analysis(verified_identity, wordpress_identity_source),
            verified_identity,
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Call Us"}},
                wordpress_identity_source.replace(
                    "<h1>Acme Plumbing</h1>",
                    '<a href="/contact">Call Us</a><h1>Acme Plumbing</h1>',
                ),
            )

        conflicting_single_title_source = (
            '<meta property="og:site_name" content="Acme Plumbing">'
            "<title>Residential Plumbing</title><h1>Acme Plumbing</h1>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Residential Plumbing"}},
                conflicting_single_title_source,
            )
        self.assertEqual(
            validate_site_analysis(verified_identity, conflicting_single_title_source),
            verified_identity,
        )

    def test_pages_to_fetch_derives_fetchability_from_destination(self):
        self.assertTrue(
            same_site_origin("https://acme.test/", "https://www.acme.test/services")
        )
        self.assertFalse(
            same_site_origin("https://acme.test/", "https://partner.test/services")
        )
        document = {
            "site": {"name": "Acme Cleaning"},
            "pages_to_fetch": [
                {
                    "label": "Contact",
                    "url": "https://acme.test/#contact",
                    "page_type": "contact",
                    "priority": 1,
                    "fetchable": True,
                },
                {
                    "label": "Services",
                    "url": "https://acme.test/services",
                    "page_type": "services",
                    "priority": 2,
                    "fetchable": False,
                },
                {
                    "label": "Partner Services",
                    "url": "https://partner.test/services",
                    "page_type": "services",
                    "priority": 3,
                    "fetchable": True,
                },
            ],
        }
        source = (
            "<h1>Acme Cleaning</h1>"
            '<a href="#contact">Contact</a>'
            '<a href="/services">Services</a>'
            '<a href="https://partner.test/services">Partner Services</a>'
        )

        admitted = validate_site_analysis(
            document, source, source_url="https://acme.test/"
        )

        self.assertTrue(document["pages_to_fetch"][0]["fetchable"])
        self.assertFalse(document["pages_to_fetch"][1]["fetchable"])
        self.assertFalse(admitted["pages_to_fetch"][0]["fetchable"])
        self.assertTrue(admitted["pages_to_fetch"][1]["fetchable"])
        self.assertEqual(
            admitted["pages_to_fetch"][1]["url"],
            "https://acme.test/services",
        )
        self.assertFalse(admitted["pages_to_fetch"][2]["fetchable"])

    def test_image_alt_must_belong_to_the_same_image(self):
        source = (
            "<h1>Acme Cleaning</h1>"
            '<img src="/jane.jpg" alt="Jane Doe">'
            '<img src="/john.jpg" alt="John Doe">'
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "images": [
                {
                    "url": "https://acme.test/jane.jpg",
                    "alt": "Jane Doe",
                    "context": "team",
                }
            ],
        }
        self.assertEqual(
            validate_site_analysis(valid, source, "https://acme.test/"), valid
        )

        swapped = {
            **valid,
            "images": [{**valid["images"][0], "alt": "John Doe"}],
        }
        with self.assertRaisesRegex(SiteExtractionError, "same source image"):
            validate_site_analysis(swapped, source, "https://acme.test/")

    def test_picture_source_candidate_uses_its_owned_image_alt(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "images": [
                {
                    "url": "https://acme.test/crew-large.jpg",
                    "alt": "Acme crew",
                    "context": "team",
                }
            ],
        }
        source = (
            "<h1>Acme Cleaning</h1><picture>"
            '<source srcset="/crew-large.jpg 2x">'
            '<img src="/crew-small.jpg" alt="Acme crew">'
            "</picture>"
        )

        self.assertEqual(
            validate_site_analysis(document, source, "https://acme.test/"),
            document,
        )

    def test_brand_logo_requires_logo_role_on_the_owning_image(self):
        source = (
            "<h1>Acme Cleaning</h1>"
            '<img src="/hero.jpg" alt="Cleaning crew">'
            '<a class="navbar-brand"><picture>'
            '<source srcset="/logo-large.png 2x">'
            '<img src="/logo.png" alt="Acme Cleaning">'
            "</picture></a>"
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "brand": {"logo_url": "https://acme.test/logo-large.png"},
        }
        self.assertEqual(
            validate_site_analysis(valid, source, "https://acme.test/"), valid
        )

        invalid = {
            "site": {"name": "Acme Cleaning"},
            "brand": {"logo_url": "https://acme.test/hero.jpg"},
        }
        with self.assertRaisesRegex(SiteExtractionError, "identified as a logo"):
            validate_site_analysis(invalid, source, "https://acme.test/")

        logo_image = {
            "site": {"name": "Acme Cleaning"},
            "images": [
                {
                    "url": "https://acme.test/logo-large.png",
                    "alt": "Acme Cleaning",
                    "context": "logo",
                }
            ],
        }
        self.assertEqual(
            validate_site_analysis(logo_image, source, "https://acme.test/"),
            logo_image,
        )

        false_logo = copy.deepcopy(logo_image)
        false_logo["images"][0] = {
            "url": "https://acme.test/hero.jpg",
            "alt": "Cleaning crew",
            "context": "logo",
        }
        with self.assertRaisesRegex(SiteExtractionError, "identified as a logo"):
            validate_site_analysis(false_logo, source, "https://acme.test/")

        third_party_logo_source = (
            '<h1>Acme Cleaning</h1><img src="/visa.png" alt="Visa logo">'
        )
        with self.assertRaisesRegex(SiteExtractionError, "identified as a logo"):
            validate_site_analysis(
                {
                    "site": {"name": "Acme Cleaning"},
                    "brand": {"logo_url": "https://acme.test/visa.png"},
                },
                third_party_logo_source,
                "https://acme.test/",
            )
        with self.assertRaisesRegex(SiteExtractionError, "identity"):
            validate_site_analysis(
                {"site": {"name": "Visa"}},
                third_party_logo_source,
                "https://acme.test/",
            )

    def test_social_platform_is_bound_to_its_destination(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "social": [
                {
                    "platform": "Facebook",
                    "url": "https://www.instagram.com/acme-cleaning",
                }
            ],
        }
        source = (
            "<h1>Acme Cleaning</h1>"
            '<a href="https://www.instagram.com/acme-cleaning">Instagram</a>'
        )

        admitted = validate_site_analysis(document, source, "https://acme.test/")

        self.assertEqual(document["social"][0]["platform"], "Facebook")
        self.assertEqual(admitted["social"][0]["platform"], "Instagram")

        unknown_destination = {
            "site": {"name": "Acme Cleaning"},
            "social": [
                {
                    "platform": "Invented Network",
                    "url": "https://community.acme.test/profile",
                }
            ],
        }
        with self.assertRaisesRegex(SiteExtractionError, "one source action"):
            validate_site_analysis(
                unknown_destination,
                (
                    "<h1>Acme Cleaning</h1>"
                    '<a href="https://community.acme.test/profile">Mastodon</a>'
                ),
                "https://acme.test/",
            )

    def test_form_fields_require_actual_labeled_controls(self):
        valid = {"form_fields": ["Your Name *", "Email", "Project Type", "Message"]}
        source = """
        <form>
          <label for="name">Your Name *</label><input id="name">
          <label>Email <input type="email"></label>
          <span id="project-label">Project Type</span>
          <select aria-labelledby="project-label"><option>Office</option></select>
          <textarea aria-label="Message"></textarea>
        </form>
        """
        self.assertEqual(
            validate_enrichment_result(
                valid,
                page_type="contact",
                source_html=source,
                source_url="https://acme.test/contact",
            )["form_fields"],
            valid["form_fields"],
        )

        for source in (
            '<img id="email-label" alt="Email"><input aria-labelledby="email-label">',
            '<span id="email-label" aria-label="Email">Wrong</span>'
            '<input aria-labelledby="email-label">',
            '<label for="email"><img alt="Email"></label><input id="email">',
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    validate_enrichment_result(
                        {"form_fields": ["Email"]},
                        page_type="contact",
                        source_html=source,
                        source_url="https://acme.test/contact",
                    )["form_fields"],
                    ["Email"],
                )
                with self.assertRaisesRegex(SiteExtractionError, "complete label"):
                    validate_enrichment_result(
                        {"form_fields": ["Wrong"]},
                        page_type="contact",
                        source_html=source,
                        source_url="https://acme.test/contact",
                    )

        dual_association = {"form_fields": ["Email"]}
        self.assertEqual(
            validate_enrichment_result(
                dual_association,
                page_type="contact",
                source_html=(
                    '<label for="email">Email<input id="email" type="email"></label>'
                ),
                source_url="https://acme.test/contact",
            )["form_fields"],
            dual_association["form_fields"],
        )

        unsupported = {"form_fields": ["Name", "Email"]}
        with self.assertRaisesRegex(SiteExtractionError, "complete label"):
            validate_enrichment_result(
                unsupported,
                page_type="contact",
                source_html=(
                    "<p>Name your project</p><h2>Email</h2>"
                    '<input type="submit" value="Name">'
                    '<input type="hidden" aria-label="Email">'
                ),
                source_url="https://acme.test/contact",
            )

        for document, source_html in (
            (
                {"form_fields": ["Name"]},
                '<label for="referral">Name of referral source</label>'
                '<input id="referral">',
            ),
            (
                {"form_fields": ["Email", "Email"]},
                '<label for="email">Email</label><input id="email">',
            ),
            (
                {"form_fields": ["Referral"]},
                '<span id="ref-kind">Referral</span>'
                '<span id="ref-source">source</span>'
                '<input aria-labelledby="ref-kind ref-source">',
            ),
        ):
            with (
                self.subTest(document=document),
                self.assertRaisesRegex(SiteExtractionError, "complete label"),
            ):
                validate_enrichment_result(
                    document,
                    page_type="contact",
                    source_html=source_html,
                    source_url="https://acme.test/contact",
                )

    def test_image_metadata_admits_only_resource_url_properties(self):
        for property_name in (
            "og:image",
            "og:image:url",
            "og:image:secure_url",
            "twitter:image",
            "twitter:image:src",
        ):
            document = {
                "site": {"name": "Acme"},
                "images": [{"url": "/hero.jpg", "alt": None, "context": "hero"}],
            }
            with self.subTest(property_name=property_name):
                self.assertEqual(
                    validate_site_analysis(
                        document,
                        f'<meta property="{property_name}" content="/hero.jpg">'
                        "<h1>Acme</h1>",
                        "https://acme.test/",
                    ),
                    document,
                )

        for property_name, value in (
            ("og:image:alt", "hero.jpg"),
            ("og:image:width", "1200"),
            ("og:image:type", "image/jpeg"),
        ):
            document = {
                "site": {"name": "Acme"},
                "images": [{"url": value, "alt": None, "context": "hero"}],
            }
            with (
                self.subTest(property_name=property_name),
                self.assertRaisesRegex(SiteExtractionError, "source image URL"),
            ):
                validate_site_analysis(
                    document,
                    f'<meta property="{property_name}" content="{value}">'
                    "<h1>Acme</h1>",
                    "https://acme.test/",
                )

    def test_image_attributes_are_bound_to_image_resources(self):
        document = {
            "site": {"name": "Acme"},
            "images": [{"url": "/tour.mp4", "alt": None, "context": "hero"}],
        }
        for source in (
            '<h1>Acme</h1><video src="/tour.mp4"></video>',
            '<h1>Acme</h1><video><source src="/tour.mp4"></video>',
        ):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(SiteExtractionError, "source image URL"),
            ):
                validate_site_analysis(document, source, "https://acme.test/")

        picture = {
            "site": {"name": "Acme"},
            "images": [{"url": "/hero.webp", "alt": None, "context": "hero"}],
        }
        self.assertEqual(
            validate_site_analysis(
                picture,
                '<h1>Acme</h1><picture><source srcset="/hero.webp">'
                '<img src="/hero.jpg"></picture>',
                "https://acme.test/",
            ),
            picture,
        )

    def test_css_image_evidence_is_bound_to_image_declarations(self):
        font = {
            "site": {"name": "Acme"},
            "images": [{"url": "/brand.woff2", "alt": None, "context": "hero"}],
        }
        with self.assertRaisesRegex(SiteExtractionError, "source image URL"):
            validate_site_analysis(
                font,
                '<style>@font-face { src: url("/brand.woff2") }</style><h1>Acme</h1>',
                "https://acme.test/",
            )

        hero = {
            "site": {"name": "Acme"},
            "images": [{"url": "/hero.jpg", "alt": None, "context": "hero"}],
        }
        self.assertEqual(
            validate_site_analysis(
                hero,
                '<style>.hero { background-image: url("/hero.jpg") }</style>'
                "<h1>Acme</h1>",
                "https://acme.test/",
            ),
            hero,
        )

    def test_image_metadata_pairs_alt_with_its_resource(self):
        document = {
            "site": {"name": "Acme"},
            "images": [
                {
                    "url": "/hero.jpg",
                    "alt": "Technician at work",
                    "context": "hero",
                }
            ],
        }
        source = (
            '<meta property="og:image" content="/hero.jpg">'
            '<meta property="og:image:alt" content="Technician at work">'
            "<h1>Acme</h1>"
        )
        self.assertEqual(
            validate_site_analysis(document, source, "https://acme.test/"),
            document,
        )

        mismatched = copy.deepcopy(document)
        mismatched["images"][0]["alt"] = "Different technician"
        with self.assertRaisesRegex(SiteExtractionError, "same source image"):
            validate_site_analysis(mismatched, source, "https://acme.test/")

    def test_ignored_source_containers_cannot_authorize_visible_meaning(self):
        claim = {"site": {"name": "Acme", "tagline": "Free Estimates"}}
        for hidden_claim in (
            "<h1>Acme</h1><template><div>Free Estimates</div></template>",
            "<h1>Acme</h1><div hidden>Free Estimates</div>",
            '<h1>Acme</h1><div style="display: none !important">Free Estimates</div>',
        ):
            with (
                self.subTest(hidden_claim=hidden_claim),
                self.assertRaisesRegex(SiteExtractionError, "site.tagline"),
            ):
                validate_site_analysis(claim, hidden_claim, "https://acme.test/")
        self.assertEqual(
            validate_site_analysis(
                claim,
                "<h1>Acme</h1><div>Free Estimates</div>",
                "https://acme.test/",
            ),
            claim,
        )

        hidden_action = (
            "<h1>Acme</h1>"
            '<template><a href="/book">Book Appointment</a></template>'
        )
        action = {
            "site": {"name": "Acme"},
            "cta": {"label": "Book Appointment", "url": "/book"},
        }
        with self.assertRaisesRegex(SiteExtractionError, "cta"):
            validate_site_analysis(action, hidden_action, "https://acme.test/")
        self.assertEqual(
            validate_site_analysis(
                action,
                '<h1>Acme</h1><a href="/book">Book Appointment</a>',
                "https://acme.test/",
            ),
            action,
        )

        with self.assertRaisesRegex(SiteExtractionError, "complete label"):
            validate_enrichment_result(
                {"form_fields": ["Email"]},
                page_type="contact",
                source_html="<template><label>Email<input></label></template>",
                source_url="https://acme.test/contact",
            )
        form_fields = {"form_fields": ["Email"]}
        self.assertEqual(
            validate_enrichment_result(
                form_fields,
                page_type="contact",
                source_html="<label>Email<input></label>",
                source_url="https://acme.test/contact",
            ),
            {
                "form_fields": ["Email"],
                "source_url": "https://acme.test/contact",
            },
        )

    def test_code_owned_image_inventory_remains_admissible(self):
        image_url = "https://cdn.acme.test/hero.jpg"
        document = {
            "site": {"name": "Acme"},
            "images": [{"url": image_url, "alt": None, "context": "hero"}],
        }
        source = (
            '<template data-code-owned-image-inventory="true">'
            f'<img src="{image_url}">'
            "</template><h1>Acme</h1>"
        )

        self.assertEqual(
            validate_site_analysis(document, source, "https://acme.test/"),
            document,
        )

    def test_article_record_does_not_span_nested_content_cards(self):
        document = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {
                    "type": "services",
                    "items": [
                        {
                            "title": "Plumbing",
                            "description": "Electrical repairs",
                        }
                    ],
                }
            ],
        }
        source = (
            "<h1>Acme Cleaning</h1><article><h1>Services</h1>"
            "<div><strong>Plumbing</strong><p>Pipe repairs</p></div>"
            "<div><strong>Electrical</strong><p>Electrical repairs</p></div>"
            "</article>"
        )

        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_site_analysis(document, source)

    def test_parent_list_item_does_not_span_nested_list_records(self):
        source = (
            "<h1>Acme Cleaning</h1><ul><li><ul>"
            "<li><strong>Plumbing</strong><p>Pipe repairs</p></li>"
            "<li><strong>Electrical</strong><p>Electrical repairs</p></li>"
            "</ul></li></ul>"
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {
                    "type": "services",
                    "items": [{"title": "Plumbing", "description": "Pipe repairs"}],
                }
            ],
        }
        self.assertEqual(validate_site_analysis(valid, source), valid)

        mixed = copy.deepcopy(valid)
        mixed["sections"][0]["items"][0]["description"] = "Electrical repairs"
        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_site_analysis(mixed, source)

    def test_definition_list_records_do_not_span_terms(self):
        source = (
            "<h1>Acme Cleaning</h1><article><h1>FAQ</h1><dl>"
            "<dt>Do you offer weekend service?</dt><dd>No weekend service.</dd>"
            "<dt>Do you offer evening service?</dt><dd>Evening service is available.</dd>"
            "</dl></article>"
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {
                    "type": "faq",
                    "items": [
                        {
                            "title": "Do you offer weekend service?",
                            "description": "No weekend service.",
                        }
                    ],
                }
            ],
        }
        self.assertEqual(validate_site_analysis(valid, source), valid)

        mixed = copy.deepcopy(valid)
        mixed["sections"][0]["items"][0]["description"] = (
            "Evening service is available."
        )
        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_site_analysis(mixed, source)

    def test_figure_records_do_not_span_cards(self):
        source = (
            "<h1>Acme Cleaning</h1><section><h2>Our Team</h2>"
            '<figure><img src="/jane.jpg" alt="Jane"><figcaption>Jane</figcaption>'
            "<p>Operations Manager</p></figure>"
            '<figure><img src="/john.jpg" alt="John"><figcaption>John</figcaption>'
            "<p>Field Manager</p></figure></section>"
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {
                    "type": "team",
                    "items": [
                        {
                            "title": "Jane",
                            "description": "Operations Manager",
                            "image_url": "/jane.jpg",
                        }
                    ],
                }
            ],
        }
        self.assertEqual(validate_site_analysis(valid, source), valid)

        mixed = copy.deepcopy(valid)
        mixed["sections"][0]["items"][0]["image_url"] = "/john.jpg"
        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_site_analysis(mixed, source)

    def test_section_headline_and_items_share_one_source_section(self):
        source = (
            "<h1>Acme Cleaning</h1>"
            "<section><h2>Cleaning Services</h2>"
            "<article><h3>Office Cleaning</h3><p>Nightly service.</p></article>"
            "</section>"
            "<section><h2>Our Team</h2>"
            "<article><h3>Jane Doe</h3><p>Operations Manager</p></article>"
            "</section>"
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "sections": [
                {
                    "type": "services",
                    "headline": "Cleaning Services",
                    "items": [
                        {
                            "title": "Office Cleaning",
                            "description": "Nightly service.",
                        }
                    ],
                }
            ],
        }
        self.assertEqual(validate_site_analysis(valid, source), valid)

        mismatched = copy.deepcopy(valid)
        mismatched["sections"][0]["headline"] = "Our Team"
        with self.assertRaisesRegex(SiteExtractionError, "one source section"):
            validate_site_analysis(mismatched, source)

        structural_siblings = (
            "<h1>Acme Cleaning</h1><h2>Our Team</h2>"
            "<section><h3>Jane Doe</h3><p>Operations Manager</p></section>"
            "<section><h3>Office Cleaning</h3><p>Nightly service.</p></section>"
        )
        structural_mismatch = copy.deepcopy(valid)
        structural_mismatch["sections"][0]["headline"] = "Our Team"
        with self.assertRaisesRegex(SiteExtractionError, "one source section"):
            validate_site_analysis(structural_mismatch, structural_siblings)

        nested_sections = (
            "<h1>Acme Cleaning</h1><article>"
            "<section><h2>Our Team</h2><h3>Jane Doe</h3>"
            "<p>Operations Manager</p></section>"
            "<section><h2>Cleaning Services</h2><h3>Office Cleaning</h3>"
            "<p>Nightly service.</p></section></article>"
        )
        nested_mismatch = copy.deepcopy(valid)
        nested_mismatch["sections"][0]["headline"] = "Our Team"
        with self.assertRaisesRegex(SiteExtractionError, "one source section"):
            validate_site_analysis(nested_mismatch, nested_sections)

        nested_articles = (
            "<h1>Acme Cleaning</h1><section>"
            "<article><h2>Our Team</h2><h3>Jane Doe</h3>"
            "<p>Operations Manager</p></article>"
            "<article><h2>Cleaning Services</h2><h3>Office Cleaning</h3>"
            "<p>Nightly service.</p></article></section>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "one source section"):
            validate_site_analysis(nested_mismatch, nested_articles)

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

        heading_target_source = (
            "<h1>Acme Cleaning</h1><nav>"
            '<a href="#about-heading">About</a>'
            '<a href="#contact-heading">Contact</a></nav>'
            '<h2 id="about-heading">About Us</h2><p>Family owned.</p>'
            '<h2 id="contact-heading">Contact Us</h2><p>Call today.</p>'
        )
        heading_target = copy.deepcopy(valid)
        heading_target["single_page_sections"][0]["anchor"] = "#about-heading"
        self.assertEqual(
            validate_site_analysis(heading_target, heading_target_source),
            heading_target,
        )
        heading_target["single_page_sections"][0]["content"] = {
            "headline": "About Us",
            "body_text": "Call today.",
        }
        with self.assertRaisesRegex(SiteExtractionError, "source text"):
            validate_site_analysis(heading_target, heading_target_source)

        nested_heading_source = (
            "<h1>Acme Cleaning</h1><nav>"
            '<a href="#about-nested">About</a></nav>'
            '<h2 id="about-nested">About Us</h2><div>Family owned.</div>'
            "<div><h2>Contact Us</h2><p>Call today.</p></div>"
        )
        nested_heading_target = copy.deepcopy(valid)
        nested_heading_target["single_page_sections"][0]["anchor"] = "#about-nested"
        self.assertEqual(
            validate_site_analysis(nested_heading_target, nested_heading_source),
            nested_heading_target,
        )
        nested_heading_target["single_page_sections"][0]["content"] = {
            "headline": "About Us",
            "body_text": "Call today.",
        }
        with self.assertRaisesRegex(SiteExtractionError, "source text"):
            validate_site_analysis(nested_heading_target, nested_heading_source)

    def test_single_page_section_without_anchor_uses_one_heading_owned_scope(self):
        source = (
            "<h1>Acme Cleaning</h1><nav><button>About</button>"
            "<button>Contact</button></nav>"
            "<section><h2>About Us</h2><p>Family owned.</p></section>"
            "<section><h2>Contact Us</h2><p>Call today.</p></section>"
        )
        valid = {
            "site": {"name": "Acme Cleaning"},
            "single_page_sections": [
                {
                    "nav_label": "About",
                    "anchor": None,
                    "page_type": "about",
                    "content": {"headline": "About Us", "body_text": "Family owned."},
                }
            ],
        }
        self.assertEqual(validate_site_analysis(valid, source), valid)

        mismatched = copy.deepcopy(valid)
        mismatched["single_page_sections"][0]["content"] = {
            "headline": "Contact Us",
            "body_text": "Call today.",
        }
        with self.assertRaisesRegex(SiteExtractionError, "one source section"):
            validate_site_analysis(mismatched, source)

        empty = copy.deepcopy(valid)
        empty["single_page_sections"][0].pop("content")
        with self.assertRaisesRegex(SiteExtractionError, "no anchor or content"):
            validate_site_analysis(empty, source)

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

    def test_cta_requires_a_complete_source_action_pair(self):
        source = (
            "<h1>Acme Cleaning</h1>"
            '<a href="/contact">Contact Us</a>'
            '<a href="https://partner.test">Partner</a>'
        )
        for partial_cta in (
            {"label": None, "url": "https://partner.test"},
            {"label": "Contact Us", "url": None},
        ):
            with (
                self.subTest(partial_cta=partial_cta),
                self.assertRaisesRegex(SiteExtractionError, "both be source-owned"),
            ):
                validate_site_analysis(
                    {"site": {"name": "Acme Cleaning"}, "cta": partial_cta},
                    source,
                    "https://acme.test/",
                )

        complete = {
            "site": {"name": "Acme Cleaning"},
            "cta": {"label": "Contact Us", "url": "https://acme.test/contact"},
        }
        self.assertEqual(
            validate_site_analysis(complete, source, "https://acme.test/"),
            complete,
        )
        empty = {
            "site": {"name": "Acme Cleaning"},
            "cta": {"label": None, "url": None},
        }
        self.assertEqual(
            validate_site_analysis(empty, source, "https://acme.test/"),
            empty,
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
                "conversion_profile": {"existing_ctas": ["Request a Quote"]},
            },
            pipeline._redesign_contact_contract({}),
            source_content=(
                '<a href="/source-link">Source</a>'
                '<a href="/image-action">Schedule <img alt="Visit"></a>'
                '<form action="/submit"><input type="submit" value="Submit">'
                '<input type="image" alt="Pay Now" formaction="/pay"></form>'
                '<span id="members-label">Members Only</span>'
                '<a href="/aria-action" aria-labelledby="members-label image-label"></a>'
                '<img id="image-label" alt="Book Appointment">'
                '<form id="external-form" action="/external"></form>'
                '<button form="external-form">External</button>'
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
                "/image-action",
                "/aria-action",
            ),
        )
        self.assertEqual(
            contract.allowed_form_urls,
            ("/submit", "/pay", "/external"),
        )
        self.assertEqual(
            contract.allowed_labels,
            (
                "Acme Cleaning",
                "Contact",
                "Book",
                "Office",
                "Facebook",
                "Privacy",
                "About",
                "Jane",
                "Request a Quote",
                "Source",
                "Schedule Visit",
                "Submit",
                "Pay Now",
                "Members Only Book Appointment",
                "External",
            ),
        )
        self.assertEqual(
            contract.allowed_pairs,
            (
                ("Contact", "/contact"),
                ("Book", "/book"),
                ("Office", "/services/office"),
                ("Facebook", "/facebook"),
                ("Privacy", "/privacy"),
                ("About", "/about"),
                ("Jane", "/jane"),
                ("Source", "/source-link"),
                ("Schedule Visit", "/image-action"),
                ("Submit", "/submit"),
                ("Pay Now", "/pay"),
                ("Members Only Book Appointment", "/aria-action"),
                ("External", "/external"),
            ),
        )

    def test_generation_action_contract_excludes_inert_source_actions(self):
        contract = pipeline._redesign_action_url_contract(
            {"site": {"name": "Acme Cleaning"}},
            pipeline._redesign_contact_contract({}),
            source_content=(
                '<template><a href="/hidden">Book Appointment</a>'
                '<form action="/hidden-form"><button>Send</button></form></template>'
                '<noscript><a href="/fallback">Fallback</a></noscript>'
                '<a hidden href="/hidden-attribute">Hidden</a>'
                '<form style="display:none" action="/hidden-style"></form>'
            ),
        )

        self.assertEqual(contract.allowed_urls, ())
        self.assertEqual(contract.allowed_form_urls, ())
        self.assertEqual(contract.allowed_labels, ("Acme Cleaning",))
        self.assertEqual(contract.allowed_pairs, ())

    def test_inert_formaction_attributes_do_not_create_source_authority(self):
        contract = pipeline._redesign_action_url_contract(
            {"site": {"name": "Acme Cleaning"}},
            pipeline._redesign_contact_contract({}),
            source_content=(
                '<button type="button" formaction="/inert">Inert</button>'
                '<input type="image" formaction="/orphan" alt="Orphan">'
            ),
        )

        self.assertEqual(contract.allowed_urls, ())
        self.assertEqual(contract.allowed_pairs, ())

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
        <section><h1>Cleaning Services</h1>
        <article><h2>Office Cleaning</h2><span>Commercial</span>
        <p>Nightly and weekly office cleaning.</p>
        <a href="/services/office">Learn more</a>
        <img src="/office.jpg"></article></section>
        """

        admitted = validate_enrichment_result(
            document,
            page_type="services",
            source_html=html,
            source_url=source_url,
        )

        self.assertEqual(admitted["source_url"], source_url)
        self.assertEqual(document["source_url"], "https://attacker.test/spoofed")

    def test_content_enrichment_headline_and_items_share_one_source_section(self):
        document = {
            "type": "services",
            "headline": "Residential Cleaning",
            "items": [
                {
                    "title": "Office Cleaning",
                    "url": None,
                    "image_url": None,
                    "tag": "Commercial",
                    "meta": "Nightly service.",
                }
            ],
        }
        source = (
            "<section><h2>Residential Cleaning</h2><p>Home care.</p></section>"
            "<section><h2>Commercial Cleaning</h2><article>"
            "<h3>Office Cleaning</h3><span>Commercial</span>"
            "<p>Nightly service.</p></article></section>"
        )

        with self.assertRaisesRegex(SiteExtractionError, "share one source section"):
            validate_enrichment_result(
                document,
                page_type="services",
                source_html=source,
                source_url="https://acme.test/services",
            )

    def test_main_h1_owns_main_only_enrichment_content(self):
        document = {
            "type": "services",
            "headline": "Plumbing Services",
            "items": [
                {
                    "title": "Drain Cleaning",
                    "url": None,
                    "image_url": None,
                    "tag": None,
                    "meta": "Clears stubborn clogs.",
                }
            ],
        }
        source_url = "https://acme.test/services"
        main_only = (
            "<main><h1>Plumbing Services</h1><div>"
            "<h2>Drain Cleaning</h2><p>Clears stubborn clogs.</p>"
            "</div></main>"
        )
        self.assertEqual(
            validate_enrichment_result(
                document,
                page_type="services",
                source_html=main_only,
                source_url=source_url,
            ),
            {**document, "source_url": source_url},
        )

        split_sections = (
            "<main><h1>Plumbing Services</h1>"
            "<section><h2>Drain Cleaning</h2><p>Basic service.</p></section>"
            "<section><h2>Water Heater Repair</h2>"
            "<p>Clears stubborn clogs.</p></section></main>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "share one source section"):
            validate_enrichment_result(
                document,
                page_type="services",
                source_html=split_sections,
                source_url=source_url,
            )

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

        with self.assertRaisesRegex(SiteExtractionError, "share one source section"):
            validate_enrichment_result(
                document,
                page_type="team",
                source_html=(
                    "<section><h1>Our Team</h1><h2>Jane Doe</h2><p>Manager</p>"
                    "<p>Leads the cleaning team.</p></section>"
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

    def test_faq_titles_preserve_the_complete_source_question(self):
        def document(title):
            return {
                "type": "misc",
                "headline": "FAQ",
                "items": [
                    {
                        "title": title,
                        "url": None,
                        "image_url": None,
                        "tag": "faq",
                        "meta": None,
                    }
                ],
            }

        source = "<h1>FAQ</h1><h2>Do you offer Free Estimates?</h2><p>No.</p>"
        with self.assertRaisesRegex(SiteExtractionError, "complete text"):
            validate_enrichment_result(
                document("Free Estimates"),
                page_type="faq",
                source_html=source,
                source_url="https://acme.test/faq",
            )
        self.assertEqual(
            validate_enrichment_result(
                document("Do you offer Free Estimates?"),
                page_type="faq",
                source_html=source,
                source_url="https://acme.test/faq",
            )["items"],
            document("Do you offer Free Estimates?")["items"],
        )

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

    def test_nested_atomic_records_cannot_authorize_cross_record_items(self):
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
        nested_details = (
            "<h1>Frequently Asked Questions</h1>"
            "<details><summary>Questions</summary>"
            "<details><summary>Do you offer free estimates?</summary>"
            "<p>No.</p></details>"
            "<details><summary>Do you offer recurring service?</summary>"
            "<p>Yes.</p></details></details>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_enrichment_result(
                document,
                page_type="faq",
                source_html=nested_details,
                source_url="https://acme.test/questions",
            )

        mixed_record_types = (
            "<h1>Frequently Asked Questions</h1><details>"
            "<article><h2>Do you offer free estimates?</h2><p>No.</p></article>"
            "<article><h2>Do you offer recurring service?</h2><p>Yes.</p></article>"
            "</details>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "one source container"):
            validate_enrichment_result(
                document,
                page_type="faq",
                source_html=mixed_record_types,
                source_url="https://acme.test/questions",
            )

        valid_details = (
            "<h1>Frequently Asked Questions</h1>"
            "<details><summary>Do you offer free estimates?</summary>"
            "<p>Yes.</p></details>"
        )
        self.assertEqual(
            validate_enrichment_result(
                document,
                page_type="faq",
                source_html=valid_details,
                source_url="https://acme.test/questions",
            )["items"],
            document["items"],
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

    def test_heading_record_stops_at_nested_heading_in_sibling_wrapper(self):
        document = {
            "type": "services",
            "headline": "Plumbing Services",
            "items": [
                {
                    "title": "Drain Cleaning",
                    "url": None,
                    "image_url": None,
                    "tag": None,
                    "meta": "Includes a warranty.",
                }
            ],
        }
        split_records = (
            "<section><h1>Plumbing Services</h1><h2>Drain Cleaning</h2>"
            "<aside><h2>Water Heater Repair</h2>"
            "<p>Includes a warranty.</p></aside></section>"
        )
        with self.assertRaisesRegex(SiteExtractionError, "share one source section"):
            validate_enrichment_result(
                document,
                page_type="services",
                source_html=split_records,
                source_url="https://acme.test/services",
            )

        one_record = (
            "<section><h1>Plumbing Services</h1><h2>Drain Cleaning</h2>"
            "<aside><p>Includes a warranty.</p></aside></section>"
        )
        self.assertEqual(
            validate_enrichment_result(
                document,
                page_type="services",
                source_html=one_record,
                source_url="https://acme.test/services",
            ),
            {**document, "source_url": "https://acme.test/services"},
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

    def test_pipeline_skips_enrichment_redirected_off_source_site(self):
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

        with (
            patch.object(
                pipeline,
                "fetch_and_clean_html",
                return_value=(
                    "<section><h1>Partner Services</h1></section>",
                    "https://partner.test/services",
                ),
            ),
            patch.object(pipeline, "get_openrouter_client") as client,
        ):
            returned = pipeline.enrich_site_json(site_json)

        self.assertIs(returned, site_json)
        self.assertEqual(site_json["sections"], [])
        client.assert_not_called()

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

    def test_fetch_enforces_secondary_page_redirect_origin(self):
        response = SimpleNamespace(
            text="<html><body><p>Partner page</p></body></html>",
            url="https://partner.test/contact",
            raise_for_status=lambda: None,
        )

        with (
            patch.object(pipeline.requests, "get", return_value=response),
            patch.object(pipeline, "_fetch_with_playwright", return_value=None),
            self.assertRaisesRegex(ValueError, "required source origin"),
        ):
            pipeline.fetch_and_clean_html(
                "https://acme.test/contact",
                required_origin="https://acme.test/contact",
            )

        response.url = "https://www.acme.test/contact"
        with (
            patch.object(pipeline.requests, "get", return_value=response),
            patch.object(pipeline, "_fetch_with_playwright", return_value=None),
        ):
            cleaned = pipeline.fetch_and_clean_html(
                "https://acme.test/contact",
                required_origin="https://acme.test/contact",
            )
        self.assertIn("Partner page", cleaned)

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
        interior_prompt = Path("references/04-interior-page-prompt.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("SOURCE AUTHORITY BOUNDARY", prompt)
        self.assertIn("Urgency controls CTA layout and relative emphasis only", prompt)
        self.assertNotIn("A response-time / availability promise tied", prompt)
        self.assertNotIn('"Call Now -- We Answer 24/7"', prompt)
        self.assertNotIn('"Get My Free Quote"', prompt)
        self.assertNotIn('"Request My Quote" not "Submit"', prompt)
        self.assertNotIn('"Schedule a Visit"', prompt)
        self.assertIn("Capability-bearing CTA text must exactly copy", prompt)
        self.assertIn("use capability-neutral source wording", prompt)
        self.assertNotIn("Build the headline from `site.type`", prompt)
        self.assertIn("do not substitute `site.type` as", prompt)
        self.assertNotIn("Every redesign includes a trust strip", prompt)
        self.assertIn("If none of the source-owned values above exists, omit", prompt)
        self.assertNotIn('Hours + "Order Online" or "Reserve" button', interior_prompt)
        self.assertNotIn('"Get My Free Quote"', interior_prompt)
        self.assertIn("copy an admitted source action label", interior_prompt)
        self.assertIn("do not infer", interior_prompt)


if __name__ == "__main__":
    unittest.main()
