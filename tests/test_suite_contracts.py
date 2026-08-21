"""
Suite contract tests — Steps 7–11.

Locks the exact composition, job expansion, deterministic ordering,
comparison-script eligibility, and preflight aggregation for each suite.

No inference, no Docker, no model downloads — all container calls are mocked.

Suites covered:
  ocr_primary     (Step 7)
  full_corpus     (Step 8)
  diagnostic_ocr  (Step 9)
  visual_ablation (Step 10)
  smoke           (Step 11)
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import load_run_batch_module

_run_batch = load_run_batch_module()


# ── Canonical suite definitions (ground truth for all tests) ──────────────────

OCR_PRIMARY_PAIRS = [
    ("pymupdf",    "ocr_auto_rapidtess"),
    ("docling",    "ocr_auto"),
    ("mineru",     "auto"),
    ("paddleocr",  "mvp_structured"),
]

FULL_CORPUS_PAIRS = [
    ("pymupdf",    "native"),
    ("pymupdf",    "ocr_auto_rapidtess"),
    ("docling",    "native"),
    ("docling",    "ocr_auto"),
    ("mineru",     "txt"),
    ("mineru",     "auto"),
    ("paddleocr",  "lightweight"),
    ("paddleocr",  "ocr_structured_visual"),
]

DIAGNOSTIC_OCR_PAIRS = [
    ("pymupdf",    "ocr_force_rapidtess"),
    ("mineru",     "ocr"),
    ("paddleocr",  "full"),
]

VISUAL_ABLATION_PAIRS = [
    ("docling",    "ocr_auto"),
    ("docling",    "ocr_auto_visual"),
    ("paddleocr",  "default"),
    ("paddleocr",  "ocr_structured_visual"),
]

SMOKE_PAIRS = [
    ("pymupdf",    "native"),
    ("docling",    "native"),
    ("mineru",     "txt"),
    ("paddleocr",  "lightweight"),
]

DEFAULT_PAIRS = OCR_PRIMARY_PAIRS


# ── Shared helpers ────────────────────────────────────────────────────────────

def _load_config() -> dict:
    return json.loads(
        (ROOT / "config" / "benchmark_profiles.json").read_text(encoding="utf-8")
    )


def _completed(
    *, returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _pass_result(parser: str, profile: str) -> dict:
    return {
        "schema_version": 1,
        "parser": parser,
        "profile": profile,
        "ok": True,
        "checks": [{"name": "adapter", "status": "pass"}],
    }


def _fail_result(parser: str, profile: str) -> dict:
    return {
        "schema_version": 1,
        "parser": parser,
        "profile": profile,
        "ok": False,
        "checks": [{"name": "model missing", "status": "fail", "detail": "not found"}],
    }


def _fake_docs(n: int) -> list[Path]:
    return [Path(f"/fake/doc_{i:02d}.pdf") for i in range(n)]


def _build_plan_no_resume(
    docs: list[Path],
    jobs_spec: list[tuple[str, str]],
    output_root: Path,
) -> list:
    with patch.object(_run_batch, "_sha256", return_value="deadbeef"):
        plan, _ = _run_batch.build_run_plan(
            docs, jobs_spec, output_root, resume=False
        )
    return plan


def _docker_ok(cmd, **kwargs) -> subprocess.CompletedProcess:
    cmd_flat = " ".join(str(c) for c in cmd)
    if "info" in cmd_flat:
        return _completed(returncode=0, stdout="27.0.3")
    if "config" in cmd_flat and "--services" in cmd_flat:
        return _completed(
            returncode=0,
            stdout="pymupdf\ndocling\nmineru\npaddleocr\n",
        )
    return _completed(returncode=0)


def _run_preflight_with_mock(
    jobs_spec: list[tuple[str, str]],
    docs: list[Path],
    preflight_side_effect,
) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch.object(_run_batch.shutil, "which", return_value="/usr/bin/docker"),
            patch.object(_run_batch.subprocess, "run", side_effect=_docker_ok),
            patch.object(
                _run_batch, "run_parser_preflight",
                side_effect=preflight_side_effect,
            ),
        ):
            return _run_batch.run_preflight(
                jobs_spec,
                docs,
                Path(tmp),
                Path(tmp) / "outputs",
                ["docker", "compose"],
                None,
            )


def run_batch_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_batch.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def _suite_pairs_from_config(suite_name: str) -> list[tuple[str, str]]:
    return [tuple(p) for p in _load_config()["suites"][suite_name]]


# ── Generic contract mixin ────────────────────────────────────────────────────

class _SuiteContractMixin:
    """
    Mixin providing contract tests for any named suite.
    Subclasses set:
      suite_name: str
      expected_pairs: list[tuple[str, str]]
    """

    suite_name: str
    expected_pairs: list[tuple[str, str]]

    # ── Definition ──────────────────────────────────────────────────────────

    def test_suite_exists_in_config(self):
        self.assertIn(self.suite_name, _load_config()["suites"])

    def test_exact_pairs(self):
        self.assertEqual(_suite_pairs_from_config(self.suite_name), self.expected_pairs)

    def test_no_duplicate_pairs(self):
        pairs = _suite_pairs_from_config(self.suite_name)
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_all_pairs_valid_in_config(self):
        config = _load_config()
        parsers_cfg = config["parsers"]
        for parser, profile in self.expected_pairs:
            self.assertIn(parser, parsers_cfg, f"parser {parser!r} missing")
            self.assertIn(
                profile,
                parsers_cfg[parser]["profiles"],
                f"profile {profile!r} missing for {parser!r}",
            )

    def test_order_is_deterministic(self):
        self.assertEqual(
            _suite_pairs_from_config(self.suite_name),
            _suite_pairs_from_config(self.suite_name),
        )

    def test_resolve_jobs_spec(self):
        config = _load_config()
        args = type("Args", (), {"suite": self.suite_name, "parser": None, "profile": None})()
        pairs = _run_batch.resolve_jobs_spec(args, config)
        self.assertEqual(pairs, self.expected_pairs)

    # ── Job expansion ────────────────────────────────────────────────────────

    def test_one_doc_job_count(self):
        n = len(self.expected_pairs)
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(1), self.expected_pairs, Path(tmp))
        self.assertEqual(len(plan), n)

    def test_two_docs_job_count(self):
        n = len(self.expected_pairs)
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(2), self.expected_pairs, Path(tmp))
        self.assertEqual(len(plan), 2 * n)

    def test_limit_one_with_two_docs(self):
        n = len(self.expected_pairs)
        docs = _run_batch.apply_document_limit(_fake_docs(2), 1)
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(docs, self.expected_pairs, Path(tmp))
        self.assertEqual(len(plan), n)

    def test_pair_order_per_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(1), self.expected_pairs, Path(tmp))
        self.assertEqual(
            [(r.parser, r.profile) for r in plan],
            list(self.expected_pairs),
        )

    def test_job_order_is_doc_outer_pair_inner(self):
        docs = _fake_docs(2)
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(docs, self.expected_pairs, Path(tmp))
        n = len(self.expected_pairs)
        for rec in plan[:n]:
            self.assertEqual(rec.doc, docs[0])
        for rec in plan[n:]:
            self.assertEqual(rec.doc, docs[1])

    def test_resume_does_not_change_plan_length(self):
        docs = _fake_docs(1)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_run_batch, "_sha256", return_value="deadbeef"):
                plan, _ = _run_batch.build_run_plan(
                    docs, self.expected_pairs, Path(tmp), resume=True
                )
        self.assertEqual(len(plan), len(self.expected_pairs))

    def test_force_all_jobs_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(1), self.expected_pairs, Path(tmp))
        self.assertTrue(all(r.status == "pending" for r in plan))

    def test_resume_pairs_unchanged(self):
        docs = _fake_docs(1)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_run_batch, "_sha256", return_value="deadbeef"):
                plan, _ = _run_batch.build_run_plan(
                    docs, self.expected_pairs, Path(tmp), resume=True
                )
        self.assertEqual(
            [(r.parser, r.profile) for r in plan],
            list(self.expected_pairs),
        )

    # ── Dry-run ──────────────────────────────────────────────────────────────

    def test_dry_run_exits_zero(self):
        result = run_batch_cli(
            "--suite", self.suite_name,
            "--input-dir", "data/raw/batch",
            "--output-root", "outputs/_test_contracts",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0)

    def test_dry_run_shows_dry_run_label(self):
        result = run_batch_cli(
            "--suite", self.suite_name,
            "--input-dir", "data/raw/batch",
            "--output-root", "outputs/_test_contracts",
            "--dry-run",
        )
        self.assertIn("DRY RUN", result.stdout + result.stderr)

    # ── Preflight aggregation (mocked) ────────────────────────────────────────

    def test_preflight_all_pass_returns_true(self):
        ok = _run_preflight_with_mock(
            self.expected_pairs,
            _fake_docs(1),
            lambda cb, parser, profile: _pass_result(parser, profile),
        )
        self.assertTrue(ok)

    def test_preflight_first_pair_fail_returns_false(self):
        first = self.expected_pairs[0]

        def side_effect(cb, parser, profile):
            if (parser, profile) == first:
                return _fail_result(parser, profile)
            return _pass_result(parser, profile)

        ok = _run_preflight_with_mock(
            self.expected_pairs, _fake_docs(1), side_effect
        )
        self.assertFalse(ok)

    def test_preflight_last_pair_fail_returns_false(self):
        last = self.expected_pairs[-1]

        def side_effect(cb, parser, profile):
            if (parser, profile) == last:
                return _fail_result(parser, profile)
            return _pass_result(parser, profile)

        ok = _run_preflight_with_mock(
            self.expected_pairs, _fake_docs(1), side_effect
        )
        self.assertFalse(ok)

    def test_preflight_failure_does_not_skip_others(self):
        """One failing pair must not prevent the remaining pairs from being checked."""
        called: list[tuple[str, str]] = []
        first = self.expected_pairs[0]

        def side_effect(cb, parser, profile):
            called.append((parser, profile))
            if (parser, profile) == first:
                return _fail_result(parser, profile)
            return _pass_result(parser, profile)

        _run_preflight_with_mock(self.expected_pairs, _fake_docs(1), side_effect)

        unique_pairs = list(dict.fromkeys(self.expected_pairs))
        self.assertEqual(len(called), len(unique_pairs))
        for pair in unique_pairs:
            self.assertIn(pair, called)


# ── ocr_primary (Step 7) ──────────────────────────────────────────────────────

class TestOcrPrimaryContracts(_SuiteContractMixin, unittest.TestCase):
    suite_name = "ocr_primary"
    expected_pairs = OCR_PRIMARY_PAIRS


class TestOcrPrimarySummaryEligibility(unittest.TestCase):

    def test_no_comparison_script_eligible(self):
        """ocr_primary has no native parsers; neither comparison script should be triggered."""
        planned = set(OCR_PRIMARY_PAIRS)
        for script_name, required in _run_batch._COMPARISON_REQUIREMENTS.items():
            self.assertFalse(
                required.issubset(planned),
                f"{script_name!r} must NOT be eligible for ocr_primary",
            )


# ── full_corpus (Step 8) ──────────────────────────────────────────────────────

class TestFullCorpusContracts(_SuiteContractMixin, unittest.TestCase):
    suite_name = "full_corpus"
    expected_pairs = FULL_CORPUS_PAIRS


class TestFullCorpusSummaryEligibility(unittest.TestCase):

    def test_build_parser_comparison_eligible(self):
        """full_corpus includes pymupdf/native + docling/native."""
        planned = set(FULL_CORPUS_PAIRS)
        required = _run_batch._COMPARISON_REQUIREMENTS["build_parser_comparison.py"]
        self.assertTrue(
            required.issubset(planned),
            "build_parser_comparison.py should be eligible for full_corpus",
        )

    def test_build_native_parser_comparison_eligible(self):
        """full_corpus includes pymupdf/native + docling/native + mineru/txt."""
        planned = set(FULL_CORPUS_PAIRS)
        required = _run_batch._COMPARISON_REQUIREMENTS["build_native_parser_comparison.py"]
        self.assertTrue(
            required.issubset(planned),
            "build_native_parser_comparison.py should be eligible for full_corpus",
        )

    def test_one_doc_eight_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(1), FULL_CORPUS_PAIRS, Path(tmp))
        self.assertEqual(len(plan), 8)

    def test_two_docs_sixteen_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(2), FULL_CORPUS_PAIRS, Path(tmp))
        self.assertEqual(len(plan), 16)


# ── diagnostic_ocr (Step 9) ───────────────────────────────────────────────────

class TestDiagnosticOcrContracts(_SuiteContractMixin, unittest.TestCase):
    suite_name = "diagnostic_ocr"
    expected_pairs = DIAGNOSTIC_OCR_PAIRS


class TestDiagnosticOcrSummaryEligibility(unittest.TestCase):

    def test_no_comparison_script_eligible(self):
        """diagnostic_ocr has no native parsers; no comparison script should fire."""
        planned = set(DIAGNOSTIC_OCR_PAIRS)
        for script_name, required in _run_batch._COMPARISON_REQUIREMENTS.items():
            self.assertFalse(
                required.issubset(planned),
                f"{script_name!r} must NOT be eligible for diagnostic_ocr",
            )


# ── visual_ablation (Step 10) ─────────────────────────────────────────────────

class TestVisualAblationContracts(_SuiteContractMixin, unittest.TestCase):
    suite_name = "visual_ablation"
    expected_pairs = VISUAL_ABLATION_PAIRS


class TestVisualAblationSummaryEligibility(unittest.TestCase):

    def test_no_comparison_script_eligible(self):
        """visual_ablation has no native parsers; no comparison script should fire."""
        planned = set(VISUAL_ABLATION_PAIRS)
        for script_name, required in _run_batch._COMPARISON_REQUIREMENTS.items():
            self.assertFalse(
                required.issubset(planned),
                f"{script_name!r} must NOT be eligible for visual_ablation",
            )


# ── smoke (Step 11) ───────────────────────────────────────────────────────────

class TestSmokeContracts(_SuiteContractMixin, unittest.TestCase):
    suite_name = "smoke"
    expected_pairs = SMOKE_PAIRS


class TestSmokeSummaryEligibility(unittest.TestCase):

    def test_build_parser_comparison_eligible(self):
        """smoke includes pymupdf/native + docling/native."""
        planned = set(SMOKE_PAIRS)
        required = _run_batch._COMPARISON_REQUIREMENTS["build_parser_comparison.py"]
        self.assertTrue(
            required.issubset(planned),
            "build_parser_comparison.py should be eligible for smoke",
        )

    def test_build_native_parser_comparison_eligible(self):
        """smoke includes pymupdf/native + docling/native + mineru/txt."""
        planned = set(SMOKE_PAIRS)
        required = _run_batch._COMPARISON_REQUIREMENTS["build_native_parser_comparison.py"]
        self.assertTrue(
            required.issubset(planned),
            "build_native_parser_comparison.py should be eligible for smoke",
        )

    def test_does_not_include_mvp_structured(self):
        """smoke must not include mvp_structured (PP-FormulaNet_plus-L dependency)."""
        self.assertNotIn(("paddleocr", "mvp_structured"), SMOKE_PAIRS)

    def test_one_doc_four_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(1), SMOKE_PAIRS, Path(tmp))
        self.assertEqual(len(plan), 4)

    def test_two_docs_eight_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(2), SMOKE_PAIRS, Path(tmp))
        self.assertEqual(len(plan), 8)


# ── default (Step 12) ─────────────────────────────────────────────────────────

class TestDefaultContracts(_SuiteContractMixin, unittest.TestCase):
    suite_name = "default"
    expected_pairs = DEFAULT_PAIRS


class TestDefaultNonDivergence(unittest.TestCase):
    """default must stay identical to ocr_primary — any drift is a regression."""

    def test_default_equals_ocr_primary(self):
        config = _load_config()
        self.assertEqual(
            config["suites"]["default"],
            config["suites"]["ocr_primary"],
            "default suite diverged from ocr_primary — update both or keep them in sync",
        )

    def test_default_cli_resolves_to_default_suite(self):
        """resolve_jobs_spec with no suite/parser uses 'default'."""
        config = _load_config()
        args = type("Args", (), {"suite": None, "parser": None, "profile": None})()
        pairs = _run_batch.resolve_jobs_spec(args, config)
        self.assertEqual(pairs, DEFAULT_PAIRS)

    def test_default_one_doc_four_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _build_plan_no_resume(_fake_docs(1), DEFAULT_PAIRS, Path(tmp))
        self.assertEqual(len(plan), 4)


if __name__ == "__main__":
    unittest.main()
