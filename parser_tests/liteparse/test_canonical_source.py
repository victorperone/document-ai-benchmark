"""Tests for LiteParse §2.2 — canonical source and OCR policy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parsers.liteparse_v2 import (
    _debug_text_items_projection,
    _extract_page_texts,
    _merge_page_texts,
    MergeDecision,
)


class TestDebugProjectionIsolation(unittest.TestCase):
    """_debug_text_items_projection must not affect any Markdown artifact."""

    def test_raising_debug_projection_does_not_affect_extract_page_texts(self) -> None:
        """Monkeypatching _debug_text_items_projection to raise must not break
        _extract_page_texts, because _extract_page_texts must not call it."""
        import src.parsers.liteparse_v2 as mod

        page = SimpleNamespace(page_num=1, text="hello world")
        result = SimpleNamespace(pages=[page])

        with patch.object(mod, "_debug_text_items_projection", side_effect=RuntimeError("must not be called")):
            texts, mapped = _extract_page_texts(result, 1)

        self.assertEqual(texts[0], "hello world")
        self.assertIn(1, mapped)

    def test_extract_page_texts_uses_page_text_not_text_items(self) -> None:
        page = SimpleNamespace(
            page_num=1,
            text="canonical text",
            text_items=[SimpleNamespace(text="item text", x=0, y=0)],
        )
        result = SimpleNamespace(pages=[page])
        texts, _ = _extract_page_texts(result, 1)
        self.assertEqual(texts[0], "canonical text")
        self.assertNotEqual(texts[0], "item text")


class TestMergeDecisionDerivedOnly(unittest.TestCase):
    """Without compatible geometry, merge must use DERIVED_ONLY (not MERGE_MISSING_REGIONS)."""

    def test_no_geometry_forces_derived_only(self) -> None:
        native = ["some native text"]
        ocr_by_page = {1: "ocr text"}
        merged, decisions = _merge_page_texts(native, ocr_by_page, 1)
        self.assertEqual(decisions[0], MergeDecision.derived_only)
        # Native text is preserved (OCR is not merged in)
        self.assertEqual(merged[0], "some native text")

    def test_merge_missing_regions_requires_geometry(self) -> None:
        """MERGE_MISSING_REGIONS can only appear when compatible_geometry_by_page is provided."""
        native = ["x" * 50]
        ocr_by_page = {1: "x" * 80}
        _, decisions_no_geo = _merge_page_texts(native, ocr_by_page, 1)
        _, decisions_with_geo = _merge_page_texts(
            native, ocr_by_page, 1, compatible_geometry_by_page={1}
        )
        self.assertNotEqual(decisions_no_geo[0], MergeDecision.merge_missing_regions)
        # With geometry, the decision may or may not be merge_missing_regions depending on content
        self.assertIn(decisions_with_geo[0], (
            MergeDecision.keep_native,
            MergeDecision.merge_missing_regions,
            MergeDecision.replace_empty_page,
            MergeDecision.replace_garbled_page,
        ))


class TestRawMdSourceIsResultText(unittest.TestCase):
    """raw.md must be exactly result.text — not a projection of text_items."""

    def test_debug_projection_diverges_from_page_text(self) -> None:
        text_items = [
            SimpleNamespace(text="B", x=10, y=0),
            SimpleNamespace(text="A", x=0, y=0),
        ]
        projected = _debug_text_items_projection(text_items)
        # Projection sorts by x — A comes before B
        self.assertTrue(projected.startswith("A"))

        # page.text (the canonical source) is independent of projection order
        page_text = "B A"
        self.assertNotEqual(projected, page_text)


if __name__ == "__main__":
    unittest.main()