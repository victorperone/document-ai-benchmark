"""Tests for Xberg layout config keys and language_detection contract (X1, X4)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile
from src.parsers.xberg_v2 import _PROFILE_KEYS

PARSER_NAME = "xberg"


class TestLayoutProfileKeys(unittest.TestCase):
    def test_layout_keys_in_profile_keys_frozenset(self):
        for key in (
            "layout_enabled", "layout_strategy", "layout_apply_heuristics",
            "layout_acceleration_provider", "layout_confidence_threshold",
            "layout_enable_chart_understanding",
        ):
            with self.subTest(key=key):
                self.assertIn(key, _PROFILE_KEYS)

    def test_allow_single_column_tables_in_profile_keys(self):
        self.assertIn("allow_single_column_tables", _PROFILE_KEYS)

    def test_qr_codes_in_profile_keys(self):
        self.assertIn("qr_codes", _PROFILE_KEYS)

    def test_full_cpu_layout_has_layout_enabled(self):
        p = get_profile(PARSER_NAME, "full_cpu_layout")
        self.assertTrue(p["layout_enabled"])

    def test_full_cpu_layout_provider_is_cpu(self):
        p = get_profile(PARSER_NAME, "full_cpu_layout")
        self.assertEqual(p["layout_acceleration_provider"], "cpu")

    def test_full_cpu_layout_apply_heuristics(self):
        p = get_profile(PARSER_NAME, "full_cpu_layout")
        self.assertTrue(p["layout_apply_heuristics"])

    def test_full_cpu_local_layout_disabled(self):
        p = get_profile(PARSER_NAME, "full_cpu_local")
        self.assertFalse(p["layout_enabled"])


class TestLanguageDetectionFixed(unittest.TestCase):
    """Confirms that language_detection is NOT a profile key (fixed to None in the adapter)."""

    def test_language_detection_not_in_profile_keys(self):
        self.assertNotIn("language_detection", _PROFILE_KEYS)

    def test_language_detection_not_in_any_profile(self):
        all_profiles = [
            "native_markdown", "ocr_auto_tesseract", "ocr_force_tesseract",
            "ocr_auto_tesseract_repair", "full_cpu_local", "full_cpu_layout",
        ]
        for name in all_profiles:
            p = get_profile(PARSER_NAME, name)
            with self.subTest(profile=name):
                self.assertNotIn("language_detection", p)


class TestAllowSingleColumnTables(unittest.TestCase):
    def test_default_is_false_in_primary_profiles(self):
        primary = [
            "native_markdown", "ocr_auto_tesseract", "ocr_force_tesseract",
            "ocr_auto_tesseract_repair", "full_cpu_local",
        ]
        for name in primary:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertFalse(p["allow_single_column_tables"])
