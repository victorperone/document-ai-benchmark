"""Tests for Docling heading hierarchy and table engine profile keys."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile

PARSER_NAME = "docling"

_ALL_PROFILES = [
    "native",
    "ocr_auto",
    "ocr_auto_visual",
    "ocr_auto_formula",
    "ocr_auto_picture_classification",
    "full_cpu_local",
    "ocr_auto_table_v2",
]

_HEADING_KEYS = frozenset({
    "heading_hierarchy",
    "heading_use_bookmarks",
    "heading_use_numbering",
    "heading_use_style",
    "heading_use_font_style",
    "heading_style_size_tolerance",
    "heading_max_level",
    "heading_bookmark_match_threshold",
})

_VALID_TABLE_ENGINES = frozenset({"tableformer_v1", "tableformer_v2"})


class TestHeadingHierarchyKeys(unittest.TestCase):
    def test_all_profiles_have_heading_keys(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                missing = _HEADING_KEYS - set(p.keys())
                self.assertEqual(missing, frozenset(), f"Missing heading keys: {missing}")

    def test_heading_style_size_tolerance_is_float(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIsInstance(p["heading_style_size_tolerance"], float)

    def test_heading_max_level_is_int(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIsInstance(p["heading_max_level"], int)
                self.assertGreaterEqual(p["heading_max_level"], 1)

    def test_heading_bookmark_match_threshold_range(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                v = p["heading_bookmark_match_threshold"]
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)


class TestTableEngineKeys(unittest.TestCase):
    def test_all_profiles_have_table_engine(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIn("table_engine", p)

    def test_table_engine_valid_values(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIn(p["table_engine"], _VALID_TABLE_ENGINES)

    def test_baseline_profiles_use_v1(self):
        for name in ("native", "ocr_auto", "full_cpu_local"):
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertEqual(p["table_engine"], "tableformer_v1")

    def test_ocr_auto_table_v2_uses_v2(self):
        p = get_profile(PARSER_NAME, "ocr_auto_table_v2")
        self.assertEqual(p["table_engine"], "tableformer_v2")

    def test_no_remote_services_in_any_profile(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertFalse(p["remote_services_enabled"])
