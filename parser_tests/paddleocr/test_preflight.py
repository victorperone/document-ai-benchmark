"""Tests for paddleocr_v2.preflight_profile (preflight contract)."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.benchmark.config import get_profile
from src.parsers import paddleocr_v2
from src.parsers.paddleocr_v2 import MODEL_NAMES, required_model_keys

PARSER_NAME = "paddleocr"


class _PreflightHelper(unittest.TestCase):
    """Base with a helper to run preflight with a temporary fake model root."""

    def _run_preflight(
        self,
        profile_name: str,
        *,
        model_dirs_present: bool = True,
        extra_absent: set[str] | None = None,
    ) -> dict:
        extra_absent = extra_absent or set()
        profile = get_profile(PARSER_NAME, profile_name)
        required = required_model_keys(profile)

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for key in required:
                model_name = MODEL_NAMES[key]
                if model_dirs_present and key not in extra_absent:
                    # Use first candidate name if available
                    from src.parsers.paddleocr_v2 import MODEL_DIRECTORY_CANDIDATES
                    candidates = MODEL_DIRECTORY_CANDIDATES.get(model_name, (model_name,))
                    (tmp_path / candidates[0]).mkdir()

            return paddleocr_v2.preflight_profile(
                profile_name,
                model_root_override=tmp_path,
            )

    def _find_check(self, result: dict, name: str) -> dict | None:
        matches = [c for c in result.get("checks", []) if c.get("name") == name]
        return matches[0] if matches else None


class TestPreflightModelRoot(_PreflightHelper):
    def test_model_root_exists_passes(self):
        result = self._run_preflight("default")
        check = self._find_check(result, "model root")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_result_has_ok_and_checks(self):
        result = self._run_preflight("default")
        self.assertIn("ok", result)
        self.assertIn("checks", result)

    def test_all_models_present_passes(self):
        result = self._run_preflight("default")
        self.assertTrue(result["ok"], result)


class TestPreflightProfileContract(_PreflightHelper):
    def test_profile_contract_passes_for_default(self):
        result = self._run_preflight("default")
        check = self._find_check(result, "profile contract")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_invalid_profile_fails_contract(self):
        bad_profile = {"ocr_enabled": True}
        with TemporaryDirectory() as tmp:
            with patch.object(paddleocr_v2, "get_profile", return_value=bad_profile):
                result = paddleocr_v2.preflight_profile(
                    "default",
                    model_root_override=Path(tmp),
                )
        check = self._find_check(result, "profile contract")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "fail")


class TestPreflightSealRecognition(_PreflightHelper):
    def test_seal_recognition_requires_two_seal_models(self):
        profile = get_profile(PARSER_NAME, "full_cpu_local")
        self.assertTrue(profile["seal_recognition"])
        keys = required_model_keys(profile)
        self.assertIn("seal_detection", keys)
        self.assertIn("seal_recognition", keys)

    def test_full_cpu_local_passes(self):
        result = self._run_preflight("full_cpu_local")
        self.assertTrue(result["ok"], result)


class TestPreflightModelSelection(_PreflightHelper):
    def test_model_selection_check_present(self):
        result = self._run_preflight("default")
        check = self._find_check(result, "model selection")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_formula_recognition_adds_formula_model(self):
        profile = get_profile(PARSER_NAME, "full_cpu_local")
        self.assertTrue(profile["formula_recognition"])
        keys = required_model_keys(profile)
        self.assertIn("formula", keys)

    def test_chart_recognition_adds_chart_model(self):
        profile = get_profile(PARSER_NAME, "full_cpu_local")
        self.assertTrue(profile["chart_recognition"])
        keys = required_model_keys(profile)
        self.assertIn("chart", keys)
