import os
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build
import pipeline
import lib.clients
from lib.generation import (
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_MODEL,
    MAX_HTML_BYTES,
    GeneratedHtmlError,
    GenerationConfig,
    GenerationConfigurationError,
    GenerationProviderUnavailable,
    GenerationResponseError,
    GenerationResult,
    PromptPart,
    atomic_write_text,
    generate_text,
    preflight_generation_provider,
    resolve_generation_config,
    validate_generated_html,
)


COMPLETE_HTML = """<!DOCTYPE html>
<html lang="en"><head><title>Test</title></head>
<body><main>Ready</main></body></html>"""


class FakeModels:
    def __init__(self, model_ids=None, error=None):
        self.model_ids = model_ids or []
        self.error = error

    def list(self):
        if self.error:
            raise self.error
        return SimpleNamespace(
            data=[SimpleNamespace(id=model_id) for model_id in self.model_ids]
        )


class FakeCompletions:
    def __init__(self, content=COMPLETE_HTML, finish_reason="stop"):
        self.content = content
        self.finish_reason = finish_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                    finish_reason=self.finish_reason,
                )
            ],
            usage=SimpleNamespace(
                model_dump=lambda: {"prompt_tokens": 12, "completion_tokens": 8}
            ),
        )


class FakeClient:
    def __init__(
        self,
        *,
        model_ids=None,
        model_error=None,
        content=COMPLETE_HTML,
        finish_reason="stop",
    ):
        self.models = FakeModels(model_ids, model_error)
        self.completions = FakeCompletions(content, finish_reason)
        self.chat = SimpleNamespace(completions=self.completions)


def config(provider="local", model=DEFAULT_LOCAL_MODEL):
    return GenerationConfig(
        provider=provider,
        model=model,
        base_url=DEFAULT_LOCAL_BASE_URL,
        api_key="test-key",
    )


def result(content=COMPLETE_HTML, finish_reason="stop"):
    return GenerationResult(
        provider="local",
        model=DEFAULT_LOCAL_MODEL,
        content=content,
        finish_reason=finish_reason,
        usage={},
    )


class GenerationConfigTests(unittest.TestCase):
    def test_local_is_default_with_qwen_model(self):
        with patch.dict(os.environ, {}, clear=True):
            selected = resolve_generation_config()

        self.assertEqual(selected.provider, "local")
        self.assertEqual(selected.model, DEFAULT_LOCAL_MODEL)
        self.assertEqual(selected.base_url, DEFAULT_LOCAL_BASE_URL)

    def test_local_explicit_model_wins_over_environment(self):
        with patch.dict(os.environ, {"LOCAL_GENERATION_MODEL": "local/from-env"}, clear=True):
            selected = resolve_generation_config("local", "local/from-cli")

        self.assertEqual(selected.model, "local/from-cli")

    def test_legacy_lm_studio_endpoint_alias_remains_supported(self):
        with patch.dict(
            os.environ,
            {
                "LM_STUDIO_BASE_URL": "http://127.0.0.1:4321/v1",
                "LM_STUDIO_API_KEY": "legacy-key",
            },
            clear=True,
        ):
            selected = resolve_generation_config()

        self.assertEqual(selected.base_url, "http://127.0.0.1:4321/v1")
        self.assertEqual(selected.api_key, "legacy-key")

    def test_openrouter_requires_model_even_when_selected(self):
        with patch("lib.generation.OPENROUTER_API_KEY", "configured"):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    GenerationConfigurationError, "requires --generation-model"
                ):
                    resolve_generation_config("openrouter")

    def test_openrouter_requires_key(self):
        with patch("lib.generation.OPENROUTER_API_KEY", None):
            with self.assertRaisesRegex(
                GenerationConfigurationError, "OPENROUTER_API_KEY"
            ):
                resolve_generation_config("openrouter", "anthropic/example")

    def test_zero_output_token_limit_is_rejected(self):
        with patch.dict(
            os.environ, {"GENERATION_MAX_OUTPUT_TOKENS": "0"}, clear=True
        ):
            with self.assertRaisesRegex(
                GenerationConfigurationError, "greater than zero"
            ):
                resolve_generation_config()


