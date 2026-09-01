import os
import importlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build
import pipeline
import lib.clients
from lib.generation import (
    DEFAULT_DOCUMENT_ACCENT,
    DEFAULT_DOCUMENT_SECONDARY,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_MODEL,
    DEFAULT_LOCAL_TIMEOUT_SECONDS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    MAX_GENERATED_BODY_BYTES,
    MAX_GENERATED_BODY_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_HTML_BYTES,
    REQUIRED_FOOTER_CLASS_COUNTS,
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
    extract_homepage_class_names,
    extract_interior_only_class_names,
    extract_square_placeholder_tokens,
    extract_template_body_scaffold,
    extract_template_class_names,
    generate_text,
    make_html_comment,
    preflight_generation_provider,
    resolve_generation_config,
    validate_generated_body,
    validate_generated_html,
)


COMPLETE_HTML = """<!DOCTYPE html>
<html lang="en"><head><title>Test</title></head>
<body><main>Ready</main></body></html>"""
COMPLETE_BODY = '<body class="theme-light"><main>Ready</main></body>'
COMPLETE_PAGE_BODY = (
    '<body class="theme-light"><main>Ready</main>'
    '<footer class="site-footer"><div class="footer-grid"></div>'
    '<div class="footer-bottom"><p>Copyright</p></div></footer></body>'
)
COMPLETE_SERVICES_GRID = (
    '<div class="services-grid">'
    + "".join(
        '<div class="service-card">'
        f'<div class="service-card-name">Service {index}</div>'
        f'<p class="service-card-desc">Description {index}</p>'
        '</div>'
        for index in range(1, 7)
    )
    + "</div>"
)
COMPLETE_BENEFITS_GRID = (
    '<div class="benefits-grid">'
    + '<div class="benefit-card"></div>' * 3
    + "</div>"
)
COMPLETE_BUILD_BODY = (
    '<body class="theme-light"><nav class="site-nav"><span>Test Business</span>'
    '<a href="tel:2175550100">217-555-0100</a></nav>'
    '<section class="dual-cta-hero"></section><div class="coverage-band"></div>'
    + COMPLETE_SERVICES_GRID
    + COMPLETE_BENEFITS_GRID
    + '<form class="contact-form-wrap" action="#"></form>'
    '<footer class="site-footer"><div class="footer-grid"></div>'
    '<div class="footer-bottom"><p>Copyright</p></div></footer></body>'
)


def build_body_with_review_section(section):
    return COMPLETE_BUILD_BODY.replace(
        '<form class="contact-form-wrap"',
        f'{section}<form class="contact-form-wrap"',
    )


def aggregate_review_section(score, count, url="https://example.com/reviews"):
    return (
        '<section><div class="reviews-aggregate">'
        f'<span class="reviews-stars-lg" style="--score: {score}">★★★★★</span>'
        f'<div class="reviews-score">{score}'
        '<span class="of-five">out of 5</span></div>'
        f'<div class="reviews-count">Based on {count} reviews on Google</div>'
        f'<a class="reviews-cta" href="{url}">Read All Reviews on Google</a>'
        '</div></section>'
    )


def review_card_section(reviews, score, count, url="https://example.com/reviews"):
    cards = "".join(
        '<div class="review-card">'
        f'<span class="review-stars-sm" style="--score: {review["rating"]}">★★★★★</span>'
        f'<p class="review-text">{review["text"]}</p>'
        '<div class="review-meta">'
        f'<span class="review-author">{review["author"]}'
        f'<span class="review-date">{review["date"]}</span></span>'
        f'<span class="review-platform">{review["platform"]}</span>'
        '</div></div>'
        for review in reviews
    )
    return (
        '<section><div class="reviews-card-grid">'
        f'{cards}</div><div class="reviews-summary-row">'
        f'<span class="reviews-summary-stars" style="--score: {score}">★★★★★</span>'
        f'<span class="reviews-summary-text"><strong>{score} out of 5</strong> '
        f'Based on {count} Google Reviews</span>'
        f'<a class="reviews-summary-cta" href="{url}">Read All on Google</a>'
        '</div></section>'
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


_UNSET = object()


class FakeLocalResponse:
    def __init__(
        self,
        payload=None,
        *,
        json_error=None,
        status_error=None,
        status_code=200,
    ):
        self.payload = payload
        self.json_error = json_error
        self.status_error = status_error
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeLocalClient:
    def __init__(
        self,
        chat_payload=_UNSET,
        *,
        health_payload=_UNSET,
        models_payload=_UNSET,
        health_status_error=None,
        models_status_error=None,
        chat_status_error=None,
        chat_json_error=None,
        health_status_code=200,
        models_status_code=200,
        chat_status_code=200,
    ):
        self.calls = []
        self.health_response = FakeLocalResponse(
            {"status": "ok"} if health_payload is _UNSET else health_payload,
            status_error=health_status_error,
            status_code=health_status_code,
        )
        self.models_response = FakeLocalResponse(
            {
                "object": "list",
                "data": [{"id": DEFAULT_LOCAL_MODEL, "object": "model"}],
            }
            if models_payload is _UNSET
            else models_payload,
            status_error=models_status_error,
            status_code=models_status_code,
        )
        self.chat_response = FakeLocalResponse(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": DEFAULT_LOCAL_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": COMPLETE_HTML,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                },
            }
            if chat_payload is _UNSET
            else chat_payload,
            json_error=chat_json_error,
            status_error=chat_status_error,
            status_code=chat_status_code,
        )

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/health"):
            return self.health_response
        if url.endswith("/v1/models"):
            return self.models_response
        raise AssertionError(f"unexpected local GET URL: {url}")

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.chat_response


