"""Tests for unstructured_v2.preflight_profile (section 22.5)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.parsers.unstructured_v2 import preflight_profile, UNSTRUCTURED_REQUIRED_VERSION


def _status(result: dict, check_name: str) -> str | None:
    for item in result.get("checks", []):
        if item.get("name") == check_name:
            return item.get("status")
    return None


class TestPreflightVersion(unittest.TestCase):
    def test_correct_version_passes(self):
        with patch("src.parsers.unstructured_v2._package_version",
                   side_effect=lambda n: UNSTRUCTURED_REQUIRED_VERSION if n == "unstructured" else None):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured version"), "pass")

    def test_wrong_version_fails(self):
        with patch("src.parsers.unstructured_v2._package_version",
                   side_effect=lambda n: "0.1.0" if n == "unstructured" else None):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured version"), "fail")

    def test_missing_package_fails(self):
        with patch("src.parsers.unstructured_v2._package_version", return_value=None):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured version"), "fail")


class TestPreflightRemoteRejection(unittest.TestCase):
    def test_remote_services_enabled_true_fails(self):
        with patch("src.benchmark.config.get_profile",
                   return_value={
                       "strategy": "fast",
                       "ocr_enabled": False,
                       "remote_services_enabled": True,
                       "network_allowed_during_run": False,
                       "infer_table_structure": False,
                       "languages": ["por"],
                       "ocr_mode": None, "ocr_engine": None,
                       "detect_language_per_element": False,
                       "include_page_breaks": True,
                       "hi_res_model_name": None,
                       "extract_image_block_types": [],
                       "extract_image_block_to_payload": False,
                       "extract_forms": False,
                       "form_extraction_skip_tables": True,
                       "password": None,
                       "pdfminer_line_margin": None,
                       "pdfminer_char_margin": None,
                       "pdfminer_line_overlap": None,
                       "pdfminer_word_margin": 0.185,
                   }):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "remote services disabled"), "fail")


class TestPreflightTesseractCheck(unittest.TestCase):
    def test_missing_tesseract_in_ocr_profile_fails(self):
        with patch("src.parsers.unstructured_v2.shutil.which", return_value=None):
            result = preflight_profile("auto_ocr")
        self.assertEqual(_status(result, "tesseract executable"), "fail")


class TestPreflightTableStrategyCompat(unittest.TestCase):
    def test_infer_table_with_fast_strategy_fails(self):
        with patch("src.benchmark.config.get_profile",
                   return_value={
                       "strategy": "fast",
                       "ocr_enabled": False,
                       "remote_services_enabled": False,
                       "network_allowed_during_run": False,
                       "infer_table_structure": True,
                       "languages": ["por"],
                       "ocr_mode": None, "ocr_engine": None,
                       "detect_language_per_element": False,
                       "include_page_breaks": True,
                       "hi_res_model_name": None,
                       "extract_image_block_types": [],
                       "extract_image_block_to_payload": False,
                       "extract_forms": False,
                       "form_extraction_skip_tables": True,
                       "password": None,
                       "pdfminer_line_margin": None,
                       "pdfminer_char_margin": None,
                       "pdfminer_line_overlap": None,
                       "pdfminer_word_margin": 0.185,
                   }):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "table structure strategy"), "fail")