class ProviderBoundaryTests(unittest.TestCase):
    def test_client_configuration_import_has_no_network_or_client_side_effect(self):
        with patch("requests.get") as http_get, patch("openai.OpenAI") as openai:
            importlib.reload(lib.clients)

        http_get.assert_not_called()
        openai.assert_not_called()

    def test_local_preflight_accepts_exact_loaded_model(self):
        selected = config()
        client = FakeClient(model_ids=[selected.model])

        preflight_generation_provider(selected, client=client)

    def test_local_preflight_rejects_missing_model_with_load_instruction(self):
        selected = config()
        client = FakeClient(model_ids=["some/other-model"])

        with self.assertRaisesRegex(
            GenerationProviderUnavailable, f"lms load {selected.model}"
        ):
            preflight_generation_provider(selected, client=client)

    def test_local_preflight_translates_connection_failure(self):
        selected = config()
        client = FakeClient(model_error=ConnectionError("offline"))

        with self.assertRaisesRegex(
            GenerationProviderUnavailable, "Start LM Studio"
        ):
            preflight_generation_provider(selected, client=client)

    def test_local_request_uses_plain_content_without_cloud_cache_metadata(self):
        client = FakeClient()

        generated = generate_text(
            config(),
            system_prompt="system",
            user_parts=(
                PromptPart("static", cacheable=True),
                PromptPart("variable"),
            ),
            temperature=0.4,
            cache_system_prompt=True,
            client=client,
        )

        call = client.completions.calls[0]
        self.assertEqual(call["messages"][0]["content"], "system")
        self.assertEqual(call["messages"][1]["content"], "static\n\nvariable")
        self.assertNotIn("cache_control", str(call["messages"]))
        self.assertEqual(generated.finish_reason, "stop")

    def test_openrouter_request_keeps_cache_metadata(self):
        client = FakeClient()

        generate_text(
            config("openrouter", "anthropic/example"),
            system_prompt="system",
            user_parts=(PromptPart("static", cacheable=True), PromptPart("variable")),
            temperature=0.4,
            cache_system_prompt=True,
            client=client,
        )

        call = client.completions.calls[0]
        self.assertEqual(
            call["messages"][0]["content"][0]["cache_control"],
            {"type": "ephemeral"},
        )
        self.assertEqual(
            call["messages"][1]["content"][0]["cache_control"],
            {"type": "ephemeral"},
        )
        self.assertNotIn("cache_control", call["messages"][1]["content"][1])


class HtmlAdmissionTests(unittest.TestCase):
    def test_complete_html_is_accepted(self):
        self.assertEqual(validate_generated_html(result()), COMPLETE_HTML)

    def test_single_outer_html_fence_is_removed(self):
        fenced = f"```html\n{COMPLETE_HTML}\n```"
        self.assertEqual(validate_generated_html(result(fenced)), COMPLETE_HTML)

    def test_inner_fence_is_rejected(self):
        unsafe = COMPLETE_HTML.replace("Ready", "```Ready```")
        with self.assertRaisesRegex(GeneratedHtmlError, "code fence"):
            validate_generated_html(result(unsafe))

    def test_length_finish_is_rejected_even_when_tags_are_present(self):
        with self.assertRaisesRegex(GenerationResponseError, "finish_reason=length"):
            validate_generated_html(result(finish_reason="length"))

    def test_missing_finish_reason_is_rejected(self):
        with self.assertRaisesRegex(GenerationResponseError, "finish_reason=missing"):
            validate_generated_html(result(finish_reason=None))

    def test_partial_html_is_rejected(self):
        partial = "<!DOCTYPE html><html><head></head><body>unfinished"
        with self.assertRaisesRegex(GeneratedHtmlError, "structurally invalid"):
            validate_generated_html(result(partial))

    def test_doctype_after_html_is_rejected(self):
        wrong_order = (
            "<html><!DOCTYPE html><head></head><body></body></html>"
        )
        with self.assertRaises(GeneratedHtmlError):
            validate_generated_html(result(wrong_order))

    def test_closing_tags_inside_script_do_not_satisfy_document_structure(self):
        disguised_partial = (
            "<!DOCTYPE html><html><head></head><body>"
            "<script>const fake = '</body></html>';</script>"
        )
        with self.assertRaisesRegex(GeneratedHtmlError, "structurally invalid"):
            validate_generated_html(result(disguised_partial))

    def test_trailing_provider_chatter_is_rejected(self):
        with self.assertRaisesRegex(GeneratedHtmlError, "after </html>"):
            validate_generated_html(result(COMPLETE_HTML + "\nFinished."))

    def test_leading_provider_chatter_is_rejected(self):
        with self.assertRaisesRegex(GeneratedHtmlError, "begin with the HTML doctype"):
            validate_generated_html(result("Finished.\n" + COMPLETE_HTML))

    def test_provider_chatter_between_doctype_and_html_is_rejected(self):
        chatter = COMPLETE_HTML.replace(
            "<!DOCTYPE html>",
            "<!DOCTYPE html>Here is your site:",
            1,
        )
        with self.assertRaisesRegex(GeneratedHtmlError, "immediately after"):
            validate_generated_html(result(chatter))

    def test_only_whitespace_may_separate_doctype_and_html(self):
        separated = COMPLETE_HTML.replace(
            "<!DOCTYPE html>",
            "<!DOCTYPE html>\n  ",
            1,
        )
        self.assertEqual(validate_generated_html(result(separated)), separated)

    def test_provider_chatter_outside_head_or_body_is_rejected(self):
        invalid_documents = {
            "before head": COMPLETE_HTML.replace(
                '<html lang="en">',
                '<html lang="en">Finished.',
                1,
            ),
            "between head and body": COMPLETE_HTML.replace(
                "</head>",
                "</head>Finished.",
                1,
            ),
            "after body": COMPLETE_HTML.replace(
                "</body>",
                "</body>Finished.",
                1,
            ),
        }
        for position, document in invalid_documents.items():
            with self.subTest(position=position):
                with self.assertRaisesRegex(GeneratedHtmlError, "outside head or body"):
                    validate_generated_html(result(document))

    def test_elements_outside_head_or_body_are_rejected(self):
        invalid_documents = {
            "before head": COMPLETE_HTML.replace(
                '<html lang="en">',
                '<html lang="en"><meta name="outside" content="bad">',
                1,
            ),
            "between head and body": COMPLETE_HTML.replace(
                "</head>",
                '</head><img src="tracking.gif" alt="">',
                1,
            ),
            "after body": COMPLETE_HTML.replace(
                "</body>",
                '</body><input value="Finished">',
                1,
            ),
        }
        for position, document in invalid_documents.items():
            with self.subTest(position=position):
                with self.assertRaisesRegex(GeneratedHtmlError, "outside head or body"):
                    validate_generated_html(result(document))

    def test_deployment_comment_inside_head_is_accepted(self):
        documented = COMPLETE_HTML.replace(
            "<head>",
            "<head><!-- deployment metadata -->",
            1,
        )
        self.assertEqual(validate_generated_html(result(documented)), documented)

    def test_whitespace_outside_head_and_body_is_accepted(self):
        separated = COMPLETE_HTML.replace(
            '<html lang="en">',
            '<html lang="en">\n  ',
            1,
        ).replace(
            "</head>",
            "</head>\n  ",
            1,
        ).replace(
            "</body>",
            "</body>\n  ",
            1,
        )
        self.assertEqual(validate_generated_html(result(separated)), separated)

    def test_utf8_bom_before_doctype_is_accepted(self):
        self.assertEqual(validate_generated_html(result("\ufeff" + COMPLETE_HTML)), COMPLETE_HTML)

    def test_maximum_byte_boundary_accepts_limit_and_rejects_limit_plus_one(self):
        padding_marker = "Ready"
        base_bytes = len(COMPLETE_HTML.encode("utf-8"))
        at_limit = COMPLETE_HTML.replace(
            padding_marker,
            "x" * (MAX_HTML_BYTES - base_bytes + len(padding_marker)),
        )
        self.assertEqual(len(at_limit.encode("utf-8")), MAX_HTML_BYTES)
        validate_generated_html(result(at_limit))

        with self.assertRaisesRegex(GeneratedHtmlError, "limit is"):
            validate_generated_html(result(at_limit + "x"))


