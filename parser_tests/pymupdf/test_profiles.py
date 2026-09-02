"""Tests for PyMuPDF benchmark profiles (sections on profile contract)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile
from src.parsers.pymupdf_v2 import _PYMUPDF_PROFILE_KEYS

PARSER_NAME = "pymupdf"
_ALL_PROFILES = [
    "native",
    "ocr_auto_rapidtess",
    "ocr_force_rapidtess",
    "ocr_auto_rapidtess_150",
    "ocr_auto_rapidtess_200",
    "ocr_auto_rapidtess_300",
    "full_cpu_local",
]


class TestProfilesExist(unittest.TestCase):
    def test_all_profiles_loadable(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIsInstance(p, dict)

    def test_all_profiles_have_required_keys(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                missing = _PYMUPDF_PROFILE_KEYS - set(p.keys())
                self.assertEqual(missing, frozenset(), f"Missing keys: {missing}")

    def test_no_extra_unknown_keys(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                extra = set(p.keys()) - _PYMUPDF_PROFILE_KEYS
                self.assertEqual(extra, set(), f"Unknown keys: {extra}")


class TestOcrModeValues(unittest.TestCase):
    _VALID_OCR_MODES = {"disabled", "auto", "forced"}

    def test_ocr_mode_valid_for_all_profiles(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIn(p["ocr_mode"], self._VALID_OCR_MODES)

    def test_ocr_disabled_mode_when_not_enabled(self):
        p = get_profile(PARSER_NAME, "native")
        self.assertFalse(p["ocr_enabled"])
        self.assertEqual(p["ocr_mode"], "disabled")

    def test_ocr_enabled_mode_not_disabled(self):
        p = get_profile(PARSER_NAME, "ocr_auto_rapidtess")
        self.assertTrue(p["ocr_enabled"])
        self.assertNotEqual(p["ocr_mode"], "disabled")

    def test_force_profile_uses_forced_mode(self):
        p = get_profile(PARSER_NAME, "ocr_force_rapidtess")
        self.assertEqual(p["ocr_mode"], "forced")


class TestFullCpuLocalProfile(unittest.TestCase):
    def _p(self):
        return get_profile(PARSER_NAME, "full_cpu_local")

    def test_ocr_mode_auto(self):
        self.assertEqual(self._p()["ocr_mode"], "auto")

    def test_layout_module_enabled(self):
        self.assertTrue(self._p()["layout_module"])

    def test_write_images_false(self):
        self.assertFalse(self._p()["write_images"])

    def test_embed_images_false(self):
        self.assertFalse(self._p()["embed_images"])

    def test_ocr_dpi_150(self):
        self.assertEqual(self._p()["ocr_dpi"], 150)

    def test_parser_header_true(self):
        self.assertTrue(self._p()["parser_header"])

    def test_parser_footer_true(self):
        self.assertTrue(self._p()["parser_footer"])

    def test_force_text_true(self):
        self.assertTrue(self._p()["force_text"])

    def test_page_separators_true(self):
        self.assertTrue(self._p()["page_separators"])

    def test_no_mutual_exclusion_violation(self):
        p = self._p()
        self.assertFalse(
            p["write_images"] and p["embed_images"],
            "write_images and embed_images must not both be True",
        )


class TestNoRemoteServices(unittest.TestCase):
    def test_ocr_engine_is_local(self):
        for name in _ALL_PROFILES:
            p = get_profile(PARSER_NAME, name)
            if p["ocr_enabled"]:
                with self.subTest(profile=name):
                    self.assertEqual(p["ocr_engine"], "rapidtess")
