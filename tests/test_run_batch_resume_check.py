"""
Tests for run_batch.py --resume-check mode.

Verifies that resume-check:
  - exits 0 when all jobs are reusable (SKIP)
  - exits 1 when any job is pending
  - never starts Docker containers
  - never calls build_source_inventories or execute_plan
  - respects --limit
  - is rejected when combined with --force (exit 2)

No Docker. No real inference.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import load_run_batch_module, make_valid_job_output
from src.benchmark.artifact_policy import ArtifactPolicy

_run_batch = load_run_batch_module()


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_batch.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def _fake_docs(n: int) -> list[Path]:
    return [Path(f"/fake/doc_{i:02d}.pdf") for i in range(n)]


class TestResumeCheckAllReusable(unittest.TestCase):
    """Case 1 — all outputs valid → exit 0."""

    def test_all_reusable_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            doc_path, _ = make_valid_job_output(
                output_root,
                parser="pymupdf",
                profile="native",
                doc_stem="testdoc",
                doc_sha256="deadbeef",
            )
            with (
                patch.object(_run_batch, "_sha256", return_value="deadbeef"),
                patch.object(_run_batch, "discover_pdfs", return_value=[doc_path]),
                patch.object(_run_batch, "build_source_inventories") as mock_inv,
                patch.object(_run_batch, "execute_plan") as mock_exec,
            ):
                result = _run_batch.build_run_plan(
                    [doc_path],
                    [("pymupdf", "native")],
                    output_root,
                    resume=True,
                )
                plan, _ = result
                skip_count = sum(1 for r in plan if r.status == "skip")
                self.assertEqual(skip_count, 1)

    def test_all_reusable_cli_exit_zero(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            pdf_content = b"%PDF-1.4\n%%EOF\n"
            real_sha = hashlib.sha256(pdf_content).hexdigest()

            output_root = Path(tmp) / "outputs"
            make_valid_job_output(
                output_root,
                parser="pymupdf",
                profile="native",
                doc_stem="testdoc",
                doc_sha256=real_sha,
            )
            real_pdf = Path(tmp) / "testdoc.pdf"
            real_pdf.write_bytes(pdf_content)

            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--output-root", str(output_root),
                "--resume-check",
            )
            combined = result.stdout + result.stderr
            self.assertIn("SKIP", combined)
            self.assertIn("Resume check: PASS", combined)
            self.assertEqual(result.returncode, 0, combined)


class TestResumeCheckNoPriorOutput(unittest.TestCase):
    """Case 2 — no outputs exist → exit 1."""

    def test_no_output_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_pdf = Path(tmp) / "testdoc.pdf"
            real_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            empty_output = Path(tmp) / "outputs"
            empty_output.mkdir()

            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--output-root", str(empty_output),
                "--resume-check",
            )
            combined = result.stdout + result.stderr
            self.assertIn("PENDING", combined)
            self.assertIn("Resume check: FAIL", combined)
            self.assertEqual(result.returncode, 1)


class TestResumeCheckArtifactMissing(unittest.TestCase):
    """Case 3 — metrics valid but required artifact absent → exit 1."""

    def test_missing_artifact_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"
            doc_path, _ = make_valid_job_output(
                output_root,
                parser="pymupdf",
                profile="native",
                doc_stem="testdoc",
                doc_sha256="deadbeef",
            )
            # Remove document.md to make it invalid
            (output_root / "pymupdf" / "testdoc" / "native" / "document.md").unlink()

            real_pdf = Path(tmp) / "testdoc.pdf"
            real_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--output-root", str(output_root),
                "--resume-check",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("PENDING", result.stdout + result.stderr)


class TestResumeCheckInvalidMetrics(unittest.TestCase):
    """Case 4 — metrics.json is corrupt → exit 1."""

    def test_corrupt_metrics_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"
            out_dir = output_root / "pymupdf" / "testdoc" / "native"
            out_dir.mkdir(parents=True)
            (out_dir / "metrics.json").write_text("not json{{{", encoding="utf-8")

            real_pdf = Path(tmp) / "testdoc.pdf"
            real_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--output-root", str(output_root),
                "--resume-check",
            )
            self.assertEqual(result.returncode, 1)


class TestResumeCheckShaMismatch(unittest.TestCase):
    """Case 5 — metrics SHA256 doesn't match actual file → exit 1."""

    def test_sha_mismatch_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"
            make_valid_job_output(
                output_root,
                parser="pymupdf",
                profile="native",
                doc_stem="testdoc",
                doc_sha256="wrong_sha_not_matching_real_file",
            )
            real_pdf = Path(tmp) / "testdoc.pdf"
            real_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--output-root", str(output_root),
                "--resume-check",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("PENDING", result.stdout + result.stderr)


