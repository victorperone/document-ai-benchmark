"""Tests for Xberg benchmark profiles (section 36.1)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile

PARSER_NAME = "xberg"
_LEGACY_PROFILES = [
    "native_markdown", "ocr_auto_tesseract",
    "ocr_force_tesseract", "ocr_auto_tesseract_repair",
]
_EXPECTED_PROFILES = _LEGACY_PROFILES + ["full_cpu_local", "full_cpu_layout"]

# Keys that all four legacy profiles must have
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
    # X1–X4 new keys
    "allow_single_column_tables", "qr_codes",
    "layout_strategy", "layout_apply_heuristics", "layout_acceleration_provider",
    "layout_confidence_threshold", "layout_enable_chart_understanding",
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
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["remote_services_enabled"])

    def test_no_network_during_run(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["network_allowed_during_run"])

    def test_no_images_extracted(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["extract_images"])

    def test_headers_included(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertTrue(self._profile(name)["include_headers"])

    def test_footers_included(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertTrue(self._profile(name)["include_footers"])

    def test_no_strip_repeating_text(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(self._profile(name)["strip_repeating_text"])


class TestFullCpuLocalProfile(unittest.TestCase):
    def _profile(self) -> dict:
        return get_profile(PARSER_NAME, "full_cpu_local")

    def test_exists(self):
        self.assertIsInstance(self._profile(), dict)

    def test_ocr_enabled(self):
        self.assertTrue(self._profile()["ocr_enabled"])

    def test_ocr_backend_tesseract(self):
        self.assertEqual(self._profile()["ocr_backend"], "tesseract")

    def test_extract_images_true(self):
        self.assertTrue(self._profile()["extract_images"])

    def test_run_ocr_on_images_true(self):
        self.assertTrue(self._profile()["run_ocr_on_images"])

    def test_append_ocr_text_true(self):
        self.assertTrue(self._profile()["append_ocr_text"])

    def test_no_base64(self):
        self.assertFalse(self._profile()["include_data_base64"])

    def test_extract_tables_true(self):
        self.assertTrue(self._profile()["extract_tables"])

    def test_extract_form_fields_true(self):
        self.assertTrue(self._profile()["extract_form_fields"])

    def test_extract_annotations_true(self):
        self.assertTrue(self._profile()["extract_annotations"])

    def test_reading_order_true(self):
        self.assertTrue(self._profile()["reading_order"])

    def test_no_chunking(self):
        self.assertFalse(self._profile()["chunking_enabled"])

    def test_no_token_reduction(self):
        self.assertEqual(self._profile()["token_reduction_mode"], "off")

    def test_no_remote_services(self):
        self.assertFalse(self._profile()["remote_services_enabled"])

    def test_no_network(self):
        self.assertFalse(self._profile()["network_allowed_during_run"])

    def test_all_keys_valid(self):
        from src.parsers.xberg_v2 import _PROFILE_KEYS
        unknown = set(self._profile()) - _PROFILE_KEYS
        self.assertEqual(unknown, set(), f"Unknown keys in full_cpu_local: {unknown}")


class TestFullCpuLayoutProfile(unittest.TestCase):
    def _profile(self) -> dict:
        return get_profile(PARSER_NAME, "full_cpu_layout")

    def test_exists(self):
        self.assertIsInstance(self._profile(), dict)

    def test_layout_enabled(self):
        self.assertTrue(self._profile()["layout_enabled"])

    def test_qr_codes_enabled(self):
        self.assertTrue(self._profile()["qr_codes"])

    def test_layout_provider_cpu(self):
        self.assertEqual(self._profile()["layout_acceleration_provider"], "cpu")

    def test_no_chart_understanding_by_default(self):
        self.assertFalse(self._profile()["layout_enable_chart_understanding"])

    def test_allow_single_column_tables_false(self):
        self.assertFalse(self._profile()["allow_single_column_tables"])

    def test_no_remote_services(self):
        self.assertFalse(self._profile()["remote_services_enabled"])

    def test_no_network(self):
        self.assertFalse(self._profile()["network_allowed_during_run"])

    def test_all_keys_valid(self):
        from src.parsers.xberg_v2 import _PROFILE_KEYS
        unknown = set(self._profile()) - _PROFILE_KEYS
        self.assertEqual(unknown, set(), f"Unknown keys in full_cpu_layout: {unknown}")


class TestNewKeysInAllProfiles(unittest.TestCase):
    def test_all_profiles_have_new_keys(self):
        new_keys = (
            "allow_single_column_tables", "qr_codes",
            "layout_strategy", "layout_apply_heuristics",
            "layout_acceleration_provider", "layout_confidence_threshold",
            "layout_enable_chart_understanding",
        )
        for name in _EXPECTED_PROFILES:
            p = get_profile(PARSER_NAME, name)
            for key in new_keys:
                with self.subTest(profile=name, key=key):
                    self.assertIn(key, p)

    def test_legacy_profiles_layout_disabled(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(get_profile(PARSER_NAME, name)["layout_enabled"])

    def test_legacy_profiles_qr_disabled(self):
        for name in _LEGACY_PROFILES:
            with self.subTest(profile=name):
                self.assertFalse(get_profile(PARSER_NAME, name)["qr_codes"])

    def test_full_cpu_local_layout_disabled(self):
        self.assertFalse(get_profile(PARSER_NAME, "full_cpu_local")["layout_enabled"])

    def test_all_profiles_no_single_column_tables_by_default(self):
        for name in _LEGACY_PROFILES + ["full_cpu_local"]:
            with self.subTest(profile=name):
                self.assertFalse(get_profile(PARSER_NAME, name)["allow_single_column_tables"])
