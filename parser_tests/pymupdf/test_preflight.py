"""Tests for pymupdf_v2.preflight_profile (section on preflight contract)."""
from __future__ import annotations

import importlib.metadata
import unittest
from unittest.mock import MagicMock, patch

from src.parsers import pymupdf_v2

PARSER_NAME = "pymupdf"


class _PreflightHelper(unittest.TestCase):
    """Base with a helper to run preflight under controlled mock conditions."""

    def _run_preflight(
        self,
        profile_name: str,
        *,
        pymupdf4llm_present: bool = True,
        pymupdf_present: bool = True,
        pymupdf_layout_present: bool = True,
        rapidocr_available: bool = True,
        onnxruntime_available: bool = True,
        tesseract_on_path: bool = True,
    ) -> dict:
        not_installed: set[str] = set()
        if not pymupdf4llm_present:
            not_installed.add("pymupdf4llm")
        if not pymupdf_present:
            not_installed.add("pymupdf")
        if not pymupdf_layout_present:
            not_installed.add("pymupdf-layout")
        if not rapidocr_available:
            not_installed.add("rapidocr")
        if not onnxruntime_available:
            not_installed.add("onnxruntime")

        def _fake_meta_version(pkg: str) -> str:
            if pkg in not_installed:
                raise importlib.metadata.PackageNotFoundError(pkg)
            return "1.0.0"

        # Fake pymupdf4llm with a to_markdown that has all expected kwargs
        fake_to_markdown = (
            lambda page_chunks=None, use_ocr=False, force_ocr=False,
            ocr_function=None, ocr_language="por", ocr_dpi=300,
            header=True, footer=True, force_text=False, write_images=False,
            embed_images=False, page_separators=True, show_progress=True: ""
        )
        fake_pymupdf4llm = MagicMock()
        fake_pymupdf4llm.to_markdown = fake_to_markdown
        fake_pymupdf4llm.use_layout = MagicMock()

        fake_rapidtess = MagicMock()
        fake_rapidtess.exec_ocr = MagicMock()

        with (
            patch.object(importlib.metadata, "version", side_effect=_fake_meta_version),
            patch.object(pymupdf_v2, "pymupdf4llm", fake_pymupdf4llm),
            patch.object(pymupdf_v2, "rapidtess_api", fake_rapidtess),
            patch.object(pymupdf_v2, "shutil", MagicMock(
                which=lambda _: "/usr/bin/tesseract" if tesseract_on_path else None
            )),
        ):
            return pymupdf_v2.preflight_profile(profile_name)

    def _find_check(self, result: dict, name: str) -> dict:
        matches = [c for c in result.get("checks", []) if c.get("name") == name]
        self.assertEqual(len(matches), 1, f"Expected 1 check named {name!r}, got {len(matches)}")
        return matches[0]


class TestPreflightPackageChecks(_PreflightHelper):
    def test_all_packages_present_native_passes(self):
        result = self._run_preflight("native")
        self.assertTrue(result["ok"], result)

    def test_pymupdf4llm_missing_fails(self):
        result = self._run_preflight("native", pymupdf4llm_present=False)
        self.assertFalse(result["ok"])

    def test_pymupdf_missing_fails(self):
        result = self._run_preflight("native", pymupdf_present=False)
        self.assertFalse(result["ok"])

    def test_result_structure(self):
        result = self._run_preflight("native")
        self.assertIn("ok", result)
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], list)


class TestPreflightOcrDependencies(_PreflightHelper):
    def test_rapidocr_missing_fails_for_ocr_profile(self):
        result = self._run_preflight("ocr_auto_rapidtess", rapidocr_available=False)
        self.assertFalse(result["ok"])

    def test_tesseract_absent_warns_not_fails(self):
        result = self._run_preflight("ocr_auto_rapidtess", tesseract_on_path=False)
        tesseract_check = self._find_check(result, "tesseract binary")
        self.assertIn(tesseract_check["status"], {"warn", "pass"})

    def test_native_profile_does_not_require_rapidocr(self):
        result = self._run_preflight("native", rapidocr_available=False)
        self.assertTrue(result["ok"], result)


class TestPreflightFullCpuLocal(_PreflightHelper):
    def test_full_cpu_local_passes(self):
        result = self._run_preflight("full_cpu_local")
        self.assertTrue(result["ok"], result)

    def test_full_cpu_local_with_rapidocr_missing_fails(self):
        result = self._run_preflight("full_cpu_local", rapidocr_available=False)
        self.assertFalse(result["ok"])
