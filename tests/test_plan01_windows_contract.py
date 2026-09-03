from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.model_manifest import build_manifest, verify_manifest
from scripts.parser_deep_smoke import PARSER_PROFILES, verify_fixture


ROOT = Path(__file__).resolve().parents[1]


class WindowsAllFeaturesContractTests(unittest.TestCase):
    def test_suite_is_exactly_the_deep_smoke_order(self) -> None:
        config = json.loads(
            (ROOT / "config" / "benchmark_profiles.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            tuple(tuple(item) for item in config["suites"]["windows_all_features_host"]),
            PARSER_PROFILES,
        )

    def test_wrapper_exposes_required_options_and_fresh_default(self) -> None:
        text = (ROOT / "scripts" / "windows" / "run_all_features_host.ps1").read_text(
            encoding="utf-8"
        )
        for option in (
            "$Resume", "$DryRun", "$PreflightOnly", "$VerboseOutput",
            "$JobTimeoutSeconds", "--artifacts", "all", "--force",
        ):
            self.assertIn(option, text)

    def test_dry_run_has_exactly_seven_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "run_batch.py"),
                    "--suite", "windows_all_features_host", "--runtime", "host",
                    "--input-dir", str(ROOT / "fixtures" / "deep_smoke"),
                    "--output-root", temporary, "--artifacts", "all", "--force", "--dry-run",
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Total jobs: 7", completed.stdout)
        for parser, profile in PARSER_PROFILES:
            self.assertRegex(completed.stdout, rf"\b{parser}\s+{profile}\b")

    def test_readiness_enables_one_functional_test_per_parser(self) -> None:
        runner = (
            ROOT / "scripts" / "windows" / "run_host_parser_tests.ps1"
        ).read_text(encoding="utf-8")
        readiness = (
            ROOT / "scripts" / "windows" / "check_server_readiness.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$FunctionalTests", runner)
        self.assertIn("BENCHMARK_WINDOWS_FUNCTIONAL", runner)
        self.assertIn("'-FunctionalTests'", readiness)
        for parser, _ in PARSER_PROFILES:
            functional_test = (
                ROOT
                / "parser_tests"
                / parser
                / "test_functional_deep_smoke.py"
            )
            self.assertTrue(functional_test.is_file(), str(functional_test))


class DeepSmokeFixtureTests(unittest.TestCase):
    def test_versioned_fixture_manifest_and_hashes(self) -> None:
        manifest = verify_fixture()
        self.assertEqual(manifest["qr_payload"], "DOC-AI-BENCHMARK-QR-2026")
        self.assertEqual(manifest["pages"], 2)


class ModelManifestTests(unittest.TestCase):
    def test_verify_rejects_tampering_and_unlisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "weights.bin"
            model.write_bytes(b"weights")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(build_manifest("unit", "1", root, manifest_path)), encoding="utf-8"
            )
            verify_manifest("unit", "1", root, manifest_path)
            (root / "download.part").write_bytes(b"unexpected")
            with self.assertRaisesRegex(RuntimeError, "unlisted model files"):
                verify_manifest("unit", "1", root, manifest_path)


if __name__ == "__main__":
    unittest.main()
