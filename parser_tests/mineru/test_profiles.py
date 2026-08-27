"""Tests for MinerU benchmark profiles (profile contract)."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile
from src.parsers.mineru_v2 import _MINERU_VALID_METHODS

PARSER_NAME = "mineru"
_ALL_PROFILES = [
    "pipeline",
    "full_cpu_local",
]


class TestProfilesExist(unittest.TestCase):
    def test_all_profiles_loadable(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIsInstance(p, dict)

    def test_all_profiles_have_method(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIn("method", p)

    def test_all_profiles_have_valid_method(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertIn(
                    p["method"],
                    _MINERU_VALID_METHODS,
                    f"Profile '{name}' method {p['method']!r} not in {sorted(_MINERU_VALID_METHODS)}",
                )


class TestFullCpuLocalProfile(unittest.TestCase):
    def _p(self):
        return get_profile(PARSER_NAME, "full_cpu_local")

    def test_method_is_auto(self):
        self.assertEqual(self._p()["method"], "auto")

    def test_ocr_enabled(self):
        self.assertTrue(self._p()["ocr_enabled"])

    def test_formula_enabled(self):
        self.assertTrue(self._p()["formula"])

    def test_table_enabled(self):
        self.assertTrue(self._p()["table"])

    def test_backend_is_pipeline(self):
        self.assertEqual(self._p()["backend"], "pipeline")

    def test_no_remote_keys(self):
        p = self._p()
        self.assertNotIn("remote_services_enabled", p, "MinerU profile should not have remote_services_enabled")
        self.assertNotIn("gpu_enabled", p, "MinerU full_cpu_local should not enable GPU")


class TestNoGpuProfiles(unittest.TestCase):
    def test_no_profile_sets_gpu(self):
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                p = get_profile(PARSER_NAME, name)
                self.assertFalse(
                    p.get("gpu_enabled", False),
                    f"Profile '{name}' has gpu_enabled=True — must be CPU-only",
                )
