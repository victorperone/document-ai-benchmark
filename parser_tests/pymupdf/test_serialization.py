"""Tests for pymupdf_v2 metrics serialization contract."""
from __future__ import annotations

import json
import unittest

PARSER_NAME = "pymupdf"


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
                "pymupdf": "1.28.2",
                "pymupdf4llm": "1.28.2",
                "rapidocr": "1.4.0",
                "onnxruntime": "1.20.0",
                "tiktoken": "0.7.0",
            },
        },
        "document": {
            "sha256": "abc123",
            "pages": 3,
            "file_size_mb": 0.5,
            "has_text_layer": True,
        },
        "source_pdf": {"path": "test.pdf"},
        "processing": {
            "timing": {
                "initialization_seconds": 0.5,
                "extraction_seconds": 1.2,
                "pipeline_seconds": 2.0,
            },
            "ocr": {
                "enabled": True,
                "mode": "auto",
                "engine": "rapidtess",
                "language": "por",
                "dpi": 300,
                "pages_requested": 3,
                "pages_processed": 1,
                "pages_failed": 0,
            },
        },
        "content_elements": {},
        "heuristics": {},
        "tokens": {},
        "normalization": {},
        "output": {"clean_markdown_bytes": 512},
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

        metrics = _minimal_metrics()
        byte_paths = _find_bytes(metrics)
        self.assertEqual(byte_paths, [], f"Bytes found at: {byte_paths}")

    def test_schema_version_is_2(self):
        metrics = _minimal_metrics()
        self.assertEqual(metrics["benchmark"]["schema_version"], 2)


class TestVersionsBlock(unittest.TestCase):
    def test_tiktoken_in_versions(self):
        metrics = _minimal_metrics()
        self.assertIn("tiktoken", metrics["run"]["versions"])

    def test_pymupdf4llm_in_versions(self):
        metrics = _minimal_metrics()
        self.assertIn("pymupdf4llm", metrics["run"]["versions"])

    def test_rapidocr_in_versions(self):
        metrics = _minimal_metrics()
        self.assertIn("rapidocr", metrics["run"]["versions"])

    def test_onnxruntime_in_versions(self):
        metrics = _minimal_metrics()
        self.assertIn("onnxruntime", metrics["run"]["versions"])
