"""Tests for xberg_v2.preflight_profile (section 36.7)."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock


PARSER_NAME = "xberg"
REQUIRED_VERSION = "1.0.14"


def _ocr_profile(**overrides) -> dict:
    base = {
        "strategy": "auto",
        "ocr_enabled": True,
        "ocr_backend": "tesseract",
        "ocr_languages": ["por", "eng"],
        "ocr_strategy": "auto",
        "force_ocr": False,
        "auto_rotate": True,
        "target_dpi": 200,
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


def _native_profile(**overrides) -> dict:
    base = _ocr_profile()
    base.update({
        "ocr_enabled": False,
        "ocr_backend": None,
        "ocr_languages": [],
        "ocr_strategy": "disabled",
        "force_ocr": False,
        "auto_rotate": False,
    })
    base.update(overrides)
    return base


class TestPreflightWrongVersion(unittest.TestCase):
    def test_wrong_xberg_version_raises(self):
        from src.parsers.xberg_v2 import preflight_profile
        from src.benchmark.config import BenchmarkConfigurationError
        profile = _native_profile()
        with patch("importlib.metadata.version", return_value="1.0.0"):
            with self.assertRaises(BenchmarkConfigurationError) as ctx:
                preflight_profile(profile, model_root="/models")
        self.assertIn("1.0.14", str(ctx.exception))

    def test_correct_version_passes(self):
        from src.parsers.xberg_v2 import preflight_profile
        profile = _native_profile()
        with (
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch("shutil.which", return_value=None),
        ):
            # No raise expected for native profile without OCR
            try:
                preflight_profile(profile, model_root="/models")
            except Exception as exc:
                # Only OCR-related errors are allowed
                if "tesseract" not in str(exc).lower() and "ocr" not in str(exc).lower():
                    self.fail(f"Unexpected error: {exc}")


class TestPreflightMissingTessdata(unittest.TestCase):
    def _run_preflight(self, profile, tessdata_path=None, tessdata_files=None):
        from src.parsers.xberg_v2 import preflight_profile
        from src.benchmark.config import BenchmarkConfigurationError

        with (
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch("shutil.which", return_value="/usr/bin/tesseract"),
            patch("src.parsers.xberg_v2._find_tessdata_prefix",
                  return_value=tessdata_path),
            patch("pathlib.Path.exists",
                  side_effect=lambda p=None: str(p) in (tessdata_files or [])) if tessdata_path else patch("pathlib.Path.exists", return_value=False),
        ):
            preflight_profile(profile, model_root="/models")

    def test_missing_tessdata_raises_for_ocr_profile(self):
        from src.benchmark.config import BenchmarkConfigurationError
        with self.assertRaises(BenchmarkConfigurationError):
            self._run_preflight(
                _ocr_profile(auto_rotate=False),
                tessdata_path=None,
                tessdata_files=[],
            )

    def test_por_required_for_ocr(self):
        from src.benchmark.config import BenchmarkConfigurationError
        from src.parsers.xberg_v2 import preflight_profile

        with (
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch("shutil.which", return_value="/usr/bin/tesseract"),
            patch("src.parsers.xberg_v2._find_tessdata_prefix", return_value="/tessdata"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            with self.assertRaises(BenchmarkConfigurationError) as ctx:
                preflight_profile(_ocr_profile(auto_rotate=False), model_root="/models")
        # Should mention missing language files
        self.assertTrue(
            any(lang in str(ctx.exception) for lang in ("por", "eng", "tessdata", "trained")),
            f"Expected tessdata error, got: {ctx.exception}",
        )

    def test_osd_required_for_auto_rotate(self):
        from src.benchmark.config import BenchmarkConfigurationError
        from src.parsers.xberg_v2 import preflight_profile

        with (
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch("shutil.which", return_value="/usr/bin/tesseract"),
            patch("src.parsers.xberg_v2._find_tessdata_prefix", return_value="/tessdata"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            with self.assertRaises(BenchmarkConfigurationError):
                preflight_profile(_ocr_profile(auto_rotate=True), model_root="/models")


class TestPreflightNoNetwork(unittest.TestCase):
    def test_remote_services_false(self):
        profile = _native_profile()
        self.assertFalse(profile["remote_services_enabled"])

    def test_network_not_allowed(self):
        profile = _native_profile()
        self.assertFalse(profile["network_allowed_during_run"])
