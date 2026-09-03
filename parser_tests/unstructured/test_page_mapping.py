"""Tests for §2.4 — unstructured page mapping and missing-page classification."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.config import BenchmarkConfigurationError
from src.parsers.unstructured_v2 import (
    _check_missing_pages,
    _elements_to_page_texts,
)


def _make_element(category: str, page_num: int | None, text: str = "text") -> object:
    meta = SimpleNamespace(page_number=page_num)
    klass = type(category, (), {"text": text, "metadata": meta})
    return klass()


def _make_page_break() -> object:
    klass = type("PageBreak", (), {"text": "", "metadata": None})
    return klass()


class TestElementsToPageTextsReturnsTuple(unittest.TestCase):
    """_elements_to_page_texts now returns a 3-tuple including observed_pages."""

    def test_returns_three_items(self) -> None:
        result = _elements_to_page_texts([], 2)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_empty_elements_no_observed_pages(self) -> None:
        _, _, observed = _elements_to_page_texts([], 3)
        self.assertEqual(observed, set())

    def test_element_on_page_1_observed(self) -> None:
        el = _make_element("NarrativeText", 1, "hello")
        _, _, observed = _elements_to_page_texts([el], 2)
        self.assertIn(1, observed)
        self.assertNotIn(2, observed)

    def test_page_break_excluded_from_observed(self) -> None:
        pb = _make_page_break()
        _, _, observed = _elements_to_page_texts([pb], 2)
        self.assertEqual(observed, set())

    def test_page_break_excluded_from_native_pages(self) -> None:
        pb = _make_page_break()
        el = _make_element("NarrativeText", 1, "text")
        _, native, _ = _elements_to_page_texts([pb, el], 1)
        for record in native.get(1, []):
            self.assertNotEqual(record.get("category"), "PageBreak")

    def test_unassigned_element_preserved_in_key_zero(self) -> None:
        el = _make_element("NarrativeText", None, "orphan text")
        _, native, observed = _elements_to_page_texts([el], 2)
        self.assertEqual(observed, set())
        self.assertEqual(len(native[0]), 1)
        self.assertEqual(native[0][0]["text"], "orphan text")

    def test_unassigned_element_not_counted_in_observed(self) -> None:
        el = _make_element("NarrativeText", None)
        _, _, observed = _elements_to_page_texts([el], 1)
        self.assertEqual(observed, set())


class TestCheckMissingPages(unittest.TestCase):
    """_check_missing_pages classifies absent pages correctly."""

    def _inventory(self, per_page: dict) -> dict:
        return {"pages": max(per_page.keys()) if per_page else 1, "per_page": per_page}

    def test_no_missing_pages_returns_empty_sets(self) -> None:
        inv = self._inventory({1: {"measurement_complete": True, "text_chars": 10}})
        empty, suspect = _check_missing_pages({1}, 1, inv, "default")
        self.assertEqual(empty, set())
        self.assertEqual(suspect, set())

    def test_legitimately_empty_page_accepted(self) -> None:
        inv = self._inventory({
            1: {"measurement_complete": True, "text_chars": 10},
            2: {"measurement_complete": True, "text_chars": 0, "image_count": 0, "drawing_count": 0},
        })
        empty, suspect = _check_missing_pages({1}, 2, inv, "default")
        self.assertIn(2, empty)
        self.assertNotIn(2, suspect)

    def test_missing_page_with_content_becomes_suspect_non_full(self) -> None:
        inv = self._inventory({
            1: {"measurement_complete": True, "text_chars": 100},
            2: {"measurement_complete": True, "text_chars": 50},
        })
        _, suspect = _check_missing_pages({1}, 2, inv, "default")
        self.assertIn(2, suspect)

    def test_missing_page_with_content_raises_on_full_cpu_local(self) -> None:
        inv = self._inventory({
            1: {"measurement_complete": True, "text_chars": 100},
            2: {"measurement_complete": True, "text_chars": 50},
        })
        with self.assertRaises(BenchmarkConfigurationError):
            _check_missing_pages({1}, 2, inv, "full_cpu_local")

    def test_incomplete_measurement_raises_on_full_cpu_local(self) -> None:
        inv = self._inventory({
            1: {"measurement_complete": True, "text_chars": 100},
            2: {"measurement_complete": False, "text_chars": 0},
        })
        with self.assertRaises(BenchmarkConfigurationError):
            _check_missing_pages({1}, 2, inv, "full_cpu_local")

    def test_incomplete_measurement_becomes_suspect_non_full(self) -> None:
        inv = self._inventory({
            1: {"measurement_complete": True, "text_chars": 100},
            2: {"measurement_complete": False, "text_chars": 0},
        })
        _, suspect = _check_missing_pages({1}, 2, inv, "default")
        self.assertIn(2, suspect)

    def test_missing_inventory_entry_raises_on_full_cpu_local(self) -> None:
        # per_page has entry for page 1 only, page 2 has no entry
        inv = {"pages": 2, "per_page": {"1": {"measurement_complete": True, "text_chars": 5}}}
        with self.assertRaises(BenchmarkConfigurationError):
            _check_missing_pages({1}, 2, inv, "full_cpu_local")

    def test_missing_inventory_entry_becomes_suspect_non_full(self) -> None:
        inv = {"pages": 2, "per_page": {"1": {"measurement_complete": True, "text_chars": 5}}}
        _, suspect = _check_missing_pages({1}, 2, inv, "default")
        self.assertIn(2, suspect)


if __name__ == "__main__":
    unittest.main()