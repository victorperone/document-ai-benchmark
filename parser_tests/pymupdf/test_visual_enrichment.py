from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.parsers.pymupdf_visual_enrichment import _derived_block, enrich_pages


class PyMuPDFVisualDeduplicationTests(unittest.TestCase):
    def test_ocr_already_in_page_is_not_repeated(self) -> None:
        block = _derived_block(
            region_id="p1-picture-0-deadbeef",
            page_number=1,
            description="A small budget table.",
            ocr_text="IMAGEM OCR: Orcamento local 2026",
            description_model="model",
            ocr_engine="paddleocr",
            base_text="Before\nIMAGEM OCR: Orcamento local 2026\nAfter",
        )
        self.assertNotIn("Texto OCR", block)
        self.assertEqual(block.casefold().count("imagem ocr"), 0)
        self.assertIn("small budget table", block)

    def test_description_covering_ocr_is_emitted_only_once(self) -> None:
        ocr = "IMAGEM OCR: Orcamento local 2026"
        block = _derived_block(
            region_id="p1-picture-0-deadbeef",
            page_number=1,
            description=f"{ocr}. A bordered label.",
            ocr_text=ocr,
            description_model="model",
            ocr_engine="paddleocr",
        )
        self.assertNotIn("Texto OCR", block)
        self.assertEqual(block.casefold().count("imagem ocr"), 1)


class PyMuPDFVisualFailurePolicyTests(unittest.TestCase):
    def test_worker_failure_is_fatal_when_requested(self) -> None:
        worker = SimpleNamespace(process=lambda request: (_ for _ in ()).throw(
            RuntimeError("worker failed")
        ))
        native_pages = [{
            "page_boxes": [{"class": "picture", "bbox": [0, 0, 100, 100]}]
        }]
        with (
            patch(
                "src.parsers.pymupdf_visual_enrichment._embedded_image_boxes",
                return_value=[],
            ),
            patch(
                "src.parsers.pymupdf_visual_enrichment._render_region",
                return_value=b"png",
            ),
            self.assertRaisesRegex(RuntimeError, "worker failed"),
        ):
            enrich_pages(
                document=object(),
                native_pages=native_pages,
                page_texts=["page"],
                worker_client=worker,
                language="pt",
                description_model="model",
                failure_fatal=True,
            )
