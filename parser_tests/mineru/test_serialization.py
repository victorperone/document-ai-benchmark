"""Tests for mineru_v2 metrics serialization contract."""
from __future__ import annotations

import json
import unittest

PARSER_NAME = "mineru"


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
                "mineru": "3.4.4",
                "torch": "2.4.0",
                "tiktoken": "0.7.0",
            },
            "resolved_config": {
                "backend": "pipeline",
                "method": "auto",
                "formula": True,
                "table": True,
                "device": "cpu",
                "threads": 2,
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
                "pipeline_seconds": 10.0,
            },
        },
        "mineru_native": {
            "backend": "pipeline",
            "mode": "auto",
            "pages_processed": 3,
            "formula_enabled": True,
            "table_enabled": True,
        },
        "content_elements": {},
        "tokens": {},
        "normalization": {},
        "output": {"clean_markdown_bytes": 1024},
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


class TestResolvedConfigBlock(unittest.TestCase):
    def test_resolved_config_present(self):
        metrics = _minimal_metrics()
        self.assertIn("resolved_config", metrics["run"])

    def test_resolved_config_has_backend(self):
        rc = _minimal_metrics()["run"]["resolved_config"]
        self.assertIn("backend", rc)

    def test_resolved_config_has_method(self):
        rc = _minimal_metrics()["run"]["resolved_config"]
        self.assertIn("method", rc)

    def test_resolved_config_has_formula(self):
        rc = _minimal_metrics()["run"]["resolved_config"]
        self.assertIn("formula", rc)

    def test_resolved_config_has_table(self):
        rc = _minimal_metrics()["run"]["resolved_config"]
        self.assertIn("table", rc)


class TestMineruNativeBlock(unittest.TestCase):
    def test_mineru_native_block_present(self):
        metrics = _minimal_metrics()
        self.assertIn("mineru_native", metrics)

    def test_mineru_native_has_formula_enabled(self):
        self.assertIn("formula_enabled", _minimal_metrics()["mineru_native"])

    def test_mineru_native_has_table_enabled(self):
        self.assertIn("table_enabled", _minimal_metrics()["mineru_native"])

    def test_mineru_native_has_backend(self):
        self.assertIn("backend", _minimal_metrics()["mineru_native"])
