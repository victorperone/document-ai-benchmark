"""
Unit tests for src.benchmark.summary_io.

Uses only stdlib: unittest + tempfile. No pytest required.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.summary_io import (
    MetricsRecord,
    SummaryInputError,
    discover_metrics,
    load_metrics_by_document,
    require_same_documents,
)


def _make_metrics(
    parser: str,
    profile: str,
    document_file: str,
) -> dict:
    return {
        "run": {
            "parser": parser,
            "profile": profile,
        },
        "document": {
            "file": document_file,
            "pages": 10,
        },
    }


def _write_metrics(
    root: Path,
    parser: str,
    doc_stem: str,
    profile: str,
    data: dict,
) -> Path:
    metrics_dir = root / parser / doc_stem / profile
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = metrics_dir / "metrics.json"
    metrics_path.write_text(json.dumps(data), encoding="utf-8")
    return metrics_path


class TestDiscoverMetrics(unittest.TestCase):

    def test_profile_aware_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("pymupdf", "native", "A.pdf"),
            )
            _write_metrics(
                root, "pymupdf", "A", "ocr_auto_rapidtess",
                _make_metrics("pymupdf", "ocr_auto_rapidtess", "A.pdf"),
            )

            records = discover_metrics(root, parser="pymupdf", profile="native")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].profile, "native")
            self.assertEqual(records[0].document, "A.pdf")

    def test_discover_all_profiles_for_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("pymupdf", "native", "A.pdf"),
            )
            _write_metrics(
                root, "pymupdf", "A", "ocr_auto_rapidtess",
                _make_metrics("pymupdf", "ocr_auto_rapidtess", "A.pdf"),
            )

            records = discover_metrics(root, parser="pymupdf")
            self.assertEqual(len(records), 2)
            profiles = {r.profile for r in records}
            self.assertIn("native", profiles)
            self.assertIn("ocr_auto_rapidtess", profiles)

    def test_parser_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("docling", "native", "A.pdf"),
            )

            with self.assertRaises(SummaryInputError) as ctx:
                discover_metrics(root, parser="pymupdf", profile="native")

            self.assertIn("parser mismatch", str(ctx.exception))

    def test_profile_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("pymupdf", "ocr_auto", "A.pdf"),
            )

            with self.assertRaises(SummaryInputError) as ctx:
                discover_metrics(root, parser="pymupdf", profile="native")

            self.assertIn("profile mismatch", str(ctx.exception))

    def test_document_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("pymupdf", "native", "B.pdf"),
            )

            with self.assertRaises(SummaryInputError) as ctx:
                discover_metrics(root, parser="pymupdf", profile="native")

            self.assertIn("document mismatch", str(ctx.exception))

    def test_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics_dir = root / "pymupdf" / "A" / "native"
            metrics_dir.mkdir(parents=True)
            (metrics_dir / "metrics.json").write_text(
                "{not valid json", encoding="utf-8"
            )

            with self.assertRaises(SummaryInputError) as ctx:
                discover_metrics(root, parser="pymupdf", profile="native")

            self.assertIn("Invalid JSON", str(ctx.exception))

    def test_missing_required_fields_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                {"run": {"parser": "pymupdf"}},
            )

            with self.assertRaises(SummaryInputError) as ctx:
                discover_metrics(root, parser="pymupdf", profile="native")

            self.assertIn("Missing required field", str(ctx.exception))

    def test_legacy_layout_ignored(self) -> None:
        """metrics.json without a profile directory level is not discovered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Old layout: parser/doc/metrics.json (only 3 path components, not 4)
            legacy_dir = root / "pymupdf" / "A"
            legacy_dir.mkdir(parents=True)
            (legacy_dir / "metrics.json").write_text(
                json.dumps(_make_metrics("pymupdf", "native", "A.pdf")),
                encoding="utf-8",
            )

            records = discover_metrics(root, parser="pymupdf", profile="native")
            self.assertEqual(records, [])

    def test_nonexistent_root_returns_empty(self) -> None:
        """discover_metrics does not raise on a non-existent root path."""
        records = discover_metrics(
            Path("/tmp/__does_not_exist_benchmark_test__"),
            parser="pymupdf",
            profile="native",
        )
        self.assertEqual(records, [])

    def test_deterministic_ordering(self) -> None:
        """Results are sorted lexicographically regardless of filesystem order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for stem, file_ in (("C", "C.pdf"), ("A", "A.pdf"), ("B", "B.pdf")):
                _write_metrics(
                    root, "pymupdf", stem, "native",
                    _make_metrics("pymupdf", "native", file_),
                )

            records = discover_metrics(root, parser="pymupdf", profile="native")
            names = [r.document for r in records]
            self.assertEqual(names, sorted(names))


class TestLoadMetricsByDocument(unittest.TestCase):

    def test_returns_correct_document_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("pymupdf", "native", "A.pdf"),
            )
            _write_metrics(
                root, "pymupdf", "B", "native",
                _make_metrics("pymupdf", "native", "B.pdf"),
            )

            result = load_metrics_by_document(root, "pymupdf", "native")
            self.assertIn("A.pdf", result)
            self.assertIn("B.pdf", result)
            self.assertEqual(len(result), 2)

    def test_duplicate_document_raises(self) -> None:
        """load_metrics_by_document rejects two records with the same document.file."""
        data = _make_metrics("pymupdf", "native", "A.pdf")

        records = [
            MetricsRecord(
                path=Path("/tmp/first/metrics.json"),
                parser="pymupdf",
                profile="native",
                document="A.pdf",
                document_stem="A",
                data=data,
            ),
            MetricsRecord(
                path=Path("/tmp/second/metrics.json"),
                parser="pymupdf",
                profile="native",
                document="A.pdf",
                document_stem="A",
                data=data,
            ),
        ]

        with patch(
            "src.benchmark.summary_io.discover_metrics",
            return_value=records,
        ):
            with self.assertRaises(SummaryInputError):
                load_metrics_by_document(Path("/unused"), "pymupdf", "native")

    def test_profile_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_metrics(
                root, "pymupdf", "A", "native",
                _make_metrics("pymupdf", "native", "A.pdf"),
            )
            _write_metrics(
                root, "pymupdf", "A", "ocr_auto_rapidtess",
                _make_metrics("pymupdf", "ocr_auto_rapidtess", "A.pdf"),
            )

            result = load_metrics_by_document(root, "pymupdf", "native")
            self.assertEqual(set(result.keys()), {"A.pdf"})
            self.assertEqual(result["A.pdf"]["run"]["profile"], "native")


class TestRequireSameDocuments(unittest.TestCase):

    def test_equal_sets_returns_sorted_list(self) -> None:
        datasets = {
            "pymupdf/native": {"A.pdf": {}, "B.pdf": {}},
            "docling/native": {"B.pdf": {}, "A.pdf": {}},
        }
        result = require_same_documents(datasets)
        self.assertEqual(result, ["A.pdf", "B.pdf"])

    def test_different_sets_raises(self) -> None:
        datasets = {
            "pymupdf/native": {"A.pdf": {}, "B.pdf": {}},
            "docling/native": {"A.pdf": {}},
        }

        with self.assertRaises(SummaryInputError) as ctx:
            require_same_documents(datasets)

        self.assertIn("differ", str(ctx.exception))
        self.assertIn("B.pdf", str(ctx.exception))

    def test_three_parsers_different_sets_raises(self) -> None:
        datasets = {
            "pymupdf/native": {"A.pdf": {}, "B.pdf": {}},
            "docling/native": {"A.pdf": {}, "B.pdf": {}},
            "mineru/txt": {"A.pdf": {}},
        }

        with self.assertRaises(SummaryInputError) as ctx:
            require_same_documents(datasets)

        self.assertIn("B.pdf", str(ctx.exception))

    def test_empty_datasets_returns_empty(self) -> None:
        result = require_same_documents({})
        self.assertEqual(result, [])

    def test_single_dataset_returns_its_documents(self) -> None:
        datasets = {"pymupdf/native": {"A.pdf": {}, "C.pdf": {}}}
        result = require_same_documents(datasets)
        self.assertEqual(result, ["A.pdf", "C.pdf"])

    def test_empty_dataset_versus_filled_raises(self) -> None:
        """An empty dataset against a filled one must fail, not return empty silently."""
        datasets = {
            "pymupdf/native": {"A.pdf": {}},
            "docling/native": {},
        }

        with self.assertRaises(SummaryInputError):
            require_same_documents(datasets)


if __name__ == "__main__":
    unittest.main()
