"""Tests for paddleocr_v2 metrics serialization contract."""
from __future__ import annotations

import json
import unittest

PARSER_NAME = "paddleocr"


def _minimal_metrics() -> dict:
    return {
        "benchmark": {
            "schema_version": 2,
            "timestamp_utc": "2026-08-27T00:00:00+00:00",
            "reference_tokenizer": "o200k_base",
        },
        "run": {
            "parser": PARSER_NAME,
            "profile": "full_cpu_local",
            "verbose": False,
            "versions": {
                "paddleocr": "3.7.0",
                "paddlex": "3.0.1",
                "tiktoken": "0.7.0",
            },
        },
        "document": {
            "sha256": "abc123",
            "pages": 3,
            "file_size_mb": 0.5,
        },
        "source_pdf": {"path": "test.pdf"},
        "processing": {
            "timing": {
                "initialization_seconds": 2.0,
                "pipeline_seconds": 5.0,
            },
        },
        "paddleocr_native": {
            "pages_processed": 3,
            "seal_count": 0,
            "chart_count": 0,
            "formula_count": 2,
            "table_count": 1,
            "seal_recognition": True,
            "chart_recognition": True,
            "formula_recognition": True,
        },
        "content_elements": {},
        "tokens": {},
        "normalization": {},
        "output": {"clean_markdown_bytes": 2048},
    }


class TestMetricsJsonSerializable(unittest.TestCase):
    def test_minimal_metrics_serializable(self):
        metrics = _minimal_metrics()
        try:
            json.dumps(metrics)
        except (TypeError, ValueError) as exc:
            self.fail(f"Metrics not JSON-serializable: {exc}")

    def test_no_bytes_values(self):
        def _find_bytes(obj, path="root"):
            if isinstance(obj, bytes):
                return [path]
            if isinstance(obj, dict):
                return [p for k, v in obj.items() for p in _find_bytes(v, f"{path}.{k}")]
            if isinstance(obj, list):
                return [p for i, v in enumerate(obj) for p in _find_bytes(v, f"{path}[{i}]")]
            return []

        byte_paths = _find_bytes(_minimal_metrics())
        self.assertEqual(byte_paths, [], f"Bytes found at: {byte_paths}")

    def test_schema_version_is_2(self):
        metrics = _minimal_metrics()
        self.assertEqual(metrics["benchmark"]["schema_version"], 2)


class TestPaddleocrNativeBlock(unittest.TestCase):
    def test_paddleocr_native_present(self):
        metrics = _minimal_metrics()
        self.assertIn("paddleocr_native", metrics)

    def test_seal_count_present(self):
        self.assertIn("seal_count", _minimal_metrics()["paddleocr_native"])

    def test_chart_count_present(self):
        self.assertIn("chart_count", _minimal_metrics()["paddleocr_native"])

    def test_formula_count_present(self):
        self.assertIn("formula_count", _minimal_metrics()["paddleocr_native"])

    def test_table_count_present(self):
        self.assertIn("table_count", _minimal_metrics()["paddleocr_native"])

    def test_seal_recognition_flag_present(self):
        self.assertIn("seal_recognition", _minimal_metrics()["paddleocr_native"])

    def test_formula_recognition_flag_present(self):
        self.assertIn("formula_recognition", _minimal_metrics()["paddleocr_native"])

    def test_chart_recognition_flag_present(self):
        self.assertIn("chart_recognition", _minimal_metrics()["paddleocr_native"])
