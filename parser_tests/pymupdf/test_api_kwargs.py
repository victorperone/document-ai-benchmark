"""Tests for pymupdf_v2 API kwargs contract (section on API compatibility)."""
from __future__ import annotations

import unittest

from src.parsers.pymupdf_v2 import _PYMUPDF_PROFILE_KEYS, _TO_MARKDOWN_ARGS
from src.benchmark.config import get_profile

PARSER_NAME = "pymupdf"


class TestApiKwargsSet(unittest.TestCase):
    def test_to_markdown_args_is_frozenset(self):
        self.assertIsInstance(_TO_MARKDOWN_ARGS, frozenset)

    def test_to_markdown_args_not_empty(self):
        self.assertGreater(len(_TO_MARKDOWN_ARGS), 0)

    def test_expected_kwargs_present(self):
        expected = {
            "use_ocr", "force_ocr", "ocr_language", "ocr_dpi",
            "header", "footer", "force_text", "write_images",
            "embed_images", "page_separators",
        }
        missing = expected - _TO_MARKDOWN_ARGS
        self.assertEqual(missing, set(), f"Expected kwargs missing: {missing}")

    def test_no_geometry_kwargs(self):
        geometry_kwargs = {"bbox", "rect", "words", "rawdict", "blocks", "origin", "clip"}
        intersection = geometry_kwargs & _TO_MARKDOWN_ARGS
        self.assertEqual(intersection, set(),
                         "No geometry/word-level kwargs should be in _TO_MARKDOWN_ARGS")


class TestMutualExclusionConstraints(unittest.TestCase):
    def test_full_cpu_local_no_dual_image_embedding(self):
        p = get_profile(PARSER_NAME, "full_cpu_local")
        self.assertFalse(
            p["write_images"] and p["embed_images"],
            "write_images and embed_images must not both be True — would duplicate images",
        )

    def test_no_existing_profile_has_dual_embedding(self):
        from src.benchmark.config import load_config
        config = load_config()
        profiles = config["parsers"][PARSER_NAME]["profiles"]
        for name, p in profiles.items():
            with self.subTest(profile=name):
                self.assertFalse(
                    p.get("write_images") and p.get("embed_images"),
                    f"Profile '{name}': write_images and embed_images are both True",
                )


class TestProfileKeysCoverage(unittest.TestCase):
    def test_profile_keys_align_with_to_markdown_args(self):
        # Keys that map from profile → to_markdown (excluding layout_module which is handled separately)
        profile_to_kwarg_map = {
            "ocr_enabled": "use_ocr",
            "ocr_language": "ocr_language",
            "ocr_dpi": "ocr_dpi",
            "parser_header": "header",
            "parser_footer": "footer",
            "force_text": "force_text",
            "write_images": "write_images",
            "embed_images": "embed_images",
            "page_separators": "page_separators",
        }
        for profile_key, kwarg in profile_to_kwarg_map.items():
            with self.subTest(profile_key=profile_key, kwarg=kwarg):
                self.assertIn(profile_key, _PYMUPDF_PROFILE_KEYS)
                self.assertIn(kwarg, _TO_MARKDOWN_ARGS)
