import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lib.connect_entitlement import (
    ACTIVATION_BUSY_CODE,
    ENTITLEMENT_FILE_NAME,
    ENTITLEMENT_LOCK_NAME,
    EntitlementActivationError,
    EntitlementGate,
    entitlement_status,
    install_entitlement,
)
from lib.connect_store import ConnectStore
from lib.connect_v2 import (
    ProviderLock,
    default_runtime_dir,
    default_state_dir,
    registration_document,
    remove_registration_if_owned,
    write_registration,
)
from lib.connect_windows import (
    WINDOWS_LOCK_LENGTH,
    WINDOWS_LOCK_OFFSET,
    WindowsFileLock,
    _protect_windows_directory,
    atomic_replace_bytes,
    ensure_private_directory,
    local_app_data_root,
    read_bounded_regular_file,
)


TOKEN = "A" * 64


@unittest.skipUnless(os.name == "nt", "native Windows storage tests")
class WindowsConnectStorageTests(unittest.TestCase):
    def setUp(self):
        self.actual_local_app_data = os.environ.get("LOCALAPPDATA")
        configured = os.environ.get("CONNECT_CONTRACTS_DIR")
        if not configured:
            self.skipTest("CONNECT_CONTRACTS_DIR is required")
        self.fixtures = Path(configured) / "entitlements" / "v1" / "fixtures"
        self.keyring = (self.fixtures / "test-keyring.json").read_bytes()
        self.now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def test_default_paths_share_local_app_data_without_xdg(self):
        if self.actual_local_app_data:
            self.assertEqual(
                local_app_data_root(self.actual_local_app_data),
                Path(self.actual_local_app_data),
            )
        with (
            tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory,
            patch.dict(
                os.environ,
                {"LOCALAPPDATA": directory},
                clear=True,
            ),
        ):
            root = Path(directory)
            _protect_windows_directory(root)
            self.assertEqual(local_app_data_root(), root)
            self.assertEqual(
                default_runtime_dir(),
                root / "LocalConnect/runtime/v2/providers",
            )
            self.assertEqual(
                default_state_dir(),
                root / "website-redesign/state",
            )
            self.assertEqual(
                EntitlementGate.from_installation().path,
                root / "LocalConnect" / ENTITLEMENT_FILE_NAME,
            )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(OSError):
                default_runtime_dir()
        with self.assertRaises(OSError):
            local_app_data_root("relative")

    def test_registration_publication_cleanup_and_provider_lock(self):
        with (
            tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory,
            patch.dict(
                os.environ,
                {"LOCALAPPDATA": directory},
                clear=True,
            ),
        ):
            _protect_windows_directory(Path(directory))
            runtime = default_runtime_dir()
            document = registration_document(
                instance_id=str(uuid.uuid4()), port=43127, token=TOKEN, pid=4242
            )
            path = write_registration(runtime, document)
            self.assertEqual(json.loads(path.read_bytes()), document)
            restarted = registration_document(
                instance_id=document["instance_id"],
                port=43128,
                token=TOKEN,
                pid=4243,
            )
            restarted_path = write_registration(runtime, restarted)
            self.assertEqual(restarted_path, path)
            self.assertEqual(json.loads(path.read_bytes()), restarted)
            self.assertEqual(list(runtime.glob("*.json")), [path])

            remove_registration_if_owned(path, "B" * 64)
            self.assertTrue(path.exists())
            remove_registration_if_owned(path, TOKEN)
            self.assertFalse(path.exists())

            state = default_state_dir()
            state.mkdir(parents=True)
            first = ProviderLock(state / "provider.lock")
            try:
                with self.assertRaises(RuntimeError):
                    ProviderLock(state / "provider.lock")
            finally:
                first.close()
                first.close()

    def test_local_app_data_rejects_broad_read_acl(self):
        with tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory:
            _protect_windows_directory(Path(directory))
            self.assertEqual(local_app_data_root(directory), Path(directory))
            subprocess.run(
                [
                    "icacls",
                    directory,
                    "/grant",
                    "*S-1-1-0:(OI)(CI)R",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            with self.assertRaises(OSError):
                local_app_data_root(directory)

    def test_owner_rights_ace_does_not_add_an_untrusted_principal(self):
        with tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory:
            root = Path(directory)
            _protect_windows_directory(root)
            subprocess.run(
                [
                    "icacls",
                    directory,
                    "/grant",
                    "*S-1-3-4:(OI)(CI)F",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(local_app_data_root(directory), root)

    def test_private_reader_rejects_a_reparse_point_ancestor(self):
        with (
            tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory,
            patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=True),
        ):
            root = Path(directory)
            _protect_windows_directory(root)
            target = ensure_private_directory(root / "target", root=root)
            candidate = target / "entitlement.json"
            candidate.write_text("{}", encoding="utf-8")
            junction = root / "LocalConnect"
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )

            with self.assertRaises(OSError):
                read_bounded_regular_file(junction / candidate.name, 16)

    def test_store_rejects_unsafe_existing_database_and_sidecar(self):
        with (
            tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory,
            patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=True),
        ):
            root = Path(directory)
            _protect_windows_directory(root)
            state = ensure_private_directory(root / "website-redesign/state", root=root)
            database = state / "connect-v2.sqlite3"
            store = ConnectStore(database)
            store.instance_id()

            sidecar = Path(f"{database}-wal")
            sidecar.write_bytes(b"unsafe")
            subprocess.run(
                ["icacls", str(sidecar), "/grant", "*S-1-1-0:R"],
                check=True,
                capture_output=True,
                text=True,
            )
            with self.assertRaises(OSError):
                store.instance_id()

            sidecar.unlink()
            subprocess.run(
                ["icacls", str(database), "/grant", "*S-1-1-0:R"],
                check=True,
                capture_output=True,
                text=True,
            )
            with self.assertRaises(OSError):
                ConnectStore(database)

    def test_atomic_replacement_retries_a_short_lived_windows_reader(self):
        with tempfile.TemporaryDirectory(
            dir=self.actual_local_app_data
        ) as directory:
            root = Path(directory)
            _protect_windows_directory(root)
            destination = root / "replaceable.json"
            atomic_replace_bytes(destination, b"old", 16)

            descriptor = os.open(destination, os.O_RDONLY)

            def release_reader():
                time.sleep(0.05)
                os.close(descriptor)

            release = threading.Thread(target=release_reader)
            release.start()
            try:
                atomic_replace_bytes(destination, b"new", 16)
            finally:
                release.join(timeout=1)

            self.assertFalse(release.is_alive())
            self.assertEqual(destination.read_bytes(), b"new")

    def test_entitlement_install_status_and_cross_process_lock_contract(self):
        with (
            tempfile.TemporaryDirectory(dir=self.actual_local_app_data) as directory,
            patch.dict(
                os.environ,
                {"LOCALAPPDATA": directory},
                clear=True,
            ),
        ):
            root = Path(directory)
            _protect_windows_directory(root)
            source = root / "selected-entitlement.json"
            source.write_bytes((self.fixtures / "valid/active.json").read_bytes())
            destination = root / "LocalConnect" / ENTITLEMENT_FILE_NAME
            gate = EntitlementGate.for_test(
                path=destination,
                keyring_document=self.keyring,
                now=self.now,
            )

            self.assertEqual(
                install_entitlement(source, gate),
                {"state": "active", "active": True},
            )
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(
                entitlement_status(gate), {"state": "active", "active": True}
            )

            lock = WindowsFileLock(destination.parent / ENTITLEMENT_LOCK_NAME)
            try:
                self.assertEqual(WINDOWS_LOCK_OFFSET, 0)
                self.assertEqual(WINDOWS_LOCK_LENGTH, 1)
                with self.assertRaises(EntitlementActivationError) as raised:
                    install_entitlement(source, gate)
                self.assertEqual(raised.exception.code, ACTIVATION_BUSY_CODE)
            finally:
                lock.close()
            self.assertEqual(lock.path.read_bytes(), b"\0")


if __name__ == "__main__":
    unittest.main()
