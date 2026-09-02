"""Tests for Docling picture description enriched markdown contract."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.parsers.docling_v2 import _build_picture_description_blocks


class _DescriptionStub:
    def __init__(self, text: str, model_name: str = "") -> None:
        self.text = text
        self.provenance = SimpleNamespace(source="smolvlm", model_name=model_name)

    def model_dump(self, *, mode: str, exclude_none: bool) -> dict:
        return {"text": self.text}


class _PictureItemStub:
    def __init__(self, description: object | None, page_numbers: list[int]) -> None:
        self.label = "picture"
        self.self_ref = "#/pictures/0"
        self.text = None
        self.content_layer = None
        self.parent = None
        self.prov = [SimpleNamespace(page_no=p) for p in page_numbers]
        self.meta = SimpleNamespace(
            description=description,
            classification=None,
        )


class _TextItemStub:
    def __init__(self, text: str, page_numbers: list[int]) -> None:
        self.label = "text"
        self.text = text
        self.self_ref = None
        self.content_layer = None
        self.parent = None
        self.prov = [SimpleNamespace(page_no=p) for p in page_numbers]
        self.meta = None


class _DocumentStub:
    def __init__(self, items: list) -> None:
        self._items = items

    def iterate_items(self):
        for item in self._items:
            yield item, 0


class TestBuildPictureDescriptionBlocks(unittest.TestCase):
    def test_no_pictures_returns_none(self):
        doc = _DocumentStub([
            _TextItemStub("paragraph text", [1]),
        ])
        enriched, derived = _build_picture_description_blocks(doc, 2, ["page1", "page2"])
        self.assertIsNone(enriched)
        self.assertEqual(derived, [[], []])

    def test_picture_without_description_returns_none(self):
        doc = _DocumentStub([
            _PictureItemStub(None, [1]),
        ])
        enriched, derived = _build_picture_description_blocks(doc, 1, ["page1"])
        self.assertIsNone(enriched)
        self.assertEqual(derived, [[]])

    def test_single_picture_produces_derived_block(self):
        desc = _DescriptionStub("A bar chart showing growth.")
        doc = _DocumentStub([
            _PictureItemStub(desc, [1]),
        ])
        page_texts = ["some native text"]
        enriched, derived = _build_picture_description_blocks(doc, 1, page_texts)
        self.assertIsNotNone(enriched)
        self.assertIn("derived:start", enriched[0])
        self.assertIn("A bar chart showing growth.", enriched[0])
        self.assertIn("derived:end", enriched[0])

    def test_derived_block_not_in_source_page_texts(self):
        desc = _DescriptionStub("Chart description.")
        doc = _DocumentStub([
            _PictureItemStub(desc, [1]),
        ])
        original = ["native text"]
        page_texts = list(original)
        enriched, _ = _build_picture_description_blocks(doc, 1, page_texts)
        # source page_texts (original) must not contain derived markers
        self.assertNotIn("derived:start", original[0])
        # enriched must contain them
        self.assertIn("derived:start", enriched[0])

    def test_region_id_format(self):
        desc = _DescriptionStub("description")
        doc = _DocumentStub([
            _PictureItemStub(desc, [2]),
        ])
        _, derived = _build_picture_description_blocks(doc, 3, ["", "", ""])
        self.assertEqual(len(derived[1]), 1)
        region_id = derived[1][0]["region_id"]
        self.assertTrue(
            region_id.startswith("p2-picture-"),
            f"unexpected region_id: {region_id!r}",
        )

    def test_multiple_pictures_same_page_indexed(self):
        desc1 = _DescriptionStub("first")
        desc2 = _DescriptionStub("second")
        doc = _DocumentStub([
            _PictureItemStub(desc1, [1]),
            _PictureItemStub(desc2, [1]),
        ])
        _, derived = _build_picture_description_blocks(doc, 1, ["text"])
        self.assertEqual(len(derived[0]), 2)
        self.assertEqual(derived[0][0]["region_id"], "p1-picture-0")
        self.assertEqual(derived[0][1]["region_id"], "p1-picture-1")

    def test_pictures_on_different_pages(self):
        desc1 = _DescriptionStub("page one image")
        desc2 = _DescriptionStub("page two image")
        doc = _DocumentStub([
            _PictureItemStub(desc1, [1]),
            _PictureItemStub(desc2, [2]),
        ])
        enriched, derived = _build_picture_description_blocks(doc, 2, ["p1", "p2"])
        self.assertIsNotNone(enriched)
        self.assertIn("page one image", enriched[0])
        self.assertIn("page two image", enriched[1])
        self.assertEqual(len(derived[0]), 1)
        self.assertEqual(len(derived[1]), 1)

    def test_derived_entry_fields(self):
        desc = _DescriptionStub("some text", model_name="SmolVLM-256M")
        doc = _DocumentStub([
            _PictureItemStub(desc, [1]),
        ])
        _, derived = _build_picture_description_blocks(doc, 1, ["text"])
        entry = derived[0][0]
        self.assertEqual(entry["type"], "visual_description")
        self.assertEqual(entry["page_number"], 1)
        self.assertEqual(entry["storage_policy"], "inline")
        self.assertIn("engine", entry)
        self.assertIn("model", entry)

    def test_picture_without_provenance_skipped(self):
        desc = _DescriptionStub("orphan")
        item = _PictureItemStub(desc, [])  # no prov
        doc = _DocumentStub([item])
        enriched, derived = _build_picture_description_blocks(doc, 1, ["text"])
        self.assertIsNone(enriched)
        self.assertEqual(derived, [[]])

    def test_native_text_preserved_before_derived_block(self):
        desc = _DescriptionStub("chart")
        doc = _DocumentStub([_PictureItemStub(desc, [1])])
        page_texts = ["## Heading\n\nSome text."]
        enriched, _ = _build_picture_description_blocks(doc, 1, page_texts)
        self.assertTrue(enriched[0].startswith("## Heading"))
        self.assertIn("chart", enriched[0])
