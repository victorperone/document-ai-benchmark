"""Tests for Docling picture description enriched markdown contract."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.parsers.docling_v2 import (
    _build_picture_description_blocks,
    build_docling_page_contract,
)


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
        enriched, derived = _build_picture_description_blocks(doc, 2, ["page1", "page2"], effective_prompt="test prompt")
        self.assertIsNone(enriched)
        self.assertEqual(derived, [[], []])

    def test_picture_without_description_returns_none(self):
        doc = _DocumentStub([
            _PictureItemStub(None, [1]),
        ])
        enriched, derived = _build_picture_description_blocks(
            doc, 1, ["page1"], effective_prompt="test prompt"
        )
        self.assertIsNone(enriched)
        self.assertEqual(derived, [[]])

    def test_single_picture_produces_derived_block(self):
        desc = _DescriptionStub("A bar chart showing growth.")
        doc = _DocumentStub([
            _PictureItemStub(desc, [1]),
        ])
        page_texts = ["some native text"]
        enriched, derived = _build_picture_description_blocks(
            doc, 1, page_texts, effective_prompt="Describe this image."
        )
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
        enriched, _ = _build_picture_description_blocks(
            doc, 1, page_texts, effective_prompt="Describe this image."
        )
        # source page_texts (original) must not contain derived markers
        self.assertNotIn("derived:start", original[0])
        # enriched must contain them
        self.assertIn("derived:start", enriched[0])

    def test_region_id_format(self):
        desc = _DescriptionStub("description")
        doc = _DocumentStub([
            _PictureItemStub(desc, [2]),
        ])
        _, derived = _build_picture_description_blocks(
            doc, 3, ["", "", ""], effective_prompt="Describe."
        )
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
        _, derived = _build_picture_description_blocks(
            doc, 1, ["text"], effective_prompt="Describe."
        )
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
        enriched, derived = _build_picture_description_blocks(
            doc, 2, ["p1", "p2"], effective_prompt="Describe."
        )
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
        prompt = "Describe this image in detail."
        _, derived = _build_picture_description_blocks(
            doc, 1, ["text"], effective_prompt=prompt
        )
        entry = derived[0][0]
        # Canonical type is picture_description (not visual_description)
        self.assertEqual(entry["type"], "picture_description")
        self.assertEqual(entry["page_number"], 1)
        self.assertEqual(entry["storage_policy"], "inline")
        self.assertIn("engine", entry)
        self.assertIn("model", entry)
        self.assertIn("prompt_sha256", entry)
        # prompt_sha256 must be the SHA-256 of the effective prompt
        import hashlib
        expected_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self.assertEqual(entry["prompt_sha256"], expected_sha)

    def test_picture_without_provenance_skipped(self):
        desc = _DescriptionStub("orphan")
        item = _PictureItemStub(desc, [])  # no prov
        doc = _DocumentStub([item])
        enriched, derived = _build_picture_description_blocks(
            doc, 1, ["text"], effective_prompt="Describe."
        )
        self.assertIsNone(enriched)
        self.assertEqual(derived, [[]])

    def test_native_text_preserved_before_derived_block(self):
        desc = _DescriptionStub("chart")
        doc = _DocumentStub([_PictureItemStub(desc, [1])])
        page_texts = ["## Heading\n\nSome text."]
        enriched, _ = _build_picture_description_blocks(
            doc, 1, page_texts, effective_prompt="Describe."
        )
        self.assertTrue(enriched[0].startswith("## Heading"))
        self.assertIn("chart", enriched[0])

    def test_empty_effective_prompt_raises(self):
        """Without a prompt, provenance would be incomplete — must fail."""
        desc = _DescriptionStub("some image")
        doc = _DocumentStub([_PictureItemStub(desc, [1])])
        with self.assertRaises(RuntimeError):
            _build_picture_description_blocks(doc, 1, ["text"], effective_prompt="")


class TestPageExportContract(unittest.TestCase):
    def test_missing_document_page_does_not_create_synthetic_blank_page(self):
        class Document:
            pages = {1: object()}

            @staticmethod
            def export_to_markdown(*, page_no, blocked_meta_names):
                if page_no == 2:
                    raise IndexError("page absent")
                return "page one"

            @staticmethod
            def iterate_items():
                return iter(())

        with self.assertRaisesRegex(RuntimeError, "source page 2"):
            build_docling_page_contract(Document(), 2)
