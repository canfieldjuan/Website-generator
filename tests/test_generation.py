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
    ActionUrlAdmissionContract,
    DEFAULT_DOCUMENT_ACCENT,
    DEFAULT_DOCUMENT_SECONDARY,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_MODEL,
    DEFAULT_LOCAL_TIMEOUT_SECONDS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    MAX_SHORT_TEXT_OUTPUT_TOKENS,
    MAX_GENERATED_BODY_BYTES,
    MAX_GENERATED_BODY_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_HTML_BYTES,
    REQUIRED_FOOTER_CLASS_COUNTS,
    DocumentColors,
    ImageAdmissionContract,
    LocationAdmissionContract,
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
    generate_with_local_admission_retry,
    make_html_comment,
    preflight_generation_provider,
    resolve_generation_config,
    short_text_generation_config,
    validate_generated_body,
    validate_generated_html,
)


COMPLETE_HTML = """<!DOCTYPE html>
<html lang="en"><head><title>Test</title></head>
<body><main>Ready</main></body></html>"""
COMPLETE_BODY = '<body class="theme-light"><main>Ready</main></body>'
COMPLETE_PAGE_BODY = (
    '<body class="theme-light"><span>Current Business</span><main>Ready</main>'
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
        self.json_calls = 0

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        self.json_calls += 1
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

    def test_vllm_endpoint_aliases_are_supported(self):
        with patch.dict(
            os.environ,
            {
                "VLLM_BASE_URL": "http://127.0.0.1:4321/v1",
                "VLLM_API_KEY": "local-key",
            },
            clear=True,
        ):
            selected = resolve_generation_config()

        self.assertEqual(selected.base_url, "http://127.0.0.1:4321/v1")
        self.assertEqual(selected.api_key, "local-key")

    def test_legacy_runtime_aliases_no_longer_select_the_local_runtime(self):
        with patch.dict(
            os.environ,
            {
                "LM_STUDIO_BASE_URL": "http://127.0.0.1:4321/v1",
                "LM_STUDIO_API_KEY": "legacy-key",
                "LLAMA_CPP_BASE_URL": "http://127.0.0.1:4322/v1",
                "LLAMA_CPP_API_KEY": "older-key",
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


class VllmStartupScriptTests(unittest.TestCase):
    script = Path(__file__).resolve().parents[1] / "scripts/start_vllm_server.sh"
    qwen_adapter_commit = "d42c0510a1bc96526fd51481ffaf70d58435fd10"
    retired_script = (
        Path(__file__).resolve().parents[1] / "scripts/start_llama_server.sh"
    )

    @staticmethod
    def environment(**overrides):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("VLLM_")
            and key not in {"LOCAL_GENERATION_MODEL", "LOCAL_GENERATION_API_KEY"}
        }
        environment.update(overrides)
        return environment

    @staticmethod
    def create_tokenizer_directory(root):
        tokenizer = root / "Qwen tokenizer"
        tokenizer.mkdir()
        (tokenizer / "config.json").write_text("{}", encoding="utf-8")
        (tokenizer / "tokenizer.json").write_text("{}", encoding="utf-8")
        (tokenizer / "tokenizer_config.json").write_text("{}", encoding="utf-8")
        (tokenizer / "chat_template.jinja").write_text(
            "{{ messages }}",
            encoding="utf-8",
        )
        return tokenizer

    @classmethod
    def create_qwen_adapter_checkout(
        cls,
        root,
        *,
        commit=None,
        status="",
        status_exit="0",
    ):
        adapter = root / "Qwen GGUF adapter"
        module = adapter / "vllm_gguf_plugin" / "weights_adapter"
        module.mkdir(parents=True)
        (module / "qwen3_5.py").write_text(
            "# pinned Qwen3.5/3.8 test adapter\n",
            encoding="utf-8",
        )
        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
case "${3-}:${4-}" in
    rev-parse:--show-toplevel)
        printf '%s\n' "${FAKE_GIT_ROOT:?}"
        ;;
    rev-parse:--verify)
        [[ "${5-}" == "HEAD" ]]
        printf '%s\n' "${FAKE_GIT_COMMIT:?}"
        ;;
    status:--porcelain)
        [[ "${FAKE_GIT_STATUS_EXIT:-0}" == "0" ]]
        printf '%s' "${FAKE_GIT_STATUS-}"
        ;;
    *)
        exit 2
        ;;
