"""Tests for xberg_v2 per-page content contract (section 36.5)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock


def _make_page(text: str = "Sample text", page_num: int = 1, tables=None):
    page = MagicMock()
    page.content = text
    page.page_number = page_num
    page.tables = tables or []
    return page


def _make_result(pages):
    result = MagicMock()
    doc = MagicMock()
    doc.pages = pages
    result.documents = [doc]
    result.errors = []
    result.warnings = []
    return result


class TestPageTextExtraction(unittest.TestCase):
    def test_page_text_mapped_by_number(self):
        pages = [_make_page("Content A", 1), _make_page("Content B", 2)]
        result = _make_result(pages)
        from src.parsers.xberg_v2 import _result_to_page_texts
        out = _result_to_page_texts(result, expected_pages=2)
        self.assertEqual(out.get(1), "Content A")
        self.assertEqual(out.get(2), "Content B")

    def test_empty_page_text_is_empty_string(self):
        pages = [_make_page("", 1)]
        result = _make_result(pages)
        from src.parsers.xberg_v2 import _result_to_page_texts
        out = _result_to_page_texts(result, expected_pages=1)
        self.assertIn(1, out)
        self.assertEqual(out[1], "")

    def test_page_text_is_string(self):
        pages = [_make_page("Some text", 1)]
        result = _make_result(pages)
        from src.parsers.xberg_v2 import _result_to_page_texts
        out = _result_to_page_texts(result, expected_pages=1)
        self.assertIsInstance(out[1], str)

    def test_page_with_table_produces_text(self):
        table = MagicMock()
        table.to_markdown.return_value = "| col |\n|---|\n| val |"
        pages = [_make_page("Before table", 1, tables=[table])]
        result = _make_result(pages)
        from src.parsers.xberg_v2 import _result_to_page_texts
        out = _result_to_page_texts(result, expected_pages=1)
        self.assertIsInstance(out.get(1), str)

    def test_page_count_matches_expected(self):
        pages = [_make_page(f"Page {i}", i) for i in range(1, 4)]
        result = _make_result(pages)
        from src.parsers.xberg_v2 import _result_to_page_texts
        out = _result_to_page_texts(result, expected_pages=3)
        self.assertEqual(len(out), 3)


class TestPageContractNoBytes(unittest.TestCase):
    def test_page_text_no_bytes_values(self):
        pages = [_make_page("Text content", 1)]
        result = _make_result(pages)
        from src.parsers.xberg_v2 import _result_to_page_texts
        out = _result_to_page_texts(result, expected_pages=1)
        for v in out.values():
            self.assertNotIsInstance(v, bytes)
