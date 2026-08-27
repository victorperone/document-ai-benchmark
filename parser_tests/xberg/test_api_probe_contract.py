"""Tests for Xberg API contract (section 36.2) — run against installed package."""
from __future__ import annotations

import asyncio
import unittest

XBERG_REQUIRED_VERSION = "1.0.14"


class TestXbergImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import xberg
            cls.xberg = xberg
            cls.available = True
        except ImportError:
            cls.xberg = None
            cls.available = False

    def setUp(self):
        if not self.available:
            self.skipTest("xberg not installed in this environment")

    def test_version(self):
        import importlib.metadata
        version = importlib.metadata.version("xberg")
        self.assertEqual(version, XBERG_REQUIRED_VERSION)

    def test_extract_exists(self):
        extract_fn = getattr(self.xberg, "extract", None)
        self.assertIsNotNone(extract_fn, "xberg.extract not found")

    def test_extract_is_async(self):
        extract_fn = getattr(self.xberg, "extract", None)
        if extract_fn is None:
            self.skipTest("xberg.extract not found")
        self.assertTrue(asyncio.iscoroutinefunction(extract_fn))

    def test_extraction_config_exists(self):
        cls = getattr(self.xberg, "ExtractionConfig", None)
        self.assertIsNotNone(cls, "xberg.ExtractionConfig not found")

    def test_extract_input_exists(self):
        cls = getattr(self.xberg, "ExtractInput", None)
        self.assertIsNotNone(cls, "xberg.ExtractInput not found")


class TestXbergConfigClasses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import xberg
            cls.xberg = xberg
            cls.available = True
        except ImportError:
            cls.available = False

    def setUp(self):
        if not self.available:
            self.skipTest("xberg not installed in this environment")

    def _check_class(self, name: str):
        cls = getattr(self.xberg, name, None)
        self.assertIsNotNone(cls, f"xberg.{name} not found")

    def test_ocr_config_exists(self):
        self._check_class("OcrConfig")

    def test_tesseract_config_exists(self):
        self._check_class("TesseractConfig")


class TestXbergResultTypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import xberg
            cls.xberg = xberg
            cls.available = True
        except ImportError:
            cls.available = False

    def setUp(self):
        if not self.available:
            self.skipTest("xberg not installed in this environment")

    def test_extraction_result_or_similar_exists(self):
        has_result = any(
            getattr(self.xberg, name, None) is not None
            for name in ("ExtractionResult", "ExtractedDocument", "ExtractionOutput")
        )
        self.assertTrue(has_result, "No result type found in xberg")
