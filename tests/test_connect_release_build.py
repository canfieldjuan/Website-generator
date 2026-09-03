import base64
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build
from scripts.build_connect_provider import (
    APPROVED_RELEASE_AUTHORITIES,
    BINARY_NAME,
    BUNDLE_DIRECTORY,
    BUNDLE_FILENAME,
    CONNECT_REFERENCE_FILES,
    KEYRING_ENV,
    ReleaseBuildError,
    binary_filename,
    build_release,
    main,
    validate_release_keyring,
)


def encoded_key(value: bytes | None = None) -> str:
    if value is None:
        return next(
            public_key
            for key_id, public_key in APPROVED_RELEASE_AUTHORITIES
            if key_id == "local-connect-prod-2026-01"
        )
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

    def test_production_shaped_but_unapproved_authority_is_rejected(self):
        self.write_keyring(public_key=encoded_key(b"Q" * 32))

        with self.assertRaisesRegex(ReleaseBuildError, "approved production authority"):
            validate_release_keyring(self.keyring)

    def test_keyring_reader_rejects_windows_reparse_metadata_before_open(self):
        path_type = type(self.keyring)
        real_lstat = path_type.lstat

        def lstat_with_reparse_leaf(candidate):
            metadata = real_lstat(candidate)
            if candidate == self.keyring:
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_size=metadata.st_size,
                    st_file_attributes=0x400,
                )
            return metadata

        with (
            patch.object(
                path_type,
                "lstat",
                autospec=True,
                side_effect=lstat_with_reparse_leaf,
            ),
            patch("scripts.build_connect_provider.os.open") as open_file,
            self.assertRaisesRegex(ReleaseBuildError, "bounded regular file"),
        ):
            validate_release_keyring(self.keyring)
        open_file.assert_not_called()

    def test_keyring_reader_rejects_reparse_point_ancestor_before_open(self):
        path_type = type(self.keyring)
        real_lstat = path_type.lstat

        def lstat_with_reparse_ancestor(candidate):
            metadata = real_lstat(candidate)
            if candidate == self.root:
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_file_attributes=0x400,
                )
            return metadata

        with (
            patch.object(
                path_type,
                "lstat",
                autospec=True,
                side_effect=lstat_with_reparse_ancestor,
            ),
            patch("scripts.build_connect_provider.os.open") as open_file,
            self.assertRaisesRegex(ReleaseBuildError, "unsafe path ancestor"),
        ):
            validate_release_keyring(self.keyring)
        open_file.assert_not_called()

    def test_keyring_reader_rejects_symbolic_link(self):
        target = self.root / "real-keyring.json"
        self.keyring.replace(target)
        self.keyring.symlink_to(target)

        with self.assertRaisesRegex(ReleaseBuildError, "bounded regular file"):
            validate_release_keyring(self.keyring)

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

    def test_keyring_parser_normalizes_numeric_and_recursion_limits(self):
        self.keyring.write_text('{"keys":' + "9" * 5_000 + "}", encoding="utf-8")
        with self.assertRaisesRegex(ReleaseBuildError, "invalid JSON"):
            validate_release_keyring(self.keyring)

        with patch(
            "scripts.build_connect_provider.json.loads",
            side_effect=RecursionError("maximum recursion depth exceeded"),
        ):
            with self.assertRaisesRegex(ReleaseBuildError, "invalid JSON"):
                validate_release_keyring(self.keyring)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is unavailable")
    def test_keyring_reader_rejects_fifo_without_waiting_for_a_writer(self):
        fifo = self.root / "keyring.fifo"
        os.mkfifo(fifo)

        with self.assertRaisesRegex(ReleaseBuildError, "bounded regular file"):
            validate_release_keyring(fifo)

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
            observed["staged_dist"] = staged_dist
            add_data_values = [
                command[index + 1]
                for index, value in enumerate(command)
                if value == "--add-data"
            ]
            observed["add_data_values"] = add_data_values
            staged_dist.mkdir(parents=True, exist_ok=True)
            (staged_dist / binary_filename()).write_bytes(b"executable")

        executable = build_release(
            keyring_path=self.keyring,
            dist_dir=dist,
            work_dir=work,
            runner=fake_runner,
        )

        self.assertEqual(executable, (dist / binary_filename()).resolve())
        self.assertEqual(observed["resource_name"], BUNDLE_FILENAME)
        self.assertEqual(observed["resource_bytes"], self.keyring.read_bytes())
        self.assertEqual(observed["destination"], BUNDLE_DIRECTORY)
        self.assertEqual(observed["staged_dist"].parent.parent.resolve(), dist.resolve())
        bundled_sources = {
            Path(value.split(os.pathsep, 1)[0]).relative_to(observed["cwd"])
            for value in observed["add_data_values"][1:]
        }
        self.assertEqual(bundled_sources, set(CONNECT_REFERENCE_FILES))
        self.assertTrue(
            all(
                value.split(os.pathsep, 1)[1] == f"{BUNDLE_DIRECTORY}/references"
                for value in observed["add_data_values"][1:]
            )
        )
        self.assertIn("--onefile", observed["command"])
        self.assertTrue(observed["check"])

        with self.assertRaisesRegex(ReleaseBuildError, "expected executable"):
            build_release(
                keyring_path=self.keyring,
                dist_dir=dist,
                work_dir=work,
                runner=lambda *args, **kwargs: None,
            )

    def test_binary_filename_matches_native_platform_convention(self):
        self.assertEqual(binary_filename("nt"), f"{BINARY_NAME}.exe")
        self.assertEqual(binary_filename("posix"), BINARY_NAME)

    def test_build_module_resolves_frozen_reference_assets(self):
        with patch.object(build.sys, "_MEIPASS", "/tmp/frozen-app", create=True):
            resolved = build.runtime_resource_path("references/06-build-prompt.md")

        self.assertEqual(
            resolved,
            str(
                Path("/tmp/frozen-app")
                / "website_redesign_data/references/06-build-prompt.md"
            ),
        )

    def test_cli_requires_build_time_keyring_configuration(self):
        error = StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(error):
            self.assertEqual(main([]), 2)
        self.assertIn(f"{KEYRING_ENV} is required", error.getvalue())

    def test_cli_normalizes_release_filesystem_errors(self):
        error = StringIO()
        with (
            patch.dict(os.environ, {KEYRING_ENV: str(self.keyring)}, clear=True),
            patch(
                "scripts.build_connect_provider.build_release",
                side_effect=OSError("destination unavailable"),
            ),
            redirect_stderr(error),
        ):
            self.assertEqual(main([]), 2)
        self.assertIn("Release build failed: destination unavailable", error.getvalue())


if __name__ == "__main__":
    unittest.main()
