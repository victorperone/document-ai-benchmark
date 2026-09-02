"""Tests for explicit OCR agent selection (U1) and new auto profiles."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile

PARSER_NAME = "unstructured"

_AUTO_PROFILES = ("auto_general", "auto_quality", "auto_ocr")
_OCR_PROFILES = ("auto_ocr", "hi_res_tables", "full_cpu_local", "auto_general", "auto_quality")


class TestOcrAgentKeys(unittest.TestCase):
    def _p(self, name: str) -> dict:
        return get_profile(PARSER_NAME, name)

    def test_all_ocr_profiles_have_ocr_agent(self):
        for name in _OCR_PROFILES:
            with self.subTest(profile=name):
                p = self._p(name)
                self.assertIn("ocr_agent", p)
                self.assertIn("table_ocr_agent", p)

    def test_ocr_profiles_agent_is_tesseract(self):
        for name in _OCR_PROFILES:
            with self.subTest(profile=name):
                p = self._p(name)
                self.assertEqual(p["ocr_agent"], "tesseract")
                self.assertEqual(p["table_ocr_agent"], "tesseract")

    def test_fast_native_agent_is_null(self):
        p = self._p("fast_native")
        self.assertIsNone(p["ocr_agent"])
        self.assertIsNone(p["table_ocr_agent"])


class TestAutoProfiles(unittest.TestCase):
    def _p(self, name: str) -> dict:
        return get_profile(PARSER_NAME, name)

    def test_auto_general_strategy_auto(self):
        self.assertEqual(self._p("auto_general")["strategy"], "auto")

    def test_auto_quality_strategy_auto(self):
        self.assertEqual(self._p("auto_quality")["strategy"], "auto")

    def test_auto_general_no_table_structure(self):
        self.assertFalse(self._p("auto_general")["infer_table_structure"])

    def test_auto_quality_table_structure_enabled(self):
        self.assertTrue(self._p("auto_quality")["infer_table_structure"])

    def test_auto_general_no_image_extraction(self):
        self.assertEqual(self._p("auto_general")["extract_image_block_types"], [])

    def test_auto_profiles_no_remote_services(self):
        for name in _AUTO_PROFILES:
            with self.subTest(profile=name):
                p = self._p(name)
                self.assertFalse(p["remote_services_enabled"])
                self.assertFalse(p["network_allowed_during_run"])

    def test_all_profiles_have_ocr_agent_and_table_ocr_agent(self):
        all_names = (
            "fast_native", "auto_ocr", "hi_res_tables",
            "ocr_only_diagnostic", "full_cpu_local",
            "auto_general", "auto_quality",
        )
        for name in all_names:
            with self.subTest(profile=name):
                p = self._p(name)
                self.assertIn("ocr_agent", p)
                self.assertIn("table_ocr_agent", p)