def local_chat_payload(content=COMPLETE_HTML, finish_reason="stop", **message_fields):
    return {
        "choices": [
            {
                "message": {"content": content, **message_fields},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }


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

    def test_llama_cpp_endpoint_aliases_are_supported(self):
        with patch.dict(
            os.environ,
            {
                "LLAMA_CPP_BASE_URL": "http://127.0.0.1:4321/v1",
                "LLAMA_CPP_API_KEY": "local-key",
            },
            clear=True,
        ):
            selected = resolve_generation_config()

        self.assertEqual(selected.base_url, "http://127.0.0.1:4321/v1")
        self.assertEqual(selected.api_key, "local-key")

    def test_lm_studio_aliases_no_longer_select_the_local_runtime(self):
        with patch.dict(
            os.environ,
            {
                "LM_STUDIO_BASE_URL": "http://127.0.0.1:4321/v1",
                "LM_STUDIO_API_KEY": "legacy-key",
            },
            clear=True,
        ):
            selected = resolve_generation_config()

        self.assertEqual(selected.base_url, DEFAULT_LOCAL_BASE_URL)
        self.assertNotEqual(selected.api_key, "legacy-key")

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


class LlamaCppStartupScriptTests(unittest.TestCase):
    script = Path(__file__).resolve().parents[1] / "scripts/start_llama_server.sh"

    def test_help_does_not_require_or_load_a_model(self):
        completed = subprocess.run(
            [str(self.script), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("LLAMA_CPP_MODEL_PATH", completed.stdout)

    def test_non_loopback_host_is_rejected_before_launch(self):
        completed = subprocess.run(
            [str(self.script)],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LLAMA_CPP_SERVER_BIN": "/bin/true",
                "LLAMA_CPP_MODEL_PATH": str(Path(__file__).resolve()),
                "LLAMA_CPP_HOST": "0.0.0.0",
            },
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("loopback", completed.stderr)

    def test_missing_model_path_is_rejected_before_launch(self):
        completed = subprocess.run(
            [str(self.script)],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LLAMA_CPP_SERVER_BIN": "/bin/true",
                "LLAMA_CPP_MODEL_PATH": "",
            },
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("LLAMA_CPP_MODEL_PATH", completed.stderr)

    def test_launcher_defaults_to_all_gpu_layers(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fake_server = root / "fake-llama-server"
            fake_server.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n',
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "qwen.gguf"
            model.write_bytes(b"")
            environment = {
                key: value
                for key, value in os.environ.items()
                if key != "LLAMA_CPP_GPU_LAYERS"
            }
            environment.update(
                {
                    "LLAMA_CPP_SERVER_BIN": str(fake_server),
                    "LLAMA_CPP_MODEL_PATH": str(model),
                }
            )
            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        arguments = completed.stdout.splitlines()
        self.assertEqual(arguments[arguments.index("--n-gpu-layers") + 1], "all")

    def test_numeric_boundaries_reject_values_outside_the_contract(self):
        invalid_values = {
            "port below minimum": {"LLAMA_CPP_PORT": "0"},
            "port above maximum": {"LLAMA_CPP_PORT": "65536"},
            "empty context": {"LLAMA_CPP_CONTEXT_SIZE": "0"},
            "negative GPU layers": {"LLAMA_CPP_GPU_LAYERS": "-1"},
            "empty server timeout": {"LLAMA_CPP_SERVER_TIMEOUT": "0"},
        }
        for label, overrides in invalid_values.items():
            with self.subTest(label=label):
                completed = subprocess.run(
                    [str(self.script)],
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "LLAMA_CPP_SERVER_BIN": "/bin/true",
                        "LLAMA_CPP_MODEL_PATH": str(Path(__file__).resolve()),
                        **overrides,
                    },
                )

                self.assertEqual(completed.returncode, 2)

    def test_safe_runtime_contract_is_forwarded_without_word_splitting(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fake_server = root / "fake llama-server"
            fake_server.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n',
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "Qwen model.gguf"
            model.write_bytes(b"")
            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "LLAMA_CPP_SERVER_BIN": str(fake_server),
                    "LLAMA_CPP_MODEL_PATH": str(model),
                    "LLAMA_CPP_HOST": "127.0.0.1",
                    "LLAMA_CPP_PORT": "18080",
                    "LLAMA_CPP_CONTEXT_SIZE": "1024",
                    "LLAMA_CPP_GPU_LAYERS": "0",
                    "LLAMA_CPP_CACHE_TYPE_K": "f16",
                    "LLAMA_CPP_CACHE_TYPE_V": "f16",
                    "LLAMA_CPP_SERVER_TIMEOUT": "60",
                    "LOCAL_GENERATION_MODEL": "local/test-model",
                    "LOCAL_GENERATION_API_KEY": "test-key",
                },
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        arguments = completed.stdout.splitlines()
        self.assertEqual(arguments[arguments.index("--model") + 1], str(model))
        self.assertEqual(arguments[arguments.index("--alias") + 1], "local/test-model")
        self.assertEqual(arguments[arguments.index("--host") + 1], "127.0.0.1")
        self.assertEqual(arguments[arguments.index("--port") + 1], "18080")
        self.assertEqual(arguments[arguments.index("--reasoning") + 1], "off")
        self.assertEqual(arguments[arguments.index("--reasoning-budget") + 1], "0")
        self.assertIn("--no-webui", arguments)
        self.assertEqual(arguments[arguments.index("--api-key") + 1], "test-key")


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

    def test_local_client_sets_auth_and_ignores_environment_proxies(self):
        selected = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url=DEFAULT_LOCAL_BASE_URL,
            api_key="secret-key",
            trust_env=True,
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

    def test_local_generation_slice_does_not_reconfigure_other_model_roles(self):
        with patch.dict(
            os.environ,
            {
                "EXTRACTION_MODEL": "unrelated/extraction-override",
                "IMAGE_MODEL": "unrelated/image-override",
            },
        ):
            importlib.reload(lib.clients)
            self.assertEqual(
                lib.clients.EXTRACTION_MODEL,
                "anthropic/claude-haiku-4.5",
            )
            self.assertEqual(
                lib.clients.IMAGE_MODEL,
                "black-forest-labs/flux.2-max",
            )
        importlib.reload(lib.clients)

    def test_local_preflight_accepts_exact_loaded_model(self):
        selected = config()
        client = FakeLocalClient(
            models_payload={"data": [{"id": selected.model}]},
        )

        preflight_generation_provider(selected, client=client)

        self.assertEqual(
            [call[:2] for call in client.calls],
            [
                ("GET", "http://127.0.0.1:8080/health"),
                ("GET", "http://127.0.0.1:8080/v1/models"),
            ],
        )
        self.assertTrue(
            all(call[2]["allow_redirects"] is False for call in client.calls)
        )

    def test_local_preflight_rejects_non_loopback_base_url_without_dispatch(self):
        selected = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url="https://example.com/v1",
            api_key="test-key",
        )
        client = FakeLocalClient()

        with self.assertRaisesRegex(GenerationConfigurationError, "loopback"):
            preflight_generation_provider(selected, client=client)

        self.assertEqual(client.calls, [])

    def test_local_preflight_rejects_missing_model_with_start_instruction(self):
        selected = config()
        client = FakeLocalClient(
            models_payload={"data": [{"id": "some/other-model"}]},
        )

        with self.assertRaisesRegex(
            GenerationProviderUnavailable, "scripts/start_llama_server.sh"
        ):
            preflight_generation_provider(selected, client=client)

    def test_local_preflight_translates_connection_failure(self):
        selected = config()
        client = FakeLocalClient(health_status_error=ConnectionError("offline"))

        with self.assertRaisesRegex(
            GenerationProviderUnavailable, "standalone llama.cpp"
        ):
            preflight_generation_provider(selected, client=client)

    def test_local_preflight_rejects_non_ready_health_without_model_lookup(self):
        selected = config()
        client = FakeLocalClient(health_payload={"status": "loading"})

        with self.assertRaisesRegex(
            GenerationProviderUnavailable, "standalone llama.cpp"
        ):
            preflight_generation_provider(selected, client=client)

        self.assertEqual(
            [call[:2] for call in client.calls],
            [("GET", "http://127.0.0.1:8080/health")],
        )

    def test_local_preflight_rejects_redirect_without_following_it(self):
        client = FakeLocalClient(health_status_code=307)

        with self.assertRaisesRegex(
            GenerationProviderUnavailable,
            "standalone llama.cpp",
        ):
            preflight_generation_provider(config(), client=client)

        self.assertEqual(len(client.calls), 1)
        self.assertIs(client.calls[0][2]["allow_redirects"], False)

    def test_local_preflight_rejects_malformed_model_identity(self):
        selected = config()
        client = FakeLocalClient(models_payload={"data": [{"id": None}]})

        with self.assertRaisesRegex(
            GenerationProviderUnavailable, "standalone llama.cpp"
        ):
            preflight_generation_provider(selected, client=client)

    def test_local_request_uses_plain_content_without_cloud_cache_metadata(self):
        client = FakeLocalClient()

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

        method, url, call = client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(
            call["json"]["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "static\n\nvariable"},
            ],
        )
        self.assertEqual(
            call["json"]["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        self.assertEqual(call["json"]["reasoning_format"], "deepseek")
        self.assertIs(call["json"]["stream"], False)
        self.assertEqual(call["timeout"], config().timeout_seconds)
        self.assertIs(call["allow_redirects"], False)
        self.assertNotIn("cache_control", str(call["json"]))
        self.assertEqual(generated.finish_reason, "stop")
        self.assertEqual(generated.usage["completion_tokens"], 8)

    def test_local_request_marks_output_limit_as_incomplete(self):
        selected = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url=DEFAULT_LOCAL_BASE_URL,
            api_key="test-key",
            max_output_tokens=8,
        )
        client = FakeLocalClient(
            {
                "choices": [
                    {
                        "message": {"content": COMPLETE_HTML},
                        "finish_reason": "length",
                    }
                ],
                "usage": {"completion_tokens": 8},
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

    def test_local_request_rejects_redirect_without_following_it(self):
        client = FakeLocalClient(chat_status_code=307)

        with self.assertRaisesRegex(
            GenerationProviderUnavailable,
            "local generation failed",
        ):
            generate_text(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("prospect"),),
                temperature=0.4,
                client=client,
            )

        self.assertEqual(len(client.calls), 1)
        self.assertIs(client.calls[0][2]["allow_redirects"], False)

    def test_local_request_rejects_multiple_choices(self):
        client = FakeLocalClient(
            {
                "choices": [
                    {
                        "message": {"content": COMPLETE_HTML},
                        "finish_reason": "stop",
                    },
                    {
                        "message": {"content": COMPLETE_HTML},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {"completion_tokens": 8},
            }
        )

        with self.assertRaisesRegex(GenerationResponseError, "exactly one choice"):
            generate_text(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("input"),),
                temperature=0.4,
                client=client,
            )

    def test_local_request_rejects_reasoning_or_tool_output(self):
        invalid_messages = {
            "reasoning": {
                "content": COMPLETE_HTML,
                "reasoning_content": "hidden work",
            },
            "tool call": {
                "content": COMPLETE_HTML,
                "tool_calls": [{"id": "call-1", "type": "function"}],
            },
        }
        for label, message in invalid_messages.items():
            with self.subTest(label=label):
                client = FakeLocalClient(
                    {
                        "choices": [
                            {"message": message, "finish_reason": "stop"}
                        ],
                        "usage": {"completion_tokens": 8},
                    }
                )
                with self.assertRaises(GenerationResponseError):
                    generate_text(
                        config(),
                        system_prompt="system",
                        user_parts=(PromptPart("input"),),
                        temperature=0.4,
                        client=client,
                    )

    def test_local_request_rejects_missing_usage_object(self):
        client = FakeLocalClient(
            {
                "choices": [
                    {
                        "message": {"content": COMPLETE_HTML},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

        with self.assertRaisesRegex(GenerationResponseError, "usage object"):
            generate_text(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("input"),),
                temperature=0.4,
                client=client,
            )

    def test_local_request_rejects_invalid_llama_cpp_base_url_before_dispatch(self):
        invalid_urls = {
            "wrong path": "http://127.0.0.1:8080/not-v1",
            "LM Studio native path": "http://127.0.0.1:8080/api/v1",
            "query": "http://127.0.0.1:8080/v1?mode=local",
            "fragment": "http://127.0.0.1:8080/v1#local",
            "wrong scheme": "ftp://127.0.0.1:8080/v1",
            "remote hostname": "https://example.com/v1",
            "wildcard host": "http://0.0.0.0:8080/v1",
            "hostname lookalike": "http://localhost.example.com:8080/v1",
            "credentials": "http://user:pass@127.0.0.1:8080/v1",
            "invalid port": "http://127.0.0.1:70000/v1",
        }
        for label, base_url in invalid_urls.items():
            with self.subTest(label=label):
                selected = GenerationConfig(
                    provider="local",
                    model=DEFAULT_LOCAL_MODEL,
                    base_url=base_url,
                    api_key="test-key",
                )
                client = FakeLocalClient()

                with self.assertRaises(GenerationConfigurationError):
                    generate_text(
                        selected,
                        system_prompt="system",
                        user_parts=(PromptPart("input"),),
                        temperature=0.4,
                        client=client,
                    )

                self.assertEqual(client.calls, [])

    def test_local_request_accepts_root_or_v1_base_url(self):
        valid_urls = {
            "IPv4 root": (
                "http://127.0.0.1:8080",
                "http://127.0.0.1:8080/v1/chat/completions",
            ),
            "localhost versioned": (
                "http://localhost:8080/v1/",
                "http://localhost:8080/v1/chat/completions",
            ),
            "IPv6 versioned": (
                "http://[::1]:8080/v1",
                "http://[::1]:8080/v1/chat/completions",
            ),
        }
        for label, (base_url, expected_endpoint) in valid_urls.items():
            with self.subTest(label=label):
                selected = GenerationConfig(
                    provider="local",
                    model=DEFAULT_LOCAL_MODEL,
                    base_url=base_url,
                    api_key="test-key",
                )
                client = FakeLocalClient()

                generate_text(
                    selected,
                    system_prompt="system",
                    user_parts=(PromptPart("input"),),
                    temperature=0.4,
                    client=client,
                )

                self.assertEqual(
                    client.calls[0][1],
                    expected_endpoint,
                )

    def test_local_request_translates_http_failure_without_retry(self):
        client = FakeLocalClient(chat_status_error=ConnectionError("offline"))

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

    def test_template_class_catalog_contains_classes_without_placeholder_markup(self):
        class_names = extract_template_class_names(self.base_template)

        self.assertIn("site-nav", class_names)
        self.assertIn("dual-cta-hero", class_names)
        self.assertIn("contact-grid", class_names)
        self.assertIn("benefit-text", class_names)
        self.assertIn("coverage-band", class_names)
        self.assertIn("reviews-card-grid", class_names)
        self.assertNotIn("{{SITE_NAME}}", class_names)

    def test_mobile_trust_strip_wraps_without_horizontal_scroller(self):
        responsive_css = self.base_template.split(
            "@media (max-width: 768px)", 1
        )[1].split("</style>", 1)[0]

        self.assertIn(
            ".trust-strip { height: auto; min-height: var(--trust-strip-height); }",
            responsive_css,
        )
        self.assertIn("flex-wrap: wrap", responsive_css)
        self.assertIn("overflow-x: visible", responsive_css)
        self.assertNotIn("overflow-x: auto", responsive_css)

    def test_body_admission_rejects_duplicate_raw_attributes(self):
        duplicate_bodies = (
            '<body><a href="/wrong" href="/right">Right</a></body>',
            '<body><div aria-label="Wrong" ARIA-LABEL="Right">Right</div></body>',
            '<body><div class="trust-item" class="trust-item">Trust</div></body>',
        )
        for body in duplicate_bodies:
            with self.subTest(body=body), self.assertRaisesRegex(
                GeneratedBodyError,
                "duplicate attribute",
            ):
                validate_generated_body(body_result(body))

        valid_body = (
            '<body><a class="cta-planned" href="#contact" '
            'aria-label="Request service">Request service</a></body>'
        )
        self.assertEqual(validate_generated_body(body_result(valid_body)), valid_body)

    def test_body_admission_rejects_nondeterministic_rendering_containers(self):
        for tag in (
            "audio",
            "canvas",
            "datalist",
            "details",
            "dialog",
            "iframe",
            "map",
            "noscript",
            "object",
            "template",
            "video",
        ):
            body = f"<body><{tag}>Hidden claim</{tag}></body>"
            with self.subTest(tag=tag), self.assertRaisesRegex(
                GeneratedBodyError,
                f"browser-inert tag: {tag}",
            ):
                validate_generated_body(body_result(body))

        rendered = "<body><section><p>Visible claim</p></section></body>"
        self.assertEqual(validate_generated_body(body_result(rendered)), rendered)

    def test_homepage_class_catalog_excludes_interior_components(self):
        template = """<style>
        .page-wrap, .page-body, .page-cta-block, .footer-bottom { display: block; }
        </style><body class="theme-light"><div class="page-wrap"></div></body>"""

        self.assertEqual(
            extract_interior_only_class_names(template),
            ("page-body", "page-cta-block"),
        )
        self.assertEqual(
            extract_homepage_class_names(template),
            ("footer-bottom", "page-wrap", "theme-light"),
        )

    def test_body_admission_rejects_interior_class_on_homepage(self):
        forbidden = ("page-body", "page-cta-block")
        with self.assertRaisesRegex(GeneratedBodyError, "unavailable to this page type"):
            validate_generated_body(
                body_result(
                    '<body><footer class="footer-bottom page-body">Ready</footer></body>'
                ),
                forbidden_class_names=forbidden,
            )

        body = '<body><main class="page-wrap">Ready</main></body>'
        self.assertEqual(
            validate_generated_body(
                body_result(body),
                forbidden_class_names=forbidden,
            ),
            body,
        )

    def test_body_admission_requires_exact_footer_class_counts(self):
        partial_body = (
            '<body><div class="footer-grid"></div>'
            '<div class="footer-bottom"></div></body>'
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "site-footer expected 1, got 0",
        ):
            validate_generated_body(
                body_result(partial_body),
                required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
            )

        complete_body = (
            '<body><footer class="site-footer"><div class="footer-grid"></div>'
            '<div class="footer-bottom"></div></footer></body>'
        )
        self.assertEqual(
            validate_generated_body(
                body_result(complete_body),
                required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
            ),
            complete_body,
        )

        duplicated_body = complete_body.replace(
            "</footer>",
            '<div class="footer-bottom"></div></footer>',
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "footer-bottom expected 1, got 2",
        ):
            validate_generated_body(
                body_result(duplicated_body),
                required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
            )

    def test_body_admission_counts_a_class_once_per_element(self):
        repeated_token_body = (
            '<body><div class="service-card service-card service-card '
            'service-card service-card service-card"></div></body>'
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "service-card expected 6, got 1",
        ):
            validate_generated_body(
                body_result(repeated_token_body),
                required_class_counts=(("service-card", 6),),
            )

        wrong_case_body = (
            "<body>" + '<div class="SERVICE-CARD"></div>' * 6 + "</body>"
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "service-card has invalid case variant: SERVICE-CARD",
        ):
            validate_generated_body(
                body_result(wrong_case_body),
                required_class_counts=(("service-card", 6),),
            )

        six_element_body = (
            "<body>"
            + '<div class="service-card"></div>' * 6
            + "</body>"
        )
        self.assertEqual(
            validate_generated_body(
                body_result(six_element_body),
                required_class_counts=(("service-card", 6),),
            ),
            six_element_body,
        )

    def test_body_admission_accepts_one_plain_body(self):
        self.assertEqual(validate_generated_body(body_result()), COMPLETE_BODY)

    def test_body_admission_rejects_malformed_descendant_structure(self):
        malformed_bodies = (
            "<body><main><a>Call</main></body>",
            "<body><main><strong><em>Text</strong></em></main></body>",
            "<body><main></a></main></body>",
        )
        for malformed in malformed_bodies:
            with self.subTest(malformed=malformed), self.assertRaisesRegex(
                GeneratedBodyError,
                "invalid descendant structure",
            ):
                validate_generated_body(body_result(malformed))

        valid = (
            '<body><main>Ready<br><img src="data:image/png;base64,AA==" alt="">'
            '<svg><path d="M0 0" /></svg></main></body>'
        )
        self.assertEqual(validate_generated_body(body_result(valid)), valid)

    def test_body_admission_rejects_gated_claim_across_elements(self):
        body = "<body><p>Upfront <strong>Flat-Rate</strong> pricing.</p></body>"
        with self.assertRaisesRegex(GeneratedBodyError, "Upfront Flat-Rate"):
            validate_generated_body(
                body_result(body),
                forbidden_visible_phrases=("Upfront Flat-Rate",),
            )

        self.assertEqual(validate_generated_body(body_result(body)), body)

    def test_body_admission_rejects_claim_across_exposure_surfaces(self):
        denied_bodies = (
            "<body><p><span>Free</span><br><span>Estimates</span></p></body>",
            "<body><p>Free Esti<span>mates</span></p></body>",
            "<body><p><span>Free</span><br><span>Esti</span>"
            "<span>mates</span></p></body>",
            '<body><span class="ft-phone-label">Free</span>'
            "<span>Estimates</span></body>",
            '<body><span style="display:block">Free</span>'
            "<span>Estimates</span></body>",
            '<body><p><img src="missing" alt="Free"> Estimates</p></body>',
            '<body><p><span aria-label="Free">Request</span> Estimates</p></body>',
        )
        for denied_body in denied_bodies:
            with self.subTest(body=denied_body):
                with self.assertRaisesRegex(GeneratedBodyError, "Free Estimates"):
                    validate_generated_body(
                        body_result(denied_body),
                        forbidden_visible_phrases=("Free Estimates",),
                    )

        clean_body = (
            "<body><p><span>Free</span><br><span>consultation</span></p></body>"
        )
        self.assertEqual(
            validate_generated_body(
                body_result(clean_body),
                forbidden_visible_phrases=("Free Estimates",),
            ),
            clean_body,
        )

    def test_body_admission_requires_declared_component_children(self):
        relationships = (
            ("site-footer", ("footer-grid", "footer-bottom")),
        )
        valid_body = (
            '<body><footer class="site-footer"><div class="footer-grid"></div>'
            '<div class="footer-bottom"></div></footer></body>'
        )
        self.assertEqual(
            validate_generated_body(
                body_result(valid_body),
                required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
                required_child_class_sequences=relationships,
            ),
            valid_body,
        )

        orphaned_body = (
            '<body><footer class="site-footer"></footer>'
            '<div class="footer-grid"></div><div class="footer-bottom"></div></body>'
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            r"site-footer\[1\].*expected footer-grid, footer-bottom, got none",
        ):
            validate_generated_body(
                body_result(orphaned_body),
                required_class_counts=REQUIRED_FOOTER_CLASS_COUNTS,
                required_child_class_sequences=relationships,
            )

    def test_body_admission_rejects_gated_claim_in_decoded_attributes(self):
        denied_bodies = (
            '<body><button aria-label="Free&#32;Estimates">Request service</button></body>',
            '<body><button aria-label="Free&nbsp;Estimates">Request service</button></body>',
            '<body><button aria-label="Free&#x2003;Estimates">Request service</button></body>',
            '<body><a title="Free%20Estimates">Request service</a></body>',
        )
        for body in denied_bodies:
            with self.subTest(body=body):
                with self.assertRaisesRegex(GeneratedBodyError, "Free Estimates"):
                    validate_generated_body(
                        body_result(body),
                        forbidden_visible_phrases=("Free Estimates",),
                    )

        clean_body = '<body><button aria-label="Request service">Request service</button></body>'
        self.assertEqual(
            validate_generated_body(
                body_result(clean_body),
                forbidden_visible_phrases=("Free Estimates",),
            ),
            clean_body,
        )

    def test_body_admission_resolves_indirect_accessibility_text_in_order(self):
        attributes = (
            "aria-labelledby",
            "aria-describedby",
            "aria-details",
            "aria-errormessage",
        )
        for attribute in attributes:
            with self.subTest(attribute=attribute):
                body = (
                    '<body><span id="estimates-id">Estimates</span>'
                    '<span id="free-id">Free</span>'
                    f'<button {attribute}="free-id estimates-id">Request</button>'
                    "</body>"
                )
                with self.assertRaisesRegex(
                    GeneratedBodyError,
                    "unsupported prospect claims",
                ):
                    validate_generated_body(
                        body_result(body),
                        forbidden_visible_phrases=("Free Estimates",),
                    )

        direct_body = (
            '<body><button aria-label="Request service">Request</button></body>'
        )
        self.assertEqual(
            validate_generated_body(
                body_result(direct_body),
                forbidden_visible_phrases=("Free Estimates",),
            ),
            direct_body,
        )

    def test_body_admission_rejects_invalid_accessibility_text_references(self):
        invalid_bodies = {
            "missing": '<body><button aria-labelledby="missing">Request</button></body>',
            "duplicate": (
                '<body><span id="label">One</span><span id="label">Two</span>'
                '<button aria-labelledby="label">Request</button></body>'
            ),
            "cycle": (
                '<body><span id="one" aria-labelledby="two">One</span>'
                '<span id="two" aria-labelledby="one">Two</span></body>'
            ),
        }
        for label, body in invalid_bodies.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    GeneratedBodyError,
                    "invalid indirect accessibility text reference",
                ):
                    validate_generated_body(body_result(body))

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
            "base": '<body><base href="https://example.test/"><main>Ready</main></body>',
            "link": '<body><link rel="stylesheet" href="theme.css"><main>Ready</main></body>',
            "meta": '<body><meta name="theme-color" content="#000"><main>Ready</main></body>',
            "title": "<body><title>Wrong head title</title><main>Ready</main></body>",
            "placeholder": "<body><main>{{SITE_NAME}}</main></body>",
        }
        for label, content in invalid_bodies.items():
            with self.subTest(label=label):
                with self.assertRaises(GeneratedBodyError):
                    validate_generated_body(body_result(content))

    def test_body_admission_preserves_svg_accessibility_title(self):
        body = "<body><svg><title>Service area map</title></svg></body>"
        self.assertEqual(validate_generated_body(body_result(body)), body)

    def test_body_admission_rejects_executable_attributes(self):
        executable_bodies = (
            '<body><button oNcLiCk="location.href=\'tel:2175550199\'">'
            "Call</button></body>",
            '<body><iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;">'
            "</iframe></body>",
            '<body><a href="java&#x09;script:alert(1)">Open</a></body>',
            '<body><form action="vbscript:alert(1)"></form></body>',
        )
        for body in executable_bodies:
            with self.subTest(body=body), self.assertRaisesRegex(
                GeneratedBodyError,
                "executable attribute",
            ):
                validate_generated_body(body_result(body))

        valid_body = (
            '<body><button data-onclick="call" aria-label="Request service">'
            "Request</button></body>"
        )
        self.assertEqual(validate_generated_body(body_result(valid_body)), valid_body)

    def test_body_admission_rejects_code_owned_comment_markers(self):
        deployment_comment = (
            "<body><!-- WEBSITE REDESIGN MOCKUP\nClient: Test Business -->"
            "<main>Ready</main></body>"
        )
        with self.assertRaisesRegex(GeneratedBodyError, "deployment metadata"):
            validate_generated_body(
                body_result(deployment_comment),
                forbidden_comment_markers=("WEBSITE REDESIGN MOCKUP", "Client:"),
            )

        formspree_todo = (
            "<body><!-- TODO: paste Formspree endpoint -->"
            '<form action="#"></form></body>'
        )
        self.assertEqual(
            validate_generated_body(
                body_result(formspree_todo),
                forbidden_comment_markers=("WEBSITE REDESIGN MOCKUP", "Client:"),
            ),
            formspree_todo,
        )

    def test_required_exposure_uses_complete_token_sequences(self):
        with self.assertRaisesRegex(GeneratedBodyError, "business_name"):
            validate_generated_body(
                body_result("<body><main>About our work</main></body>"),
                required_exposed_values=(("business_name", "A&B"),),
            )

        marked_up_identity = (
            "<body><main><span>A</span>&amp;<span>B</span></main></body>"
        )
        self.assertEqual(
            validate_generated_body(
                body_result(marked_up_identity),
                required_exposed_values=(("business_name", "A&B"),),
            ),
            marked_up_identity,
        )

    def test_prompt_defined_square_placeholders_fail_without_rejecting_other_brackets(self):
        prompt = "Use [PROSPECT.phone], [SITE_SLUG], and [N]-MILE RADIUS. - [ ] check"
        placeholders = extract_square_placeholder_tokens(
            prompt,
            "Industry defaults also define [YEAR] and - [ ] checklist syntax.",
        )

        self.assertIn("[PROSPECT.phone]", placeholders)
        self.assertIn("[SITE_SLUG]", placeholders)
        self.assertIn("[N]", placeholders)
        self.assertIn("[YEAR]", placeholders)
        self.assertNotIn("[ ]", placeholders)
        with self.assertRaisesRegex(GeneratedBodyError, "prompt placeholders"):
            validate_generated_body(
                body_result("<body><main>Call [PROSPECT.phone]</main></body>"),
                forbidden_square_placeholders=placeholders,
            )
        self.assertEqual(
            validate_generated_body(
                body_result("<body><main>Open [Saturday]</main></body>"),
                forbidden_square_placeholders=placeholders,
            ),
            "<body><main>Open [Saturday]</main></body>",
        )

    def test_placeholder_admission_uses_browser_decoded_text_and_attributes(self):
        placeholders = extract_square_placeholder_tokens("Use [YEAR].")
        invalid_bodies = {
            "decimal character references": (
                "<body><main>Serving since &#91;YEAR&#93;</main></body>"
            ),
            "hex character references in an attribute": (
                '<body><main aria-label="Serving since &#x5b;YEAR&#x5d;">Ready</main></body>'
            ),
            "token split across elements": (
                "<body><main>[YE<strong>AR]</strong></main></body>"
            ),
            "encoded curly placeholder": (
                "<body><main>&#123;&#123;SITE_NAME&#125;&#125;</main></body>"
            ),
        }
        for label, content in invalid_bodies.items():
            with self.subTest(label=label):
                with self.assertRaises(GeneratedBodyError):
                    validate_generated_body(
                        body_result(content),
                        forbidden_square_placeholders=placeholders,
                    )

        self.assertEqual(
            validate_generated_body(
                body_result("<body><main>&#91;Saturday&#93;</main></body>"),
                forbidden_square_placeholders=placeholders,
            ),
            "<body><main>&#91;Saturday&#93;</main></body>",
        )

        with self.assertRaisesRegex(GeneratedBodyError, r"\{\{SITE_NAME\}\}"):
            validate_generated_body(
                body_result("<body><main>{{SITE_NAME}}</main></body>")
            )

    def test_placeholder_admission_percent_decodes_attribute_values(self):
        placeholders = extract_square_placeholder_tokens("Use [PROSPECT.phone].")

        with self.assertRaisesRegex(GeneratedBodyError, "prompt placeholders"):
            validate_generated_body(
                body_result(
                    '<body><a href="tel:%5BPROSPECT.phone%5D">Call</a></body>'
                ),
                forbidden_square_placeholders=placeholders,
            )

        valid_body = '<body><a href="/service%20areas">Areas</a></body>'
        self.assertEqual(
            validate_generated_body(
                body_result(valid_body),
                forbidden_square_placeholders=placeholders,
            ),
            valid_body,
        )

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

    def test_assembly_uses_trusted_head_and_code_owned_comment(self):
        trusted_comment = make_html_comment("deployment metadata")
        document = assemble_generated_html(
            body_result(),
            base_template=self.base_template,
            theme_catalog=self.theme_catalog,
            theme_name="warm",
            colors=self.colors,
            title=r"Drees \1 <Plumbing>",
            body_theme="theme-light",
            trusted_head_comment=trusted_comment,
        )

        self.assertTrue(document.startswith("<!DOCTYPE html>"))
        self.assertIn("<head>\n<!--\ndeployment metadata\n-->", document)
        self.assertIn("<title>Drees \\1 &lt;Plumbing&gt;</title>", document)
        self.assertIn("--accent: #B91C1C;", document)
        self.assertIn("--font-display: 'Lexend', sans-serif;", document)
        self.assertIn('<body class="theme-light"><main>Ready</main></body>', document)
        self.assertEqual(document.count(trusted_comment), 1)

    def test_assembly_adds_fixed_image_fallback_after_admission(self):
        generated_body = (
            '<body class="theme-light"><main><img src="/hero.jpg" alt="Team">'
            "Ready</main></body>"
        )
        document = assemble_generated_html(
            body_result(generated_body),
            base_template=self.base_template,
            theme_catalog=self.theme_catalog,
            theme_name="warm",
            colors=self.colors,
            title="Test",
            body_theme="theme-light",
        )

        self.assertIn("onerror=\"this.style.display='none'\"", document)
        self.assertEqual(document.count("onerror="), 1)

    def test_assembly_rejects_unsafe_comment_invalid_color_and_unknown_theme(self):
        with self.assertRaisesRegex(GeneratedHtmlError, "exactly one HTML comment"):
            assemble_generated_html(
                body_result(),
                base_template=self.base_template,
                theme_catalog=self.theme_catalog,
                theme_name="warm",
                colors=self.colors,
                title="Test",
                body_theme="theme-light",
                trusted_head_comment="deployment metadata",
            )

        with self.assertRaisesRegex(GeneratedHtmlError, "unsafe nested delimiter"):
            assemble_generated_html(
                body_result(),
                base_template=self.base_template,
                theme_catalog=self.theme_catalog,
                theme_name="warm",
                colors=self.colors,
                title="Test",
                body_theme="theme-light",
                trusted_head_comment="<!-- unsafe -- delimiter -->",
            )

        with self.assertRaisesRegex(GeneratedHtmlError, "unsafe nested delimiter"):
            assemble_generated_html(
                body_result(),
                base_template=self.base_template,
                theme_catalog=self.theme_catalog,
                theme_name="warm",
                colors=self.colors,
                title="Test",
                body_theme="theme-light",
                trusted_head_comment="<!-- ends--->",
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

    def test_comment_builder_neutralizes_dynamic_closing_delimiter(self):
        comment = make_html_comment("Client: Acme --> injected")

        self.assertEqual(comment.count("<!--"), 1)
        self.assertEqual(comment.count("-->"), 1)
        self.assertIn("Acme - -> injected", comment)

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
                self.assertIn(
                    "Do NOT output HTML head metadata (`<base>`, `<link>`, `<meta>`, or a page `<title>`) anywhere in the body; an accessibility `<title>` nested inside `<svg>` is allowed.",
                    prompt,
                )
                self.assertNotIn("(or a leading comment)", prompt)

    def test_image_fallback_is_code_owned_in_every_wired_html_prompt(self):
        for prompt_path in (
            Path("references/02-redesign-gen-prompt.md"),
            Path("references/04-interior-page-prompt.md"),
            Path("references/06-build-prompt.md"),
        ):
            with self.subTest(prompt=str(prompt_path)):
                prompt = prompt_path.read_text(encoding="utf-8")
                self.assertNotIn("onerror", prompt.casefold())
                self.assertIn("trusted code", prompt.casefold())

    def test_deployment_comments_are_code_owned_and_absent_from_prompts(self):
        for prompt_path, markers in (
            (Path("references/06-build-prompt.md"), build.BUILD_DEPLOYMENT_COMMENT_MARKERS),
            (
                Path("references/02-redesign-gen-prompt.md"),
                pipeline.REDESIGN_DEPLOYMENT_COMMENT_MARKERS,
            ),
        ):
            with self.subTest(prompt=str(prompt_path)):
                prompt = prompt_path.read_text(encoding="utf-8")
                self.assertIn("Trusted code derives", prompt)
                self.assertIn("Do not output", prompt)
                for marker in markers:
                    self.assertNotIn(marker, prompt)

        build_comment = build.build_deployment_comment(
            {
                "business_name": "Test Business",
                "trade": "plumber",
                "city": "Effingham",
                "state": "IL",
                "build_date": "2026-09-01",
            }
        )
        redesign_comment = pipeline.redesign_deployment_comment(
            {"site": {"name": "Current Business"}},
            theme="minimal",
        )
        for comment, markers in (
            (build_comment, build.BUILD_DEPLOYMENT_COMMENT_MARKERS),
            (redesign_comment, pipeline.REDESIGN_DEPLOYMENT_COMMENT_MARKERS),
        ):
            with self.subTest(comment=comment[:40]):
                for marker in markers:
                    self.assertIn(marker, comment)

    def test_build_prompt_does_not_seed_fixture_forbidden_claims(self):
        prompt = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                Path("references/06-build-prompt.md"),
                Path("references/07-industry-defaults.md"),
            )
        ).casefold()
        for claim in build.GATED_SERVICE_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotIn(claim.casefold(), prompt)
        self.assertNotIn("same-day replacement available", prompt)
        self.assertNotIn("same-day repair, multi-day install", prompt)

    def test_build_prompt_conditions_every_business_phone_action(self):
        prompt = Path("references/06-build-prompt.md").read_text(encoding="utf-8")
        defaults = Path("references/07-industry-defaults.md").read_text(
            encoding="utf-8"
        )
        normalized_defaults = " ".join(defaults.split())

        self.assertNotIn("phone number with `tel:` link, single CTA", prompt)
        self.assertNotIn(
            'Plumbers default to urgency_type = "emergency". Render',
            prompt,
        )
        self.assertNotIn(
            "Phone number is a `tel:` link in nav, hero, and footer",
            prompt,
        )
        self.assertIn("If `prospect.phone` is set", prompt)
        self.assertIn("When `prospect.phone` is null or empty", prompt)
        self.assertIn("otherwise no business phone value or phone action", prompt)
        self.assertNotIn("Phone visible in nav, sticky", defaults)
        self.assertNotIn("emergency first -- phone visible", defaults)
        self.assertNotIn("sticky phone", defaults.casefold())
        self.assertIn("When `prospect.phone` is set", normalized_defaults)
        self.assertIn(
            "When `prospect.phone` is null or empty",
            normalized_defaults,
        )


class AtomicWriteAndCliTests(unittest.TestCase):
    def test_uncatalogued_trade_uses_generic_document_colors(self):
        colors = build.resolve_build_document_colors(
            {"business_name": "Test Business", "trade": "roofer"}
        )

        self.assertEqual(colors.accent, DEFAULT_DOCUMENT_ACCENT)
        self.assertEqual(colors.accent_dark, build._darken_hex_color(DEFAULT_DOCUMENT_ACCENT))
        self.assertEqual(colors.secondary, DEFAULT_DOCUMENT_SECONDARY)

    def test_malformed_computed_palette_does_not_use_generic_fallback(self):
        with self.assertRaisesRegex(ValueError, "_computed_palette"):
            build.resolve_build_document_colors(
                {
                    "business_name": "Test Business",
                    "trade": "roofer",
                    "_computed_palette": "not-a-palette",
                }
            )

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
        client = FakeLocalClient(local_chat_payload(COMPLETE_BUILD_BODY))
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        html = build.generate_build_html(prospect, config(), client)

        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("NEW WEBSITE BUILD - - FROM SCRATCH", html)
        self.assertIn(COMPLETE_BUILD_BODY, html)
        request = next(call for call in client.calls if call[0] == "POST")
        user_content = request[2]["json"]["messages"][1]["content"]
        self.assertIn(build.BUILD_RESPONSE_BOUNDARY_REMINDER, user_content)
        self.assertIn(
            '"business_name": "Test Business"',
            user_content,
        )
        self.assertIn('"service-card": 6', user_content)
        self.assertIn("MANDATORY SERVICES: At the position required by", user_content)
        self.assertIn('<div class="services-grid">', user_content)
        self.assertEqual(user_content.count('<div class="service-card">'), 6)
        self.assertEqual(user_content.count('<div class="service-card-name">'), 6)
        self.assertEqual(user_content.count('<p class="service-card-desc">'), 6)
        self.assertIn("[SERVICE_1_NAME]", user_content)
        self.assertIn("[SERVICE_6_DESCRIPTION]", user_content)
        self.assertNotIn("BASE BODY TEMPLATE", user_content)
        self.assertNotIn("{{SITE_NAME}}", user_content)
        self.assertTrue(
            user_content.endswith(
                "No logo URL was supplied. Omit the nav-logo image entirely, show "
                "the text business name, and do not invent a logo URL."
            )
        )

    def test_build_generator_validates_brand_colors_before_model_request(self):
        client = FakeLocalClient(
            local_chat_payload(
                body_with_markers(build.BUILD_DEPLOYMENT_COMMENT_MARKERS)
            )
        )
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "brand_colors": {
                "accent": "#123456",
                "secondary": "red",
            },
        }

        with self.assertRaisesRegex(GeneratedHtmlError, "secondary.*six-digit"):
            build.generate_build_html(prospect, config(), client)

        self.assertEqual(client.calls, [])

    def test_build_generator_rejects_placeholder_from_static_industry_defaults(self):
        leaked_body = COMPLETE_BUILD_BODY.replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero">Serving Effingham since [YEAR]</section>',
        )
        client = FakeLocalClient(local_chat_payload(leaked_body))
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        with self.assertRaisesRegex(GeneratedBodyError, r"\[YEAR\]"):
            build.generate_build_html(prospect, config(), client)

    def test_build_generator_rejects_unresolved_services_scaffold_token(self):
        leaked_body = COMPLETE_BUILD_BODY.replace(
            "Service 1",
            "[SERVICE_1_NAME]",
        )
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        with self.assertRaisesRegex(GeneratedBodyError, r"\[SERVICE_1_NAME\]"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(leaked_body)),
            )

    def test_build_generator_rejects_missing_mandatory_services(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }
        missing_services = COMPLETE_BUILD_BODY.replace(COMPLETE_SERVICES_GRID, "")

        with self.assertRaisesRegex(
            GeneratedBodyError,
            "services-grid expected 1, got 0",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(missing_services)),
            )

    def test_build_generator_rejects_service_cards_outside_the_grid(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }
        service_cards = COMPLETE_SERVICES_GRID.removeprefix(
            '<div class="services-grid">'
        ).removesuffix("</div>")
        orphaned_services = COMPLETE_BUILD_BODY.replace(
            COMPLETE_SERVICES_GRID,
            '<div class="services-grid"></div>' + service_cards,
        )

        with self.assertRaisesRegex(
            GeneratedBodyError,
            r"services-grid\[1\].*got none",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(orphaned_services)),
            )

    def test_build_generator_requires_coverage_band_only_with_a_phone(self):
        body_without_phone = COMPLETE_BUILD_BODY.replace(
            '<a href="tel:2175550100">217-555-0100</a>',
            "",
        )
        body_without_coverage = body_without_phone.replace(
            '<div class="coverage-band"></div>',
            "",
        ).replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero"><a class="cta-planned" '
            'href="#contact">Request Service</a></section>',
        )
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "REPLACE",
        }
        build.sanitize_placeholders(prospect)
        self.assertIsNone(prospect["phone"])

        client = FakeLocalClient(local_chat_payload(body_without_coverage))
        html = build.generate_build_html(
            prospect,
            config(),
            client,
        )
        self.assertIn(body_without_coverage, html)
        request = next(call for call in client.calls if call[0] == "POST")
        user_content = request[2]["json"]["messages"][1]["content"]
        self.assertIn('"coverage-band": 0', user_content)
        self.assertIn("NO VERIFIED BUSINESS PHONE", user_content)
        self.assertIn(
            "omit `.nav-phone`, `.cta-emergency`, `.cta-or`",
            user_content.casefold(),
        )
        self.assertIn("Keep the visitor phone input", user_content)

        verified_client = FakeLocalClient(local_chat_payload(COMPLETE_BUILD_BODY))
        build.generate_build_html(
            {**prospect, "phone": "217-555-0100"},
            config(),
            verified_client,
        )
        verified_request = next(
            call for call in verified_client.calls if call[0] == "POST"
        )
        verified_user_content = verified_request[2]["json"]["messages"][1]["content"]
        self.assertIn("VERIFIED BUSINESS PHONE", verified_user_content)
        self.assertNotIn("NO VERIFIED BUSINESS PHONE", verified_user_content)

        with self.assertRaisesRegex(
            GeneratedBodyError,
            "coverage-band expected 0, got 1",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(COMPLETE_BUILD_BODY)),
            )

        wrong_case_coverage = COMPLETE_BUILD_BODY.replace(
            '<a href="tel:2175550100">217-555-0100</a>',
            "",
        ).replace(
            'class="coverage-band"',
            'class="Coverage-Band"',
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "coverage-band has invalid case variant: Coverage-Band",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_case_coverage)),
            )

        unexpected_phone = body_without_coverage.replace(
            "</nav>",
            '<a href="tel:2175550199">217-555-0199</a></nav>',
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "no verified phone",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(unexpected_phone)),
            )

        unexpected_plain_phone = body_without_coverage.replace(
            "</nav>",
            "<span>Call 217-555-0199</span></nav>",
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "phone-like value with no verified phone",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(unexpected_plain_phone)),
            )

        unexpected_tooltip_phone = body_without_coverage.replace(
            "</nav>",
            '<button title="Call 217-555-0199">Request service</button></nav>',
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "phone-like value with no verified phone",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(unexpected_tooltip_phone)),
            )

        unexpected_accessible_description_phone = body_without_coverage.replace(
            "</nav>",
            '<button aria-description="Call 217-555-0199">'
            "Request service</button></nav>",
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "phone-like value with no verified phone",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(
                    local_chat_payload(unexpected_accessible_description_phone)
                ),
            )

        nested_accessible_description_phone = body_without_coverage.replace(
            '<nav class="site-nav">',
            '<nav class="site-nav" aria-label="Main navigation">',
        ).replace(
            "</nav>",
            '<button aria-description="Call 217-555-0199">'
            "Request service</button></nav>",
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "phone-like value with no verified phone",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(
                    local_chat_payload(nested_accessible_description_phone)
                ),
            )

        unicode_phone_variants = (
            "217\u2011555\u20110199",
            "217\u2013555\u20130199",
            "217\u200b555\u200b0199",
            "\u0662\u0661\u0667-\u0665\u0665\u0665-\u0660\u0661\u0669\u0669",
        )
        for phone_variant in unicode_phone_variants:
            with self.subTest(phone_variant=phone_variant), self.assertRaisesRegex(
                GeneratedBodyError,
                "phone-like value with no verified phone",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(
                        local_chat_payload(
                            body_without_coverage.replace(
                                "</nav>",
                                f"<span>Call {phone_variant}</span></nav>",
                            )
                        )
                    ),
                )

        unverified_action_urls = (
            "sms:2175550199",
            "https://wa.me/%2B12175550199",
        )
        for action_url in unverified_action_urls:
            with self.subTest(action_url=action_url), self.assertRaisesRegex(
                GeneratedBodyError,
                "phone-like value with no verified phone",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(
                        local_chat_payload(
                            body_without_coverage.replace(
                                "</nav>",
                                f'<a href="{action_url}">Contact us</a></nav>',
                            )
                        )
                    ),
                )

        event_handler_phone = body_without_coverage.replace(
            "</nav>",
            '<button onclick="location.href=\'tel:2175550199\'">'
            "Call</button></nav>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "executable attribute"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(event_handler_phone)),
            )

        inline_fragment_phone = body_without_coverage.replace(
            "</nav>",
            '<div aria-label="Call us"><span>21</span>'
            "<span>7-555-0199</span></div></nav>",
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "phone-like value with no verified phone",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(inline_fragment_phone)),
            )

        block_separated_numbers = body_without_coverage.replace(
            "</nav>",
            '<div aria-label="Route notes"><p>21</p>'
            "<p>7-555-0199</p></div></nav>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(block_separated_numbers)),
        )
        self.assertIn("Route notes", html)

        non_exposed_attribute_phones = body_without_coverage.replace(
            "</nav>",
            '<span data-tracking-id="217-555-0199"></span>'
            '<span hidden title="Call 217-555-0199"></span></nav>',
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(non_exposed_attribute_phones)),
        )
        self.assertIn('data-tracking-id="217-555-0199"', html)

        non_phone_numbers = body_without_coverage.replace(
            "</nav>",
            "<span>Route 2011 covers 12 service zones.</span></nav>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(non_phone_numbers)),
        )
        self.assertIn("Route 2011 covers 12 service zones", html)

        prospect["phone"] = "217-555-0100"
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "coverage-band expected 1, got 0",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(body_without_coverage)),
            )

    def test_build_generator_rejects_reviews_without_source_evidence(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "reviews": [],
            "google_review_score": None,
            "google_review_count": None,
        }
        fabricated_reviews = build_body_with_review_section(
            aggregate_review_section("4.9", "127")
        )

        with self.assertRaisesRegex(
            GeneratedBodyError,
            "reviews-aggregate expected 0, got 1",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(fabricated_reviews)),
            )

        ambient_claim = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            '<span class="trust-stars" style="--score: 4.9">Stars</span>'
            "<span>Rated 4.9 by 127 customers</span></nav>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unsourced ambient review"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(ambient_claim)),
            )

        split_inline_claim = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            "<span>Rated 4.</span><span>9 by 127 customers</span></nav>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unsourced ambient review"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(split_inline_claim)),
            )

        testimonial = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap"',
            "<blockquote>They were fantastic.</blockquote><cite>Jane D.</cite>"
            '<form class="contact-form-wrap"',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "testimonial tag"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(testimonial)),
            )

        unscored_widget = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            '<span class="form-trust-stars">Stars</span></nav>',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "without a scored overlay"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(unscored_widget)),
            )

    def test_build_generator_binds_aggregate_review_claims_to_source(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "reviews": [],
            "google_review_score": 4.4,
            "google_review_count": 12,
            "google_business_url": "https://example.com/reviews",
        }
        admitted_body = build_body_with_review_section(
            aggregate_review_section("4.4", "12")
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(admitted_body)),
        )
        self.assertIn(admitted_body, html)

        exact_ambient = admitted_body.replace(
            "</nav>",
            '<span class="trust-stars" style="--score: 4.4">★★★★★</span>'
            "<span>Rated 4.4 by 12 customers</span></nav>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(exact_ambient)),
        )
        self.assertIn("Rated 4.4 by 12 customers", html)

        wrong_count = build_body_with_review_section(
            aggregate_review_section("4.4", "127")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "review count"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_count)),
            )

        wrong_score = build_body_with_review_section(
            aggregate_review_section("4.9", "12")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "review score"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_score)),
            )

        wrong_url = build_body_with_review_section(
            aggregate_review_section("4.4", "12", "https://example.com/invented")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "reviews URL"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_url)),
            )

        non_anchor = build_body_with_review_section(
            aggregate_review_section("4.4", "12")
            .replace('<a class="reviews-cta"', '<span class="reviews-cta"')
            .replace("</a>", "</span>")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "CTA must be an anchor"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(non_anchor)),
            )

        wrong_ambient = admitted_body.replace(
            "</nav>",
            "<span>Rated 4.9 by 127 customers</span></nav>",
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "unexpected ambient review score",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_ambient)),
            )

    def test_build_generator_binds_review_cards_to_source_entries(self):
        reviews = [
            {
                "author": "Ada A.",
                "rating": 5,
                "date": "a month ago",
                "platform": "Google",
                "text": "Prompt and careful work.",
            },
            {
                "author": "Ben B.",
                "rating": 4,
                "date": "two months ago",
                "platform": "Google",
                "text": "Clear communication throughout.",
            },
            {
                "author": "Cora C.",
                "rating": 5,
                "date": "three months ago",
                "platform": "Google",
                "text": "The repair has held up well.",
            },
        ]
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "reviews": reviews,
            "google_review_score": 4.8,
            "google_review_count": 31,
            "google_business_url": "https://example.com/reviews",
        }
        admitted_body = build_body_with_review_section(
            review_card_section(reviews, "4.8", "31")
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(admitted_body)),
        )
        self.assertIn(admitted_body, html)

        fabricated = [dict(review) for review in reviews]
        fabricated[1]["text"] = "Invented review copy."
        fabricated_body = build_body_with_review_section(
            review_card_section(fabricated, "4.8", "31")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "review card"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(fabricated_body)),
            )

        accessible_override = admitted_body.replace(
            '<p class="review-text">Prompt and careful work.</p>',
            '<p class="review-text" role="img" '
            'aria-label="Best plumber in town">Prompt and careful work.</p>',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "review component attribute"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(accessible_override)),
            )

        wrong_rating = [dict(review) for review in reviews]
        wrong_rating[0]["rating"] = 3
        wrong_rating_body = build_body_with_review_section(
            review_card_section(wrong_rating, "4.8", "31")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "review card"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_rating_body)),
            )

        duplicate_card_body = build_body_with_review_section(
            review_card_section([reviews[0], reviews[0], reviews[2]], "4.8", "31")
        )
        with self.assertRaisesRegex(GeneratedBodyError, "review card"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(duplicate_card_body)),
            )

    def test_review_sanitizer_drops_entries_that_cannot_render_truthfully(self):
        valid = {
            "author": "Ada A.",
            "rating": 5,
            "date": "a month ago",
            "platform": "Google",
            "text": "Prompt and careful work.",
        }
        prospect = {
            "reviews": [
                valid,
                {**valid, "author": None},
                {**valid, "rating": "5"},
                {**valid, "rating": 6},
                {**valid, "text": ""},
            ]
        }

        build.sanitize_reviews(prospect)

        self.assertEqual(prospect["reviews"], [valid])

    def test_build_generator_enforces_identity_and_phone_substitutions(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }
        adverse_bodies = (
            (
                COMPLETE_BUILD_BODY.replace("Test Business", "Other Business"),
                "business_name",
            ),
            (
                COMPLETE_BUILD_BODY.replace(">217-555-0100</a>", ">Call now</a>"),
                "phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    ">217-555-0100</a>",
                    ">Call now</a>",
                ).replace(
                    "</nav>",
                    '<input type="hidden" value="217-555-0100"></nav>',
                ),
                "phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    ">217-555-0100</a>",
                    '>Call now</a><span hidden>217-555-0100</span>',
                ),
                "phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    ">217-555-0100</a>",
                    '>Call now</a><span style="display: none">217-555-0100</span>',
                ),
                "phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    '<body class="theme-light">',
                    '<body class="theme-light" hidden>',
                ),
                "business_name",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    '<a href="tel:2175550100">217-555-0100</a>',
                    '<a href="tel:2175550100" '
                    'style="display:none!important">217-555-0100</a>',
                ),
                "missing required visible substitution: phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    '<a href="tel:2175550100">217-555-0100</a>',
                    "<span>217-555-0100</span>",
                ),
                "missing the required tel target",
            ),
            (
                COMPLETE_BUILD_BODY.replace("tel:2175550100", "tel:2175550199"),
                "unexpected tel target",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    "</nav>",
                    '<a href="tel:2175550199">Other number</a></nav>',
                ),
                "unexpected tel target",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    "</nav>",
                    "<span>Alternate 217-555-0199</span></nav>",
                ),
                "unexpected exposed phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    "</nav>",
                    '<button title="Call 217-555-0199">Request service</button>'
                    "</nav>",
                ),
                "unexpected exposed phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    "</nav>",
                    "<span>Alternate 217\u2011555\u20110199</span></nav>",
                ),
                "unexpected exposed phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    "</nav>",
                    '<a href="sms:2175550199">Text us</a></nav>',
                ),
                "unexpected actionable phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    'href="tel:2175550100"',
                    'href="tel:2175550199" href="tel:2175550100"',
                ),
                "duplicate attribute",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    '<span>Test Business</span>'
                    '<a href="tel:2175550100">217-555-0100</a>',
                    '<template><span>Test Business</span>'
                    '<a href="tel:2175550100">217-555-0100</a></template>',
                ),
                "browser-inert tag: template",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    "</nav>",
                    '<form action="https://wa.me/12175550199">'
                    "<button>Message us</button></form></nav>",
                ),
                "unexpected actionable phone",
            ),
            (
                COMPLETE_BUILD_BODY.replace(
                    ">217-555-0100</a>",
                    ">217-555-\u202e0100\u202c</a>",
                ),
                "directional controls",
            ),
        )
        for adverse_body, message in adverse_bodies:
            with self.subTest(message=message), self.assertRaisesRegex(
                GeneratedBodyError,
                message,
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(adverse_body)),
                )

        unicode_formatted_verified_phone = COMPLETE_BUILD_BODY.replace(
            ">217-555-0100</a>",
            ">217\u2011555\u20110100</a>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(unicode_formatted_verified_phone)),
        )
        self.assertIn("217\u2011555\u20110100", html)

        matching_optional_action = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            '<a href="sms:2175550100">Text us</a></nav>',
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(matching_optional_action)),
        )
        self.assertIn("sms:2175550100", html)

    def test_generators_reject_classes_outside_provided_catalog(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }
        invalid_build = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap" action="#">',
            '<div class="invented-layout"></div>'
            '<form class="contact-form-wrap" action="#">',
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "outside the allowed class catalog: invented-layout",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(invalid_build)),
            )

        invalid_page = COMPLETE_PAGE_BODY.replace(
            "<main>",
            '<main class="invented-layout">',
        )
        site_json = {"site": {"name": "Current Business"}}
        generators = (
            lambda: pipeline.generate_redesign(
                site_json,
                theme="minimal",
                generation_config=config(),
                generation_client=FakeLocalClient(local_chat_payload(invalid_page)),
            ),
            lambda: pipeline.generate_interior_page(
                site_json,
                "contact",
                theme="warm",
                generation_config=config(),
                generation_client=FakeLocalClient(local_chat_payload(invalid_page)),
            ),
        )
        for generator in generators:
            with self.subTest(generator=generator), self.assertRaisesRegex(
                GeneratedBodyError,
                "outside the allowed class catalog: invented-layout",
            ):
                generator()

    def test_build_generator_rejects_claim_without_matching_promise(self):
        unsupported = COMPLETE_BUILD_BODY.replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero">Upfront <strong>Flat-Rate</strong> pricing</section>',
        )
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "service_promises": [],
        }

        with self.assertRaisesRegex(GeneratedBodyError, "Upfront Flat-Rate"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(unsupported)),
            )

        prospect["service_promises"] = ["Flat-rate pricing"]
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(unsupported)),
        )
        self.assertIn("Upfront <strong>Flat-Rate</strong> pricing", html)

    def test_build_generator_gates_field_owned_claim_families(self):
        field_claims = (
            ("licensed_and_insured", True, "Licensed & Insured"),
            ("family_owned", True, "Family Owned & Operated"),
            ("locally_owned", True, "Locally Owned, Not a Franchise"),
            ("has_24_7", True, "24/7 Service"),
            ("same_day_service", True, "Same-Day Service"),
            ("same_day_service", True, "Same-day replacement available"),
            ("same_day_service", True, "Same-day repair"),
            ("epa_certified", True, "EPA-Certified Technicians"),
            ("master_electrician_license", "IL-123", "Master Electrician"),
            ("ibew_local_number", "176", "IBEW Local 176 Member"),
        )
        base_prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "service_promises": [],
        }
        for field, supported_value, claim in field_claims:
            claim_body = COMPLETE_BUILD_BODY.replace(
                '<section class="dual-cta-hero"></section>',
                f'<section class="dual-cta-hero">{claim}</section>',
            )
            with self.subTest(field=field, state="unsupported"), self.assertRaisesRegex(
                GeneratedBodyError,
                "unsupported prospect claims",
            ):
                build.generate_build_html(
                    dict(base_prospect),
                    config(),
                    FakeLocalClient(local_chat_payload(claim_body)),
                )

            supported_prospect = dict(base_prospect)
            supported_prospect[field] = supported_value
            html = build.generate_build_html(
                supported_prospect,
                config(),
                FakeLocalClient(local_chat_payload(claim_body)),
            )
            self.assertIn(claim, html)

    def test_build_generator_requires_exact_contact_form_action(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "formspree_endpoint": "https://formspree.io/f/verified",
        }
        wrong_endpoint_body = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap" action="#">',
            '<form class="contact-form-wrap" action="https://formspree.io/f/wrong">',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "contact form action"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_endpoint_body)),
            )

        verified_body = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap" action="#">',
            '<form class="contact-form-wrap" '
            'action="https://formspree.io/f/verified">',
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(verified_body)),
        )
        self.assertIn('action="https://formspree.io/f/verified"', html)

        wrong_override_body = verified_body.replace(
            "</form>",
            '<button type="submit" formaction="https://formspree.io/f/wrong">'
            "Send</button></form>",
            1,
        )
        with self.assertRaisesRegex(GeneratedBodyError, "alternate unverified"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_override_body)),
            )

        verified_override_body = verified_body.replace(
            "</form>",
            '<button type="submit" '
            'formaction="https://formspree.io/f/verified">Send</button></form>',
            1,
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(verified_override_body)),
        )
        self.assertIn('formaction="https://formspree.io/f/verified"', html)

        no_endpoint_prospect = dict(prospect)
        no_endpoint_prospect.pop("formspree_endpoint")
        missing_action_body = COMPLETE_BUILD_BODY.replace(' action="#"', "")
        with self.assertRaisesRegex(GeneratedBodyError, "contact form action"):
            build.generate_build_html(
                no_endpoint_prospect,
                config(),
                FakeLocalClient(local_chat_payload(missing_action_body)),
            )

        html = build.generate_build_html(
            no_endpoint_prospect,
            config(),
            FakeLocalClient(local_chat_payload(COMPLETE_BUILD_BODY)),
        )
        self.assertIn('action="#"', html)

    def test_redesign_generator_assembles_body_with_site_brand_contract(self):
        client = FakeLocalClient(local_chat_payload(COMPLETE_PAGE_BODY))
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
        self.assertIn("WEBSITE REDESIGN MOCKUP", html)
        self.assertIn('class="site-footer"', html)
        self.assertIn('<body class="theme-dark">', html)

    def test_generators_reject_model_authored_deployment_comments(self):
        build_body = COMPLETE_BUILD_BODY.replace(
            '<footer class="site-footer">',
            '<!-- Prospect: Invented Business --><footer class="site-footer">',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "deployment metadata"):
            build.generate_build_html(
                {
                    "business_name": "Test Business",
                    "trade": "plumber",
                    "city": "Effingham",
                    "state": "IL",
                    "phone": "217-555-0100",
                },
                config(),
                FakeLocalClient(local_chat_payload(build_body)),
            )

        redesign_body = COMPLETE_PAGE_BODY.replace(
            '<footer class="site-footer">',
            '<!-- WEBSITE REDESIGN MOCKUP --><footer class="site-footer">',
        )
        for generator in (
            lambda: pipeline.generate_redesign(
                {"site": {"name": "Current Business"}},
                theme="minimal",
                generation_config=config(),
                generation_client=FakeLocalClient(local_chat_payload(redesign_body)),
            ),
            lambda: pipeline.generate_interior_page(
                {"site": {"name": "Current Business"}},
                "contact",
                theme="warm",
                generation_config=config(),
                generation_client=FakeLocalClient(local_chat_payload(redesign_body)),
            ),
        ):
            with self.subTest(generator=generator), self.assertRaisesRegex(
                GeneratedBodyError,
                "deployment metadata",
            ):
                generator()

    def test_interior_generator_assembles_body_without_deployment_comment(self):
        client = FakeLocalClient(local_chat_payload(COMPLETE_PAGE_BODY))
        site_json = {"site": {"name": "Current Business"}}

        html = pipeline.generate_interior_page(
            site_json,
            "contact",
            theme="warm",
            generation_config=config(),
            generation_client=client,
        )

        self.assertIn("<title>Contact | Current Business</title>", html)
        self.assertIn(COMPLETE_PAGE_BODY, html)
        self.assertNotIn("<!-- deployment metadata -->", html)


if __name__ == "__main__":
    unittest.main()