esac
""",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
        return adapter, {
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "FAKE_GIT_ROOT": str(adapter),
            "FAKE_GIT_COMMIT": commit or cls.qwen_adapter_commit,
            "FAKE_GIT_STATUS": status,
            "FAKE_GIT_STATUS_EXIT": status_exit,
            "VLLM_GGUF_PLUGIN_PATH": str(adapter),
        }

    def test_help_does_not_require_or_load_a_model(self):
        completed = subprocess.run(
            [str(self.script), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VLLM_MODEL_PATH", completed.stdout)

    def test_generator_workflow_tracks_the_active_vllm_launcher(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/generator-tests.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            workflow.count('"scripts/start_vllm_server.sh"'),
            2,
        )

    def test_retired_llama_launcher_fails_with_vllm_instruction(self):
        completed = subprocess.run(
            [str(self.retired_script)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("scripts/start_vllm_server.sh", completed.stderr)

    def test_non_loopback_host_is_rejected_before_launch(self):
        completed = subprocess.run(
            [str(self.script)],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment(
                VLLM_BIN="/bin/true",
                VLLM_MODEL_PATH=str(Path(__file__).resolve()),
                VLLM_HOST="0.0.0.0",
            ),
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("loopback", completed.stderr)

    def test_missing_model_path_is_rejected_before_launch(self):
        completed = subprocess.run(
            [str(self.script)],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment(VLLM_BIN="/bin/true", VLLM_MODEL_PATH=""),
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("VLLM_MODEL_PATH", completed.stderr)

    def test_launcher_defaults_to_one_gpu_and_zero_cpu_offload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tokenizer = self.create_tokenizer_directory(root)
            adapter, adapter_environment = self.create_qwen_adapter_checkout(root)
            fake_server = root / "fake-vllm"
            fake_server.write_text(
                '#!/usr/bin/env bash\n'
                'printf "CUDA_VISIBLE_DEVICES=%s\\n" "${CUDA_VISIBLE_DEVICES-}"\n'
                'printf "VLLM_USE_FLASHINFER_SAMPLER=%s\\n" '
                '"${VLLM_USE_FLASHINFER_SAMPLER-}"\n'
                'printf "PYTHONPATH=%s\\n" "${PYTHONPATH-}"\n'
                'printf "%s\\n" "$@"\n',
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "qwen.gguf"
            model.write_bytes(b"")
            (root / "config.json").write_text("{}", encoding="utf-8")
            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN=str(fake_server),
                    VLLM_MODEL_PATH=str(model),
                    VLLM_TOKENIZER_PATH=str(tokenizer),
                    **adapter_environment,
                ),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        arguments = completed.stdout.splitlines()
        self.assertEqual(arguments[0], "CUDA_VISIBLE_DEVICES=0")
        self.assertEqual(arguments[1], "VLLM_USE_FLASHINFER_SAMPLER=0")
        self.assertEqual(arguments[2].split(":", 1)[0], f"PYTHONPATH={adapter}")
        self.assertEqual(arguments[3:5], ["serve", str(model)])
        self.assertEqual(
            arguments[arguments.index("--tensor-parallel-size") + 1], "1"
        )
        self.assertEqual(arguments[arguments.index("--cpu-offload-gb") + 1], "0")
        self.assertEqual(
            arguments[arguments.index("--generation-config") + 1], "vllm"
        )
        self.assertEqual(
            arguments[arguments.index("--default-chat-template-kwargs") + 1],
            '{"enable_thinking":false}',
        )
        self.assertIn("--no-enable-log-requests", arguments)
        self.assertIn("--disable-uvicorn-access-log", arguments)
        self.assertIn("--enforce-eager", arguments)
        self.assertEqual(
            arguments[arguments.index("--chat-template") + 1],
            str(tokenizer / "chat_template.jinja"),
        )
        self.assertEqual(
            arguments[arguments.index("--tokenizer") + 1], str(tokenizer)
        )
        self.assertEqual(
            arguments[arguments.index("--hf-config-path") + 1], str(root)
        )
        self.assertNotIn("--disable-log-requests", arguments)
        self.assertNotIn("--api-key", arguments)

    def test_default_qwen_gguf_requires_adapter_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tokenizer = self.create_tokenizer_directory(root)
            marker = root / "vllm-started"
            fake_server = root / "fake-vllm"
            fake_server.write_text(
                '#!/usr/bin/env bash\ntouch "${FAKE_VLLM_MARKER:?}"\n',
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "qwen.gguf"
            model.write_bytes(b"")
            (root / "config.json").write_text("{}", encoding="utf-8")

            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN=str(fake_server),
                    VLLM_MODEL_PATH=str(model),
                    VLLM_TOKENIZER_PATH=str(tokenizer),
                    FAKE_VLLM_MARKER=str(marker),
                ),
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("VLLM_GGUF_PLUGIN_PATH", completed.stderr)
            self.assertFalse(marker.exists())

    def test_qwen_config_requires_adapter_even_with_custom_served_alias(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tokenizer = self.create_tokenizer_directory(root)
            model = root / "renamed.gguf"
            model.write_bytes(b"")
            (root / "config.json").write_text(
                '{"model_type": "qwen3_5"}',
                encoding="utf-8",
            )

            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN="/bin/true",
                    VLLM_MODEL_PATH=str(model),
                    VLLM_TOKENIZER_PATH=str(tokenizer),
                    LOCAL_GENERATION_MODEL="renamed/local-model",
                ),
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("VLLM_GGUF_PLUGIN_PATH", completed.stderr)

    def test_default_qwen_gguf_rejects_wrong_or_dirty_adapter_checkout(self):
        rejected_adapters = {
            "wrong commit": ({"commit": "0" * 40}, "pinned to commit"),
            "dirty checkout": ({"status": "?? unexpected.py\n"}, "clean"),
            "unreadable status": ({"status_exit": "1"}, "Unable to verify"),
        }
        for label, (adapter_overrides, expected_error) in rejected_adapters.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                tokenizer = self.create_tokenizer_directory(root)
                _, adapter_environment = self.create_qwen_adapter_checkout(
                    root,
                    **adapter_overrides,
                )
                model = root / "qwen.gguf"
                model.write_bytes(b"")
                (root / "config.json").write_text("{}", encoding="utf-8")

                completed = subprocess.run(
                    [str(self.script)],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=self.environment(
                        VLLM_BIN="/bin/true",
                        VLLM_MODEL_PATH=str(model),
                        VLLM_TOKENIZER_PATH=str(tokenizer),
                        **adapter_environment,
                    ),
                )

                self.assertEqual(completed.returncode, 2)
                self.assertIn(expected_error, completed.stderr)

    def test_non_gguf_model_does_not_require_qwen_adapter_checkout(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            model = Path(temporary_directory) / "qwen.safetensors"
            model.write_bytes(b"")

            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN="/bin/true",
                    VLLM_MODEL_PATH=str(model),
                ),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_numeric_boundaries_reject_values_outside_the_contract(self):
        invalid_values = {
            "port below minimum": {"VLLM_PORT": "0"},
            "port above maximum": {"VLLM_PORT": "65536"},
            "empty context": {"VLLM_MAX_MODEL_LEN": "0"},
            "zero GPU fraction": {"VLLM_GPU_MEMORY_UTILIZATION": "0"},
            "GPU fraction above one": {"VLLM_GPU_MEMORY_UTILIZATION": "1.01"},
            "zero tensor parallelism": {"VLLM_TENSOR_PARALLEL_SIZE": "0"},
            "malformed CUDA list": {"VLLM_CUDA_VISIBLE_DEVICES": "0, 1"},
            "invalid sampler toggle": {"VLLM_USE_FLASHINFER_SAMPLER": "yes"},
            "more workers than visible GPUs": {
                "VLLM_TENSOR_PARALLEL_SIZE": "2",
                "VLLM_CUDA_VISIBLE_DEVICES": "0",
            },
        }
        for label, overrides in invalid_values.items():
            with self.subTest(label=label):
                completed = subprocess.run(
                    [str(self.script)],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=self.environment(
                        VLLM_BIN="/bin/true",
                        VLLM_MODEL_PATH=str(Path(__file__).resolve()),
                        **overrides,
                    ),
                )

                self.assertEqual(completed.returncode, 2)

    def test_numeric_boundary_values_are_accepted(self):
        valid_values = {
            "minimum port and sizes": {
                "VLLM_PORT": "1",
                "VLLM_MAX_MODEL_LEN": "1",
                "VLLM_GPU_MEMORY_UTILIZATION": "0.1",
                "VLLM_TENSOR_PARALLEL_SIZE": "1",
            },
            "maximum port and GPU fraction": {
                "VLLM_PORT": "65535",
                "VLLM_GPU_MEMORY_UTILIZATION": "1",
            },
        }
        for label, overrides in valid_values.items():
            with self.subTest(label=label):
                completed = subprocess.run(
                    [str(self.script)],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=self.environment(
                        VLLM_BIN="/bin/true",
                        VLLM_MODEL_PATH=str(Path(__file__).resolve()),
                        **overrides,
                    ),
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_safe_runtime_contract_is_forwarded_without_word_splitting(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tokenizer = self.create_tokenizer_directory(root)
            fake_server = root / "fake vllm"
            fake_server.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n',
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "Qwen model.gguf"
            model.write_bytes(b"")
            (root / "config.json").write_text("{}", encoding="utf-8")
            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN=str(fake_server),
                    VLLM_MODEL_PATH=str(model),
                    VLLM_TOKENIZER_PATH=str(tokenizer),
                    VLLM_HOST="127.0.0.1",
                    VLLM_PORT="18080",
                    VLLM_MAX_MODEL_LEN="1024",
                    VLLM_GPU_MEMORY_UTILIZATION="0.75",
                    VLLM_TENSOR_PARALLEL_SIZE="2",
                    VLLM_CUDA_VISIBLE_DEVICES="0,1",
                    VLLM_USE_FLASHINFER_SAMPLER="1",
                    LOCAL_GENERATION_MODEL="local/test-model",
                    LOCAL_GENERATION_API_KEY="test-key",
                ),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        arguments = completed.stdout.splitlines()
        self.assertEqual(arguments[:2], ["serve", str(model)])
        self.assertEqual(
            arguments[arguments.index("--served-model-name") + 1],
            "local/test-model",
        )
        self.assertEqual(arguments[arguments.index("--host") + 1], "127.0.0.1")
        self.assertEqual(arguments[arguments.index("--port") + 1], "18080")
        self.assertEqual(arguments[arguments.index("--max-model-len") + 1], "1024")
        self.assertEqual(
            arguments[arguments.index("--gpu-memory-utilization") + 1], "0.75"
        )
        self.assertEqual(
            arguments[arguments.index("--tensor-parallel-size") + 1], "2"
        )
        self.assertEqual(arguments[arguments.index("--api-key") + 1], "test-key")
        self.assertEqual(
            arguments[arguments.index("--chat-template") + 1],
            str(tokenizer / "chat_template.jinja"),
        )
        self.assertIn("--enforce-eager", arguments)

    def test_gguf_without_complete_local_tokenizer_fails_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fake_server = root / "fake-vllm"
            fake_server.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "qwen.gguf"
            model.write_bytes(b"")
            (root / "config.json").write_text("{}", encoding="utf-8")
            tokenizer = self.create_tokenizer_directory(root)
            (tokenizer / "chat_template.jinja").unlink()

            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN=str(fake_server),
                    VLLM_MODEL_PATH=str(model),
                    VLLM_TOKENIZER_PATH=str(tokenizer),
                ),
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("chat_template.jinja", completed.stderr)

    def test_gguf_with_mmproj_sibling_fails_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fake_server = root / "fake-vllm"
            fake_server.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
            )
            fake_server.chmod(0o755)
            model = root / "qwen.gguf"
            model.write_bytes(b"")
            (root / "config.json").write_text("{}", encoding="utf-8")
            (root / "mmproj-qwen.gguf").write_bytes(b"")
            tokenizer = self.create_tokenizer_directory(root)

            completed = subprocess.run(
                [str(self.script)],
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(
                    VLLM_BIN=str(fake_server),
                    VLLM_MODEL_PATH=str(model),
                    VLLM_TOKENIZER_PATH=str(tokenizer),
                ),
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("text-only GGUF directory", completed.stderr)


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
                ("GET", "http://127.0.0.1:8000/health"),
                ("GET", "http://127.0.0.1:8000/v1/models"),
            ],
        )
        self.assertEqual(client.health_response.json_calls, 0)
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
            GenerationProviderUnavailable, "scripts/start_vllm_server.sh"
        ):
            preflight_generation_provider(selected, client=client)

    def test_local_preflight_translates_connection_failure(self):
        selected = config()
        client = FakeLocalClient(health_status_error=ConnectionError("offline"))

        with self.assertRaisesRegex(GenerationProviderUnavailable, "standalone vLLM"):
            preflight_generation_provider(selected, client=client)

    def test_local_preflight_accepts_empty_vllm_health_body(self):
        selected = config()
        client = FakeLocalClient(health_payload=None)

        preflight_generation_provider(selected, client=client)

        self.assertEqual(
            [call[:2] for call in client.calls],
            [
                ("GET", "http://127.0.0.1:8000/health"),
                ("GET", "http://127.0.0.1:8000/v1/models"),
            ],
        )
        self.assertEqual(client.health_response.json_calls, 0)

    def test_local_preflight_rejects_redirect_without_following_it(self):
        client = FakeLocalClient(health_status_code=307)

        with self.assertRaisesRegex(
            GenerationProviderUnavailable,
            "standalone vLLM",
        ):
            preflight_generation_provider(config(), client=client)

        self.assertEqual(len(client.calls), 1)
        self.assertIs(client.calls[0][2]["allow_redirects"], False)

    def test_local_preflight_rejects_malformed_model_identity(self):
        selected = config()
        client = FakeLocalClient(models_payload={"data": [{"id": None}]})

        with self.assertRaisesRegex(GenerationProviderUnavailable, "standalone vLLM"):
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
        self.assertEqual(url, "http://127.0.0.1:8000/v1/chat/completions")
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
        self.assertNotIn("reasoning_format", call["json"])
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

    def test_local_request_rejects_invalid_vllm_base_url_before_dispatch(self):
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

    def test_local_admission_failure_gets_one_source_preserving_retry(self):
        first = body_result("<body><div></body>")
        corrected = body_result()
        original_part = PromptPart("original source contract", cacheable=True)

        def admit(candidate):
            if candidate is first:
                raise GeneratedBodyError("misnested closing tag")
            return "accepted"

        with patch(
            "lib.generation.generate_text",
            side_effect=(first, corrected),
        ) as generator:
            final_result, admitted = generate_with_local_admission_retry(
                config(),
                system_prompt="system",
                user_parts=(original_part,),
                temperature=0.4,
                admit=admit,
                cache_system_prompt=True,
            )

        self.assertIs(final_result, corrected)
        self.assertEqual(admitted, "accepted")
        self.assertEqual(generator.call_count, 2)
        retry_parts = generator.call_args_list[1].kwargs["user_parts"]
        self.assertEqual(retry_parts[0], original_part)
        self.assertIn("misnested closing tag", retry_parts[-1].text)
        self.assertIn("<body><div></body>", retry_parts[-1].text)
        self.assertTrue(generator.call_args_list[1].kwargs["cache_system_prompt"])

    def test_second_local_admission_failure_is_terminal(self):
        attempts = (body_result("first"), body_result("second"))
        admission_attempt = 0

        def reject(_candidate):
            nonlocal admission_attempt
            admission_attempt += 1
            raise GeneratedBodyError(f"rejected attempt {admission_attempt}")

        with patch(
            "lib.generation.generate_text",
            side_effect=attempts,
        ) as generator, self.assertRaisesRegex(
            GeneratedBodyError,
            "rejected attempt 2",
        ):
            generate_with_local_admission_retry(
                config(),
                system_prompt="system",
                user_parts=(PromptPart("source"),),
                temperature=0.4,
                admit=reject,
            )

        self.assertEqual(generator.call_count, 2)

    def test_openrouter_admission_failure_does_not_retry(self):
        candidate = GenerationResult(
            provider="openrouter",
            model="anthropic/example",
            content="invalid",
            finish_reason="stop",
            usage={},
        )

        def reject(_candidate):
            raise GeneratedBodyError("invalid body")

        with patch(
            "lib.generation.generate_text",
            return_value=candidate,
        ) as generator, self.assertRaisesRegex(GeneratedBodyError, "invalid body"):
            generate_with_local_admission_retry(
                config("openrouter", "anthropic/example"),
                system_prompt="system",
                user_parts=(PromptPart("source"),),
                temperature=0.4,
                admit=reject,
            )

        self.assertEqual(generator.call_count, 1)

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

    def test_short_text_cap_stays_below_the_local_context_window(self):
        default_config = config()
        smaller_config = GenerationConfig(
            provider="local",
            model=DEFAULT_LOCAL_MODEL,
            base_url=DEFAULT_LOCAL_BASE_URL,
            api_key="test-key",
            max_output_tokens=1024,
        )

        self.assertEqual(
            short_text_generation_config(default_config).max_output_tokens,
            MAX_SHORT_TEXT_OUTPUT_TOKENS,
        )
        self.assertLess(MAX_SHORT_TEXT_OUTPUT_TOKENS, 49152)
        self.assertEqual(
            short_text_generation_config(smaller_config).max_output_tokens,
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

    def test_body_action_destinations_are_source_owned(self):
        contract = ActionUrlAdmissionContract(
            allowed_urls=(
                "https://source.test/book",
                "https://source.test/form",
            ),
            phones=("217-555-0100",),
            emails=("office@source.test",),
        )
        valid_body = (
            '<body><a href="#contact">Contact</a>'
            '<a href="https://source.test/book">Book</a>'
            '<a href="tel:2175550100">Call</a>'
            '<a href="sms:2175550100?body=Hello">Text</a>'
            '<a href="mailto:office@source.test?subject=Hello">Email</a>'
            '<form action="https://source.test/form">'
            '<button formaction="https://source.test/form">Send</button>'
            "</form></body>"
        )
        self.assertEqual(
            validate_generated_body(
                body_result(valid_body),
                expected_action_urls=contract,
            ),
            valid_body,
        )
        no_action_body = "<body><main>No actions</main></body>"
        self.assertEqual(
            validate_generated_body(
                body_result(no_action_body),
                expected_action_urls=ActionUrlAdmissionContract(),
            ),
            no_action_body,
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "empty actionable destination",
        ):
            validate_generated_body(
                body_result('<body><a href="">Empty</a></body>'),
                expected_action_urls=ActionUrlAdmissionContract(),
            )

        invalid_destinations = (
            '<a href="https://calendly.com/wrong">Book</a>',
            '<area href="//unrelated.test/path">',
            '<a xlink:href="https://unrelated.test/path">Open</a>',
            '<form action="https://unrelated.test/form"></form>',
            '<button formaction="https://unrelated.test/form">Send</button>',
            '<a href="tel:2175550199">Call</a>',
            '<a href="mailto:wrong@source.test">Email</a>',
        )
        for invalid in invalid_destinations:
            mixed_body = (
                '<body><a href="https://source.test/book">Book</a>'
                f"{invalid}</body>"
            )
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                GeneratedBodyError,
                "outside source-owned destinations",
            ):
                validate_generated_body(
                    body_result(mixed_body),
                    expected_action_urls=contract,
                )

    def test_body_admission_restricts_inline_styles_to_declared_properties(self):
        hiding_styles = (
            "opacity: 0",
            "font-size: 0",
            "clip-path: inset(50%)",
            "position: absolute; left: -9999px",
        )
        for style in hiding_styles:
            body = f'<body><span style="{style}">Test Business</span></body>'
            with self.subTest(style=style), self.assertRaisesRegex(
                GeneratedBodyError,
                "unsupported inline style property",
            ):
                validate_generated_body(body_result(body))

        mixed = (
            '<body><span style="--score: 4.8; opacity: 0">★★★★★</span></body>'
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "unsupported inline style property: opacity",
        ):
            validate_generated_body(body_result(mixed))

        allowed = (
            '<body><section style="background-image: url(\'images/hero.jpg\'); '
            'padding: 4rem 0">'
            '<span style="--score: 4.8">★★★★★</span></section></body>'
        )
        self.assertEqual(validate_generated_body(body_result(allowed)), allowed)

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

    def test_pitch_email_uses_the_bounded_short_text_budget(self):
        client = FakeLocalClient(
            local_chat_payload("Subject: A local website\n\n[VERCEL_URL_PLACEHOLDER]")
        )
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        draft = build.generate_email_draft(prospect, config(), client)

        self.assertIn("[VERCEL_URL_PLACEHOLDER]", draft)
        request = next(call for call in client.calls if call[0] == "POST")
        self.assertEqual(
            request[2]["json"]["max_tokens"],
            MAX_SHORT_TEXT_OUTPUT_TOKENS,
        )

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
        request_prompt = "\n".join(
            message["content"] for message in request[2]["json"]["messages"]
        )
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
        self.assertIn("SOURCE-GATED CLAIM ALLOWLIST (EXHAUSTIVE): []", user_content)
        self.assertIn("TENURE CLAIM CONTRACT (OPTIONAL OUTPUT)", user_content)
        self.assertNotIn("Not a Franchise", request_prompt)
        self.assertNotIn("Free Estimates", request_prompt)
        self.assertNotIn("BASE BODY TEMPLATE", user_content)
        self.assertNotIn("{{SITE_NAME}}", user_content)
        self.assertTrue(
            user_content.endswith(
                "No logo URL was supplied. Omit the nav-logo image entirely, show "
                "the text business name, and do not invent a logo URL."
            )
        )

    def test_build_claim_allowlist_uses_the_same_source_evidence_as_admission(self):
        unsupported = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "locally_owned": None,
            "service_promises": [],
        }
        unsupported_instruction = build.source_claim_boundary_instruction(unsupported)
        self.assertIn("SOURCE-GATED CLAIM ALLOWLIST (EXHAUSTIVE): []", unsupported_instruction)
        self.assertNotIn("Not a Franchise", unsupported_instruction)
        self.assertNotIn("Free Estimates", unsupported_instruction)

        verified = {
            **unsupported,
            "locally_owned": True,
            "service_promises": ["We provide free estimates."],
        }
        verified_instruction = build.source_claim_boundary_instruction(verified)
        self.assertIn("Locally Owned", verified_instruction)
        self.assertIn("Not a Franchise", verified_instruction)
        self.assertIn("Free Estimates", verified_instruction)

    def test_build_prompt_filters_only_unverified_source_claim_examples(self):
        catalog = (
            "Locally Owned, Not a Franchise. Licensed & Insured. "
            "Free Estimates. Same Day service. prospect.locally_owned"
        )
        unverified = {
            "locally_owned": None,
            "licensed_and_insured": None,
            "same_day_service": None,
            "service_promises": [],
        }
        filtered = build.filter_unverified_claim_examples(catalog, unverified)
        for claim in ("Locally Owned", "Not a Franchise", "Licensed", "Insured", "Free Estimates", "Same Day"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, filtered)
        self.assertIn("prospect.locally_owned", filtered)

        partially_verified = {
            **unverified,
            "locally_owned": True,
            "service_promises": ["We provide free estimates."],
        }
        filtered = build.filter_unverified_claim_examples(catalog, partially_verified)
        self.assertIn("Locally Owned", filtered)
        self.assertIn("Not a Franchise", filtered)
        self.assertIn("Free Estimates", filtered)
        self.assertNotIn("Licensed & Insured", filtered)
        self.assertNotIn("Same Day", filtered)

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

        ordinary_testimonial = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap"',
            '<p>“They were fantastic.” — Jane D.</p>'
            '<form class="contact-form-wrap"',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unstructured testimonial"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(ordinary_testimonial)),
            )

        for opening_quote, closing_quote in (("‘", "’"), ("'", "'")):
            with self.subTest(quote=(opening_quote, closing_quote)):
                single_quoted_testimonial = ordinary_testimonial.replace(
                    "“They were fantastic.”",
                    f"{opening_quote}They were fantastic.{closing_quote}",
                )
                with self.assertRaisesRegex(
                    GeneratedBodyError,
                    "unstructured testimonial",
                ):
                    build.generate_build_html(
                        prospect,
                        config(),
                        FakeLocalClient(local_chat_payload(single_quoted_testimonial)),
                    )

        attributed_testimonial = ordinary_testimonial.replace(
            "“They were fantastic.”",
            "They were fantastic.",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unstructured testimonial"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(attributed_testimonial)),
            )

        for attribution in (
            "a happy customer",
            "a very loyal repeat customer",
            "loyal client",
            "THE SATISFIED HOMEOWNER",
        ):
            with self.subTest(attribution=attribution), self.assertRaisesRegex(
                GeneratedBodyError,
                "unstructured testimonial",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(
                        local_chat_payload(
                            ordinary_testimonial.replace("Jane D.", attribution)
                        )
                    ),
                )

        ordinary_quotation = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap"',
            '<p>Ask about our “Comfort Club” plan.</p>'
            '<form class="contact-form-wrap"',
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(ordinary_quotation)),
        )
        self.assertIn("Ask about our “Comfort Club” plan.", html)

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

        extra_root_text = admitted_body.replace(
            '<div class="reviews-aggregate">',
            '<div class="reviews-aggregate">“Best plumber in town.” — Jane D.',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "invalid component hierarchy"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(extra_root_text)),
            )

        extra_cta_text = admitted_body.replace(
            "Read All Reviews on Google",
            "Read All Reviews on Google — Best plumber in town",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "invalid CTA text"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(extra_cta_text)),
            )

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
                "text": "“Prompt and careful work.”",
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

        extra_grid_text = admitted_body.replace(
            '<div class="reviews-card-grid">',
            '<div class="reviews-card-grid">Unexpected direct text',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "invalid component hierarchy"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(extra_grid_text)),
            )

        extra_card_text = admitted_body.replace(
            '<div class="review-card">',
            '<div class="review-card">“Best plumber in town.” — Jane D.',
            1,
        )
        with self.assertRaisesRegex(GeneratedBodyError, "invalid component hierarchy"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(extra_card_text)),
            )

        extra_summary_text = admitted_body.replace(
            '<div class="reviews-summary-row">',
            '<div class="reviews-summary-row">“Best plumber in town.” — Jane D.',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "invalid component hierarchy"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(extra_summary_text)),
            )

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
            '<p class="review-text">“Prompt and careful work.”</p>',
            '<p class="review-text" role="img" '
            'aria-label="Best plumber in town">“Prompt and careful work.”</p>',
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
                "unsupported inline style property: display",
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
                "unsupported inline style property: display",
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
                "exactly one generated form",
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
            (
                "master_electrician_license",
                "IL-123",
                "Master Electrician licensed, #IL-123",
            ),
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

    def test_build_generator_binds_master_electrician_license_value(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "electrician",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "master_electrician_license": "IL-123",
        }

        def with_claim(claim):
            return COMPLETE_BUILD_BODY.replace(
                '<section class="dual-cta-hero"></section>',
                f'<section class="dual-cta-hero">{claim}</section>',
            )

        invalid_claims = (
            "Master Electrician",
            "Master Electrician licensed, #IL-999",
            "Master Licensed, #IL-999",
            "Master-Licensed, #IL-999",
            '<span title="Master Electrician licensed, #IL-999">'
            "Master Electrician licensed, #IL-123</span>",
        )
        for claim in invalid_claims:
            with self.subTest(claim=claim), self.assertRaisesRegex(
                GeneratedBodyError,
                "verified Master electrician license",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(with_claim(claim))),
                )

        for exact_claim in (
            "Master Electrician licensed, #IL-123",
            "Master Licensed, #IL-123",
            "Master-Licensed, #IL-123",
            "Master <span>Electrician licensed, #IL-123</span>",
        ):
            with self.subTest(exact_claim=exact_claim):
                html = build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(with_claim(exact_claim))),
                )
                self.assertIn(exact_claim, html)

        with self.assertRaisesRegex(
            GeneratedBodyError,
            "unsupported prospect claims",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(with_claim("Insured"))),
            )

        for empty_license in ("", "#", " ## "):
            with self.subTest(empty_license=empty_license), self.assertRaisesRegex(
                GeneratedBodyError,
                "unsupported prospect claims",
            ):
                build.generate_build_html(
                    {**prospect, "master_electrician_license": empty_license},
                    config(),
                    FakeLocalClient(
                        local_chat_payload(
                            with_claim("Master Electrician licensed, #IL-123")
                        )
                    ),
                )

    def test_build_generator_binds_footer_address_to_source(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        def with_address(value):
            return COMPLETE_BUILD_BODY.replace(
                '<div class="footer-grid"></div>',
                '<div class="footer-grid"><div>'
                f'<div class="ft-address">{value}</div>'
                '</div></div>',
            )

        invented = with_address("123 Main St.<br>Effingham, IL 62401")
        with self.assertRaisesRegex(GeneratedBodyError, "no verified address"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(invented)),
            )
        moved_invented = COMPLETE_BUILD_BODY.replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero"><p>Visit 123 Main St.</p></section>',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected physical address"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(moved_invented)),
            )
        uncatalogued_suffix = COMPLETE_BUILD_BODY.replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero">Visit us at 123 Market Place, '
            'Effingham, IL 62401.</section>',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected physical address"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(uncatalogued_suffix)),
            )
        unpunctuated_full_address = COMPLETE_BUILD_BODY.replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero">Visit us at 123 Market Place '
            'Effingham IL 62401.</section>',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected physical address"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(unpunctuated_full_address)),
            )

        prospect["address"] = "100 W Elm St, Dieterich, IL 62424"
        with self.assertRaisesRegex(GeneratedBodyError, "does not match"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(invented)),
            )
        with self.assertRaisesRegex(GeneratedBodyError, "exactly one"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(COMPLETE_BUILD_BODY)),
            )

        verified = with_address(
            "100 W Elm St,<br><span>Dieterich, IL 62424</span><br>Mon-Fri 8-5"
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(verified)),
        )
        self.assertIn("100 W Elm St,", html)

        wrong_attribute = verified.replace(
            '<div class="ft-address">',
            '<div class="ft-address" title="Visit 123 Main St.">',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected physical address"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_attribute)),
            )

    def test_build_generator_binds_tenure_claims_to_source_values(self):
        base_prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }

        def with_claim(value):
            return COMPLETE_BUILD_BODY.replace(
                '<section class="dual-cta-hero"></section>',
                f'<section class="dual-cta-hero">{value}</section>',
            )

        unsupported_claims = (
            ("Serving since 1999", "establishment year"),
            ("20 years of plumbing service", "years in business"),
            ("50 years experience", "years in business"),
            ("Serving families for 50 years", "years in business"),
            ("Serving local families for decades", "generic tenure"),
        )
        for claim, message in unsupported_claims:
            with self.subTest(claim=claim), self.assertRaisesRegex(
                GeneratedBodyError,
                message,
            ):
                build.generate_build_html(
                    base_prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(with_claim(claim))),
                )

        established_prospect = {**base_prospect, "established_year": 2011}
        with self.assertRaisesRegex(GeneratedBodyError, "establishment year"):
            build.generate_build_html(
                established_prospect,
                config(),
                FakeLocalClient(
                    local_chat_payload(with_claim("Serving since 1999"))
                ),
            )
        exact_established = with_claim(
            "Serving <span>since</span> <span>2011</span>"
        )
        html = build.generate_build_html(
            established_prospect,
            config(),
            FakeLocalClient(local_chat_payload(exact_established)),
        )
        self.assertIn("<span>2011</span>", html)

        years_prospect = {**base_prospect, "years_in_business": 12}
        with self.assertRaisesRegex(GeneratedBodyError, "years in business"):
            build.generate_build_html(
                years_prospect,
                config(),
                FakeLocalClient(
                    local_chat_payload(with_claim("20 years of plumbing service"))
                ),
            )
        exact_years = with_claim("12 years of plumbing service")
        html = build.generate_build_html(
            years_prospect,
            config(),
            FakeLocalClient(local_chat_payload(exact_years)),
        )
        self.assertIn("12 years of plumbing service", html)

        for exact_bare_claim in (
            "12 years experience",
            "Serving families for 12 years",
        ):
            with self.subTest(exact_bare_claim=exact_bare_claim):
                html = build.generate_build_html(
                    years_prospect,
                    config(),
                    FakeLocalClient(
                        local_chat_payload(with_claim(exact_bare_claim))
                    ),
                )
                self.assertIn(exact_bare_claim, html)

        wrong_attribute = with_claim(
            '<span title="Serving since 1999">Serving since 2011</span>'
        )
        with self.assertRaisesRegex(GeneratedBodyError, "establishment year"):
            build.generate_build_html(
                established_prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_attribute)),
            )

        non_tenure_years = with_claim("Includes a sourced 2-year parts warranty")
        html = build.generate_build_html(
            base_prospect,
            config(),
            FakeLocalClient(local_chat_payload(non_tenure_years)),
        )
        self.assertIn("2-year parts warranty", html)

    def test_build_generator_binds_location_and_radius_claims_to_source(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "service_radius": (
                "Effingham and surrounding communities within 25 miles"
            ),
        }

        def with_location(value):
            return COMPLETE_BUILD_BODY.replace(
                '<section class="dual-cta-hero"></section>',
                f'<section class="dual-cta-hero">{value}</section>',
            )

        exact = with_location(
            "Serving Effingham and surrounding communities within 25 miles."
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(exact)),
        )
        self.assertIn("within 25 miles", html)

        adverse = (
            ("Serving Springfield and surrounding communities within 25 miles.", "service location"),
            ("serving springfield and surrounding communities within 25 miles.", "service location"),
            ("Serving Effingham and surrounding communities within 50 miles.", "service radius"),
            ("Located in Springfield, IL.", "location"),
        )
        for claim, message in adverse:
            with self.subTest(claim=claim), self.assertRaisesRegex(
                GeneratedBodyError,
                message,
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(with_location(claim))),
                )

        no_radius = {**prospect, "service_radius": None}
        with self.assertRaisesRegex(GeneratedBodyError, "service radius"):
            build.generate_build_html(
                no_radius,
                config(),
                FakeLocalClient(
                    local_chat_payload(with_location("A 25-mile service area."))
                ),
            )

    def test_build_tenure_instruction_uses_only_verified_values(self):
        absent = build.tenure_contract_instruction(
            build.expected_tenure_contract({})
        )
        self.assertIn("No establishment year is verified", absent)
        self.assertIn("No years-in-business count is verified", absent)

        exact = build.tenure_contract_instruction(
            build.expected_tenure_contract(
                {"established_year": 2011, "years_in_business": 12}
            )
        )
        self.assertIn("exactly 2011", exact)
        self.assertIn("exactly 12 years", exact)

    def test_build_generator_binds_every_image_surface_to_source_assets(self):
        logo_url = "https://assets.example.test/logo.png"
        hero_url = "images/hero.webp"
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "logo_url": logo_url,
            "photos": [{"url": hero_url, "context": "hero"}],
        }
        exact = COMPLETE_BUILD_BODY.replace(
            "<span>Test Business</span>",
            f'<img class="nav-logo" src="{logo_url}" alt="Test Business">',
        ).replace(
            '<section class="dual-cta-hero"></section>',
            '<section class="dual-cta-hero" '
            f'style="background-image: url(\'{hero_url}\');"></section>',
        )
        client = FakeLocalClient(local_chat_payload(exact))
        html = build.generate_build_html(
            prospect,
            config(),
            client,
        )
        self.assertIn(hero_url, html)
        request = next(call for call in client.calls if call[0] == "POST")
        prompt = request[2]["json"]["messages"][1]["content"]
        self.assertIn("IMAGE SOURCE CONTRACT (EXHAUSTIVE)", prompt)
        self.assertIn(logo_url, prompt)
        self.assertIn(hero_url, prompt)

        adverse = (
            exact.replace(logo_url, "https://example.invalid/logo.png"),
            exact.replace(hero_url, "https://example.invalid/hero.png"),
            exact.replace(
                f'src="{logo_url}"',
                f'src="{logo_url}" srcset="{logo_url} 1x, '
                'https://example.invalid/logo@2x.png 2x"',
            ),
        )
        for body in adverse:
            with self.subTest(body=body), self.assertRaisesRegex(
                GeneratedBodyError,
                "image URL outside source-owned assets",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(body)),
                )

        without_logo = dict(prospect)
        without_logo.pop("logo_url")
        with self.assertRaisesRegex(GeneratedBodyError, "nav logo"):
            build.generate_build_html(
                without_logo,
                config(),
                FakeLocalClient(
                    local_chat_payload(
                        COMPLETE_BUILD_BODY.replace(
                            "<span>Test Business</span>",
                            f'<img class="nav-logo" src="{hero_url}" '
                            'alt="Test Business">',
                        )
                    )
                ),
            )

    def test_photo_dependent_hero_shape_falls_back_only_without_asset(self):
        self.assertEqual(
            build.resolve_hero_shape_for_assets(
                {"_computed_hero_shape": "fullbleed", "photos": []}
            ),
            "gradient",
        )
        self.assertEqual(
            build.resolve_hero_shape_for_assets(
                {
                    "_computed_hero_shape": "split",
                    "photos": [{"context": "logo", "url": "images/logo.png"}],
                }
            ),
            "gradient",
        )
        self.assertEqual(
            build.resolve_hero_shape_for_assets(
                {"_computed_hero_shape": "gradient", "photos": []}
            ),
            "gradient",
        )
        self.assertEqual(
            build.resolve_hero_shape_for_assets(
                {
                    "_computed_hero_shape": "fullbleed",
                    "photos": [
                        {"context": "hero", "url": "images/hero.webp"}
                    ],
                }
            ),
            "fullbleed",
        )

    def test_build_generator_binds_ibew_claim_to_exact_local(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "electrician",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
            "ibew_local_number": "176",
        }

        def with_claim(value):
            return COMPLETE_BUILD_BODY.replace(
                '<section class="dual-cta-hero"></section>',
                f'<section class="dual-cta-hero">{value}</section>',
            )

        for claim in ("IBEW Member", "IBEW Local 1 Member"):
            with self.subTest(claim=claim), self.assertRaisesRegex(
                GeneratedBodyError,
                "verified IBEW local number",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(with_claim(claim))),
                )

        split_exact = with_claim(
            "Proud <span>IBEW</span> <span>Local 176</span> Member"
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(split_exact)),
        )
        self.assertIn("<span>IBEW</span> <span>Local 176</span>", html)

        wrong_attribute = with_claim(
            '<span aria-label="IBEW Local 1 Member">IBEW Local 176 Member</span>'
        )
        with self.assertRaisesRegex(
            GeneratedBodyError,
            "verified IBEW local number",
        ):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_attribute)),
            )

    def test_build_claim_allowlist_preserves_exact_ibew_local(self):
        instruction = build.source_claim_boundary_instruction(
            {
                "ibew_local_number": "176",
                "service_promises": [],
            }
        )
        allowlist_instruction = instruction.split(" EXACT SOURCE CLAIMS:", 1)[0]

        self.assertIn('"IBEW Local 176"', allowlist_instruction)
        self.assertNotIn('"IBEW"', allowlist_instruction)
        self.assertIn('["IBEW", "IBEW Local 176"]', instruction)

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

        alternate_form_body = COMPLETE_BUILD_BODY.replace(
            '<form class="contact-form-wrap" action="#">',
            '<form class="contact-form-wrap" '
            'action="https://formspree.io/f/verified">',
        ).replace(
            '<form class="contact-form-wrap"',
            '<form action="https://formspree.io/f/other"></form>'
            '<form class="contact-form-wrap"',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "exactly one generated form"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(alternate_form_body)),
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

    def test_build_generator_rejects_unsourced_action_destinations(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }
        for destination in (
            "https://calendly.com/unrelated-account",
            "/invented-booking-path",
        ):
            body = COMPLETE_BUILD_BODY.replace(
                "</nav>",
                f'<a href="{destination}">Book online</a></nav>',
            )
            with self.subTest(destination=destination), self.assertRaisesRegex(
                GeneratedBodyError,
                "outside source-owned destinations",
            ):
                build.generate_build_html(
                    prospect,
                    config(),
                    FakeLocalClient(local_chat_payload(body)),
                )

    def test_build_generator_binds_every_business_email_to_source(self):
        prospect = {
            "business_name": "Test Business",
            "trade": "plumber",
            "city": "Effingham",
            "state": "IL",
            "phone": "217-555-0100",
        }
        invented_email = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            '<a href="mailto:invented@example.com">invented@example.com</a></nav>',
        )
        with self.assertRaisesRegex(GeneratedBodyError, "no verified business email"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(invented_email)),
            )

        inline_split_email = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            "<span>invented@</span><span>example.com</span></nav>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "no verified business email"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(inline_split_email)),
            )

        block_separated_fragments = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            "<p>invented@</p><p>example.com</p></nav>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(block_separated_fragments)),
        )
        self.assertIn("<p>invented@</p><p>example.com</p>", html)

        prospect["owner_email"] = "owner@realbusiness.test"
        verified_email = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            '<a href="mailto:owner@realbusiness.test">owner@realbusiness.test</a>'
            "</nav>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(verified_email)),
        )
        self.assertIn("mailto:owner@realbusiness.test", html)

        split_verified_email = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            "<p><span>owner@</span><span>realbusiness.test</span></p></nav>",
        )
        html = build.generate_build_html(
            prospect,
            config(),
            FakeLocalClient(local_chat_payload(split_verified_email)),
        )
        self.assertIn("<span>owner@</span><span>realbusiness.test</span>", html)

        prefixed_verified_email = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            "<p><span>invented</span><span>owner@realbusiness.test</span></p></nav>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected business email"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(prefixed_verified_email)),
            )

        split_wrong_email = COMPLETE_BUILD_BODY.replace(
            "</nav>",
            "<p><span>invented@</span><span>example.com</span></p></nav>",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected business email"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(split_wrong_email)),
            )

        wrong_email = verified_email.replace(
            "owner@realbusiness.test",
            "invented@example.com",
        )
        with self.assertRaisesRegex(GeneratedBodyError, "unexpected business email"):
            build.generate_build_html(
                prospect,
                config(),
                FakeLocalClient(local_chat_payload(wrong_email)),
            )

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

    def test_redesign_generators_bind_identity_and_action_destinations(self):
        source_url = "https://current.test/book"
        site_json = {
            "site": {"name": "Current Business"},
            "cta": {"label": "Book", "url": source_url},
        }

        def generators(body):
            return (
                lambda: pipeline.generate_redesign(
                    site_json,
                    theme="minimal",
                    generation_config=config(),
                    generation_client=FakeLocalClient(local_chat_payload(body)),
                ),
                lambda: pipeline.generate_interior_page(
                    site_json,
                    "contact",
                    theme="warm",
                    generation_config=config(),
                    generation_client=FakeLocalClient(local_chat_payload(body)),
                ),
            )

        exact_body = COMPLETE_PAGE_BODY.replace(
            "</main>",
            f'<a href="{source_url}">Book</a><a href="#contact">Contact</a></main>',
        )
        for generator in generators(exact_body):
            html = generator()
            self.assertIn(f'href="{source_url}"', html)

        wrong_identity = COMPLETE_PAGE_BODY.replace(
            "Current Business",
            "Invented Business",
        )
        for generator in generators(wrong_identity):
            with self.assertRaisesRegex(GeneratedBodyError, "site_name"):
                generator()

        wrong_destination = exact_body.replace(
            source_url,
            "https://calendly.com/unrelated-account",
        )
        for generator in generators(wrong_destination):
            with self.assertRaisesRegex(
                GeneratedBodyError,
                "outside source-owned destinations",
            ):
                generator()

        fetched_source_url = "https://current.test/source-only-action"
        fetched_body = COMPLETE_PAGE_BODY.replace(
            "</main>",
            f'<a href="{fetched_source_url}">Source action</a></main>',
        )
        html = pipeline.generate_interior_page(
            {"site": {"name": "Current Business"}},
            "contact",
            source_content=f'<a href="{fetched_source_url}">Original</a>',
            theme="warm",
            generation_config=config(),
            generation_client=FakeLocalClient(local_chat_payload(fetched_body)),
        )
        self.assertIn(f'href="{fetched_source_url}"', html)

    def test_contact_fallback_only_handles_source_fetch_failures(self):
        page = {
            "page_type": "contact",
            "url": "https://current.test/contact",
            "fetchable": True,
        }
        site_json = {"site": {"name": "Current Business"}}
        with patch(
            "pipeline.fetch_and_clean_html",
            return_value="<main>Verified contact source</main>",
        ), patch(
            "pipeline.generate_interior_page",
            side_effect=GenerationResponseError("rejected generated body"),
        ) as generator:
            with self.assertRaisesRegex(
                GenerationResponseError,
                "rejected generated body",
            ):
                pipeline._generate_contact_page(
                    site_json,
                    page,
                    "minimal",
                    config(),
                )
        self.assertEqual(generator.call_count, 1)
        self.assertEqual(
            generator.call_args.kwargs["source_content"],
            "<main>Verified contact source</main>",
        )

        with patch(
            "pipeline.fetch_and_clean_html",
            side_effect=RuntimeError("source unavailable"),
        ), patch(
            "pipeline.generate_interior_page",
            return_value="fallback page",
        ) as generator:
            result = pipeline._generate_contact_page(
                site_json,
                page,
                "minimal",
                config(),
            )
        self.assertEqual(result, "fallback page")
        generator.assert_called_once_with(
            site_json,
            "contact",
            theme="minimal",
            generation_config=config(),
        )

    def test_redesign_generators_bind_contacts_and_images_to_extracted_json(self):
        logo_url = "https://assets.example.test/logo.png"
        hero_url = "images/hero.webp"
        site_json = {
            "site": {
                "name": "Current Business",
                "contact": {
                    "phone": "217-555-0100",
                    "email": "office@current.test",
                    "addresses": [
                        "123 Market Place, Effingham, IL 62401",
                    ],
                },
            },
            "brand": {"logo_url": logo_url},
            "images": [{"url": hero_url, "context": "hero"}],
        }
        exact_body = COMPLETE_PAGE_BODY.replace(
            '<main>Ready</main>',
            '<main style="background-image: url(\'images/hero.webp\');">'
            f'<img class="nav-logo" src="{logo_url}" alt="Current Business">'
            '<a href="tel:2175550100">217-555-0100</a>'
            '<a href="mailto:office@current.test">office@current.test</a>'
            '<div class="ft-address">123 Market Place, Effingham, IL 62401</div>'
            '</main>',
        )

        def generators(body):
            return (
                lambda: pipeline.generate_redesign(
                    site_json,
                    theme="minimal",
                    generation_config=config(),
                    generation_client=FakeLocalClient(local_chat_payload(body)),
                ),
                lambda: pipeline.generate_interior_page(
                    site_json,
                    "contact",
                    theme="warm",
                    generation_config=config(),
                    generation_client=FakeLocalClient(local_chat_payload(body)),
                ),
            )

        for generator in generators(exact_body):
            with self.subTest(path="exact"):
                html = generator()
                self.assertIn("office@current.test", html)
                self.assertIn(hero_url, html)

        adverse = (
            (
                exact_body.replace("217-555-0100", "217-555-0199").replace(
                    "2175550100", "2175550199"
                ),
                "phone outside extracted source data",
            ),
            (
                exact_body.replace("office@current.test", "other@example.test"),
                "email outside extracted source data",
            ),
            (
                exact_body.replace(
                    "123 Market Place, Effingham, IL 62401",
                    "999 Invented Plaza, Springfield, IL 62701",
                ),
                "footer address is outside extracted source data",
            ),
            (
                exact_body.replace(hero_url, "https://example.invalid/hero.png"),
                "image URL outside source-owned assets",
            ),
        )
        for body, message in adverse:
            for generator in generators(body):
                with self.subTest(message=message), self.assertRaisesRegex(
                    GeneratedBodyError,
                    message,
                ):
                    generator()

        image_logo_contract = pipeline._redesign_image_contract(
            {
                "brand": {"logo_url": ""},
                "images": [{"url": logo_url, "context": "logo"}],
            }
        )
        self.assertEqual(image_logo_contract.nav_logo_url, logo_url)

    def test_redesign_contact_contract_covers_every_structured_source(self):
        contract = pipeline._redesign_contact_contract(
            {
                "site": {
                    "contact": {
                        "phone": "217-555-0100",
                        "email": "primary@example.test",
                        "addresses": ["1 Primary Place, Effingham, IL 62401"],
                    }
                },
                "conversion_profile": {"phone": "217-555-0101"},
                "contact_form": {
                    "contact_info": {
                        "email": "form@example.test",
                        "address": "2 Form Place, Effingham, IL 62401",
                    }
                },
                "single_page_sections": [
                    {
                        "content": {
                            "contact_info": {
                                "phone": "217-555-0102",
                                "email": "section@example.test",
                                "address": "3 Section Place, Effingham, IL 62401",
                            }
                        }
                    }
                ],
            }
        )

        self.assertEqual(
            contract.phones,
            ("217-555-0100", "217-555-0101", "217-555-0102"),
        )
        self.assertEqual(
            contract.emails,
            (
                "primary@example.test",
                "form@example.test",
                "section@example.test",
            ),
        )
        self.assertEqual(
            contract.addresses,
            (
                "1 Primary Place, Effingham, IL 62401",
                "2 Form Place, Effingham, IL 62401",
                "3 Section Place, Effingham, IL 62401",
            ),
        )

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
