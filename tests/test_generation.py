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
    '<body class="theme-light"><nav class="site-nav"></nav>'
    '<section class="dual-cta-hero"></section><div class="coverage-band"></div>'
    + COMPLETE_SERVICES_GRID
    + COMPLETE_BENEFITS_GRID
    + '<form class="contact-form-wrap"></form>'
    '<footer class="site-footer"><div class="footer-grid"></div>'
    '<div class="footer-bottom"><p>Copyright</p></div></footer></body>'
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
    ):
        self.calls = []
        self.health_response = FakeLocalResponse(
            {"status": "ok"} if health_payload is _UNSET else health_payload,
            status_error=health_status_error,
        )
        self.models_response = FakeLocalResponse(
            {
                "object": "list",
                "data": [{"id": DEFAULT_LOCAL_MODEL, "object": "model"}],
            }
            if models_payload is _UNSET
            else models_payload,
            status_error=models_status_error,
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
            '<body><div class="service-card SERVICE-CARD service-card '
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

    def test_body_admission_rejects_gated_claim_across_elements(self):
        body = "<body><p>Upfront <strong>Flat-Rate</strong> pricing.</p></body>"
        with self.assertRaisesRegex(GeneratedBodyError, "Upfront Flat-Rate"):
            validate_generated_body(
                body_result(body),
                forbidden_visible_phrases=("Upfront Flat-Rate",),
            )

        self.assertEqual(validate_generated_body(body_result(body)), body)

    def test_body_admission_preserves_rendered_text_boundaries_for_claims(self):
        denied_body = (
            "<body><p><span>Free</span><br><span>Estimates</span></p></body>"
        )
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


class AtomicWriteAndCliTests(unittest.TestCase):
    def test_uncatalogued_trade_uses_generic_document_colors(self):
        colors = build._resolve_build_document_colors(
            {"business_name": "Test Business", "trade": "roofer"}
        )

        self.assertEqual(colors.accent, DEFAULT_DOCUMENT_ACCENT)
        self.assertEqual(colors.accent_dark, build._darken_hex_color(DEFAULT_DOCUMENT_ACCENT))
        self.assertEqual(colors.secondary, DEFAULT_DOCUMENT_SECONDARY)

    def test_malformed_computed_palette_does_not_use_generic_fallback(self):
        with self.assertRaisesRegex(ValueError, "_computed_palette"):
            build._resolve_build_document_colors(
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

    def test_build_generator_requires_coverage_band_only_with_a_phone(self):
        body_without_coverage = COMPLETE_BUILD_BODY.replace(
            '<div class="coverage-band"></div>',
            "",
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
        self.assertNotIn('"coverage-band": 1', user_content)

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
