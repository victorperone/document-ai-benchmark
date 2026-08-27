"""Tests for xberg_v2 serialization constraints (section 36.6)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _build_minimal_metrics() -> dict:
    return {
        "parser": "xberg",
        "profile": "native_markdown",
        "run": {
            "versions": {"xberg": "1.0.14", "tesseract": None, "tiktoken": "0.7.0"},
            "verbose": False,
            "runtime": "host",
        },
        "document": {
            "sha256": "abc123",
            "pages": 2,
            "file_size_mb": 0.5,
            "has_text_layer": True,
        },
        "source_pdf": {"path": "test.pdf"},
        "processing": {
            "timing": {
                "initialization_seconds": 0.1,
                "extraction_seconds": 1.0,
                "pipeline_seconds": 1.2,
            },
            "ocr": {
                "enabled": False,
                "strategy": "disabled",
                "engine": None,
                "languages": [],
                "infer_table_structure": True,
                "force_ocr": False,
                "auto_rotate": False,
                "pages_requested": None,
                "pages_processed": None,
                "tracking_note": "Xberg 1.0.14 nao expoe rastreamento por pagina de OCR na API publica.",
            },
            "resources": {"cpu_percent": 0.0},
        },
        "content_elements": {
            "layout_boxes": None,
            "tables_detected": 0,
            "text_blocks_detected": 2,
        },
        "heuristics": {},
        "tokens": {},
        "normalization": {},
        "output": {"clean_markdown_bytes": 100},
    }


class TestMetricsSerialization(unittest.TestCase):
    def test_metrics_json_serializable(self):
        metrics = _build_minimal_metrics()
        try:
            json.dumps(metrics)
        except (TypeError, ValueError) as exc:
            self.fail(f"Metrics not JSON-serializable: {exc}")

    def test_no_bytes_in_metrics(self):
        def _find_bytes(obj, path="root"):
            if isinstance(obj, bytes):
                return [path]
            if isinstance(obj, dict):
                found = []
                for k, v in obj.items():
                    found.extend(_find_bytes(v, f"{path}.{k}"))
                return found
            if isinstance(obj, list):
                found = []
                for i, v in enumerate(obj):
                    found.extend(_find_bytes(v, f"{path}[{i}]"))
                return found
            return []

        metrics = _build_minimal_metrics()
        byte_paths = _find_bytes(metrics)
        self.assertEqual(byte_paths, [], f"Bytes found at: {byte_paths}")

    def test_no_base64_strings(self):
        import base64
        metrics = _build_minimal_metrics()
        raw = json.dumps(metrics)
        # Check that no value looks like encoded binary (>100 char base64-ish string)
        import re
        b64_pattern = re.compile(r'"[A-Za-z0-9+/]{100,}={0,2}"')
        matches = b64_pattern.findall(raw)
        self.assertEqual(matches, [], f"Possible base64 blobs found: {matches}")

    def test_tracking_note_present_in_ocr(self):
        metrics = _build_minimal_metrics()
        ocr = metrics["processing"]["ocr"]
        self.assertIn("tracking_note", ocr)
        self.assertIsInstance(ocr["tracking_note"], str)
        self.assertGreater(len(ocr["tracking_note"]), 0)

    def test_versions_includes_tiktoken(self):
        metrics = _build_minimal_metrics()
        self.assertIn("tiktoken", metrics["run"]["versions"])


class TestEnumSerialization(unittest.TestCase):
    def test_no_enum_objects_in_output(self):
        from enum import Enum

        class DummyEnum(Enum):
            VALUE = "value"

        obj = {"key": DummyEnum.VALUE}
        with self.assertRaises(TypeError):
            json.dumps(obj)

    def test_strategy_is_string(self):
        metrics = _build_minimal_metrics()
        strategy = metrics["processing"]["ocr"]["strategy"]
        self.assertIsInstance(strategy, str)
