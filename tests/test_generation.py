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
    DEFAULT_LOCAL_TIMEOUT_SECONDS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    MAX_GENERATED_BODY_BYTES,
    MAX_GENERATED_BODY_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_HTML_BYTES,
    DocumentColors,
    GeneratedBodyError,
    GeneratedHtmlError,
    GenerationConfig,
    GenerationConfigurationError,
    GenerationProviderUnavailable,
    GenerationResponseError,
    GenerationResult,
    PromptPart,
    assemble_generated_html,
    atomic_write_text,
    body_generation_config,
    create_generation_client,
    create_local_generation_client,
    extract_template_body_scaffold,
    generate_text,
    preflight_generation_provider,
    resolve_generation_config,
    validate_generated_body,
    validate_generated_html,
)


COMPLETE_HTML = """<!DOCTYPE html>
<html lang="en"><head><title>Test</title></head>
<body><main>Ready</main></body></html>"""
COMPLETE_BODY = '<body class="theme-light"><main>Ready</main></body>'
COMMENTED_BODY = (
    '<body class="theme-light">'
    '<!-- deployment metadata -->'
    '<main>Ready</main>'
    '</body>'
)


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


class FakeNativeResponse:
    def __init__(self, payload=None, *, json_error=None, status_error=None):
        self.payload = payload
        self.json_error = json_error
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeNativeClient:
    def __init__(self, payload=None, *, json_error=None, status_error=None):
        self.calls = []
        self.response = FakeNativeResponse(
            payload
            if payload is not None
            else {
                "output": [{"type": "message", "content": COMPLETE_HTML}],
                "stats": {
                    "input_tokens": 12,
                    "total_output_tokens": 8,
                    "reasoning_output_tokens": 0,
                },
            },
            json_error=json_error,
            status_error=status_error,
        )

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


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


def body_result(content=COMPLETE_BODY, finish_reason="stop"):
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
        self.assertEqual(selected.timeout_seconds, DEFAULT_LOCAL_TIMEOUT_SECONDS)
        self.assertEqual(selected.max_output_tokens, DEFAULT_MAX_OUTPUT_TOKENS)

    def test_openrouter_keeps_remote_timeout_default(self):
        with patch("lib.generation.OPENROUTER_API_KEY", "configured"):
            with patch.dict(os.environ, {}, clear=True):
                selected = resolve_generation_config("openrouter", "anthropic/example")

        self.assertEqual(selected.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)

    def test_explicit_timeout_override_wins_for_local_generation(self):
        with patch.dict(
            os.environ, {"GENERATION_TIMEOUT_SECONDS": "123.5"}, clear=True
        ):
            selected = resolve_generation_config()

        self.assertEqual(selected.timeout_seconds, 123.5)

    def test_zero_timeout_override_is_rejected(self):
        with patch.dict(
            os.environ, {"GENERATION_TIMEOUT_SECONDS": "0"}, clear=True
        ):
            with self.assertRaisesRegex(
                GenerationConfigurationError, "greater than zero"
            ):
                resolve_generation_config()

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

    def test_explicit_output_token_limit_overrides_the_template_sized_default(self):
        with patch.dict(
            os.environ, {"GENERATION_MAX_OUTPUT_TOKENS": "32768"}, clear=True
        ):
            selected = resolve_generation_config()

        self.assertEqual(selected.max_output_tokens, 32768)


