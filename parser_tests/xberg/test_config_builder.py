"""Tests for xberg_v2._build_xberg_config (section 36.3)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _minimal_profile(**overrides) -> dict:
    base = {
        "strategy": "fast",
        "ocr_enabled": False,
        "ocr_backend": None,
        "ocr_languages": [],
        "ocr_strategy": "disabled",
        "force_ocr": False,
        "auto_rotate": False,
        "target_dpi": 150,
        "deskew": False,
        "denoise": False,
        "contrast_enhance": False,
        "extract_tables": True,
        "extract_images": False,
        "extract_pages": True,
        "insert_page_markers": False,
        "include_headers": True,
        "include_footers": True,
        "strip_repeating_text": False,
        "chunking_enabled": False,
        "token_reduction_mode": "off",
        "layout_enabled": False,
        "use_cache": False,
        "enable_quality_processing": False,
        "reading_order": False,
        "remote_services_enabled": False,
        "network_allowed_during_run": False,
        "output_format": "markdown",
        "result_format": "unified",
        "escape_markdown": True,
        "table_anchors": False,
        "include_document_structure": False,
        "extract_metadata": True,
        "extract_annotations": False,
        "extract_form_fields": True,
        "include_watermarks": True,
    }
    base.update(overrides)
    return base


class TestConfigBuilderNoOcr(unittest.TestCase):
    def _build(self, profile: dict):
        from src.parsers.xberg_v2 import _build_xberg_config
        ExtractionConfig = MagicMock()
        OcrConfig = MagicMock()
        with patch.dict("sys.modules", {
            "xberg": MagicMock(
                ExtractionConfig=ExtractionConfig,
                OcrConfig=OcrConfig,
                TesseractConfig=MagicMock(),
            )
        }):
            import sys
            fake_xberg = sys.modules["xberg"]
            with patch("src.parsers.xberg_v2._build_xberg_config",
                       wraps=lambda p, m: _build_xberg_config(p, m)):
                pass
        return ExtractionConfig, OcrConfig

    def test_no_ocr_returns_config(self):
        from src.parsers.xberg_v2 import _build_xberg_config
        ExtractionConfig = MagicMock(return_value=MagicMock())
        OcrConfig = MagicMock()
        TesseractConfig = MagicMock()
        mock_xberg = MagicMock(
            ExtractionConfig=ExtractionConfig,
            OcrConfig=OcrConfig,
            TesseractConfig=TesseractConfig,
        )
        with patch.dict("sys.modules", {"xberg": mock_xberg}):
            result = _build_xberg_config(_minimal_profile(ocr_enabled=False), Path("/models"))
        ExtractionConfig.assert_called()
        OcrConfig.assert_not_called()

    def test_ocr_enabled_builds_ocr_config(self):
        from src.parsers.xberg_v2 import _build_xberg_config
        ExtractionConfig = MagicMock(return_value=MagicMock())
        OcrConfig = MagicMock(return_value=MagicMock())
        TesseractConfig = MagicMock(return_value=MagicMock())
        mock_xberg = MagicMock(
            ExtractionConfig=ExtractionConfig,
            OcrConfig=OcrConfig,
            TesseractConfig=TesseractConfig,
        )
        with patch.dict("sys.modules", {"xberg": mock_xberg}):
            _build_xberg_config(
                _minimal_profile(ocr_enabled=True, ocr_backend="tesseract",
                                  ocr_languages=["por", "eng"]),
                Path("/models"),
            )
        OcrConfig.assert_called()


class TestConfigConstraints(unittest.TestCase):
    def test_extraction_config_raises_if_missing(self):
        from src.parsers.xberg_v2 import _build_xberg_config
        from src.benchmark.config import BenchmarkConfigurationError
        mock_xberg = MagicMock(spec=[])  # no ExtractionConfig attribute
        mock_xberg.ExtractionConfig = None
        with patch.dict("sys.modules", {"xberg": mock_xberg}):
            with self.assertRaises(BenchmarkConfigurationError):
                _build_xberg_config(_minimal_profile(), Path("/models"))
