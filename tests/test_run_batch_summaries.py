"""
Unit tests for run_batch.run_summary_scripts().

Imports run_batch as a module and mocks subprocess.run to verify:
- which comparison scripts are triggered based on jobs_spec
- which are skipped
- that paths are propagated correctly
- that failures are reported

No Docker, models, or inference required.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load run_batch as a module without executing main().
# Must register in sys.modules before exec_module so that @dataclass
# can resolve the module's namespace via sys.modules[cls.__module__].
_spec = importlib.util.spec_from_file_location(
    "scripts_run_batch",
    ROOT / "scripts" / "run_batch.py",
)
_run_batch = importlib.util.module_from_spec(_spec)
sys.modules["scripts_run_batch"] = _run_batch
_spec.loader.exec_module(_run_batch)


def _make_completed(returncode: int) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    return m


class TestRunSummaryScripts(unittest.TestCase):

    def _run(
        self,
        jobs_spec: list[tuple[str, str]],
        subprocess_side_effect: list[MagicMock] | None = None,
        output_root: Path | None = None,
    ) -> tuple[bool, MagicMock]:
        if output_root is None:
            output_root = ROOT / "outputs"

        side_effect = subprocess_side_effect or [_make_completed(0), _make_completed(0)]

        with patch.object(
            _run_batch.subprocess,
            "run",
            side_effect=side_effect,
        ) as mock_run:
            ok = _run_batch.run_summary_scripts(jobs_spec, output_root)

        return ok, mock_run

    def test_ocr_primary_skips_both_comparisons(self) -> None:
        """ocr_primary suite has no native profiles; both comparisons are skipped."""
        jobs = [
            ("pymupdf", "ocr_auto_rapidtess"),
            ("docling", "ocr_auto"),
            ("mineru", "auto"),
            ("paddleocr", "mvp_structured"),
        ]
        ok, mock_run = self._run(jobs)
        self.assertTrue(ok)
        mock_run.assert_not_called()

    def test_native_native_txt_triggers_both_comparisons(self) -> None:
        """pymupdf/native + docling/native + mineru/txt triggers both scripts."""
        jobs = [
            ("pymupdf", "native"),
            ("docling", "native"),
            ("mineru", "txt"),
        ]
        ok, mock_run = self._run(jobs, [_make_completed(0), _make_completed(0)])
        self.assertTrue(ok)
        self.assertEqual(mock_run.call_count, 2)

        called_scripts = [
            Path(call_args[0][0][1]).name
            for call_args in mock_run.call_args_list
        ]
        self.assertIn("build_parser_comparison.py", called_scripts)
        self.assertIn("build_native_parser_comparison.py", called_scripts)

    def test_native_native_only_triggers_two_parser_comparison(self) -> None:
        """pymupdf/native + docling/native (no mineru/txt) triggers only the 2-parser comparison."""
        jobs = [
            ("pymupdf", "native"),
            ("docling", "native"),
        ]
        ok, mock_run = self._run(jobs, [_make_completed(0)])
        self.assertTrue(ok)
        self.assertEqual(mock_run.call_count, 1)

        called_script = Path(mock_run.call_args[0][0][1]).name
        self.assertEqual(called_script, "build_parser_comparison.py")

    def test_output_root_and_metrics_root_propagated(self) -> None:
        """--output-root and --metrics-root values are forwarded to subprocesses."""
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            jobs = [("pymupdf", "native"), ("docling", "native")]
            _, mock_run = self._run(jobs, [_make_completed(0)], output_root=out_root)

            call_args = mock_run.call_args[0][0]
            self.assertIn("--output-root", call_args)
            out_root_idx = call_args.index("--output-root")
            self.assertEqual(call_args[out_root_idx + 1], str(out_root))

            self.assertIn("--metrics-root", call_args)
            met_idx = call_args.index("--metrics-root")
            expected_metrics_root = str(ROOT / "metrics")
            self.assertEqual(call_args[met_idx + 1], expected_metrics_root)

    def test_summary_failure_returns_false(self) -> None:
        """If any comparison script fails, run_summary_scripts returns False."""
        jobs = [
            ("pymupdf", "native"),
            ("docling", "native"),
            ("mineru", "txt"),
        ]
        # First comparison fails, second succeeds
        ok, mock_run = self._run(
            jobs,
            [_make_completed(1), _make_completed(0)],
        )
        self.assertFalse(ok)
        # Both scripts are still attempted (no early abort)
        self.assertEqual(mock_run.call_count, 2)

    def test_both_failures_returns_false(self) -> None:
        jobs = [("pymupdf", "native"), ("docling", "native"), ("mineru", "txt")]
        ok, mock_run = self._run(jobs, [_make_completed(1), _make_completed(1)])
        self.assertFalse(ok)

    def test_empty_jobs_skips_all(self) -> None:
        ok, mock_run = self._run([])
        self.assertTrue(ok)
        mock_run.assert_not_called()

    def test_mixed_suite_with_native_triggers_both(self) -> None:
        """A suite that includes native profiles alongside OCR triggers comparisons."""
        jobs = [
            ("pymupdf", "native"),
            ("pymupdf", "ocr_auto_rapidtess"),
            ("docling", "native"),
            ("docling", "ocr_auto"),
            ("mineru", "txt"),
        ]
        ok, mock_run = self._run(jobs, [_make_completed(0), _make_completed(0)])
        self.assertTrue(ok)
        self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
