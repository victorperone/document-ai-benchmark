"""Tests for xberg_v2._build_xberg_config using real Xberg 1.0.14 classes."""
from __future__ import annotations

import unittest
import warnings
from pathlib import Path

try:
    import xberg as _xberg_module  # noqa: F401
    XBERG_AVAILABLE = True
except ImportError:
    XBERG_AVAILABLE = False
    warnings.warn(
        "xberg not installed — test_config_builder tests will be skipped",
        stacklevel=1,
    )


def _profile(**overrides) -> dict:
    base = {
        "output_format": "markdown",
        "result_format": "unified",
        "escape_markdown": True,
        "table_anchors": False,
        "include_document_structure": False,
        "use_cache": False,
        "enable_quality_processing": True,
        "ocr_enabled": True,
        "ocr_backend": "tesseract",
        "ocr_languages": ["por", "eng"],
        "ocr_strategy": "auto",
        "force_ocr": False,
        "auto_rotate": True,
        "tesseract_psm": 3,
        "tesseract_oem": 3,
        "min_confidence": 50.0,
        "enable_table_detection": True,
        "tesseract_use_cache": False,
        "target_dpi": 300,
        "deskew": True,
        "denoise": True,
        "contrast_enhance": True,
        "extract_pages": True,
        "insert_page_markers": False,
        "extract_tables": True,
        "extract_images": True,
        "extract_metadata": True,
        "extract_annotations": False,
        "extract_form_fields": True,
        "reading_order": True,
        "ocr_inline_images": True,
        "run_ocr_on_images": True,
        "append_ocr_text": True,
        "include_data_base64": False,
        "include_headers": True,
        "include_footers": True,
        "strip_repeating_text": False,
        "include_watermarks": True,
        "layout_enabled": False,
        "chunking_enabled": False,
        "token_reduction_mode": "off",
        "remote_services_enabled": False,
        "network_allowed_during_run": False,
    }
    base.update(overrides)
    return base


@unittest.skipUnless(XBERG_AVAILABLE, "xberg not installed")
class TestXbergConfigBuilder(unittest.TestCase):
    def test_root_strategy_is_not_pipeline(self) -> None:
        from src.parsers.xberg_v2 import _build_xberg_config

        config = _build_xberg_config(_profile(), Path("models/xberg"))

        self.assertEqual(config["ocr_strategy"], "auto")
        self.assertIsNone(config["ocr"].pipeline)

    def test_preprocessing_is_effective(self) -> None:
        from src.parsers.xberg_v2 import _build_xberg_config

        config = _build_xberg_config(_profile(), Path("models/xberg"))

        preprocessing = config["ocr"].tesseract_config.preprocessing

        self.assertIsNotNone(preprocessing)
        self.assertEqual(preprocessing.target_dpi, 300)
        self.assertTrue(preprocessing.auto_rotate)
        self.assertTrue(preprocessing.deskew)
        self.assertTrue(preprocessing.denoise)
        self.assertTrue(preprocessing.contrast_enhance)

    def test_languages_are_set_at_both_levels(self) -> None:
        from src.parsers.xberg_v2 import _build_xberg_config

        config = _build_xberg_config(_profile(), Path("models/xberg"))

        self.assertEqual(config["ocr"].language, ["por", "eng"])
        self.assertEqual(config["ocr"].tesseract_config.language, ["por", "eng"])

    def test_cache_and_downstream_features_are_off(self) -> None:
        from src.parsers.xberg_v2 import _build_xberg_config

        config = _build_xberg_config(_profile(), Path("models/xberg"))

        self.assertFalse(config["use_cache"])
        self.assertFalse(config["ocr"].tesseract_config.use_cache)
        self.assertIsNone(config["chunking"])
        self.assertIsNone(config["token_reduction"])
        self.assertIsNone(config["structured_extraction"])
        self.assertIsNone(config["ner"])
        self.assertIsNone(config["summarization"])
        self.assertIsNone(config["translation"])
        self.assertIsNone(config["captioning"])

    def test_pdf_images_follow_profile(self) -> None:
        from src.parsers.xberg_v2 import _build_xberg_config

        config = _build_xberg_config(
            _profile(extract_images=True), Path("models/xberg")
        )

        self.assertTrue(config["pdf_options"].extract_images)
        self.assertIsNotNone(config["images"])

    def test_native_disables_ocr(self) -> None:
        from src.parsers.xberg_v2 import _build_xberg_config

        config = _build_xberg_config(
            _profile(
                ocr_enabled=False,
                ocr_backend=None,
                ocr_languages=[],
                ocr_strategy="disabled",
                auto_rotate=False,
            ),
            Path("models/xberg"),
        )

        self.assertTrue(config["disable_ocr"])
        self.assertIsNone(config["ocr"])
        self.assertNotIn("ocr_strategy", config)

    def test_layout_fails_closed_until_certified(self) -> None:
        from src.parsers.xberg_v2 import XbergConfigurationError, _build_xberg_config

        with self.assertRaises(XbergConfigurationError):
            _build_xberg_config(
                _profile(layout_enabled=True), Path("models/xberg")
            )


if __name__ == "__main__":
    unittest.main()