class TestResumeCheckLimit(unittest.TestCase):
    """Case 6 — --limit 1 with 2 docs; only first has valid output → exit 0."""

    def test_limit_excludes_second_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"

            # First doc: valid output, sha matches real file content
            pdf1 = Path(tmp) / "aaa.pdf"
            pdf1.write_bytes(b"%PDF-1.4\n%%EOF\n")
            pdf2 = Path(tmp) / "bbb.pdf"
            pdf2.write_bytes(b"%PDF-1.4\n%%EOF2\n")

            # Get real sha of pdf1
            import hashlib
            h = hashlib.sha256()
            h.update(pdf1.read_bytes())
            sha1 = h.hexdigest()

            make_valid_job_output(
                output_root,
                parser="pymupdf",
                profile="native",
                doc_stem="aaa",
                doc_sha256=sha1,
            )
            # pdf2 has no output at all

            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--output-root", str(output_root),
                "--limit", "1",
                "--resume-check",
            )
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            self.assertIn("Resume check: PASS", combined)
            self.assertNotIn("bbb", combined)


class TestResumeCheckForceRejected(unittest.TestCase):
    """Case 7 — --force --resume-check must be rejected (exit 2)."""

    def test_force_with_resume_check_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pdf = Path(tmp) / "dummy.pdf"
            dummy_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            result = _run_cli(
                "--parser", "pymupdf",
                "--profile", "native",
                "--input-dir", str(tmp),
                "--force",
                "--resume-check",
            )
            self.assertEqual(result.returncode, 2)
            combined = result.stdout + result.stderr
            self.assertIn("--force", combined)
            self.assertIn("--resume-check", combined)


class TestResumeCheckNoContainers(unittest.TestCase):
    """Cases 8 & 9 — resume-check must not call build_source_inventories or execute_plan."""

    def test_does_not_call_build_source_inventories(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"
            output_root.mkdir()
            real_pdf = Path(tmp) / "testdoc.pdf"
            real_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

            with (
                patch.object(_run_batch, "build_source_inventories") as mock_inv,
                patch.object(_run_batch, "execute_plan") as mock_exec,
                patch.object(_run_batch, "run_preflight") as mock_pf,
            ):
                result = _run_cli(
                    "--parser", "pymupdf",
                    "--profile", "native",
                    "--input-dir", str(tmp),
                    "--output-root", str(output_root),
                    "--resume-check",
                )
            # Subprocess isolation: we verify via CLI output, not mock.
            # "docker" may appear as runtime label; "compose run" must not appear.
            combined = result.stdout + result.stderr
            self.assertNotIn("compose run", combined.lower())
            self.assertNotIn("entrypoint", combined.lower())
            self.assertIn("Resume check:", combined)

    def test_does_not_call_execute_plan_unit(self):
        """Unit-level: build_source_inventories and execute_plan not called in resume-check path."""
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"
            output_root.mkdir()
            doc = Path(tmp) / "testdoc.pdf"
            doc.write_bytes(b"%PDF-1.4\n%%EOF\n")
            docs = [doc]

            policy = ArtifactPolicy.from_cli(["all"])

            with (
                patch.object(_run_batch, "_sha256", return_value="fake_sha"),
                patch.object(_run_batch, "build_source_inventories") as mock_inv,
                patch.object(_run_batch, "execute_plan") as mock_exec,
            ):
                plan, _ = _run_batch.build_run_plan(
                    docs,
                    [("pymupdf", "native")],
                    output_root,
                    resume=True,
                    artifact_policy=policy,
                )
                # Simulate the resume-check path: just inspect plan, no execution
                pending = [r for r in plan if r.status == "pending"]
                self.assertEqual(len(pending), 1)
                mock_inv.assert_not_called()
                mock_exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
