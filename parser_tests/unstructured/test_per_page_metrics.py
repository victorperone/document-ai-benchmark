"""Tests for per-page element count fix (U3)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.parsers.unstructured_v2 import _count_elements_by_page


def _el(category: str, page: int | None) -> object:
    meta = SimpleNamespace(page_number=page) if page is not None else None
    el = SimpleNamespace(metadata=meta)
    el.__class__ = type(category, (), {"__name__": category})
    return el


class _FakeEl:
    def __init__(self, category: str, page: int | None) -> None:
        self.__class__ = type(category, (object,), {})
        self.__class__.__name__ = category
        self.metadata = SimpleNamespace(page_number=page) if page is not None else None


class TestCountElementsByPage(unittest.TestCase):
    def test_single_table_on_page_2(self):
        elements = [_FakeEl("Table", 2)]
        result = _count_elements_by_page(elements, 3)
        self.assertEqual(result[0]["tables_detected"], 0)  # page 1
        self.assertEqual(result[1]["tables_detected"], 1)  # page 2
        self.assertEqual(result[2]["tables_detected"], 0)  # page 3

    def test_all_pages_get_entry(self):
        elements = []
        result = _count_elements_by_page(elements, 5)
        self.assertEqual(len(result), 5)
        for entry in result:
            self.assertEqual(entry["tables_detected"], 0)

    def test_page_numbers_are_correct(self):
        elements = []
        result = _count_elements_by_page(elements, 3)
        self.assertEqual([r["page_number"] for r in result], [1, 2, 3])

    def test_elements_distributed_not_accumulated_on_page_1(self):
        """Regression test for the prior bug: all counts landed on page 1."""
        elements = [
            _FakeEl("Title", 1),
            _FakeEl("Title", 2),
            _FakeEl("Title", 3),
        ]
        result = _count_elements_by_page(elements, 3)
        # Each page must have exactly 1 heading, not 3 on page 1
        for entry in result:
            self.assertEqual(
                entry["headings_detected"],
                1,
                f"Page {entry['page_number']} expected 1 heading",
            )

    def test_unassigned_elements_excluded_from_page_counts(self):
        elements = [
            _FakeEl("Table", None),   # no page → unassigned
            _FakeEl("Table", 1),
        ]
        result = _count_elements_by_page(elements, 2)
        self.assertEqual(result[0]["tables_detected"], 1)
        self.assertEqual(result[1]["tables_detected"], 0)

    def test_out_of_range_page_excluded(self):
        elements = [_FakeEl("Image", 99)]  # page 99, page_count=2
        result = _count_elements_by_page(elements, 2)
        self.assertEqual(result[0]["images_detected"], 0)
        self.assertEqual(result[1]["images_detected"], 0)

    def test_page_break_ignored(self):
        elements = [
            _FakeEl("PageBreak", 1),
            _FakeEl("NarrativeText", 1),
        ]
        result = _count_elements_by_page(elements, 1)
        self.assertEqual(result[0]["layout_boxes"], 1)  # only NarrativeText counted

    def test_multiple_categories_per_page(self):
        elements = [
            _FakeEl("Table", 1),
            _FakeEl("Image", 1),
            _FakeEl("Title", 1),
            _FakeEl("NarrativeText", 1),
        ]
        result = _count_elements_by_page(elements, 1)
        self.assertEqual(result[0]["tables_detected"], 1)
        self.assertEqual(result[0]["images_detected"], 1)
        self.assertEqual(result[0]["headings_detected"], 1)
        self.assertEqual(result[0]["text_blocks_detected"], 1)
        self.assertEqual(result[0]["layout_boxes"], 4)