class PromptContractTests(unittest.TestCase):
    def test_deployment_comments_are_required_inside_document_head(self):
        for prompt_path in (
            Path("references/06-build-prompt.md"),
            Path("references/02-redesign-gen-prompt.md"),
        ):
            with self.subTest(prompt=str(prompt_path)):
                prompt = prompt_path.read_text(encoding="utf-8")
                self.assertIn("first characters must be `<!DOCTYPE html>`", prompt)
                self.assertIn(
                    "immediately after the opening `<head>` tag",
                    prompt,
                )
                self.assertNotIn(
                    "at the very top of the output, before DOCTYPE",
                    prompt,
                )
                self.assertNotIn(
                    "at the very top of every HTML file output, before the DOCTYPE",
                    prompt,
                )
                self.assertNotIn("after the comment block", prompt)


class AtomicWriteAndCliTests(unittest.TestCase):
    def test_atomic_write_replaces_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "index.html"
            atomic_write_text(destination, "first")
            atomic_write_text(destination, "second")

            self.assertEqual(destination.read_text(encoding="utf-8"), "second")
            self.assertEqual(list(destination.parent.glob(".*.tmp")), [])

    def test_build_cli_defaults_to_local(self):
        args = build.parse_args(["prospect.json"])

        self.assertEqual(args.generation_provider, "local")
        self.assertIsNone(args.generation_model)

    def test_build_cli_accepts_explicit_openrouter_model(self):
        args = build.parse_args(
            [
                "prospect.json",
                "--generation-provider",
                "openrouter",
                "--generation-model",
                "anthropic/example",
            ]
        )

        self.assertEqual(args.generation_provider, "openrouter")
        self.assertEqual(args.generation_model, "anthropic/example")

    def test_redesign_cli_defaults_to_local(self):
        args = pipeline.parse_args(["https://example.com"])

        self.assertEqual(args.generation_provider, "local")
        self.assertIsNone(args.generation_model)

    def test_build_generator_uses_shared_admission_gate(self):
        client = FakeClient(content=COMPLETE_HTML, finish_reason="stop")
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        html = build.generate_build_html(prospect, config(), client)

        self.assertEqual(html, COMPLETE_HTML)


if __name__ == "__main__":
    unittest.main()
