"""OCR routing tests for LiteParse selective OCR."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers import liteparse_v2


def _make_complexity_result(
    page_number: int,
    reasons: list[str],
) -> MagicMock:
    """Return a mock page-complexity result object."""
    result = MagicMock()
    result.page_number = page_number
    result.reasons = reasons
    result.needs_ocr = bool(reasons)
    return result


def _triggers_full_page_ocr(reasons: list[str]) -> bool:
    """Return True if any reason is in FULL_PAGE_OCR_REASONS."""
    return bool(
        set(reasons) & liteparse_v2.FULL_PAGE_OCR_REASONS
    )


class LiteParseOCRRoutingTests(unittest.TestCase):

    def test_scanned_reason_triggers_full_page_ocr(self) -> None:
        cr = _make_complexity_result(1, ["scanned"])
        self.assertTrue(_triggers_full_page_ocr(cr.reasons))

    def test_no_text_reason_triggers_full_page_ocr(self) -> None:
        cr = _make_complexity_result(2, ["no-text"])
        self.assertTrue(_triggers_full_page_ocr(cr.reasons))

    def test_sparse_text_reason_triggers_full_page_ocr(self) -> None:
        cr = _make_complexity_result(3, ["sparse-text"])
        self.assertTrue(_triggers_full_page_ocr(cr.reasons))

    def test_garbled_reason_triggers_full_page_ocr(self) -> None:
        cr = _make_complexity_result(4, ["garbled"])
        self.assertTrue(_triggers_full_page_ocr(cr.reasons))

    def test_embedded_images_alone_does_not_trigger_full_page_ocr(
        self,
    ) -> None:
        cr = _make_complexity_result(5, ["embedded-images"])
        self.assertFalse(_triggers_full_page_ocr(cr.reasons))

    def test_vector_text_alone_does_not_trigger_full_page_ocr(
        self,
    ) -> None:
        cr = _make_complexity_result(6, ["vector-text"])
        self.assertFalse(_triggers_full_page_ocr(cr.reasons))

    def test_annotation_text_alone_does_not_trigger_full_page_ocr(
        self,
    ) -> None:
        cr = _make_complexity_result(7, ["annotation-text"])
        self.assertFalse(_triggers_full_page_ocr(cr.reasons))

    def test_empty_reasons_stays_native(self) -> None:
        cr = _make_complexity_result(8, [])
        self.assertFalse(_triggers_full_page_ocr(cr.reasons))
        self.assertFalse(cr.needs_ocr)

    def test_full_page_ocr_reasons_constant(self) -> None:
        """FULL_PAGE_OCR_REASONS must contain exactly the expected reasons."""
        expected = frozenset({"scanned", "no-text", "sparse-text", "garbled"})
        self.assertEqual(
            liteparse_v2.FULL_PAGE_OCR_REASONS,
            expected,
            "FULL_PAGE_OCR_REASONS diverged from the expected set",
        )

    def test_scanned_plus_embedded_triggers_full_page_ocr(self) -> None:
        """A mix of full-page and image-only reasons still triggers full-page."""
        cr = _make_complexity_result(9, ["scanned", "embedded-images"])
        self.assertTrue(_triggers_full_page_ocr(cr.reasons))


if __name__ == "__main__":
    unittest.main()
