import hashlib
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

import build
import connect_provider
from lib.connect_entitlement import EntitlementDecision, EntitlementGate
from lib.connect_store import ConnectStore, JobConflict, ProviderBusy, canonical_json
from lib.connect_v2 import (
    APP_ID,
    CAPABILITY_ID,
    CAPABILITY_VERSION,
    DEFAULT_LOCAL_MODEL,
    MAX_INPUT_BYTES,
    OUTPUT_MEDIA_TYPE,
    ProviderLock,
    ProviderRuntime,
    create_app,
    decode_job_request,
    default_runtime_dir,
    default_state_dir,
    error_response,
    generate_website_artifact,
    job_status_document,
    manifest,
    new_bearer_token,
    registration_document,
    remove_registration_if_owned,
    resolve_connect_generation_config,
    sanitize_display_name,
    validate_job_request,
    write_registration,
)
from lib.generation import (
    GenerationConfigurationError,
    GenerationProviderUnavailable,
    GenerationResponseError,
)


TOKEN = "A" * 64
HTML = b"<!DOCTYPE html><html><head><title>Test</title></head><body>Ready</body></html>"
PROSPECT = {
    "business_name": "Example Plumbing",
    "trade": "plumber",
    "city": "Effingham",
    "state": "IL",
    "phone": "217-555-0100",
}


def artifact_bytes(size=None):
    encoded = json.dumps(PROSPECT, separators=(",", ":")).encode("utf-8")
    if size is None:
        return encoded
    if size < len(encoded):
        raise ValueError("Requested fixture size is smaller than the prospect JSON.")
    return encoded + (b" " * (size - len(encoded)))


def job_request(data, *, job_id=None, artifact_id=None, **artifact_updates):
    artifact = {
        "artifact_id": artifact_id or str(uuid.uuid4()),
        "media_type": "application/json",
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "display_name": "prospect.json",
        "source_app_id": "email-watcher",
    }
    artifact.update(artifact_updates)
    return {
        "protocol_version": 2,
        "job_id": job_id or str(uuid.uuid4()),
        "capability": {"id": CAPABILITY_ID, "version": CAPABILITY_VERSION},
        "inputs": [artifact],
        "parameters": {},
    }


def multipart_parts(request_document, data, *, artifact_media="application/json"):
    return [
        (
            "request",
            (None, canonical_json(request_document), "application/json"),
        ),
        ("artifact", ("prospect.json", data, artifact_media)),
    ]


def fake_generation(_input):
    return HTML, "example-plumbing-homepage.html"


class MutableEntitlementGate:
    def __init__(self, decision=EntitlementDecision.ACTIVE):
        self.current = decision

    def decision(self):
        return self.current


