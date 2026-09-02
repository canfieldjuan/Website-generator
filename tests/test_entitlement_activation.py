import fcntl
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import connect_provider
from lib.connect_entitlement import (
    ACTIVATION_BUSY_CODE,
    AUTHORITY_UNAVAILABLE_CODE,
    ENTITLEMENT_FILE_NAME,
    ENTITLEMENT_LOCK_NAME,
    INSTALL_FAILED_CODE,
    MAX_ENTITLEMENT_BYTES,
    NOT_ACTIVE_CODE,
    SOURCE_INVALID_CODE,
    STORAGE_UNAVAILABLE_CODE,
    EntitlementActivationError,
    EntitlementDecision,
    EntitlementGate,
    entitlement_status,
    install_entitlement,
)
from lib.connect_store import ConnectStore
from lib.connect_v2 import ProviderRuntime, create_app


TOKEN = "A" * 64


class EntitlementActivationTests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get("CONNECT_CONTRACTS_DIR")
        if not configured:
            self.skipTest("CONNECT_CONTRACTS_DIR is required for entitlement fixtures")
        self.fixtures = Path(configured) / "entitlements" / "v1" / "fixtures"
        self.keyring = (self.fixtures / "test-keyring.json").read_bytes()
        self.now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def gate(self, root: Path, *, keys=True) -> EntitlementGate:
        destination = root / "local-connect" / ENTITLEMENT_FILE_NAME
        if keys:
            return EntitlementGate.for_test(
                path=destination,
                keyring_document=self.keyring,
                now=self.now,
            )
        return EntitlementGate(path=destination, keys={}, now=lambda: self.now)

    def source(self, root: Path, fixture: str = "valid/active.json") -> Path:
        source = root / "selected-entitlement.json"
        source.write_bytes((self.fixtures / fixture).read_bytes())
        return source

    def assert_activation_error(self, code, callable_):
        with self.assertRaises(EntitlementActivationError) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)

    def write_installed(self, root: Path, content: bytes) -> Path:
        parent = root / "local-connect"
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        destination = parent / ENTITLEMENT_FILE_NAME
        destination.write_bytes(content)
        destination.chmod(0o600)
        return destination

    def test_status_returns_only_stable_state_and_active_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = self.gate(root)
            self.assertEqual(
                entitlement_status(missing), {"state": "missing", "active": False}
            )

            active_bytes = (self.fixtures / "valid/active.json").read_bytes()
            self.write_installed(root, active_bytes)
            self.assertEqual(
                entitlement_status(missing), {"state": "active", "active": True}
            )

    def test_active_source_is_installed_exactly_and_route_gate_sees_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = self.gate(root)
            source = self.source(root)
            expected = source.read_bytes()

            self.assertEqual(
                install_entitlement(source, gate),
                {"state": "active", "active": True},
            )
            destination = gate.path
            assert destination is not None
            self.assertEqual(destination.read_bytes(), expected)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o077, 0)

            store = ConnectStore(root / "connect.sqlite3")
            runtime = ProviderRuntime(store, lambda _input: (b"<html></html>", "x.html"))
            client = TestClient(create_app(runtime, TOKEN, gate))
            try:
                response = client.get(
                    "/v2/manifest", headers={"Authorization": f"Bearer {TOKEN}"}
                )
                self.assertEqual(response.status_code, 200)
            finally:
                client.close()
                runtime.close()

    def test_installer_sets_exact_private_modes_under_restrictive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = self.gate(root)
            source = self.source(root)
            prior_umask = os.umask(0o777)
            try:
                install_entitlement(source, gate)
            finally:
                os.umask(prior_umask)

            assert gate.path is not None
            self.assertEqual(gate.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(gate.path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (gate.path.parent / ENTITLEMENT_LOCK_NAME).stat().st_mode & 0o777,
                0o600,
            )

    def test_invalid_and_inactive_sources_preserve_existing_entitlement(self):
        cases = (
            ("invalid/bad-signature.json", SOURCE_INVALID_CODE),
            ("valid/expired.json", NOT_ACTIVE_CODE),
            ("valid/not-yet-valid.json", NOT_ACTIVE_CODE),
            ("valid/missing-feature.json", NOT_ACTIVE_CODE),
        )
        for fixture, code in cases:
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                installed = b"prior-entitlement"
                destination = self.write_installed(root, installed)
                gate = self.gate(root)
                source = self.source(root, fixture)

                self.assert_activation_error(
                    code, lambda: install_entitlement(source, gate)
                )
                self.assertEqual(destination.read_bytes(), installed)

    def test_source_must_be_bounded_regular_file_without_final_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = self.gate(root)
            target = self.source(root)
            symlink = root / "selected-link.json"
            symlink.symlink_to(target)
            folder = root / "selected-folder"
            folder.mkdir()
            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * (MAX_ENTITLEMENT_BYTES + 1))

            for source in (symlink, folder, oversized, root / "missing.json"):
                with self.subTest(source=source.name):
                    self.assert_activation_error(
                        SOURCE_INVALID_CODE,
                        lambda source=source: install_entitlement(source, gate),
                    )
            self.assertFalse((root / "local-connect").exists())

    def test_missing_authority_fails_before_source_or_destination_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_source = root / "missing.json"
            gate = self.gate(root, keys=False)

            self.assert_activation_error(
                AUTHORITY_UNAVAILABLE_CODE,
                lambda: install_entitlement(missing_source, gate),
            )
            self.assertFalse((root / "local-connect").exists())

    def test_unsafe_directory_or_destination_fails_without_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "local-connect"
            parent.mkdir(mode=0o700)
            parent.chmod(0o755)
            source = self.source(root)
            gate = self.gate(root)
            self.assert_activation_error(
                STORAGE_UNAVAILABLE_CODE,
                lambda: install_entitlement(source, gate),
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "local-connect"
            parent.mkdir(mode=0o700)
            target = root / "unrelated.json"
            target.write_bytes(b"do-not-replace")
            (parent / ENTITLEMENT_FILE_NAME).symlink_to(target)
            source = self.source(root)
            gate = self.gate(root)
            self.assert_activation_error(
                STORAGE_UNAVAILABLE_CODE,
                lambda: install_entitlement(source, gate),
            )
            self.assertEqual(target.read_bytes(), b"do-not-replace")

    def test_lock_contention_fails_fast_and_preserves_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = (self.fixtures / "valid/active.json").read_bytes()
            destination = self.write_installed(root, active)
            source = self.source(root)
            lock_path = destination.parent / ENTITLEMENT_LOCK_NAME
            with lock_path.open("a+b") as held:
                lock_path.chmod(0o600)
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assert_activation_error(
                    ACTIVATION_BUSY_CODE,
                    lambda: install_entitlement(source, self.gate(root)),
                )
            self.assertEqual(destination.read_bytes(), active)

    def test_unsafe_existing_lock_fails_before_destination_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = (self.fixtures / "valid/active.json").read_bytes()
            destination = self.write_installed(root, prior)
            lock_path = destination.parent / ENTITLEMENT_LOCK_NAME
            lock_path.write_bytes(b"")
            lock_path.chmod(0o644)
            source = self.source(root)

            self.assert_activation_error(
                STORAGE_UNAVAILABLE_CODE,
                lambda: install_entitlement(source, self.gate(root)),
            )
            self.assertEqual(destination.read_bytes(), prior)

    def test_candidate_is_rechecked_under_lock_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_gate = self.gate(root)
            clock = Mock(
                side_effect=(
                    self.now,
                    datetime(2100, 1, 1, tzinfo=timezone.utc),
                )
            )
            gate = EntitlementGate(
                path=base_gate.path,
                keys=base_gate.keys,
                now=clock,
            )
            source = self.source(root)

            self.assert_activation_error(
                NOT_ACTIVE_CODE, lambda: install_entitlement(source, gate)
            )
            assert gate.path is not None
            self.assertFalse(gate.path.exists())
            self.assertEqual(clock.call_count, 2)

    def test_pre_replace_storage_failure_preserves_prior_bytes_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = (self.fixtures / "valid/active.json").read_bytes()
            destination = self.write_installed(root, prior)
            source = self.source(root)
            with patch(
                "lib.connect_entitlement.os.replace",
                side_effect=OSError("simulated replacement failure"),
            ):
                self.assert_activation_error(
                    STORAGE_UNAVAILABLE_CODE,
                    lambda: install_entitlement(source, self.gate(root)),
                )
            self.assertEqual(destination.read_bytes(), prior)
            self.assertEqual(
                list(destination.parent.glob(f".{ENTITLEMENT_FILE_NAME}.*.tmp")), []
            )

    def test_post_replace_failures_never_report_activation_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            gate = self.gate(root)
            with patch(
                "lib.connect_entitlement.os.fsync",
                side_effect=(
                    None,
                    OSError("simulated directory sync failure"),
                    None,
                ),
            ):
                self.assert_activation_error(
                    INSTALL_FAILED_CODE,
                    lambda: install_entitlement(source, gate),
                )
            assert gate.path is not None
            self.assertFalse(gate.path.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            prior = b"prior-entitlement"
            destination = self.write_installed(root, prior)
            base_gate = self.gate(root)
            clock = Mock(
                side_effect=(
                    self.now,
                    self.now,
                    datetime(2100, 1, 1, tzinfo=timezone.utc),
                )
            )
            gate = EntitlementGate(
                path=base_gate.path,
                keys=base_gate.keys,
                now=clock,
            )
            self.assert_activation_error(
                INSTALL_FAILED_CODE,
                lambda: install_entitlement(source, gate),
            )
            self.assertEqual(destination.read_bytes(), prior)
            self.assertEqual(clock.call_count, 3)

    def test_cli_activation_commands_do_not_preflight_or_start_generation(self):
        stdout = io.StringIO()
        with patch.object(
            connect_provider,
            "entitlement_status",
            return_value={"state": "missing", "active": False},
        ), patch.object(
            connect_provider,
            "preflight_generation_provider",
            side_effect=AssertionError("generation preflight must not run"),
        ), redirect_stdout(stdout):
            result = connect_provider.main(["entitlement", "status"])

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), '{"active":false,"state":"missing"}\n')

        stderr = io.StringIO()
        with patch.object(
            connect_provider,
            "install_entitlement",
            side_effect=EntitlementActivationError(
                SOURCE_INVALID_CODE, "The selected source is invalid."
            ),
        ), patch.object(
            connect_provider,
            "preflight_generation_provider",
            side_effect=AssertionError("generation preflight must not run"),
        ), redirect_stderr(stderr):
            result = connect_provider.main(
                ["entitlement", "install", "/tmp/selected.json"]
            )

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue(),
            '{"error":{"code":"CONNECT_ENTITLEMENT_SOURCE_INVALID",'
            '"message":"The selected source is invalid."}}\n',
        )


if __name__ == "__main__":
    unittest.main()
