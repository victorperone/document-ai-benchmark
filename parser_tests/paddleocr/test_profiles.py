"""Tests for PaddleOCR benchmark profiles (profile contract)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile
from src.parsers.paddleocr_v2 import (
    PROFILE_BOOL_KEYS,
    PROFILE_EXTRA_KEYS,
    validate_profile,
)

PARSER_NAME = "paddleocr"
_ALL_PROFILES = [
    "default",
    "full_cpu_local",
]


class TestProfilesExist(unittest.TestCase):
    def test_all_profiles_loadable(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIsInstance(p, dict)

    def test_all_profiles_pass_validate_profile(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                try:
                    validate_profile(p)
                except ValueError as exc:
                    self.fail(f"validate_profile raised for '{name}': {exc}")

    def test_all_profiles_have_required_bool_keys(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                for key in PROFILE_BOOL_KEYS:
                    self.assertIn(key, p, f"Profile '{name}' missing bool key '{key}'")

    def test_all_bool_keys_are_actually_bool(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                for key in PROFILE_BOOL_KEYS:
                    if key in p:
                        self.assertIsInstance(
                            p[key], bool,
                            f"Profile '{name}' key '{key}' is not bool: {type(p[key]).__name__}",
                        )

    def test_no_unknown_keys_in_any_profile(self):
        all_known = set(PROFILE_BOOL_KEYS) | PROFILE_EXTRA_KEYS
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                extra = set(p.keys()) - all_known
                self.assertEqual(extra, set(), f"Profile '{name}' has unknown keys: {extra}")


class TestFullCpuLocalProfile(unittest.TestCase):
    def _p(self):
        return get_profile(PARSER_NAME, "full_cpu_local")

    def test_ocr_enabled(self):
        self.assertTrue(self._p()["ocr_enabled"])

    def test_table_recognition_enabled(self):
        self.assertTrue(self._p()["table_recognition"])

    def test_formula_recognition_enabled(self):
        self.assertTrue(self._p()["formula_recognition"])

    def test_chart_recognition_enabled(self):
        self.assertTrue(self._p()["chart_recognition"])

    def test_seal_recognition_enabled(self):
        self.assertTrue(self._p()["seal_recognition"])

    def test_document_orientation_classification_enabled(self):
        self.assertTrue(self._p()["document_orientation_classification"])

    def test_document_unwarping_enabled(self):
        self.assertTrue(self._p()["document_unwarping"])

    def test_region_detection_enabled(self):
        self.assertTrue(self._p()["region_detection"])

    def test_textline_orientation_enabled(self):
        self.assertTrue(self._p()["textline_orientation"])

    def test_format_block_content_enabled(self):
        self.assertTrue(self._p()["format_block_content"])

    def test_markdown_ignore_labels_is_list(self):
        p = self._p()
        self.assertIn("markdown_ignore_labels", p)
        self.assertIsInstance(p["markdown_ignore_labels"], list)


class TestOcrEnabledInvariant(unittest.TestCase):
    def test_all_profiles_have_ocr_enabled_true(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertTrue(
                    p.get("ocr_enabled"),
                    f"Profile '{name}': ocr_enabled must be True (PPStructureV3 requires it)",
                )
