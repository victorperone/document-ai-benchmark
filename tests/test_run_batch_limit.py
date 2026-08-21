"""
Tests for --limit N document limiting.

Verifies:
- apply_document_limit() pure function
- parse_positive_int() type validator
- Limit is per document, not per job
- Deterministic order preserved
- build_run_plan receives limited docs
- resume respects limit
- force respects limit
- dry-run CLI shows limited docs
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import load_run_batch_module

_run_batch = load_run_batch_module()


def run_batch_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_batch.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


class TestApplyDocumentLimit(unittest.TestCase):

    def test_none_limit_returns_all(self):
        docs = [Path("a.pdf"), Path("b.pdf"), Path("c.pdf")]
        self.assertEqual(_run_batch.apply_document_limit(docs, None), docs)

    def test_limit_1_returns_first(self):
        docs = [Path("a.pdf"), Path("b.pdf"), Path("c.pdf")]
        self.assertEqual(_run_batch.apply_document_limit(docs, 1), [Path("a.pdf")])

    def test_limit_2_returns_first_two(self):
        docs = [Path("a.pdf"), Path("b.pdf"), Path("c.pdf")]
        result = _run_batch.apply_document_limit(docs, 2)
        self.assertEqual(result, [Path("a.pdf"), Path("b.pdf")])

    def test_limit_exceeds_corpus_returns_all(self):
        docs = [Path("a.pdf"), Path("b.pdf")]
        self.assertEqual(_run_batch.apply_document_limit(docs, 10), docs)

    def test_limit_equals_corpus_size_returns_all(self):
        docs = [Path("a.pdf"), Path("b.pdf")]
        self.assertEqual(_run_batch.apply_document_limit(docs, 2), docs)

    def test_does_not_mutate_original(self):
        docs = [Path("a.pdf"), Path("b.pdf"), Path("c.pdf")]
        original = list(docs)
        _run_batch.apply_document_limit(docs, 1)
        self.assertEqual(docs, original)


class TestParsePositiveInt(unittest.TestCase):

    def test_valid_1(self):
        self.assertEqual(_run_batch.parse_positive_int("1"), 1)

    def test_valid_10(self):
        self.assertEqual(_run_batch.parse_positive_int("10"), 10)

    def test_zero_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _run_batch.parse_positive_int("0")

    def test_negative_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _run_batch.parse_positive_int("-1")

    def test_non_integer_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _run_batch.parse_positive_int("abc")


class TestLimitPerDocument(unittest.TestCase):
    """--limit N limits documents, not parser/profile pairs."""

    def test_1_doc_2_parsers_gives_2_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            jobs_spec = [("pymupdf", "native"), ("docling", "native")]
            with patch.object(_run_batch, "validate_resume_candidate",
                              return_value={"ok": False, "checks": []}):
                plan, _ = _run_batch.build_run_plan(docs, jobs_spec, t, False)
        self.assertEqual(len(plan), 2)

    def test_2_docs_2_parsers_limit_1_gives_2_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            (t / "B.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            jobs_spec = [("pymupdf", "native"), ("docling", "native")]
            with patch.object(_run_batch, "validate_resume_candidate",
                              return_value={"ok": False, "checks": []}):
                plan, _ = _run_batch.build_run_plan(docs, jobs_spec, t, False)
        self.assertEqual(len(plan), 2)

    def test_2_docs_2_parsers_limit_2_gives_4_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            (t / "B.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 2)
            jobs_spec = [("pymupdf", "native"), ("docling", "native")]
            with patch.object(_run_batch, "validate_resume_candidate",
                              return_value={"ok": False, "checks": []}):
                plan, _ = _run_batch.build_run_plan(docs, jobs_spec, t, False)
        self.assertEqual(len(plan), 4)


class TestDeterministicOrder(unittest.TestCase):

    def test_limit_2_returns_alphabetically_first_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            for name in ["C.pdf", "A.pdf", "B.pdf"]:
                (t / name).write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 2)
        self.assertEqual([d.name for d in docs], ["A.pdf", "B.pdf"])

    def test_no_limit_preserves_full_sorted_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            for name in ["C.pdf", "A.pdf", "B.pdf"]:
                (t / name).write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), None)
        self.assertEqual([d.name for d in docs], ["A.pdf", "B.pdf", "C.pdf"])


class TestLimitWithResume(unittest.TestCase):

    def test_limited_to_1_second_doc_not_in_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            (t / "B.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            with patch.object(_run_batch, "validate_resume_candidate",
                              return_value={"ok": True, "checks": []}):
                plan, _ = _run_batch.build_run_plan(docs, [("pymupdf", "native")], t, True)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].doc.name, "A.pdf")

    def test_skip_status_with_valid_resume_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            with patch.object(_run_batch, "validate_resume_candidate",
                              return_value={"ok": True, "checks": []}):
                plan, _ = _run_batch.build_run_plan(docs, [("pymupdf", "native")], t, True)
        self.assertEqual(plan[0].status, "skip")


class TestLimitWithForce(unittest.TestCase):

    def test_force_with_limit_1_only_first_doc_in_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            (t / "B.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            plan, _ = _run_batch.build_run_plan(docs, [("pymupdf", "native")], t, False)
        self.assertEqual(len(plan), 1)

    def test_force_with_limit_1_first_doc_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            (t / "B.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            plan, _ = _run_batch.build_run_plan(docs, [("pymupdf", "native")], t, False)
        self.assertEqual(plan[0].status, "pending")

    def test_force_with_limit_1_first_doc_is_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "A.pdf").write_bytes(b"%PDF\n")
            (t / "B.pdf").write_bytes(b"%PDF\n")
            docs = _run_batch.apply_document_limit(_run_batch.discover_pdfs(t), 1)
            plan, _ = _run_batch.build_run_plan(docs, [("pymupdf", "native")], t, False)
        self.assertEqual(plan[0].doc.name, "A.pdf")


class TestLimitDryRunCLI(unittest.TestCase):

    def test_limit_1_with_2_pdfs_shows_limit_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.pdf").write_bytes(b"%PDF\n")
            (Path(tmp) / "B.pdf").write_bytes(b"%PDF\n")
            result = run_batch_cli(
                "--parser", "pymupdf", "--profile", "native",
                "--input-dir", tmp,
                "--output-root", "outputs/_test_limit_dry",
                "--limit", "1",
                "--dry-run",
                "--no-summary",
            )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0)
        self.assertIn("Limit:", combined)

    def test_limit_1_dry_run_shows_1_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.pdf").write_bytes(b"%PDF\n")
            (Path(tmp) / "B.pdf").write_bytes(b"%PDF\n")
            result = run_batch_cli(
                "--parser", "pymupdf", "--profile", "native",
                "--input-dir", tmp,
                "--output-root", "outputs/_test_limit_dry",
                "--limit", "1",
                "--dry-run",
                "--no-summary",
            )
        # 1 doc × 1 parser/profile = 1 job total → "1/1" in plan
        self.assertIn("1/1", result.stdout + result.stderr)

    def test_no_limit_dry_run_does_not_show_limit_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.pdf").write_bytes(b"%PDF\n")
            (Path(tmp) / "B.pdf").write_bytes(b"%PDF\n")
            result = run_batch_cli(
                "--parser", "pymupdf", "--profile", "native",
                "--input-dir", tmp,
                "--output-root", "outputs/_test_limit_dry",
                "--dry-run",
                "--no-summary",
            )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Limit:", combined)

    def test_no_limit_dry_run_shows_2_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.pdf").write_bytes(b"%PDF\n")
            (Path(tmp) / "B.pdf").write_bytes(b"%PDF\n")
            result = run_batch_cli(
                "--parser", "pymupdf", "--profile", "native",
                "--input-dir", tmp,
                "--output-root", "outputs/_test_limit_dry",
                "--dry-run",
                "--no-summary",
            )
        # 2 docs × 1 parser/profile = 2 jobs → "2/2" in plan
        self.assertIn("2/2", result.stdout + result.stderr)

    def test_limit_larger_than_corpus_no_limit_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.pdf").write_bytes(b"%PDF\n")
            (Path(tmp) / "B.pdf").write_bytes(b"%PDF\n")
            result = run_batch_cli(
                "--parser", "pymupdf", "--profile", "native",
                "--input-dir", tmp,
                "--output-root", "outputs/_test_limit_dry",
                "--limit", "10",
                "--dry-run",
                "--no-summary",
            )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0)
        # limit >= corpus → no reduction → no Limit: line
        self.assertNotIn("Limit:", combined)


if __name__ == "__main__":
    unittest.main()