class RequestBoundaryTests(unittest.TestCase):
    def test_valid_request_and_exact_capability_are_accepted(self):
        validate_job_request(job_request(artifact_bytes()))

    def test_missing_and_extra_keys_are_rejected(self):
        document = job_request(artifact_bytes())
        del document["parameters"]
        document["surprise"] = True

        with self.assertRaisesRegex(ValueError, "missing parameters; unexpected surprise"):
            validate_job_request(document)

    def test_boolean_fractional_and_out_of_range_sizes_are_rejected(self):
        for invalid in (False, 1.5, -1, MAX_INPUT_BYTES + 1):
            with self.subTest(invalid=invalid):
                document = job_request(artifact_bytes())
                document["inputs"][0]["byte_size"] = invalid
                with self.assertRaises(ValueError):
                    validate_job_request(document)

    def test_integral_numeric_forms_and_size_boundaries_are_admitted(self):
        for boundary in (0, 1.0, MAX_INPUT_BYTES):
            with self.subTest(boundary=boundary):
                document = job_request(b"")
                document["inputs"][0]["byte_size"] = boundary
                validate_job_request(document)

    def test_unsupported_capability_media_and_parameters_fail_closed(self):
        mutations = (
            lambda value: value["capability"].update(version="2.0"),
            lambda value: value["inputs"][0].update(media_type="text/plain"),
            lambda value: value["parameters"].update(theme="warm"),
        )
        for mutate in mutations:
            document = job_request(artifact_bytes())
            mutate(document)
            with self.assertRaises(ValueError):
                validate_job_request(document)

    def test_non_uuid4_and_duplicate_json_keys_are_rejected(self):
        document = job_request(artifact_bytes())
        document["job_id"] = str(uuid.uuid1())
        with self.assertRaises(ValueError):
            validate_job_request(document)

        with self.assertRaisesRegex(ValueError, "strict UTF-8 JSON"):
            decode_job_request(b'{"protocol_version":2,"protocol_version":2}')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ConnectStore(Path(self.temp.name) / "connect.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_instance_identity_is_stable_and_database_is_owner_private(self):
        first = self.store.instance_id()
        second = ConnectStore(self.store.path).instance_id()

        self.assertEqual(first, second)
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)

    def test_same_request_is_idempotent_but_conflicting_id_is_rejected(self):
        data = artifact_bytes()
        request = job_request(data)
        request_hash = hashlib.sha256(canonical_json(request).encode()).hexdigest()

        first, created = self.store.accept(
            request=request, request_hash=request_hash, input_bytes=data
        )
        replay, replay_created = self.store.accept(
            request=request, request_hash=request_hash, input_bytes=data
        )
        conflicting = json.loads(json.dumps(request))
        conflicting["inputs"][0]["display_name"] = "different.json"

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(first.job_id, replay.job_id)
        with self.assertRaises(JobConflict):
            self.store.accept(
                request=conflicting,
                request_hash=hashlib.sha256(
                    canonical_json(conflicting).encode()
                ).hexdigest(),
                input_bytes=data,
            )

    def test_second_active_job_is_rejected_by_database_constraint(self):
        first_data = artifact_bytes()
        first = job_request(first_data)
        self.store.accept(
            request=first,
            request_hash=hashlib.sha256(canonical_json(first).encode()).hexdigest(),
            input_bytes=first_data,
        )
        second = job_request(first_data)

        with self.assertRaises(ProviderBusy):
            self.store.accept(
                request=second,
                request_hash=hashlib.sha256(
                    canonical_json(second).encode()
                ).hexdigest(),
                input_bytes=first_data,
            )

    def test_restart_marks_processing_ambiguous_and_resumes_accepted(self):
        processing_data = artifact_bytes()
        processing_request = job_request(processing_data)
        processing_hash = hashlib.sha256(
            canonical_json(processing_request).encode()
        ).hexdigest()
        self.store.accept(
            request=processing_request,
            request_hash=processing_hash,
            input_bytes=processing_data,
        )
        self.assertTrue(self.store.mark_processing(processing_request["job_id"]))

        runtime = ProviderRuntime(self.store, fake_generation)
        try:
            interrupted = self.store.get(processing_request["job_id"])
            self.assertEqual(interrupted.status, "failed")
            self.assertEqual(interrupted.error_code, "PROVIDER_INTERRUPTED")
            self.assertTrue(interrupted.error_retryable)

            accepted_request = job_request(processing_data)
            accepted_hash = hashlib.sha256(
                canonical_json(accepted_request).encode()
            ).hexdigest()
            self.store.accept(
                request=accepted_request,
                request_hash=accepted_hash,
                input_bytes=processing_data,
            )
        finally:
            runtime.close()

        resumed = ProviderRuntime(self.store, fake_generation)
        try:
            completed = resumed.wait_for_terminal(accepted_request["job_id"])
            self.assertEqual(completed.status, "completed")
        finally:
            resumed.close()


class ProviderApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ConnectStore(Path(self.temp.name) / "connect.sqlite3")
        self.runtime = ProviderRuntime(self.store, fake_generation)
        self.entitlement = MutableEntitlementGate()
        self.client = TestClient(
            create_app(self.runtime, TOKEN, self.entitlement)
        )
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        self.client.close()
        self.runtime.close()
        self.temp.cleanup()

    def submit(self, document, data, **kwargs):
        files = kwargs.pop("files", multipart_parts(document, data))
        return self.client.post("/v2/jobs", headers=self.headers, files=files, **kwargs)

    def test_all_routes_require_the_exact_bearer_token(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            with self.subTest(headers=headers):
                response = self.client.get("/v2/manifest", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error"]["code"], "AUTHENTICATION_REQUIRED")

        response = self.client.get("/v2/manifest", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), manifest(self.runtime.instance_id))

    def test_job_completes_with_integrity_bound_html_output(self):
        data = artifact_bytes()
        document = job_request(data)
        response = self.submit(document, data)

        self.assertEqual(response.status_code, 202)
        completed = self.runtime.wait_for_terminal(document["job_id"])
        status_response = self.client.get(
            f"/v2/jobs/{document['job_id']}", headers=self.headers
        )
        output = status_response.json()["result"]["outputs"][0]
        self.assertEqual(completed.status, "completed")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(output["media_type"], OUTPUT_MEDIA_TYPE)
        self.assertEqual(output["byte_size"], len(HTML))
        self.assertEqual(output["sha256"], hashlib.sha256(HTML).hexdigest())
        self.assertEqual(output["payload_base64"], __import__("base64").b64encode(HTML).decode())
        self.assertNotEqual(output["artifact_id"], document["inputs"][0]["artifact_id"])

    def test_same_request_replays_and_conflicting_job_id_fails(self):
        data = artifact_bytes()
        document = job_request(data)
        self.assertEqual(self.submit(document, data).status_code, 202)
        self.runtime.wait_for_terminal(document["job_id"])

        replay = self.submit(document, data)
        self.assertEqual(replay.status_code, 200)
        conflicting = json.loads(json.dumps(document))
        conflicting["inputs"][0]["display_name"] = "changed.json"
        conflict = self.submit(conflicting, data)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "JOB_ID_CONFLICT")

    def test_integral_numeric_forms_replay_as_the_same_request(self):
        data = artifact_bytes()
        document = job_request(data)
        document["protocol_version"] = 2.0
        document["inputs"][0]["byte_size"] = float(len(data))
        self.assertEqual(self.submit(document, data).status_code, 202)
        self.runtime.wait_for_terminal(document["job_id"])

        replay = json.loads(json.dumps(document))
        replay["protocol_version"] = 2
        replay["inputs"][0]["byte_size"] = len(data)
        self.assertEqual(self.submit(replay, data).status_code, 200)

    def test_artifact_size_digest_and_part_media_must_match(self):
        data = artifact_bytes()
        cases = []
        wrong_size = job_request(data)
        wrong_size["inputs"][0]["byte_size"] -= 1
        cases.append((wrong_size, "application/json", "ARTIFACT_IDENTITY_MISMATCH"))
        wrong_hash = job_request(data)
        wrong_hash["inputs"][0]["sha256"] = "0" * 64
        cases.append((wrong_hash, "application/json", "ARTIFACT_IDENTITY_MISMATCH"))
        cases.append((job_request(data), "text/plain", "INPUT_MEDIA_UNSUPPORTED"))

        for document, media, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                response = self.submit(
                    document,
                    data,
                    files=multipart_parts(document, data, artifact_media=media),
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], expected_code)

    def test_multipart_order_missing_and_extra_parts_fail(self):
        data = artifact_bytes()
        document = job_request(data)
        request_part, artifact_part = multipart_parts(document, data)
        cases = (
            [artifact_part, request_part],
            [request_part],
            [request_part, artifact_part, ("extra", (None, "x"))],
        )
        for files in cases:
            with self.subTest(parts=[item[0] for item in files]):
                response = self.submit(document, data, files=files)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "MULTIPART_INVALID")

    def test_input_maximum_passes_and_max_plus_one_is_rejected(self):
        maximum = artifact_bytes(MAX_INPUT_BYTES)
        accepted = self.submit(job_request(maximum), maximum)
        self.assertEqual(accepted.status_code, 202)
        self.runtime.wait_for_terminal(accepted.json()["job_id"])

        too_large = artifact_bytes(MAX_INPUT_BYTES + 1)
        rejected = self.submit(job_request(too_large), too_large)
        self.assertEqual(rejected.status_code, 413)
        self.assertEqual(rejected.json()["error"]["code"], "INPUT_TOO_LARGE")

    def test_invalid_job_path_is_distinct_from_missing_job(self):
        invalid = self.client.get("/v2/jobs/not-a-uuid", headers=self.headers)
        missing = self.client.get(f"/v2/jobs/{uuid.uuid4()}", headers=self.headers)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)


