"""
Integration tests for build_*_summary.py scripts.

Runs scripts via subprocess against synthetic fixture directories.
No Docker, no model downloads, no real PDF inference.
"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import make_metrics, run_script, write_metrics


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestProfileRequired(unittest.TestCase):
    """--profile must be required; missing it returns exit 2."""

    def _assert_profile_required(self, script: str) -> None:
        result = run_script(script)
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("--profile", result.stderr)

    def test_pymupdf_requires_profile(self) -> None:
        self._assert_profile_required("build_pymupdf_summary.py")

    def test_docling_requires_profile(self) -> None:
        self._assert_profile_required("build_docling_summary.py")

    def test_mineru_requires_profile(self) -> None:
        self._assert_profile_required("build_mineru_summary.py")


class TestPyMuPDFSummary(unittest.TestCase):

    def test_profile_isolation(self) -> None:
        """Only the requested profile is included; the other profile is invisible."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "A", "native",
                make_metrics("pymupdf", "native", "A.pdf", tokens=123),
            )
            write_metrics(
                out_root, "pymupdf", "A", "ocr_auto_rapidtess",
                make_metrics("pymupdf", "ocr_auto_rapidtess", "A.pdf", tokens=999),
            )

            result = run_script(
                "build_pymupdf_summary.py",
                "--profile", "native",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "pymupdf" / "native" / "summary.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["profile"], "native")
            self.assertEqual(rows[0]["tokens"], "123")
            # The other profile's tokens must not appear
            for row in rows:
                self.assertNotEqual(row["tokens"], "999")

    def test_v2_field_paths(self) -> None:
        """All v2 field paths resolve correctly into the CSV."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "DOC", "native",
                make_metrics(
                    "pymupdf", "native", "DOC.pdf",
                    tokens=1234,
                    tokens_per_page=61.7,
                    markdown_mb=0.042,
                    jsonl_mb=0.21,
                    size_ratio=9.8,
                    empty_output_pages=2,
                ),
            )

            result = run_script(
                "build_pymupdf_summary.py",
                "--profile", "native",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "pymupdf" / "native" / "summary.csv")
            row = rows[0]
            self.assertEqual(row["tokens"], "1234")
            self.assertEqual(row["tokens_per_page"], "61.7")
            self.assertEqual(row["markdown_mb"], "0.042")
            self.assertEqual(row["jsonl_mb"], "0.21")
            self.assertEqual(row["size_ratio"], "9.8")
            self.assertEqual(row["blank_pages"], "2")

    def test_profile_without_results_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            result = run_script(
                "build_pymupdf_summary.py",
                "--profile", "ocr_auto_rapidtess",
                "--output-root", str(out_tmp),
                "--metrics-root", str(met_tmp),
            )
            self.assertEqual(result.returncode, 1)
            combined = result.stdout + result.stderr
            self.assertIn("No metrics found", combined)
            # No CSV should be written
            csv_path = Path(met_tmp) / "pymupdf" / "ocr_auto_rapidtess" / "summary.csv"
            self.assertFalse(csv_path.exists())

    def test_custom_metrics_root(self) -> None:
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "A", "native",
                make_metrics("pymupdf", "native", "A.pdf"),
            )
            result = run_script(
                "build_pymupdf_summary.py",
                "--profile", "native",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((met_root / "pymupdf" / "native" / "summary.csv").exists())
            self.assertTrue((met_root / "pymupdf" / "native" / "summary.md").exists())

    def test_none_fields_not_converted_to_zero(self) -> None:
        """Optional fields that are None must appear as empty/None, never '0'."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            # Use None for optional output fields
            data = make_metrics("pymupdf", "native", "A.pdf")
            data["output"]["input_to_clean_markdown_size_ratio"] = None
            data["processing"]["extraction_pages_per_second"] = None
            write_metrics(out_root, "pymupdf", "A", "native", data)

            result = run_script(
                "build_pymupdf_summary.py",
                "--profile", "native",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "pymupdf" / "native" / "summary.csv")
            row = rows[0]
            self.assertNotEqual(row["size_ratio"], "0")
            self.assertNotEqual(row["pages_per_second"], "0")


class TestDoclingStructuralFields(unittest.TestCase):

    def test_tables_and_pictures_from_v2_paths(self) -> None:
        """tables reads tables_detected; pictures reads images_detected."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "docling", "A", "native",
                make_metrics("docling", "native", "A.pdf", tables=7, images=8),
            )
            result = run_script(
                "build_docling_summary.py",
                "--profile", "native",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "docling" / "native" / "summary.csv")
            self.assertEqual(rows[0]["tables"], "7")
            self.assertEqual(rows[0]["pictures"], "8")


class TestMinerUChartsNone(unittest.TestCase):

    def test_charts_none_not_converted_to_zero(self) -> None:
        """charts_detected=None must not become '0' in the CSV."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "mineru", "A", "txt",
                make_metrics("mineru", "txt", "A.pdf", charts=None),
            )
            result = run_script(
                "build_mineru_summary.py",
                "--profile", "txt",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "mineru" / "txt" / "summary.csv")
            self.assertNotEqual(rows[0]["charts"], "0")

            md = (met_root / "mineru" / "txt" / "summary.md").read_text()
            self.assertIn("N/A", md)

    def test_charts_integer_value_preserved(self) -> None:
        """When charts_detected is an int, it appears correctly in the CSV."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "mineru", "A", "auto",
                make_metrics("mineru", "auto", "A.pdf", charts=5),
            )
            result = run_script(
                "build_mineru_summary.py",
                "--profile", "auto",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "mineru" / "auto" / "summary.csv")
            self.assertEqual(rows[0]["charts"], "5")


if __name__ == "__main__":
    unittest.main()
