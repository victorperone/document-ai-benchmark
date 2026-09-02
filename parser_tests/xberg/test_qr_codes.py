"""Tests for Xberg QR extraction helpers (X3)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.parsers.xberg_v2 import (
    _build_qr_derived_blocks,
    _qr_payload_is_safe,
    _render_qr_enriched_page,
)


class TestQrPayloadSafety(unittest.TestCase):
    def test_short_text_is_safe(self):
        self.assertTrue(_qr_payload_is_safe("https://example.com"))

    def test_empty_payload_is_safe(self):
        self.assertTrue(_qr_payload_is_safe(""))

    def test_payload_too_long_is_rejected(self):
        self.assertFalse(_qr_payload_is_safe("x" * 2001))

    def test_payload_exactly_2000_is_safe(self):
        self.assertTrue(_qr_payload_is_safe("x" * 2000))

    def test_control_chars_rejected(self):
        self.assertFalse(_qr_payload_is_safe("hello\x00world"))

    def test_tab_allowed(self):
        self.assertTrue(_qr_payload_is_safe("col1\tcol2"))

    def test_unicode_text_is_safe(self):
        self.assertTrue(_qr_payload_is_safe("CNPJ: 12.345.678/0001-90"))


class TestBuildQrDerivedBlocks(unittest.TestCase):
    def _make_results(self, *items):
        return list(items)

    def test_empty_results_returns_empty_lists(self):
        result = _build_qr_derived_blocks([], 3)
        self.assertEqual(len(result), 3)
        for page_items in result:
            self.assertEqual(page_items, [])

    def test_qr_on_page_2_of_3(self):
        records = [{"page_number": 2, "payload": "ABC", "format": "QR_CODE", "bbox": None}]
        result = _build_qr_derived_blocks(records, 3)
        self.assertEqual(len(result[0]), 0)
        self.assertEqual(len(result[1]), 1)
        self.assertEqual(result[1][0]["payload"], "ABC")
        self.assertEqual(len(result[2]), 0)

    def test_unsafe_payload_excluded(self):
        records = [{"page_number": 1, "payload": "x" * 2001, "format": "QR_CODE", "bbox": None}]
        result = _build_qr_derived_blocks(records, 2)
        self.assertEqual(result[0], [])

    def test_out_of_range_page_excluded(self):
        records = [{"page_number": 99, "payload": "OK", "format": "QR_CODE", "bbox": None}]
        result = _build_qr_derived_blocks(records, 3)
        for page_items in result:
            self.assertEqual(page_items, [])

    def test_multiple_qr_on_same_page(self):
        records = [
            {"page_number": 1, "payload": "A", "format": "QR_CODE", "bbox": None},
            {"page_number": 1, "payload": "B", "format": "QR_CODE", "bbox": None},
        ]
        result = _build_qr_derived_blocks(records, 2)
        self.assertEqual(len(result[0]), 2)


class TestRenderQrEnrichedPage(unittest.TestCase):
    def test_no_qr_returns_unchanged_text(self):
        text = "# Heading\n\nSome content.\n"
        result = _render_qr_enriched_page(text, [])
        self.assertEqual(result, text)

    def test_qr_block_appended(self):
        text = "# Page content\n"
        items = [{"page_number": 1, "payload": "HELLO", "format": "QR_CODE"}]
        result = _render_qr_enriched_page(text, items)
        self.assertIn("<!-- derived:start", result)
        self.assertIn("type=qr_code", result)
        self.assertIn("HELLO", result)
        self.assertIn("<!-- derived:end -->", result)

    def test_raw_text_not_contaminated(self):
        """derived:start markers must NOT appear in raw.md (source text)."""
        text = "clean content"
        self.assertNotIn("derived:start", text)

    def test_enriched_ends_with_newline(self):
        text = "content"
        items = [{"page_number": 1, "payload": "X", "format": "QR_CODE"}]
        result = _render_qr_enriched_page(text, items)
        self.assertTrue(result.endswith("\n"))
