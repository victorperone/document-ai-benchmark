"""Tests for Xberg benchmark profiles (section 36.1)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile

PARSER_NAME = "xberg"
_EXPECTED_PROFILES = [
    "native_markdown", "ocr_auto_tesseract",
    "ocr_force_tesseract", "ocr_auto_tesseract_repair",
]
_REQUIRED_KEYS = frozenset({
    "output_format", "result_format", "escape_markdown", "table_anchors",
    "include_document_structure", "use_cache", "enable_quality_processing",
    "ocr_enabled", "ocr_backend", "ocr_languages", "ocr_strategy",
    "force_ocr", "auto_rotate", "target_dpi", "deskew", "denoise",
    "contrast_enhance", "extract_pages", "insert_page_markers", "extract_tables",
    "extract_images", "extract_metadata", "extract_annotations", "extract_form_fields",
    "reading_order", "include_headers", "include_footers", "strip_repeating_text",
    "include_watermarks", "chunking_enabled", "token_reduction_mode", "layout_enabled",
    "remote_services_enabled", "network_allowed_during_run",
})


class TestXbergProfilesExist(unittest.TestCase):
    def test_all_required_profiles_exist(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                profile = get_profile(PARSER_NAME, name)
                self.assertIsInstance(profile, dict)


class TestProfileValues(unittest.TestCase):
    def _profile(self, name: str) -> dict:
        return get_profile(PARSER_NAME, name)

    def test_native_markdown_no_ocr(self):
        self.assertFalse(self._profile("native_markdown")["ocr_enabled"])

    def test_native_markdown_tables_extracted(self):
        self.assertTrue(self._profile("native_markdown")["extract_tables"])

    def test_native_markdown_no_chunking(self):
        self.assertFalse(self._profile("native_markdown")["chunking_enabled"])

    def test_native_markdown_no_token_reduction(self):
        self.assertEqual(self._profile("native_markdown")["token_reduction_mode"], "off")

    def test_native_markdown_no_cache(self):
        self.assertFalse(self._profile("native_markdown")["use_cache"])

    def test_native_markdown_output_format(self):
        self.assertEqual(self._profile("native_markdown")["output_format"], "markdown")

    def test_ocr_auto_tesseract_ocr_enabled(self):
        self.assertTrue(self._profile("ocr_auto_tesseract")["ocr_enabled"])

    def test_ocr_auto_tesseract_backend(self):
        self.assertEqual(self._profile("ocr_auto_tesseract")["ocr_backend"], "tesseract")

    def test_ocr_auto_tesseract_auto_rotate(self):
        self.assertTrue(self._profile("ocr_auto_tesseract")["auto_rotate"])

    def test_ocr_force_tesseract_force_ocr(self):
        self.assertTrue(self._profile("ocr_force_tesseract")["force_ocr"])

    def test_ocr_repair_deskew(self):
        self.assertTrue(self._profile("ocr_auto_tesseract_repair")["deskew"])

    def test_ocr_repair_denoise(self):
        self.assertTrue(self._profile("ocr_auto_tesseract_repair")["denoise"])

    def test_ocr_repair_contrast(self):
        self.assertTrue(self._profile("ocr_auto_tesseract_repair")["contrast_enhance"])

    def test_no_remote_services(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["remote_services_enabled"])

    def test_no_network_during_run(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["network_allowed_during_run"])

    def test_no_images_extracted(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["extract_images"])

    def test_headers_included(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertTrue(self._profile(name)["include_headers"])

    def test_footers_included(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertTrue(self._profile(name)["include_footers"])

    def test_no_strip_repeating_text(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["strip_repeating_text"])
