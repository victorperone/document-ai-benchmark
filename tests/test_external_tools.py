"""
Tests for src.benchmark.external_tools.resolve_tesseract_executable().

All filesystem and platform checks are mocked — no real Tesseract required.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.external_tools import resolve_tesseract_executable


class TestResolveTesseractFoundInPath(unittest.TestCase):

    def test_returns_path_string_when_found_in_path(self):
        with patch("shutil.which", return_value="/usr/bin/tesseract"):
            result = resolve_tesseract_executable()
        self.assertEqual(result, "/usr/bin/tesseract")

    def test_returns_string_not_path(self):
        with patch("shutil.which", return_value="/usr/bin/tesseract"):
            result = resolve_tesseract_executable()
        self.assertIsInstance(result, str)

    def test_which_result_takes_priority_over_windows_candidates(self):
        with patch("shutil.which", return_value="/usr/bin/tesseract"), \
             patch.object(sys, "platform", "win32"):
            result = resolve_tesseract_executable()
        self.assertEqual(result, "/usr/bin/tesseract")


class TestResolveTesseractNotInPath(unittest.TestCase):

    def test_returns_none_on_linux_when_not_found(self):
        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "linux"):
            result = resolve_tesseract_executable()
        self.assertIsNone(result)

    def test_returns_none_on_linux_no_windows_fallback(self):
        # Ensure Windows candidate paths are NOT checked on Linux even if they existed
        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "linux"), \
             patch("pathlib.Path.is_file", return_value=True):
            result = resolve_tesseract_executable()
        self.assertIsNone(result)

    def test_returns_none_on_windows_when_no_candidate_exists(self):
        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "win32"), \
             patch("pathlib.Path.is_file", return_value=False):
            result = resolve_tesseract_executable()
        self.assertIsNone(result)


class TestResolveTesseractWindowsFallback(unittest.TestCase):

    def test_finds_first_windows_candidate(self):
        found = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

        def is_file_side_effect(self_path):
            return self_path == found

        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "win32"), \
             patch.object(Path, "is_file", is_file_side_effect):
            result = resolve_tesseract_executable()

        self.assertEqual(result, str(found))

    def test_finds_second_windows_candidate_when_first_missing(self):
        first = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        second = Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")

        def is_file_side_effect(self_path):
            return self_path == second

        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "win32"), \
             patch.object(Path, "is_file", is_file_side_effect):
            result = resolve_tesseract_executable()

        self.assertEqual(result, str(second))


if __name__ == "__main__":
    unittest.main()
