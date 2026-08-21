"""
Integration tests for post-execution validation inside execute_plan().

Mocks _run_subprocess and validate_post_execution — no Docker, no models.
Verifies that exit-code=0 triggers post-validation, that DONE/FAIL status
is set based on validation.ok, that parser failures skip the validator,
and that the results JSONL contains the validation field.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import load_run_batch_module
from src.benchmark.artifact_policy import ArtifactPolicy

_run_batch = load_run_batch_module()

_PARSER = "pymupdf"
_PROFILE = "native"
_POLICY = ArtifactPolicy.from_cli(["all"])


def _make_job(tmp: Path, *, status: str = "pending", parser: str = _PARSER,
               profile: str = _PROFILE) -> _run_batch.JobRecord:
    doc = tmp / "A.pdf"
    doc.touch()
    return _run_batch.JobRecord(
        doc=doc,
        parser=parser,
        profile=profile,
        sha256="deadbeef",
        output_dir=str(tmp / parser / "A" / profile),
    )


def _validation_result(ok: bool, has_warn: bool = False) -> dict:
    checks = [{"name": "artifact document.md", "status": "pass"}]
    if not ok:
        checks.append({"name": "artifact document.md", "status": "fail",
                        "detail": "file not found"})
    if has_warn:
        checks.append({"name": "metrics processing.pages_processed", "status": "warn",
                        "detail": "2/3 pages reported as processed"})
    return {"schema_version": 1, "parser": _PARSER, "profile": _PROFILE,
            "document": "A.pdf", "ok": ok, "checks": checks}


def _run_plan(tmp: Path, plan, mock_exit_code: int, mock_validation: dict | None = None,
              continue_on_error: bool = False):
    results_path = tmp / "results.jsonl"
    log_lines: list[str] = []

    def _log(msg: str) -> None:
        log_lines.append(msg)

    with patch.object(_run_batch, "_run_subprocess", return_value=mock_exit_code), \
         patch.object(_run_batch, "validate_post_execution",
                      return_value=mock_validation or _validation_result(True)):
        _run_batch.execute_plan(
            plan, ["docker", "compose"], "/outputs", "all",
            continue_on_error, results_path, _log,
            output_root=tmp,
            artifact_policy=_POLICY,
        )
    return results_path, log_lines


class TestExecuteExit0ValidationPass(unittest.TestCase):

    def test_exit0_pass_status_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            rp, _ = _run_plan(t, plan, 0, _validation_result(True))
        self.assertEqual(plan[0].status, "done")
        self.assertIsNotNone(plan[0].validation)
        self.assertTrue(plan[0].validation["ok"])

    def test_exit0_warn_status_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            rp, log = _run_plan(t, plan, 0, _validation_result(True, has_warn=True))
        self.assertEqual(plan[0].status, "done")
        warn_logged = any("[WARN ]" in line for line in log)
        self.assertTrue(warn_logged)


class TestExecuteExit0ValidationFail(unittest.TestCase):

    def test_exit0_fail_status_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            rp, _ = _run_plan(t, plan, 0, _validation_result(False))
        self.assertEqual(plan[0].status, "fail")

    def test_exit0_fail_exit_code_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            _run_plan(t, plan, 0, _validation_result(False))
        self.assertEqual(plan[0].exit_code, 0)

    def test_exit0_fail_error_starts_with_post_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            _run_plan(t, plan, 0, _validation_result(False))
        self.assertIsNotNone(plan[0].error)
        self.assertTrue(plan[0].error.startswith("post_validation:"))


class TestExecuteParserFailure(unittest.TestCase):

    def test_exit_nonzero_status_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            with patch.object(_run_batch, "_run_subprocess", return_value=1), \
                 patch.object(_run_batch, "validate_post_execution") as mock_v:
                rp = t / "results.jsonl"
                _run_batch.execute_plan(
                    plan, ["docker", "compose"], "/outputs", "all",
                    False, rp, lambda msg: None,
                    output_root=t,
                    artifact_policy=_POLICY,
                )
                mock_v.assert_not_called()
        self.assertEqual(plan[0].status, "fail")

    def test_exit_nonzero_validation_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            with patch.object(_run_batch, "_run_subprocess", return_value=2), \
                 patch.object(_run_batch, "validate_post_execution"):
                rp = t / "results.jsonl"
                _run_batch.execute_plan(
                    plan, ["docker", "compose"], "/outputs", "all",
                    False, rp, lambda msg: None,
                    output_root=t,
                    artifact_policy=_POLICY,
                )
        self.assertIsNone(plan[0].validation)


class TestExecuteContinueOnError(unittest.TestCase):

    def test_fail_without_continue_aborts_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc1 = t / "A.pdf"; doc1.touch()
            doc2 = t / "B.pdf"; doc2.touch()
            plan = [
                _run_batch.JobRecord(doc=doc1, parser=_PARSER, profile=_PROFILE,
                                     sha256="s1", output_dir=str(t / "o1")),
                _run_batch.JobRecord(doc=doc2, parser=_PARSER, profile=_PROFILE,
                                     sha256="s2", output_dir=str(t / "o2")),
            ]
            _run_plan(t, plan, 0, _validation_result(False), continue_on_error=False)
        self.assertEqual(plan[0].status, "fail")
        self.assertEqual(plan[1].status, "aborted")

    def test_fail_with_continue_runs_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            doc1 = t / "A.pdf"; doc1.touch()
            doc2 = t / "B.pdf"; doc2.touch()
            plan = [
                _run_batch.JobRecord(doc=doc1, parser=_PARSER, profile=_PROFILE,
                                     sha256="s1", output_dir=str(t / "o1")),
                _run_batch.JobRecord(doc=doc2, parser=_PARSER, profile=_PROFILE,
                                     sha256="s2", output_dir=str(t / "o2")),
            ]
            _run_plan(t, plan, 0, _validation_result(False), continue_on_error=True)
        self.assertEqual(plan[0].status, "fail")
        self.assertNotEqual(plan[1].status, "aborted")


class TestResultsJsonl(unittest.TestCase):

    def test_done_result_has_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            rp, _ = _run_plan(t, plan, 0, _validation_result(True))
            rows = [json.loads(ln) for ln in rp.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(rows), 1)
        self.assertIn("validation", rows[0])
        self.assertIsNotNone(rows[0]["validation"])

    def test_fail_result_has_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            rp, _ = _run_plan(t, plan, 0, _validation_result(False))
            rows = [json.loads(ln) for ln in rp.read_text().splitlines() if ln.strip()]
        self.assertIn("validation", rows[0])
        self.assertFalse(rows[0]["validation"]["ok"])

    def test_parser_failure_has_validation_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t)]
            rp = t / "r.jsonl"
            with patch.object(_run_batch, "_run_subprocess", return_value=1), \
                 patch.object(_run_batch, "validate_post_execution"):
                _run_batch.execute_plan(
                    plan, ["docker", "compose"], "/outputs", "all",
                    False, rp, lambda msg: None,
                    output_root=t,
                    artifact_policy=_POLICY,
                )
            rows = [json.loads(ln) for ln in rp.read_text().splitlines() if ln.strip()]
        self.assertIn("validation", rows[0])
        self.assertIsNone(rows[0]["validation"])

    def test_skip_result_has_validation_from_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            plan = [_make_job(t, status="pending")]
            plan[0].status = "skip"
            plan[0].validation = _validation_result(True)
            rp = t / "r.jsonl"
            _run_batch.execute_plan(
                plan, ["docker", "compose"], "/outputs", "all",
                False, rp, lambda msg: None,
                output_root=t,
                artifact_policy=_POLICY,
            )
            rows = [json.loads(ln) for ln in rp.read_text().splitlines() if ln.strip()]
        self.assertEqual(rows[0]["status"], "skip")
        self.assertIsNotNone(rows[0]["validation"])
        self.assertTrue(rows[0]["validation"]["ok"])


class TestBatchExitCode(unittest.TestCase):
    """Verify batch_summary counts lead to correct sys.exit via counts."""

    def test_counts_done_only(self):
        plan = [
            MagicMock(status="done"),
            MagicMock(status="done"),
        ]
        counts = _run_batch.batch_summary(plan, 1.0, lambda msg: None)
        self.assertEqual(counts["fail"], 0)
        self.assertEqual(counts["aborted"], 0)

    def test_counts_fail_nonzero(self):
        plan = [MagicMock(status="done"), MagicMock(status="fail")]
        counts = _run_batch.batch_summary(plan, 1.0, lambda msg: None)
        self.assertGreater(counts["fail"], 0)

    def test_counts_aborted_nonzero(self):
        plan = [MagicMock(status="done"), MagicMock(status="aborted")]
        counts = _run_batch.batch_summary(plan, 1.0, lambda msg: None)
        self.assertGreater(counts["aborted"], 0)

    def test_counts_skip_only(self):
        plan = [MagicMock(status="skip")]
        counts = _run_batch.batch_summary(plan, 1.0, lambda msg: None)
        self.assertEqual(counts["fail"], 0)
        self.assertEqual(counts["aborted"], 0)


if __name__ == "__main__":
    unittest.main()
