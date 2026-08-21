"""
Integration tests for build_run_plan() resume logic.

Patches validate_resume_candidate inside _run_batch to verify that:
- ok=True → rec.status="skip" with validation attached
- ok=False → rec.status="pending"
- resume=False → validate_resume_candidate not called
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import load_run_batch_module
from src.benchmark.artifact_policy import ArtifactPolicy

_run_batch = load_run_batch_module()

_PARSER = "pymupdf"
_PROFILE = "native"
_POLICY = ArtifactPolicy.from_cli(["all"])


def _ok_result() -> dict:
    return {"schema_version": 1, "parser": _PARSER, "profile": _PROFILE,
            "document": "A.pdf", "ok": True,
            "checks": [{"name": "artifact document.md", "status": "pass"}]}


def _fail_result() -> dict:
    return {"schema_version": 1, "parser": _PARSER, "profile": _PROFILE,
            "document": "A.pdf", "ok": False,
            "checks": [{"name": "metrics.json", "status": "fail",
                         "detail": "file not found"}]}


def _build_plan(doc: Path, output_root: Path, resume: bool,
                resume_result: dict | None = None, policy=None):
    policy = policy or _POLICY
    docs = [doc]
    jobs_spec = [(_PARSER, _PROFILE)]
    with patch.object(_run_batch, "validate_resume_candidate",
                      return_value=resume_result or _ok_result()) as mock_vrc:
        plan, _ = _run_batch.build_run_plan(docs, jobs_spec, output_root, resume,
                                             artifact_policy=policy)
    return plan, mock_vrc


class TestResumeSkip(unittest.TestCase):

    def test_ok_result_sets_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            plan, _ = _build_plan(doc, t, resume=True, resume_result=_ok_result())
        self.assertEqual(plan[0].status, "skip")

    def test_skip_has_validation_attached(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            plan, _ = _build_plan(doc, t, resume=True, resume_result=_ok_result())
        self.assertIsNotNone(plan[0].validation)
        self.assertTrue(plan[0].validation["ok"])


class TestResumePending(unittest.TestCase):

    def test_fail_result_stays_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            plan, _ = _build_plan(doc, t, resume=True, resume_result=_fail_result())
        self.assertEqual(plan[0].status, "pending")

    def test_fail_result_no_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            plan, _ = _build_plan(doc, t, resume=True, resume_result=_fail_result())
        self.assertIsNone(plan[0].validation)


class TestResumeDisabled(unittest.TestCase):

    def test_resume_false_does_not_call_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            _, mock_vrc = _build_plan(doc, t, resume=False)
        mock_vrc.assert_not_called()

    def test_resume_false_all_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            plan, _ = _build_plan(doc, t, resume=False)
        self.assertEqual(plan[0].status, "pending")


class TestResumeMultipleJobs(unittest.TestCase):

    def test_mixed_ok_fail(self):
        """Two jobs: first valid (skip), second invalid (pending)."""
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc = t / "A.pdf"; doc.touch()
            jobs = [(_PARSER, _PROFILE), ("docling", "native")]
            results = [_ok_result(), _fail_result()]
            with patch.object(_run_batch, "validate_resume_candidate",
                              side_effect=results):
                plan, _ = _run_batch.build_run_plan(
                    [doc], jobs, t, True, artifact_policy=_POLICY
                )
        self.assertEqual(plan[0].status, "skip")
        self.assertEqual(plan[1].status, "pending")


if __name__ == "__main__":
    unittest.main()