class ConcurrencyAndFailureTests(unittest.TestCase):
    def test_active_generation_rejects_a_second_job(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_generation(_input):
            started.set()
            release.wait(timeout=2)
            return HTML, "result.html"

        with tempfile.TemporaryDirectory() as directory:
            runtime = ProviderRuntime(
                ConnectStore(Path(directory) / "connect.sqlite3"), blocking_generation
            )
            client = TestClient(
                create_app(runtime, TOKEN, MutableEntitlementGate())
            )
            headers = {"Authorization": f"Bearer {TOKEN}"}
            data = artifact_bytes()
            try:
                first = job_request(data)
                self.assertEqual(
                    client.post(
                        "/v2/jobs",
                        headers=headers,
                        files=multipart_parts(first, data),
                    ).status_code,
                    202,
                )
                self.assertTrue(started.wait(timeout=1))
                second = job_request(data)
                response = client.post(
                    "/v2/jobs",
                    headers=headers,
                    files=multipart_parts(second, data),
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "PROVIDER_BUSY")
                self.assertTrue(response.json()["error"]["retryable"])
            finally:
                release.set()
                client.close()
                runtime.close()

    def test_invalid_input_and_model_unavailability_have_distinct_failures(self):
        failures = (
            (lambda _input: (_ for _ in ()).throw(ValueError("bad input")), "INPUT_INVALID", False),
            (
                lambda _input: (_ for _ in ()).throw(
                    GenerationProviderUnavailable("offline")
                ),
                "MODEL_RUNTIME_UNAVAILABLE",
                True,
            ),
            (
                lambda _input: (_ for _ in ()).throw(
                    GenerationResponseError("truncated")
                ),
                "MODEL_RESPONSE_INVALID",
                True,
            ),
        )
        for generation, expected_code, retryable in failures:
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as directory:
                runtime = ProviderRuntime(
                    ConnectStore(Path(directory) / "connect.sqlite3"), generation
                )
                data = artifact_bytes()
                document = job_request(data)
                runtime.accept(document, data)
                try:
                    failed = runtime.wait_for_terminal(document["job_id"])
                    self.assertEqual(failed.error_code, expected_code)
                    self.assertEqual(failed.error_retryable, retryable)
                finally:
                    runtime.close()


class GenerationSeamTests(unittest.TestCase):
    def test_connect_generation_forces_local_qwen_and_reuses_build_preparation(self):
        captured = {}

        def generated(prospect, config):
            captured["prospect"] = prospect
            captured["config"] = config
            return HTML.decode()

        with patch.object(build, "generate_build_html", side_effect=generated):
            output, name = generate_website_artifact(artifact_bytes())

        self.assertEqual(output, HTML)
        self.assertEqual(name, "example-plumbing-homepage.html")
        self.assertEqual(captured["config"].provider, "local")
        self.assertEqual(captured["config"].model, DEFAULT_LOCAL_MODEL)
        self.assertIn("_computed_theme", captured["prospect"])
        self.assertIn("build_date", captured["prospect"])

    def test_connect_generation_uses_photo_free_hero_without_supplied_asset(self):
        generated_prospects = []

        def select_split(prospect, *, announce=True):
            prospect["_computed_hero_shape"] = "split"
            return prospect

        def generated(prospect, _config):
            generated_prospects.append(prospect)
            return HTML.decode()

        missing_assets = []
        for photos in (
            None,
            [],
            [{"context": "hero", "url": "   "}],
            [{"context": "gallery", "url": "https://images.example.test/other.jpg"}],
        ):
            source = dict(PROSPECT)
            if photos is not None:
                source["photos"] = photos
            missing_assets.append(source)
        supplied_asset = dict(PROSPECT)
        supplied_asset["photos"] = [
            {
                "context": "background",
                "url": "https://images.example.test/hero.jpg",
            }
        ]
        with patch.object(
            build, "apply_design_selections", side_effect=select_split
        ), patch.object(
            build, "generate_build_html", side_effect=generated
        ):
            for source in (*missing_assets, supplied_asset):
                generate_website_artifact(json.dumps(source).encode("utf-8"))

        for prospect in generated_prospects[:-1]:
            self.assertEqual(prospect["_computed_hero_shape"], "gradient")
        self.assertEqual(generated_prospects[-1]["_computed_hero_shape"], "split")

    def test_required_prospect_fields_must_be_nonempty_strings(self):
        for invalid in (123, True, [], "   "):
            with self.subTest(invalid=invalid):
                source = dict(PROSPECT)
                source["business_name"] = invalid
                with self.assertRaisesRegex(ValueError, "non-empty strings"):
                    build.prepare_prospect(source)

    def test_malformed_required_field_is_nonretryable_input_failure(self):
        source = dict(PROSPECT)
        source["business_name"] = 123
        data = json.dumps(source).encode("utf-8")
        document = job_request(data)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            build, "generate_build_html"
        ) as generated:
            runtime = ProviderRuntime(
                ConnectStore(Path(directory) / "connect.sqlite3"),
                generate_website_artifact,
            )
            try:
                runtime.accept(document, data)
                failed = runtime.wait_for_terminal(document["job_id"])
                self.assertEqual(failed.status, "failed")
                self.assertEqual(failed.error_code, "INPUT_INVALID")
                self.assertFalse(failed.error_retryable)
                generated.assert_not_called()
            finally:
                runtime.close()

    def test_connect_generation_accepts_only_literal_loopback_endpoints(self):
        valid_endpoints = (
            "http://localhost:1234/v1",
            "https://127.0.0.7:9443/v1",
            "http://[::1]:1234/v1",
        )
        for endpoint in valid_endpoints:
            with self.subTest(valid=endpoint), patch.dict(
                os.environ,
                {"LOCAL_GENERATION_BASE_URL": endpoint},
            ):
                self.assertEqual(resolve_connect_generation_config().base_url, endpoint)

        invalid_endpoints = (
            "https://api.example.com/v1",
            "http://127.0.0.1.example.com/v1",
            "http://0.0.0.0:1234/v1",
            "file:///tmp/model",
        )
        for endpoint in invalid_endpoints:
            with self.subTest(invalid=endpoint), patch.dict(
                os.environ,
                {"LOCAL_GENERATION_BASE_URL": endpoint},
            ):
                with self.assertRaisesRegex(
                    GenerationConfigurationError,
                    "loopback",
                ):
                    resolve_connect_generation_config()

    def test_in_memory_preparation_matches_file_loading_without_mutating_input(self):
        source = dict(PROSPECT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prospect.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            loaded = build.load_prospect(path)
        prepared = build.prepare_prospect(source)

        self.assertEqual(loaded, prepared)
        self.assertEqual(source, PROSPECT)

    def test_duplicate_keys_in_prospect_artifact_fail_before_generation(self):
        duplicated = (
            b'{"business_name":"First","business_name":"Second",'
            b'"trade":"plumber","city":"Effingham","state":"IL",'
            b'"phone":"217-555-0100"}'
        )
        with self.assertRaisesRegex(ValueError, "valid prospect"):
            generate_website_artifact(duplicated)

    def test_provider_preflight_failure_does_not_publish_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                runtime_dir=Path(directory) / "runtime",
                state_dir=Path(directory) / "state",
            )
            with patch.object(connect_provider, "parse_args", return_value=args), patch.object(
                connect_provider,
                "preflight_generation_provider",
                side_effect=GenerationProviderUnavailable("offline"),
            ), patch.object(connect_provider, "write_registration") as write:
                self.assertEqual(connect_provider.main(), 2)
                write.assert_not_called()

    def test_registration_is_published_only_after_listener_accepts_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                runtime_dir=Path(directory) / "runtime",
                state_dir=Path(directory) / "state",
            )
            observed = {"connected": False}

            def assert_listening(runtime_dir, document):
                endpoint = urlsplit(document["transport"]["base_url"])
                with socket.create_connection(
                    (endpoint.hostname, endpoint.port),
                    timeout=1.0,
                ):
                    observed["connected"] = True
                return Path(runtime_dir) / "registration.json"

            with patch.object(
                connect_provider,
                "parse_args",
                return_value=args,
            ), patch.object(
                connect_provider,
                "resolve_connect_generation_config",
                return_value=SimpleNamespace(),
            ), patch.object(
                connect_provider,
                "preflight_generation_provider",
            ), patch.object(
                connect_provider,
                "write_registration",
                side_effect=assert_listening,
            ), patch.object(connect_provider.uvicorn.Server, "run"):
                self.assertEqual(connect_provider.main(), 0)

            self.assertTrue(observed["connected"])