class ProviderBoundaryTests(unittest.TestCase):
    def test_generation_client_disables_automatic_provider_retries(self):
        selected = config()

        with patch("lib.generation.OpenAI") as openai:
            create_generation_client(selected)

        openai.assert_called_once_with(
            base_url=selected.base_url,
            api_key=selected.api_key,
            timeout=selected.timeout_seconds,
            max_retries=0,
        )

    def test_local_client_sets_auth_and_honors_proxy_setting(self):
        selected = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url=DEFAULT_LOCAL_BASE_URL,
            api_key="secret-key",
            trust_env=False,
        )

        with patch("lib.generation.requests.Session") as session_factory:
            session = session_factory.return_value
            created = create_local_generation_client(selected)

        self.assertIs(created, session)
        self.assertFalse(session.trust_env)
        session.headers.update.assert_called_once_with(
            {
                "Authorization": "Bearer secret-key",
                "Content-Type": "application/json",
            }
        )

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
        client = FakeNativeClient()

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

        url, call = client.calls[0]
        self.assertEqual(url, "http://127.0.0.1:1234/api/v1/chat")
        self.assertEqual(call["json"]["system_prompt"], "system")
        self.assertEqual(call["json"]["input"], "static\n\nvariable")
        self.assertEqual(call["json"]["reasoning"], "off")
        self.assertIs(call["json"]["store"], False)
        self.assertEqual(call["timeout"], config().timeout_seconds)
        self.assertNotIn("cache_control", str(call["json"]))
        self.assertEqual(generated.finish_reason, "stop")
        self.assertEqual(generated.usage["reasoning_output_tokens"], 0)

    def test_local_request_marks_output_limit_as_incomplete(self):
        selected = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url=DEFAULT_LOCAL_BASE_URL,
            api_key="test-key",
            max_output_tokens=8,
        )
        client = FakeNativeClient(
            {
                "output": [{"type": "message", "content": COMPLETE_HTML}],
                "stats": {"total_output_tokens": 8},
            }
        )

        generated = generate_text(
            selected,
            system_prompt="system",
            user_parts=(PromptPart("input"),),
            temperature=0.4,
            client=client,
        )

        self.assertEqual(generated.finish_reason, "length")
        with self.assertRaisesRegex(GenerationResponseError, "finish_reason=length"):
            validate_generated_html(generated)

    def test_local_request_rejects_reasoning_or_tool_output(self):
        client = FakeNativeClient(
            {
                "output": [
                    {"type": "reasoning", "content": "hidden work"},
                    {"type": "message", "content": COMPLETE_HTML},
                ],
                "stats": {"total_output_tokens": 8},
            }
        )

        with self.assertRaisesRegex(GenerationResponseError, "non-message output"):
            generate_text(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("input"),),
                temperature=0.4,
                client=client,
            )

    def test_local_request_rejects_missing_token_statistics(self):
        client = FakeNativeClient(
            {
                "output": [{"type": "message", "content": COMPLETE_HTML}],
                "stats": {},
            }
        )

        with self.assertRaisesRegex(GenerationResponseError, "output-token statistics"):
            generate_text(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("input"),),
                temperature=0.4,
                client=client,
            )

    def test_local_request_rejects_invalid_native_base_url_before_dispatch(self):
        selected = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url="http://127.0.0.1:1234/not-v1",
            api_key="test-key",
        )
        client = FakeNativeClient()

        with self.assertRaisesRegex(GenerationConfigurationError, "path must"):
            generate_text(
                selected,
                system_prompt="system",
                user_parts=(PromptPart("input"),),
                temperature=0.4,
                client=client,
            )

        self.assertEqual(client.calls, [])

    def test_local_request_translates_http_failure_without_retry(self):
        client = FakeNativeClient(status_error=ConnectionError("offline"))

        with self.assertRaisesRegex(GenerationProviderUnavailable, "offline"):
            generate_text(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("input"),),
                temperature=0.4,
                client=client,
            )

        self.assertEqual(len(client.calls), 1)

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


class BodyAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.base_template = Path("references/03-base-template.html").read_text(
            encoding="utf-8"
        )
        self.theme_catalog = Path("references/09-themes.md").read_text(
            encoding="utf-8"
        )
        self.colors = DocumentColors(
            accent="#B91C1C",
            accent_dark="#991B1B",
            secondary="#1F3A5F",
        )

    def test_body_generation_cap_preserves_smaller_explicit_limit(self):
        default_config = config()
        smaller_config = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url=DEFAULT_LOCAL_BASE_URL,
            api_key="test-key",
            max_output_tokens=1024,
        )

        self.assertEqual(
            body_generation_config(default_config).max_output_tokens,
            MAX_GENERATED_BODY_TOKENS,
        )
        self.assertEqual(
            body_generation_config(smaller_config).max_output_tokens,
            1024,
        )

    def test_template_body_scaffold_excludes_head_and_interior_examples(self):
        scaffold = extract_template_body_scaffold(self.base_template)

        self.assertTrue(scaffold.startswith("<body>"))
        self.assertTrue(scaffold.endswith("</body>"))
        self.assertNotIn("<head>", scaffold)
        self.assertNotIn("INTERIOR PAGE EXAMPLES", scaffold)

    def test_body_admission_accepts_one_plain_body(self):
        self.assertEqual(validate_generated_body(body_result()), COMPLETE_BODY)

    def test_body_admission_rejects_document_wrapper_and_provider_chatter(self):
        invalid_bodies = {
            "full document": COMPLETE_HTML,
            "leading chatter": f"Here is the body: {COMPLETE_BODY}",
            "trailing chatter": f"{COMPLETE_BODY} Done.",
            "two bodies": f"{COMPLETE_BODY}{COMPLETE_BODY}",
        }
        for label, content in invalid_bodies.items():
            with self.subTest(label=label):
                with self.assertRaises(GeneratedBodyError):
                    validate_generated_body(body_result(content))

    def test_body_admission_rejects_head_style_script_and_placeholders(self):
        invalid_bodies = {
            "head": "<body><head><title>bad</title></head></body>",
            "style": "<body><style>body{color:red}</style></body>",
            "script": "<body><script>alert(1)</script></body>",
            "placeholder": "<body><main>{{SITE_NAME}}</main></body>",
        }
        for label, content in invalid_bodies.items():
            with self.subTest(label=label):
                with self.assertRaises(GeneratedBodyError):
                    validate_generated_body(body_result(content))

    def test_body_byte_boundary_accepts_limit_and_rejects_limit_plus_one(self):
        base = "<body></body>"
        at_limit = base.replace(
            "</body>",
            "x" * (MAX_GENERATED_BODY_BYTES - len(base)) + "</body>",
        )
        self.assertEqual(len(at_limit.encode("utf-8")), MAX_GENERATED_BODY_BYTES)
        validate_generated_body(body_result(at_limit))

        over_limit = base.replace(
            "</body>",
            "x" * (MAX_GENERATED_BODY_BYTES - len(base) + 1) + "</body>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "byte limit"):
            validate_generated_body(body_result(over_limit))

    def test_assembly_uses_trusted_head_and_relocates_deployment_comment(self):
        document = assemble_generated_html(
            body_result(COMMENTED_BODY),
            base_template=self.base_template,
            theme_catalog=self.theme_catalog,
            theme_name="warm",
            colors=self.colors,
            title=r"Drees \1 <Plumbing>",
            body_theme="theme-light",
            relocate_leading_comment=True,
        )

        self.assertTrue(document.startswith("<!DOCTYPE html>"))
        self.assertIn("<head>\n<!-- deployment metadata -->", document)
        self.assertIn("<title>Drees \\1 &lt;Plumbing&gt;</title>", document)
        self.assertIn("--accent: #B91C1C;", document)
        self.assertIn("--font-display: 'Lexend', sans-serif;", document)
        self.assertIn('<body class="theme-light"><main>Ready</main></body>', document)
        self.assertEqual(document.count("<!-- deployment metadata -->"), 1)

    def test_assembly_rejects_missing_comment_invalid_color_and_unknown_theme(self):
        with self.assertRaisesRegex(GeneratedBodyError, "deployment comment"):
            assemble_generated_html(
                body_result(),
                base_template=self.base_template,
                theme_catalog=self.theme_catalog,
                theme_name="warm",
                colors=self.colors,
                title="Test",
                body_theme="theme-light",
                relocate_leading_comment=True,
            )

        with self.assertRaisesRegex(GeneratedHtmlError, "six-digit hex"):
            assemble_generated_html(
                body_result(),
                base_template=self.base_template,
                theme_catalog=self.theme_catalog,
                theme_name="warm",
                colors=DocumentColors("red;", "#991B1B", "#1F3A5F"),
                title="Test",
                body_theme="theme-light",
            )

        with self.assertRaisesRegex(GeneratedHtmlError, "not defined"):
            assemble_generated_html(
                body_result(),
                base_template=self.base_template,
                theme_catalog=self.theme_catalog,
                theme_name="missing",
                colors=self.colors,
                title="Test",
                body_theme="theme-light",
            )


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
    def test_every_wired_html_prompt_requires_body_only_output(self):
        for prompt_path in (
            Path("references/02-redesign-gen-prompt.md"),
            Path("references/04-interior-page-prompt.md"),
            Path("references/06-build-prompt.md"),
        ):
            with self.subTest(prompt=str(prompt_path)):
                prompt = prompt_path.read_text(encoding="utf-8")
                self.assertIn("first characters", prompt)
                self.assertIn("must be `<body`", prompt)
                self.assertIn("Do NOT output `<style>`, `<script>`, `<head>`, `<html>`, or a doctype", prompt)
                self.assertNotIn("(or a leading comment)", prompt)

    def test_deployment_comments_are_generated_first_and_relocated_to_head(self):
        for prompt_path in (
            Path("references/06-build-prompt.md"),
            Path("references/02-redesign-gen-prompt.md"),
        ):
            with self.subTest(prompt=str(prompt_path)):
                prompt = prompt_path.read_text(encoding="utf-8")
                self.assertIn(
                    "immediately after the opening `<body>` tag",
                    prompt,
                )
                self.assertIn(
                    "inserts it immediately after the opening `<head>`",
                    prompt,
                )


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
        client = FakeNativeClient(
            {
                "output": [{"type": "message", "content": COMMENTED_BODY}],
                "stats": {"total_output_tokens": 8},
            }
        )
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        html = build.generate_build_html(prospect, config(), client)

        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("<head>\n<!-- deployment metadata -->", html)
        self.assertIn('<body class="theme-light"><main>Ready</main></body>', html)

    def test_redesign_generator_assembles_body_with_site_brand_contract(self):
        client = FakeNativeClient(
            {
                "output": [{"type": "message", "content": COMMENTED_BODY}],
                "stats": {"total_output_tokens": 8},
            }
        )
        site_json = {
            "site": {"name": "Current Business"},
            "brand": {
                "color_mode": "dark",
                "colors": {
                    "primary": "#123456",
                    "secondary": "#ABCDEF",
                },
            },
        }

        html = pipeline.generate_redesign(
            site_json,
            theme="minimal",
            generation_config=config(),
            generation_client=client,
        )

        self.assertIn("<title>Current Business</title>", html)
        self.assertIn("--accent: #123456;", html)
        self.assertIn("--secondary: #ABCDEF;", html)
        self.assertIn("<head>\n<!-- deployment metadata -->", html)
        self.assertIn('<body class="theme-dark"><main>Ready</main></body>', html)

    def test_interior_generator_assembles_body_without_deployment_comment(self):
        client = FakeNativeClient(
            {
                "output": [{"type": "message", "content": COMPLETE_BODY}],
                "stats": {"total_output_tokens": 8},
            }
        )
        site_json = {"site": {"name": "Current Business"}}

        html = pipeline.generate_interior_page(
            site_json,
            "contact",
            theme="warm",
            generation_config=config(),
            generation_client=client,
        )

        self.assertIn("<title>Contact | Current Business</title>", html)
        self.assertIn('<body class="theme-light"><main>Ready</main></body>', html)
        self.assertNotIn("<!-- deployment metadata -->", html)


if __name__ == "__main__":
    unittest.main()
