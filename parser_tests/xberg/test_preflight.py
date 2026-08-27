"""Tests for xberg_v2.preflight_profile (section 36.7)."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


PARSER_NAME = "xberg"
REQUIRED_VERSION = "1.0.14"

# Minimal profile matching the config JSON keys accepted by _PROFILE_KEYS
_NATIVE_PROFILE = {
    "output_format": "markdown",
    "result_format": "unified",
    "escape_markdown": True,
    "table_anchors": False,
    "include_document_structure": False,
    "use_cache": False,
    "enable_quality_processing": False,
    "ocr_enabled": False,
    "ocr_backend": None,
    "ocr_languages": [],
    "ocr_strategy": "disabled",
    "force_ocr": False,
    "auto_rotate": False,
    "target_dpi": 300,
    "deskew": False,
    "denoise": False,
    "contrast_enhance": False,
    "extract_pages": True,
    "insert_page_markers": False,
    "extract_tables": True,
    "extract_images": False,
    "extract_metadata": True,
    "extract_annotations": False,
    "extract_form_fields": True,
    "reading_order": False,
    "include_headers": True,
    "include_footers": True,
    "strip_repeating_text": False,
    "include_watermarks": True,
    "chunking_enabled": False,
    "token_reduction_mode": "off",
    "layout_enabled": False,
    "remote_services_enabled": False,
    "network_allowed_during_run": False,
}


def _make_mock_xberg():
    """Return a mock xberg module with all required 1.0.14 class attributes."""
    m = MagicMock()
    m.ExtractionConfig = MagicMock(return_value=MagicMock())
    m.ExtractInput = MagicMock(return_value=MagicMock())
    m.OcrConfig = MagicMock(return_value=MagicMock())
    m.TesseractConfig = MagicMock(return_value=MagicMock())
    m.PdfConfig = MagicMock(return_value=MagicMock())
    m.PageConfig = MagicMock(return_value=MagicMock())
    m.ImageExtractionConfig = MagicMock(return_value=MagicMock())
    m.ContentFilterConfig = MagicMock(return_value=MagicMock())
    m.extract = AsyncMock(return_value=MagicMock())
    return m


class TestPreflightResultStructure(unittest.TestCase):
    """preflight_profile returns a result dict with checks and an overall status."""

    def _run(self, profile_name: str = "native_markdown"):
        from src.parsers.xberg_v2 import preflight_profile
        mock_xberg = _make_mock_xberg()
        with (
            patch("src.parsers.xberg_v2.get_profile", return_value=_NATIVE_PROFILE),
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch.dict("sys.modules", {"xberg": mock_xberg}),
            patch("src.parsers.xberg_v2._build_xberg_config", return_value=MagicMock()),
        ):
            return preflight_profile(profile_name)

    def test_returns_dict(self):
        result = self._run()
        self.assertIsInstance(result, dict)

    def test_has_checks_list(self):
        result = self._run()
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], list)

    def test_has_parser_key(self):
        result = self._run()
        self.assertIn("parser", result)

    def test_no_fail_checks_on_clean_env(self):
        result = self._run()
        # Exclude python version check — test env may differ from required 3.12
        failed = [
            c for c in result["checks"]
            if c.get("status") == "fail" and "python" not in c.get("name", "").lower()
        ]
        self.assertEqual(failed, [], f"Unexpected non-python failures: {failed}")


class TestPreflightWrongVersion(unittest.TestCase):
    def _run_with_version(self, version: str):
        from src.parsers.xberg_v2 import preflight_profile
        mock_xberg = _make_mock_xberg()
        with (
            patch("src.parsers.xberg_v2.get_profile", return_value=_NATIVE_PROFILE),
            patch("importlib.metadata.version", return_value=version),
            patch.dict("sys.modules", {"xberg": mock_xberg}),
            patch("src.parsers.xberg_v2._build_xberg_config", return_value=MagicMock()),
        ):
            return preflight_profile("native_markdown")

    def test_wrong_version_produces_fail_check(self):
        result = self._run_with_version("1.0.0")
        failed = [c for c in result["checks"] if c.get("status") == "fail"]
        self.assertTrue(
            any("version" in c.get("name", "").lower() for c in failed),
            f"Expected version fail check, got: {failed}",
        )

    def test_correct_version_no_xberg_version_fail(self):
        result = self._run_with_version(REQUIRED_VERSION)
        # Only check that xberg version passes; python version may differ in test env
        xberg_version_fails = [
            c for c in result["checks"]
            if c.get("status") == "fail" and c.get("name") == "xberg version"
        ]
        self.assertEqual(xberg_version_fails, [])


class TestPreflightUnknownKeys(unittest.TestCase):
    def test_unknown_profile_key_produces_fail(self):
        from src.parsers.xberg_v2 import preflight_profile
        bad_profile = {**_NATIVE_PROFILE, "bogus_key_xyz": True}
        mock_xberg = _make_mock_xberg()
        with (
            patch("src.parsers.xberg_v2.get_profile", return_value=bad_profile),
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch.dict("sys.modules", {"xberg": mock_xberg}),
            patch("src.parsers.xberg_v2._build_xberg_config", return_value=MagicMock()),
        ):
            result = preflight_profile("native_markdown")
        key_fails = [
            c for c in result["checks"]
            if c.get("status") == "fail" and "profile keys" in c.get("name", "").lower()
        ]
        self.assertTrue(len(key_fails) > 0, "Expected a 'profile keys' fail check for unknown keys")


class TestPreflightOcrChecks(unittest.TestCase):
    def _ocr_profile(self, **overrides) -> dict:
        base = {
            **_NATIVE_PROFILE,
            "ocr_enabled": True,
            "ocr_backend": "tesseract",
            "ocr_languages": ["por", "eng"],
            "ocr_strategy": "auto",
            "auto_rotate": False,
        }
        base.update(overrides)
        return base

    def _run_ocr(self, profile: dict, tessdata_path: str | None = None) -> dict:
        from src.parsers.xberg_v2 import preflight_profile
        mock_xberg = _make_mock_xberg()

        def _fake_is_file(self):
            return False

        with (
            patch("src.parsers.xberg_v2.get_profile", return_value=profile),
            patch("importlib.metadata.version", return_value=REQUIRED_VERSION),
            patch("shutil.which", return_value="/usr/bin/tesseract"),
            patch("src.parsers.xberg_v2._find_tessdata_prefix", return_value=tessdata_path),
            patch("pathlib.Path.is_file", _fake_is_file),
            patch.dict("sys.modules", {"xberg": mock_xberg}),
            patch("src.parsers.xberg_v2._build_xberg_config", return_value=MagicMock()),
        ):
            return preflight_profile("ocr_auto_tesseract")

    def test_missing_tessdata_dir_produces_fail(self):
        result = self._run_ocr(self._ocr_profile(), tessdata_path=None)
        failed = [c for c in result["checks"] if c.get("status") == "fail"]
        self.assertTrue(
            any("tessdata" in c.get("name", "").lower() for c in failed),
            f"Expected tessdata fail, got: {failed}",
        )

    def test_osd_check_present_when_auto_rotate_true(self):
        result = self._run_ocr(self._ocr_profile(auto_rotate=True), tessdata_path="/tessdata")
        check_names = [c.get("name", "") for c in result["checks"]]
        self.assertTrue(
            any("osd" in n.lower() for n in check_names),
            f"Expected osd check, got: {check_names}",
        )


class TestPreflightNoNetwork(unittest.TestCase):
    def test_remote_services_disabled_in_native(self):
        self.assertFalse(_NATIVE_PROFILE["remote_services_enabled"])

    def test_network_not_allowed_in_native(self):
        self.assertFalse(_NATIVE_PROFILE["network_allowed_during_run"])
