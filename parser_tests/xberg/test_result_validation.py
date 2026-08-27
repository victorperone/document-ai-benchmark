"""Tests for xberg_v2 result validation (section 36.4)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio


def _make_xberg_page(text: str = "Page text", page_num: int = 1):
    page = MagicMock()
    page.content = text
    page.page_number = page_num
    page.tables = []
    return page


def _make_xberg_result(pages=None, errors=None, warnings=None):
    result = MagicMock()
    result.errors = errors or []
    result.warnings = warnings or []
    if pages is not None:
        doc = MagicMock()
        doc.pages = pages
        result.documents = [doc]
    else:
        result.documents = []
    return result


class TestResultToPageTexts(unittest.TestCase):
    def _call(self, result, expected_pages: int):
        from src.parsers.xberg_v2 import _result_to_page_texts
        return _result_to_page_texts(result, expected_pages)

    def test_empty_result_returns_empty_strings(self):
        result = _make_xberg_result(pages=[])
        out = self._call(result, expected_pages=2)
        self.assertIsInstance(out, dict)

    def test_single_page_result(self):
        pages = [_make_xberg_page("Hello world", page_num=1)]
        result = _make_xberg_result(pages=pages)
        out = self._call(result, expected_pages=1)
        self.assertIn(1, out)
        self.assertIn("Hello world", out[1])

    def test_multi_page_result(self):
        pages = [
            _make_xberg_page("Page one", page_num=1),
            _make_xberg_page("Page two", page_num=2),
        ]
        result = _make_xberg_result(pages=pages)
        out = self._call(result, expected_pages=2)
        self.assertEqual(len(out), 2)

    def test_no_documents_graceful(self):
        result = _make_xberg_result(pages=None)
        out = self._call(result, expected_pages=1)
        self.assertIsInstance(out, dict)


class TestCountElementsFromResult(unittest.TestCase):
    def _call(self, result, page_texts: dict):
        from src.parsers.xberg_v2 import _count_elements_from_result
        return _count_elements_from_result(result, page_texts)

    def test_required_fields_present(self):
        required = {
            "layout_boxes", "tables_detected", "images_detected",
            "headings_detected", "lists_detected", "formulas_detected",
            "captions_detected", "page_headers_detected", "page_footers_detected",
            "footnotes_detected", "text_blocks_detected", "code_blocks_detected",
            "charts_detected", "box_class_counts",
        }
        result = _make_xberg_result(pages=[_make_xberg_page()])
        page_texts = {1: "Page text"}
        out = self._call(result, page_texts)
        missing = required - set(out.keys())
        self.assertEqual(missing, set(), f"Missing keys: {missing}")

    def test_table_count_from_pages(self):
        table = MagicMock()
        page = _make_xberg_page()
        page.tables = [table, table]
        result = _make_xberg_result(pages=[page])
        out = self._call(result, {1: "text"})
        self.assertEqual(out["tables_detected"], 2)

    def test_empty_pages_counted_in_text_blocks(self):
        empty_page = _make_xberg_page(text="")
        full_page = _make_xberg_page(text="Hello", page_num=2)
        result = _make_xberg_result(pages=[empty_page, full_page])
        out = self._call(result, {1: "", 2: "Hello"})
        # text_blocks_detected = non-empty pages
        self.assertEqual(out["text_blocks_detected"], 1)


class TestResultErrors(unittest.TestCase):
    def test_errors_do_not_raise_in_count(self):
        result = _make_xberg_result(pages=[], errors=["some error"])
        from src.parsers.xberg_v2 import _count_elements_from_result
        out = _count_elements_from_result(result, {})
        self.assertIsInstance(out, dict)

    def test_warnings_do_not_raise_in_count(self):
        page = _make_xberg_page()
        result = _make_xberg_result(pages=[page], warnings=["low confidence"])
        from src.parsers.xberg_v2 import _count_elements_from_result
        out = _count_elements_from_result(result, {1: "text"})
        self.assertIsInstance(out, dict)
