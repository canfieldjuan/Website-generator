import base64
import io
import json
import unittest
from unittest.mock import patch

import connect_provider
from lib.desktop_protocol import (
    MAX_DESKTOP_REQUEST_BYTES,
    decode_desktop_request,
    execute_desktop_request,
    resolve_desktop_generation_config,
    run_desktop_stdio,
)
from lib.generation import (
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_MODEL,
    GeneratedHtmlError,
    GenerationProviderUnavailable,
)
from lib.site_artifact import SiteArtifact
from lib.site_artifact import generate_prepared_site_artifact


PROSPECT = {
    "business_name": "Example Plumbing",
    "trade": "plumber",
    "city": "Effingham",
    "state": "IL",
    "phone": "217-555-0100",
}
HTML = b"<!DOCTYPE html><html><head><title>Ready</title></head><body>Ready</body></html>"


def request(operation, payload, *, protocol=1):
    return {"protocol": protocol, "operation": operation, "payload": payload}


def invoke(document=None, *, raw=None):
    source = raw if raw is not None else json.dumps(document).encode("utf-8")
    output = io.BytesIO()
    exit_code = run_desktop_stdio(io.BytesIO(source), output)
    encoded = output.getvalue()
    return exit_code, encoded, json.loads(encoded)


class DesktopRequestBoundaryTests(unittest.TestCase):
    def test_empty_non_object_duplicate_and_non_finite_json_fail_closed(self):
        cases = (
            b"",
            b"[]",
            b'{"protocol":1,"protocol":1,"operation":"prospect.validate","payload":{}}',
            b'{"protocol":1,"operation":"prospect.validate","payload":{"value":NaN}}',
            b"\xff",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                exit_code, encoded, result = invoke(raw=raw)
                self.assertEqual(exit_code, 2)
                self.assertEqual(result["error"]["code"], "REQUEST_INVALID")
                self.assertEqual(encoded.count(b"\n"), 1)

    def test_oversized_request_stops_after_the_boundary(self):
        raw = b"{" + (b" " * MAX_DESKTOP_REQUEST_BYTES)

        exit_code, _encoded, result = invoke(raw=raw)

        self.assertEqual(exit_code, 2)
        self.assertEqual(result["error"]["code"], "INPUT_TOO_LARGE")

    def test_exact_request_boundary_is_decoded_without_truncation(self):
        compact = json.dumps(request("prospect.validate", {})).encode("utf-8")
        raw = compact + (b" " * (MAX_DESKTOP_REQUEST_BYTES - len(compact)))

        decoded = decode_desktop_request(raw)

        self.assertEqual(decoded["operation"], "prospect.validate")

    def test_partial_extra_and_mixed_request_shapes_are_rejected(self):
        cases = (
            {"protocol": 1, "operation": "prospect.validate"},
            {**request("prospect.validate", {"prospect": PROSPECT}), "extra": True},
            request("prospect.validate", []),
            request("prospect.validate", {"prospect": PROSPECT, "generation": {}}),
        )
        for document in cases:
            with self.subTest(document=document):
                exit_code, _encoded, result = invoke(document)
                self.assertEqual(exit_code, 2)
                self.assertEqual(result["error"]["code"], "REQUEST_INVALID")

    def test_protocol_rejects_boolean_fractional_and_unknown_versions(self):
        for invalid in (True, 1.0, 0, 2):
            with self.subTest(invalid=invalid):
                exit_code, _encoded, result = invoke(
                    request("prospect.validate", {"prospect": PROSPECT}, protocol=invalid)
                )
                self.assertEqual(exit_code, 2)
                self.assertEqual(result["error"]["code"], "PROTOCOL_UNSUPPORTED")

    def test_unknown_operation_is_rejected(self):
        exit_code, _encoded, result = invoke(request("site.deploy", {}))

        self.assertEqual(exit_code, 2)
        self.assertEqual(result["error"]["code"], "OPERATION_UNSUPPORTED")

    def test_strict_decoder_rejects_lone_surrogate(self):
        with self.assertRaisesRegex(ValueError, "strict UTF-8 JSON"):
            decode_desktop_request(
                b'{"protocol":1,"operation":"prospect.validate","payload":{"prospect":"\\ud800"}}'
            )


class DesktopGenerationConfigurationTests(unittest.TestCase):
    def test_local_defaults_are_pinned_and_do_not_trust_proxy_environment(self):
        config = resolve_desktop_generation_config({"provider": "local"})

        self.assertEqual(config.provider, "local")
        self.assertEqual(config.model, DEFAULT_LOCAL_MODEL)
        self.assertEqual(config.base_url, DEFAULT_LOCAL_BASE_URL)
        self.assertFalse(config.trust_env)

    def test_local_loopback_endpoint_and_model_are_editable(self):
        for endpoint in (
            "http://127.0.0.1:9000/v1",
            "http://localhost:9000/v1",
            "http://localhost.:9000/v1",
            "http://[::1]:9000/v1",
        ):
            with self.subTest(endpoint=endpoint):
                config = resolve_desktop_generation_config(
                    {"provider": "local", "model": "local/model", "base_url": endpoint}
                )
                self.assertEqual(config.model, "local/model")
                self.assertEqual(config.base_url, endpoint)

    def test_non_loopback_ambiguous_and_credentialed_endpoints_fail_closed(self):
        endpoints = (
            "https://example.com/v1",
            "http://vllm.internal:8000/v1",
            "http://user:secret@localhost:8000/v1",
            "http://localhost:bad/v1",
            "http://localhost:8000/v1?token=secret",
            "http://localhost:8000/not-v1",
            "file:///tmp/v1",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValueError, "endpoint"):
                    resolve_desktop_generation_config(
                        {"provider": "local", "base_url": endpoint}
                    )

    def test_openrouter_requires_exact_session_fields(self):
        invalid = (
            {"provider": "openrouter"},
            {"provider": "openrouter", "model": "openai/gpt", "api_key": ""},
            {
                "provider": "openrouter",
                "model": "openai/gpt",
                "api_key": "secret",
                "base_url": "https://attacker.example/v1",
            },
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    resolve_desktop_generation_config(value)

        config = resolve_desktop_generation_config(
            {"provider": "openrouter", "model": "openai/gpt", "api_key": "secret"}
        )
        self.assertEqual(config.provider, "openrouter")
        self.assertEqual(config.model, "openai/gpt")
        self.assertEqual(config.api_key, "secret")

    def test_secret_is_not_returned_when_configuration_is_invalid(self):
        secret = "desktop-secret-value"
        exit_code, encoded, result = invoke(
            request(
                "generation.status",
                {
                    "generation": {
                        "provider": "openrouter",
                        "model": "openai/gpt",
                        "api_key": secret,
                        "unexpected": True,
                    }
                },
            )
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            result["error"]["code"], "GENERATION_CONFIGURATION_INVALID"
        )
        self.assertNotIn(secret.encode(), encoded)


class DesktopOperationTests(unittest.TestCase):
    def test_prospect_validation_returns_one_envelope_and_suppresses_library_logs(self):
        def prepare(value):
            print("library progress must not reach stdout")
            return dict(value)

        with patch("lib.desktop_protocol.prepare_site_prospect", side_effect=prepare):
            exit_code, encoded, result = invoke(
                request("prospect.validate", {"prospect": PROSPECT})
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["business_name"], PROSPECT["business_name"])
        self.assertEqual(encoded.count(b"\n"), 1)
        self.assertNotIn(b"library progress", encoded)

    def test_invalid_prospect_returns_field_error_without_claiming_success(self):
        exit_code, _encoded, result = invoke(
            request("prospect.validate", {"prospect": {"business_name": "Only"}})
        )

        self.assertEqual(exit_code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "PROSPECT_INVALID")

    def test_local_status_distinguishes_available_from_unavailable(self):
        document = request(
            "generation.status", {"generation": {"provider": "local"}}
        )
        with patch("lib.desktop_protocol.preflight_generation_provider"):
            exit_code, _encoded, available = invoke(document)
        with patch(
            "lib.desktop_protocol.preflight_generation_provider",
            side_effect=GenerationProviderUnavailable("offline"),
        ):
            unavailable_code, _encoded, unavailable = invoke(document)

        self.assertEqual(exit_code, 0)
        self.assertTrue(available["data"]["available"])
        self.assertEqual(unavailable_code, 0)
        self.assertFalse(unavailable["data"]["available"])

    def test_openrouter_status_validates_without_network_probe(self):
        with patch("lib.desktop_protocol.preflight_generation_provider") as preflight:
            result = execute_desktop_request(
                request(
                    "generation.status",
                    {
                        "generation": {
                            "provider": "openrouter",
                            "model": "openai/gpt",
                            "api_key": "secret",
                        }
                    },
                )
            )

        self.assertTrue(result["available"])
        preflight.assert_not_called()

    def test_site_generation_returns_exact_admitted_artifact(self):
        captured = {}

        def generated(prepared, config):
            captured["prepared"] = prepared
            captured["config"] = config
            return SiteArtifact(HTML, "example-plumbing-homepage.html", prepared)

        generation = {
            "provider": "openrouter",
            "model": "openai/gpt",
            "api_key": "desktop-secret-value",
        }
        with patch(
            "lib.desktop_protocol.prepare_site_prospect", return_value=dict(PROSPECT)
        ), patch("lib.desktop_protocol.preflight_generation_provider"), patch(
            "lib.desktop_protocol.generate_prepared_site_artifact",
            side_effect=generated,
        ):
            exit_code, encoded, result = invoke(
                request("site.generate", {"prospect": PROSPECT, "generation": generation})
            )

        artifact = result["data"]["artifact"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(base64.b64decode(artifact["payload_base64"]), HTML)
        self.assertEqual(artifact["byte_size"], len(HTML))
        self.assertEqual(captured["config"].api_key, generation["api_key"])
        self.assertNotIn(generation["api_key"].encode(), encoded)

    def test_generation_failure_is_safe_and_does_not_echo_secret(self):
        secret = "desktop-secret-value"
        document = request(
            "site.generate",
            {
                "prospect": PROSPECT,
                "generation": {
                    "provider": "openrouter",
                    "model": "openai/gpt",
                    "api_key": secret,
                },
            },
        )
        with patch(
            "lib.desktop_protocol.prepare_site_prospect", return_value=dict(PROSPECT)
        ), patch(
            "lib.desktop_protocol.preflight_generation_provider",
            side_effect=GenerationProviderUnavailable(secret),
        ):
            exit_code, encoded, result = invoke(document)

        self.assertEqual(exit_code, 2)
        self.assertEqual(result["error"]["code"], "GENERATION_UNAVAILABLE")
        self.assertNotIn(secret.encode(), encoded)

    def test_generated_html_admission_failure_has_stable_code(self):
        with patch(
            "lib.desktop_protocol.prepare_site_prospect", return_value=dict(PROSPECT)
        ), patch("lib.desktop_protocol.preflight_generation_provider"), patch(
            "lib.desktop_protocol.generate_prepared_site_artifact",
            side_effect=GeneratedHtmlError("raw provider detail"),
        ):
            exit_code, _encoded, result = invoke(
                request(
                    "site.generate",
                    {"prospect": PROSPECT, "generation": {"provider": "local"}},
                )
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(result["error"]["code"], "GENERATION_FAILED")
        self.assertNotIn("raw provider detail", result["error"]["message"])

    def test_shared_artifact_service_enforces_html_byte_boundary(self):
        config = resolve_desktop_generation_config({"provider": "local"})
        prepared = dict(PROSPECT)
        with patch(
            "build.generate_build_html",
            return_value="x" * (2 * 1024 * 1024),
        ):
            artifact = generate_prepared_site_artifact(prepared, config)
        self.assertEqual(len(artifact.html), 2 * 1024 * 1024)

        with patch(
            "build.generate_build_html",
            return_value="x" * ((2 * 1024 * 1024) + 1),
        ):
            with self.assertRaises(GeneratedHtmlError):
                generate_prepared_site_artifact(prepared, config)

    def test_connect_provider_desktop_subcommand_dispatches_without_starting_http(self):
        with patch.object(connect_provider, "run_desktop_stdio", return_value=7) as desktop:
            result = connect_provider.main(["desktop"])

        self.assertEqual(result, 7)
        desktop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
