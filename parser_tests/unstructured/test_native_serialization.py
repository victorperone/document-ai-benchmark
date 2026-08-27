"""Tests for parser_native serialization in unstructured_v2 (section 22.4)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers.unstructured_v2 import _element_to_native


def _make_el(**meta_attrs) -> MagicMock:
    el = MagicMock()
    type(el).__name__ = "NarrativeText"
    el.text = "sample text"
    el.id = "abc-123"
    meta = MagicMock()
    defaults = {
        "page_number": 1,
        "parent_id": None,
        "category_depth": None,
        "detection_class_prob": None,
        "detection_origin": None,
        "languages": None,
        "coordinates": None,
        "text_as_html": None,
        "links": None,
        "image_path": None,
    }
    defaults.update(meta_attrs)
    for k, v in defaults.items():
        setattr(meta, k, v)
    el.metadata = meta
    return el


class TestNativeFields(unittest.TestCase):
    def test_element_id_present(self):
        el = _make_el()
        native = _element_to_native(el)
        self.assertEqual(native["element_id"], "abc-123")

    def test_category_present(self):
        el = _make_el()
        native = _element_to_native(el)
        self.assertEqual(native["category"], "NarrativeText")

    def test_text_present(self):
        el = _make_el()
        native = _element_to_native(el)
        self.assertEqual(native["text"], "sample text")

    def test_page_number_present(self):
        el = _make_el(page_number=3)
        native = _element_to_native(el)
        self.assertEqual(native["page_number"], 3)

    def test_none_values_removed(self):
        el = _make_el(parent_id=None)
        native = _element_to_native(el)
        self.assertNotIn("parent_id", native)

    def test_text_as_html_included_when_present(self):
        el = _make_el(text_as_html="<table></table>")
        native = _element_to_native(el)
        self.assertIn("text_as_html", native)
        self.assertEqual(native["text_as_html"], "<table></table>")

    def test_coordinates_serialized(self):
        coords = MagicMock()
        coords.points = [(0, 0), (100, 100)]
        coords.system = "PixelSpace"
        el = _make_el(coordinates=coords)
        native = _element_to_native(el)
        self.assertIn("coordinates", native)
        self.assertEqual(native["coordinates"]["system"], "PixelSpace")

    def test_languages_included(self):
        el = _make_el(languages=["por", "eng"])
        native = _element_to_native(el)
        self.assertIn("languages", native)
        self.assertEqual(native["languages"], ["por", "eng"])


class TestNativeExclusions(unittest.TestCase):
    def test_no_base64_image_data(self):
        el = _make_el()
        native = _element_to_native(el)
        # image_path=None so no image fields; ensure no base64 key
        self.assertNotIn("image_base64", native)
        self.assertNotIn("image_bytes", native)

    def test_result_is_dict(self):
        el = _make_el()
        native = _element_to_native(el)
        self.assertIsInstance(native, dict)

    def test_all_values_serializable(self):
        import json
        el = _make_el(
            page_number=1,
            languages=["por"],
            detection_class_prob=0.95,
        )
        native = _element_to_native(el)
        # Should not raise
        json.dumps(native)
