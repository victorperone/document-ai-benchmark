"""Tests for page grouping algorithm in unstructured_v2 (section 22.3)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers.unstructured_v2 import _elements_to_page_texts


def _make_el(category: str, text: str, page_num: int | None) -> MagicMock:
    el = MagicMock()
    type(el).__name__ = category
    el.text = text
    meta = MagicMock()
    meta.page_number = page_num
    meta.text_as_html = None
    meta.parent_id = None
    meta.category_depth = None
    meta.detection_class_prob = None
    meta.detection_origin = None
    meta.languages = None
    meta.coordinates = None
    meta.links = None
    meta.image_path = None
    el.metadata = meta
    el.id = "id-test"
    return el


class TestPageBoundaries(unittest.TestCase):
    def test_exactly_n_page_texts_returned(self):
        page_count = 3
        elements = [_make_el("NarrativeText", f"text p{i+1}", i + 1) for i in range(3)]
        texts, native, _observed = _elements_to_page_texts(elements, page_count)
        self.assertEqual(len(texts), 3)

    def test_elements_routed_to_correct_page(self):
        elements = [
            _make_el("NarrativeText", "page one", 1),
            _make_el("NarrativeText", "page two", 2),
        ]
        texts, native, _observed = _elements_to_page_texts(elements, 2)
        self.assertIn("page one", texts[0])
        self.assertIn("page two", texts[1])

    def test_page_below_range_goes_to_no_page_bucket(self):
        elements = [_make_el("NarrativeText", "orphan", 0)]
        texts, native, _observed = _elements_to_page_texts(elements, 2)
        self.assertEqual(texts[0], "")
        self.assertEqual(texts[1], "")
        self.assertIn(0, native)  # stored in key-0 diagnostic bucket

    def test_page_above_range_goes_to_no_page_bucket(self):
        elements = [_make_el("NarrativeText", "orphan", 99)]
        texts, native, _observed = _elements_to_page_texts(elements, 2)
        self.assertEqual(texts[0], "")
        self.assertEqual(texts[1], "")
        self.assertIn(0, native)

    def test_none_page_number_goes_to_no_page_bucket(self):
        elements = [_make_el("NarrativeText", "no page", None)]
        texts, native, _observed = _elements_to_page_texts(elements, 2)
        self.assertIn(0, native)
        self.assertEqual(texts[0], "")

    def test_pagebreak_not_duplicated(self):
        elements = [
            _make_el("NarrativeText", "before", 1),
            _make_el("PageBreak", "", 1),
            _make_el("NarrativeText", "after", 1),
        ]
        texts, native, _observed = _elements_to_page_texts(elements, 1)
        self.assertNotIn("PageBreak", texts[0])
        self.assertIn("before", texts[0])
        self.assertIn("after", texts[0])

    def test_empty_page_is_empty_string(self):
        texts, native, _observed = _elements_to_page_texts([], 3)
        for t in texts:
            self.assertEqual(t, "")

    def test_element_order_within_page_preserved(self):
        elements = [
            _make_el("NarrativeText", "first", 1),
            _make_el("NarrativeText", "second", 1),
            _make_el("NarrativeText", "third", 1),
        ]
        texts, native, _observed = _elements_to_page_texts(elements, 1)
        idx_first = texts[0].index("first")
        idx_second = texts[0].index("second")
        idx_third = texts[0].index("third")
        self.assertLess(idx_first, idx_second)
        self.assertLess(idx_second, idx_third)

    def test_one_native_record_per_page_key(self):
        elements = [
            _make_el("NarrativeText", "a", 1),
            _make_el("NarrativeText", "b", 2),
        ]
        texts, native, _observed = _elements_to_page_texts(elements, 2)
        self.assertIn(1, native)
        self.assertIn(2, native)
        self.assertEqual(len(native[1]), 1)
        self.assertEqual(len(native[2]), 1)

    def test_no_proportional_split(self):
        """Output must come from elements, not from character-count splitting."""
        long_text = "x" * 1000
        elements = [_make_el("NarrativeText", long_text, 1)]
        texts, native, _observed = _elements_to_page_texts(elements, 3)
        # All text on page 1; pages 2 and 3 are empty
        self.assertIn(long_text, texts[0])
        self.assertEqual(texts[1], "")
        self.assertEqual(texts[2], "")