class EntitlementTests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get("CONNECT_CONTRACTS_DIR")
        if not configured:
            self.skipTest("CONNECT_CONTRACTS_DIR is required for entitlement fixtures")
        self.fixtures = Path(configured) / "entitlements" / "v1" / "fixtures"
        self.keyring = (self.fixtures / "test-keyring.json").read_bytes()
        self.now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def write_fixture(self, root, name):
        parent = Path(root) / "local-connect"
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        path = parent / "entitlement-v1.json"
        path.write_bytes((self.fixtures / name).read_bytes())
        path.chmod(0o600)
        return path

    def test_canonical_entitlement_fixtures_match_contract_decisions(self):
        cases = {
            "valid/active.json": EntitlementDecision.ACTIVE,
            "valid/expired.json": EntitlementDecision.EXPIRED,
            "valid/not-yet-valid.json": EntitlementDecision.NOT_YET_VALID,
            "valid/missing-feature.json": EntitlementDecision.FEATURE_MISSING,
            "invalid/unknown-key.json": EntitlementDecision.INVALID,
            "invalid/bad-signature.json": EntitlementDecision.INVALID,
            "invalid/duplicate-claim-key.json": EntitlementDecision.INVALID,
            "invalid/malformed-base64.json": EntitlementDecision.INVALID,
        }
        for fixture, expected in cases.items():
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as root:
                path = self.write_fixture(root, fixture)
                gate = EntitlementGate.for_test(
                    path=path, keyring_document=self.keyring, now=self.now
                )
                self.assertEqual(gate.decision(), expected)

    def test_missing_authority_missing_file_and_unsafe_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "local-connect" / "entitlement-v1.json"
            no_authority = EntitlementGate(path=missing, keys={}, now=lambda: self.now)
            self.assertEqual(
                no_authority.decision(), EntitlementDecision.AUTHORITY_UNAVAILABLE
            )
            gate = EntitlementGate.for_test(
                path=missing, keyring_document=self.keyring, now=self.now
            )
            self.assertEqual(gate.decision(), EntitlementDecision.MISSING)

            path = self.write_fixture(root, "valid/active.json")
            path.chmod(0o644)
            self.assertEqual(gate.decision(), EntitlementDecision.MISSING)

    def test_every_route_rechecks_entitlement_and_authentication_stays_first(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConnectStore(Path(root) / "connect.sqlite3")
            runtime = ProviderRuntime(store, fake_generation)
            entitlement = MutableEntitlementGate(EntitlementDecision.EXPIRED)
            client = TestClient(create_app(runtime, TOKEN, entitlement))
            headers = {"Authorization": f"Bearer {TOKEN}"}
            data = artifact_bytes()
            document = job_request(data)
            try:
                self.assertEqual(client.get("/v2/manifest").status_code, 401)
                denied = (
                    client.get("/v2/manifest", headers=headers),
                    client.post("/v2/jobs", headers=headers),
                    client.get(f"/v2/jobs/{document['job_id']}", headers=headers),
                )
                for response in denied:
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(
                        response.json()["error"]["code"],
                        "CONNECT_ENTITLEMENT_REQUIRED",
                    )

                entitlement.current = EntitlementDecision.ACTIVE
                self.assertEqual(
                    client.get("/v2/manifest", headers=headers).status_code, 200
                )
                accepted = client.post(
                    "/v2/jobs",
                    headers=headers,
                    files=multipart_parts(document, data),
                )
                self.assertEqual(accepted.status_code, 202)
                runtime.wait_for_terminal(document["job_id"])

                entitlement.current = EntitlementDecision.MISSING
                self.assertEqual(
                    client.get(
                        f"/v2/jobs/{document['job_id']}", headers=headers
                    ).status_code,
                    403,
                )
            finally:
                client.close()
                runtime.close()


class RegistrationTests(unittest.TestCase):
    def test_registration_is_private_atomic_and_token_rotates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConnectStore(Path(directory) / "state" / "connect.sqlite3")
            instance_id = store.instance_id()
            first_token = new_bearer_token()
            second_token = new_bearer_token()
            document = registration_document(
                instance_id=instance_id, port=43127, token=first_token, pid=4242
            )
            path = write_registration(Path(directory) / "runtime", document)

            self.assertNotEqual(first_token, second_token)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(json.loads(path.read_text()), document)
            self.assertEqual(ConnectStore(store.path).instance_id(), instance_id)

            remove_registration_if_owned(path, second_token)
            self.assertTrue(path.exists())
            remove_registration_if_owned(path, first_token)
            self.assertFalse(path.exists())

    def test_registration_boundaries_and_exclusive_lock_fail_closed(self):
        instance_id = str(uuid.uuid4())
        for invalid_port in (False, 0, 65_536):
            with self.subTest(port=invalid_port), self.assertRaises(ValueError):
                registration_document(
                    instance_id=instance_id, port=invalid_port, token=TOKEN, pid=1
                )
        with self.assertRaises(ValueError):
            registration_document(
                instance_id=instance_id, port=1, token=TOKEN, pid=False
            )

        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "provider.lock"
            first = ProviderLock(lock_path)
            try:
                with self.assertRaises(RuntimeError):
                    ProviderLock(lock_path)
            finally:
                first.close()

    def test_relative_xdg_directories_are_rejected(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "relative"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "absolute"):
                default_runtime_dir()
        with patch.dict(os.environ, {"XDG_STATE_HOME": "relative"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "absolute"):
                default_state_dir()

    def test_constructed_output_name_cannot_escape_or_lose_html_extension(self):
        self.assertEqual(sanitize_display_name("../../outside"), "outside.html")
        long_name = sanitize_display_name("x" * 400)
        self.assertLessEqual(len(long_name), 255)
        self.assertTrue(long_name.endswith(".html"))


class CanonicalContractTests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get("CONNECT_CONTRACTS_DIR")
        if not configured:
            self.skipTest("CONNECT_CONTRACTS_DIR is required for canonical schema checks")
        self.schemas = Path(configured) / "schemas" / "v2"

    def validate(self, name, document):
        schema = json.loads((self.schemas / name).read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)

    def test_manifest_registration_completed_and_failed_shapes_match_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConnectStore(Path(directory) / "connect.sqlite3")
            instance_id = store.instance_id()
            self.validate("manifest.schema.json", manifest(instance_id))
            self.validate(
                "registration.schema.json",
                registration_document(
                    instance_id=instance_id, port=43127, token=TOKEN, pid=4242
                ),
            )

            data = artifact_bytes()
            completed_request = job_request(data)
            self.validate("job-request.schema.json", completed_request)
            self.validate(
                "error.schema.json",
                json.loads(
                    error_response(
                        409, "PROVIDER_BUSY", "Provider is busy.", True
                    ).body
                ),
            )
            request_hash = hashlib.sha256(
                canonical_json(completed_request).encode()
            ).hexdigest()
            store.accept(
                request=completed_request,
                request_hash=request_hash,
                input_bytes=data,
            )
            store.mark_processing(completed_request["job_id"])
            store.complete(
                completed_request["job_id"],
                artifact_id=str(uuid.uuid4()),
                display_name="result.html",
                output_bytes=HTML,
            )
            self.validate(
                "job-status.schema.json",
                job_status_document(store.get(completed_request["job_id"]), instance_id),
            )

            failed_request = job_request(data)
            failed_hash = hashlib.sha256(canonical_json(failed_request).encode()).hexdigest()
            store.accept(
                request=failed_request,
                request_hash=failed_hash,
                input_bytes=data,
            )
            store.fail(
                failed_request["job_id"],
                code="INPUT_INVALID",
                message="Invalid prospect.",
                retryable=False,
            )
            self.validate(
                "job-status.schema.json",
                job_status_document(store.get(failed_request["job_id"]), instance_id),
            )


if __name__ == "__main__":
    unittest.main()
