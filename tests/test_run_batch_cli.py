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


class TestDefaultSuiteBehavior(unittest.TestCase):
    """Omitting --suite and --parser must use the 'default' suite."""

    def test_no_target_uses_default_suite_dry_run(self):
        """No --suite/--parser + --dry-run uses default (4 pairs)."""
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            result = run_batch_cli(
                "--input-dir", str(tmp),
                "--dry-run",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("default", combined)
        self.assertIn("DRY RUN", combined)

    def test_explicit_suite_smoke(self):
        """--suite smoke resolves to smoke, not default."""
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            result = run_batch_cli(
                "--suite", "smoke",
                "--input-dir", str(tmp),
                "--dry-run",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("smoke", result.stdout + result.stderr)

    def test_explicit_suite_ocr_primary(self):
        """--suite ocr_primary resolves correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            result = run_batch_cli(
                "--suite", "ocr_primary",
                "--input-dir", str(tmp),
                "--dry-run",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ocr_primary", result.stdout + result.stderr)

    def test_explicit_parser_profile(self):
        """--parser + --profile resolves to a single pair."""
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            result = run_batch_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--dry-run",
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_target_dry_run_four_jobs(self):
        """No target with 1 doc produces 4 jobs (default suite = 4 pairs)."""
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            result = run_batch_cli(
                "--input-dir", str(tmp),
                "--dry-run",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("Total jobs: 4", output)


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


class TestWindowsConsoleCompatibility(unittest.TestCase):
    """Regression: run_batch output must be encodable in Windows cp1252 (U+2192 was broken)."""

    def _run_dry_run_cp1252(self):
        import os
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_batch.py"),
                    "--parser", "pymupdf",
                    "--profile", "native",
                    "--input-dir", str(tmp),
                    "--dry-run",
                ],
                cwd=str(ROOT),
                capture_output=True,
                env=env,
            )
        # Decode with cp1252 — same encoding the subprocess wrote with
        combined = proc.stdout.decode("cp1252", errors="replace") + \
                   proc.stderr.decode("cp1252", errors="replace")
        return proc.returncode, combined

    def test_dry_run_exits_zero_with_cp1252(self):
        returncode, _ = self._run_dry_run_cp1252()
        self.assertEqual(returncode, 0)

    def test_output_line_is_ascii_safe(self):
        _, combined = self._run_dry_run_cp1252()
        # Must not contain the non-ASCII arrow that broke cp1252 consoles
        self.assertNotIn("→", combined)

    def test_dry_run_contains_expected_headers(self):
        returncode, combined = self._run_dry_run_cp1252()
        self.assertEqual(returncode, 0)
        self.assertIn("DRY RUN", combined)


if __name__ == "__main__":
    unittest.main()
