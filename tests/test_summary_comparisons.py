"""
Integration tests for build_parser_comparison.py and
build_native_parser_comparison.py.

Runs scripts via subprocess against synthetic fixtures.
No Docker, models or inference.
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


class TestParserComparison(unittest.TestCase):
    """Tests for build_parser_comparison.py (pymupdf/native vs docling/native)."""

    def test_uses_native_profiles_only(self) -> None:
        """Comparison uses only native profiles; other profiles are ignored."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "A", "native",
                make_metrics("pymupdf", "native", "A.pdf", pipeline_seconds=2.0, tokens=100),
            )
            write_metrics(
                out_root, "pymupdf", "A", "ocr_auto_rapidtess",
                make_metrics("pymupdf", "ocr_auto_rapidtess", "A.pdf", pipeline_seconds=99.0, tokens=9999),
            )
            write_metrics(
                out_root, "docling", "A", "native",
                make_metrics("docling", "native", "A.pdf", pipeline_seconds=6.0, tokens=125, tables=4, images=3),
            )
            write_metrics(
                out_root, "docling", "A", "ocr_auto",
                make_metrics("docling", "ocr_auto", "A.pdf", pipeline_seconds=88.0, tokens=8888),
            )

            result = run_script(
                "build_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "parser_comparison.csv")
            self.assertEqual(len(rows), 1)
            # Must use native values, never the distractor values
            self.assertEqual(rows[0]["pymupdf_seconds"], "2.0")
            self.assertEqual(rows[0]["docling_seconds"], "6.0")
            self.assertNotIn("99.0", [r["pymupdf_seconds"] for r in rows])

    def test_historical_formulas_preserved(self) -> None:
        """slowdown and token_delta_percent formulas are unchanged."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "A", "native",
                make_metrics("pymupdf", "native", "A.pdf", pipeline_seconds=2.0, tokens=100),
            )
            write_metrics(
                out_root, "docling", "A", "native",
                make_metrics("docling", "native", "A.pdf", pipeline_seconds=6.0, tokens=125),
            )

            result = run_script(
                "build_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "parser_comparison.csv")
            row = rows[0]
            self.assertEqual(row["docling_slowdown_x"], "3.0")
            self.assertEqual(row["token_delta_percent"], "25.0")

    def test_structural_fields_from_v2_paths(self) -> None:
        """tables and pictures come from content_elements.parser_output."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "A", "native",
                make_metrics("pymupdf", "native", "A.pdf"),
            )
            write_metrics(
                out_root, "docling", "A", "native",
                make_metrics("docling", "native", "A.pdf", tables=11, images=7),
            )

            result = run_script(
                "build_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "parser_comparison.csv")
            self.assertEqual(rows[0]["docling_tables"], "11")
            self.assertEqual(rows[0]["docling_pictures"], "7")

    def test_incomplete_corpus_rejected(self) -> None:
        """Comparison must fail if document sets differ; no partial CSV written."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            write_metrics(
                out_root, "pymupdf", "A", "native",
                make_metrics("pymupdf", "native", "A.pdf"),
            )
            write_metrics(
                out_root, "pymupdf", "B", "native",
                make_metrics("pymupdf", "native", "B.pdf"),
            )
            write_metrics(
                out_root, "docling", "A", "native",
                make_metrics("docling", "native", "A.pdf"),
            )
            # B.pdf missing for docling/native

            result = run_script(
                "build_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 1)
            combined = result.stdout + result.stderr
            self.assertIn("B.pdf", combined)
            self.assertFalse((met_root / "parser_comparison.csv").exists())
            self.assertFalse((met_root / "parser_comparison.md").exists())


class TestNativeParserComparison(unittest.TestCase):
    """Tests for build_native_parser_comparison.py."""

    def _write_three_parser_fixture(
        self,
        out_root: Path,
        *,
        py_seconds: float = 2.0,
        dc_seconds: float = 4.0,
        mu_seconds: float = 8.0,
        tables: int = 5,
        images: int = 3,
    ) -> None:
        write_metrics(
            out_root, "pymupdf", "A", "native",
            make_metrics("pymupdf", "native", "A.pdf", pipeline_seconds=py_seconds),
        )
        write_metrics(
            out_root, "docling", "A", "native",
            make_metrics("docling", "native", "A.pdf", pipeline_seconds=dc_seconds, tables=tables, images=images),
        )
        write_metrics(
            out_root, "mineru", "A", "txt",
            make_metrics("mineru", "txt", "A.pdf", pipeline_seconds=mu_seconds),
        )

    def test_uses_native_native_txt_profiles(self) -> None:
        """Only native/native/txt profiles are used; auto is ignored."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            self._write_three_parser_fixture(out_root, mu_seconds=8.0)
            # Distractor: mineru/auto with absurd value
            write_metrics(
                out_root, "mineru", "A", "auto",
                make_metrics("mineru", "auto", "A.pdf", pipeline_seconds=999.0),
            )

            result = run_script(
                "build_native_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "native_parser_comparison.csv")
            self.assertEqual(rows[0]["mineru_seconds"], "8.0")
            self.assertNotIn("999.0", [r["mineru_seconds"] for r in rows])

    def test_ratio_formulas_preserved(self) -> None:
        """Docling/PyMuPDF = 2, MinerU/PyMuPDF = 4, MinerU/Docling = 2."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            self._write_three_parser_fixture(out_root, py_seconds=2.0, dc_seconds=4.0, mu_seconds=8.0)

            result = run_script(
                "build_native_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "native_parser_comparison.csv")
            row = rows[0]
            self.assertEqual(row["docling_vs_pymupdf_x"], "2.0")
            self.assertEqual(row["mineru_vs_pymupdf_x"], "4.0")
            self.assertEqual(row["mineru_vs_docling_x"], "2.0")

    def test_structural_fields_from_v2_paths(self) -> None:
        """tables and pictures come from content_elements.parser_output."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            self._write_three_parser_fixture(out_root, tables=9, images=6)

            result = run_script(
                "build_native_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            rows = _read_csv(met_root / "native_parser_comparison.csv")
            self.assertEqual(rows[0]["docling_tables"], "9")
            self.assertEqual(rows[0]["docling_pictures"], "6")

    def test_incomplete_corpus_rejected(self) -> None:
        """Missing B.pdf for mineru/txt must fail; no partial CSV written."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            # A and B for pymupdf/docling, only A for mineru
            for doc in ("A", "B"):
                write_metrics(
                    out_root, "pymupdf", doc, "native",
                    make_metrics("pymupdf", "native", f"{doc}.pdf"),
                )
                write_metrics(
                    out_root, "docling", doc, "native",
                    make_metrics("docling", "native", f"{doc}.pdf"),
                )
            write_metrics(
                out_root, "mineru", "A", "txt",
                make_metrics("mineru", "txt", "A.pdf"),
            )

            result = run_script(
                "build_native_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 1)
            combined = result.stdout + result.stderr
            self.assertIn("B.pdf", combined)
            self.assertFalse((met_root / "native_parser_comparison.csv").exists())
            self.assertFalse((met_root / "native_parser_comparison.md").exists())

    def test_markdown_declares_profiles(self) -> None:
        """Markdown must explicitly state which profile each parser uses."""
        with tempfile.TemporaryDirectory() as out_tmp, \
             tempfile.TemporaryDirectory() as met_tmp:
            out_root = Path(out_tmp)
            met_root = Path(met_tmp)

            self._write_three_parser_fixture(out_root)

            result = run_script(
                "build_native_parser_comparison.py",
                "--output-root", str(out_root),
                "--metrics-root", str(met_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            md = (met_root / "native_parser_comparison.md").read_text()
            self.assertIn("native", md)
            self.assertIn("txt", md)


if __name__ == "__main__":
    unittest.main()
