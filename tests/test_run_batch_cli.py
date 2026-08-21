"""
Integration tests for run_batch.py CLI validation rules.

Runs scripts/run_batch.py as a subprocess — no Docker, no models.
All cases terminate before any inference attempt (argparse errors
or early SystemExit from resolve_jobs_spec / validate_batch).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_batch_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_batch.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


class TestDryRunPreflightMutualExclusion(unittest.TestCase):

    def test_dry_run_and_preflight_together_rejected(self) -> None:
        """--dry-run and --preflight are mutually exclusive → exit 2."""
        result = run_batch_cli(
            "--parser", "paddleocr",
            "--profile", "mvp_structured",
            "--dry-run",
            "--preflight",
            "--no-summary",
        )
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("--preflight", combined)


class TestParserProfileCovalidation(unittest.TestCase):

    def test_parser_without_profile_rejected(self) -> None:
        """--parser without --profile → exit 2 from parse_args validation."""
        result = run_batch_cli("--parser", "pymupdf", "--dry-run")
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("--profile", combined)

    def test_profile_without_parser_rejected(self) -> None:
        """--profile without --parser (and without --suite) → exit 2."""
        result = run_batch_cli("--profile", "native", "--dry-run")
        self.assertEqual(result.returncode, 2)


class TestSuiteParserMutualExclusion(unittest.TestCase):

    def test_suite_and_parser_together_rejected(self) -> None:
        """--suite and --parser are mutually exclusive → exit 2."""
        result = run_batch_cli(
            "--suite", "ocr_primary",
            "--parser", "pymupdf",
            "--profile", "native",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("--parser", combined)


class TestUnknownSuite(unittest.TestCase):

    def test_unknown_suite_fails_clearly(self) -> None:
        """An unrecognised suite name is caught before PDF discovery → non-zero exit."""
        result = run_batch_cli("--suite", "suite_que_nao_existe", "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("suite_que_nao_existe", combined)


class TestUnknownParser(unittest.TestCase):

    def test_unknown_parser_fails_clearly(self) -> None:
        """An unrecognised parser name is caught in validate_batch → non-zero exit."""
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

            result = run_batch_cli(
                "--parser", "parser_que_nao_existe",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--dry-run",
            )

        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("parser_que_nao_existe", combined)


class TestLimitCLIValidation(unittest.TestCase):

    def test_limit_0_rejected(self):
        """--limit 0 is not a positive integer → exit 2."""
        result = run_batch_cli(
            "--parser", "pymupdf",
            "--profile", "native",
            "--limit", "0",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)

    def test_limit_negative_rejected(self):
        """--limit -1 is not a positive integer → exit 2."""
        result = run_batch_cli(
            "--parser", "pymupdf",
            "--profile", "native",
            "--limit", "-1",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)

    def test_limit_non_integer_rejected(self):
        """--limit abc is not an integer → exit 2."""
        result = run_batch_cli(
            "--parser", "pymupdf",
            "--profile", "native",
            "--limit", "abc",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
