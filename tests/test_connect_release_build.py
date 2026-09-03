import base64
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.build_connect_provider import (
    BINARY_NAME,
    BUNDLE_DIRECTORY,
    BUNDLE_FILENAME,
    KEYRING_ENV,
    ReleaseBuildError,
    build_release,
    main,
    validate_release_keyring,
)


def encoded_key(value: bytes = b"P" * 32) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class ConnectReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.keyring = self.root / "keyring.json"
        self.write_keyring()

    def tearDown(self):
        self.temporary.cleanup()

    def write_keyring(self, *, key_id="local-connect-prod-2026-01", public_key=None):
        document = {
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "Ed25519",
                    "public_key_base64url": public_key or encoded_key(),
                }
            ]
        }
        self.keyring.write_text(json.dumps(document), encoding="utf-8")

    def test_valid_production_keyring_is_admitted_exactly(self):
        original = self.keyring.read_bytes()
        self.assertEqual(validate_release_keyring(self.keyring), original)

    def test_missing_empty_partial_duplicate_and_test_keyrings_fail_closed(self):
        with self.assertRaisesRegex(ReleaseBuildError, "unavailable"):
            validate_release_keyring(self.root / "missing.json")

        self.keyring.write_bytes(b"")
        with self.assertRaisesRegex(ReleaseBuildError, "bounded regular file"):
            validate_release_keyring(self.keyring)

        self.keyring.write_text('{"keys":[{"key_id":"local-connect-prod-2026-01"}]}')
        with self.assertRaisesRegex(ReleaseBuildError, "entry is invalid"):
            validate_release_keyring(self.keyring)

        self.keyring.write_text('{"keys":[],"keys":[]}')
        with self.assertRaisesRegex(ReleaseBuildError, "duplicate JSON member"):
            validate_release_keyring(self.keyring)

        self.write_keyring(key_id="local-connect-test-2026-01")
        with self.assertRaisesRegex(ReleaseBuildError, "non-production"):
            validate_release_keyring(self.keyring)

    def test_key_id_algorithm_and_public_key_boundaries_fail_closed(self):
        self.write_keyring(key_id="local-connect-2026-01")
        with self.assertRaisesRegex(ReleaseBuildError, "non-production"):
            validate_release_keyring(self.keyring)

        document = json.loads(self.keyring.read_text())
        document["keys"][0]["key_id"] = "local-connect-prod-2026-01"
        document["keys"][0]["algorithm"] = "RSA"
        self.keyring.write_text(json.dumps(document))
        with self.assertRaisesRegex(ReleaseBuildError, "Ed25519"):
            validate_release_keyring(self.keyring)

        self.write_keyring(public_key=encoded_key(b"short"))
        with self.assertRaisesRegex(ReleaseBuildError, "public key is invalid"):
            validate_release_keyring(self.keyring)

    def test_builder_stages_fixed_resource_and_requires_expected_executable(self):
        dist = self.root / "dist"
        work = self.root / "work"
        observed = {}

        def fake_runner(command, *, cwd, check):
            observed["command"] = list(command)
            observed["cwd"] = cwd
            observed["check"] = check
            add_data = command[command.index("--add-data") + 1]
            source, destination = add_data.split(os.pathsep, 1)
            observed["resource_name"] = Path(source).name
            observed["resource_bytes"] = Path(source).read_bytes()
            observed["destination"] = destination
            staged_dist = Path(command[command.index("--distpath") + 1])
            staged_dist.mkdir(parents=True, exist_ok=True)
            (staged_dist / BINARY_NAME).write_bytes(b"executable")

        executable = build_release(
            keyring_path=self.keyring,
            dist_dir=dist,
            work_dir=work,
            runner=fake_runner,
        )

        self.assertEqual(executable, dist / BINARY_NAME)
        self.assertEqual(observed["resource_name"], BUNDLE_FILENAME)
        self.assertEqual(observed["resource_bytes"], self.keyring.read_bytes())
        self.assertEqual(observed["destination"], BUNDLE_DIRECTORY)
        self.assertIn("--onefile", observed["command"])
        self.assertTrue(observed["check"])

        with self.assertRaisesRegex(ReleaseBuildError, "expected executable"):
            build_release(
                keyring_path=self.keyring,
                dist_dir=dist,
                work_dir=work,
                runner=lambda *args, **kwargs: None,
            )

    def test_cli_requires_build_time_keyring_configuration(self):
        error = StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(error):
            self.assertEqual(main([]), 2)
        self.assertIn(f"{KEYRING_ENV} is required", error.getvalue())


if __name__ == "__main__":
    unittest.main()
