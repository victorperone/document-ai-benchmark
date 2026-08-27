"""Tests for Unstructured benchmark profiles (section 22.1)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile

PARSER_NAME = "unstructured"
_EXPECTED_PROFILES = ["fast_native", "auto_ocr", "hi_res_tables", "ocr_only_diagnostic"]
_VALID_STRATEGIES = frozenset({"fast", "auto", "hi_res", "ocr_only"})
_REQUIRED_KEYS = frozenset({
    "strategy", "ocr_enabled", "ocr_mode", "ocr_engine",
    "languages", "detect_language_per_element", "infer_table_structure",
    "include_page_breaks", "hi_res_model_name", "extract_image_block_types",
    "extract_image_block_to_payload", "extract_forms", "form_extraction_skip_tables",
    "password", "pdfminer_line_margin", "pdfminer_char_margin",
    "pdfminer_line_overlap", "pdfminer_word_margin",
    "remote_services_enabled", "network_allowed_during_run",
})


class TestUnstructuredProfilesExist(unittest.TestCase):
    def test_all_required_profiles_exist(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                profile = get_profile(PARSER_NAME, name)
                self.assertIsInstance(profile, dict)

    def test_no_unexpected_profiles(self):
        from src.benchmark.config import get_parser_profiles
        defined = set(get_parser_profiles(PARSER_NAME).keys())
        for expected in _EXPECTED_PROFILES:
            self.assertIn(expected, defined)


class TestProfileKeys(unittest.TestCase):
    def _profile(self, name: str) -> dict:
        return get_profile(PARSER_NAME, name)

    def test_fast_native_keys(self):
        p = self._profile("fast_native")
        self.assertEqual(set(p.keys()), _REQUIRED_KEYS)

    def test_auto_ocr_keys(self):
        p = self._profile("auto_ocr")
        self.assertEqual(set(p.keys()), _REQUIRED_KEYS)

    def test_hi_res_tables_keys(self):
        p = self._profile("hi_res_tables")
        self.assertEqual(set(p.keys()), _REQUIRED_KEYS)

    def test_ocr_only_diagnostic_keys(self):
        p = self._profile("ocr_only_diagnostic")
        self.assertEqual(set(p.keys()), _REQUIRED_KEYS)


class TestProfileValues(unittest.TestCase):
    def _profile(self, name: str) -> dict:
        return get_profile(PARSER_NAME, name)

    def test_fast_native_strategy(self):
        self.assertEqual(self._profile("fast_native")["strategy"], "fast")

    def test_fast_native_no_ocr(self):
        self.assertFalse(self._profile("fast_native")["ocr_enabled"])

    def test_auto_ocr_strategy(self):
        self.assertEqual(self._profile("auto_ocr")["strategy"], "auto")

    def test_auto_ocr_enabled(self):
        self.assertTrue(self._profile("auto_ocr")["ocr_enabled"])

    def test_auto_ocr_engine_tesseract(self):
        self.assertEqual(self._profile("auto_ocr")["ocr_engine"], "tesseract")

    def test_hi_res_tables_strategy(self):
        self.assertEqual(self._profile("hi_res_tables")["strategy"], "hi_res")

    def test_hi_res_tables_infer_tables(self):
        self.assertTrue(self._profile("hi_res_tables")["infer_table_structure"])

    def test_hi_res_tables_model_name(self):
        self.assertEqual(self._profile("hi_res_tables")["hi_res_model_name"], "yolox")

    def test_ocr_only_strategy(self):
        self.assertEqual(self._profile("ocr_only_diagnostic")["strategy"], "ocr_only")

    def test_ocr_only_enabled(self):
        self.assertTrue(self._profile("ocr_only_diagnostic")["ocr_enabled"])

    def test_all_strategies_valid(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                p = self._profile(name)
                self.assertIn(p["strategy"], _VALID_STRATEGIES)

    def test_no_remote_services(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                p = self._profile(name)
                self.assertFalse(p["remote_services_enabled"])

    def test_no_network_during_run(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                p = self._profile(name)
                self.assertFalse(p["network_allowed_during_run"])

    def test_languages_non_empty(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                langs = self._profile(name)["languages"]
                self.assertIsInstance(langs, list)
                self.assertGreater(len(langs), 0)

    def test_include_page_breaks_true(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                self.assertTrue(self._profile(name)["include_page_breaks"])

    def test_pdfminer_word_margin(self):
        for name in _EXPECTED_PROFILES:
            with self.subTest(profile=name):
                margin = self._profile(name)["pdfminer_word_margin"]
                self.assertIsInstance(margin, float)
                self.assertAlmostEqual(margin, 0.185, places=4)

    def test_fast_native_infer_table_false(self):
        self.assertFalse(self._profile("fast_native")["infer_table_structure"])


class TestFullCpuLocalProfile(unittest.TestCase):
    def _profile(self) -> dict:
        return get_profile(PARSER_NAME, "full_cpu_local")

    def test_exists(self):
        self.assertIsInstance(self._profile(), dict)

    def test_strategy_hi_res(self):
        self.assertEqual(self._profile()["strategy"], "hi_res")

    def test_ocr_enabled(self):
        self.assertTrue(self._profile()["ocr_enabled"])

    def test_infer_table_structure_true(self):
        self.assertTrue(self._profile()["infer_table_structure"])

    def test_extract_forms_true(self):
        self.assertTrue(self._profile()["extract_forms"])

    def test_form_extraction_skip_tables_false(self):
        self.assertFalse(self._profile()["form_extraction_skip_tables"])

    def test_extract_image_block_types_nonempty(self):
        types = self._profile()["extract_image_block_types"]
        self.assertTrue(len(types) > 0, "full_cpu_local must extract at least one image block type")

    def test_detect_language_per_element_true(self):
        self.assertTrue(self._profile()["detect_language_per_element"])

    def test_no_payload_extraction(self):
        self.assertFalse(self._profile()["extract_image_block_to_payload"])

    def test_no_remote_services(self):
        self.assertFalse(self._profile()["remote_services_enabled"])

    def test_no_network(self):
        self.assertFalse(self._profile()["network_allowed_during_run"])

    def test_all_keys_valid(self):
        from src.parsers.unstructured_v2 import _PROFILE_KEYS
        unknown = set(self._profile()) - _PROFILE_KEYS
        self.assertEqual(unknown, set(), f"Unknown keys in full_cpu_local: {unknown}")
