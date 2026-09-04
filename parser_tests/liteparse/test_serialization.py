"""Serialization and Markdown output contract tests for LiteParse."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers import liteparse_v2


def _make_image_obj(path: str, page_num: int = 1) -> MagicMock:
    img = MagicMock()
    img.path = path
    img.page_num = page_num
    img.name = path.split("/")[-1]
    return img


def _build(
    raw: str,
    page_images: list | None = None,
    enrichments: dict | None = None,
) -> str:
    return liteparse_v2._build_page_text_with_enrichments(
        raw,
        page_images or [],
        enrichments or {},
    )


class LiteParseMarkdownFormattingTests(unittest.TestCase):
    """Test _build_page_text_with_enrichments() formatting contracts."""

    def test_no_double_blank_lines_in_output(self) -> None:
        raw = "Line one.\n\n\n\nLine two."
        out = _build(raw)
        self.assertNotIn("\n\n\n", out)

    def test_trailing_whitespace_removed_from_lines(self) -> None:
        raw = "Line with trailing spaces.   \nNext line."
        out = _build(raw)
        for line in out.splitlines():
            self.assertEqual(
                line,
                line.rstrip(),
                f"Line has trailing whitespace: {line!r}",
            )

    def test_output_ends_with_single_newline(self) -> None:
        out = _build("Some content.")
        self.assertTrue(out.endswith("\n"), "Output must end with a newline")
        self.assertFalse(
            out.endswith("\n\n"),
            "Output must end with exactly one newline",
        )

    def test_no_extra_content_without_images(self) -> None:
        raw = "Before.\n\nAfter."
        out = _build(raw)
        self.assertIn("Before.", out)
        self.assertIn("After.", out)

    def test_table_whitespace_compacted(self) -> None:
        """_compact_markdown_tables strips excess whitespace inside cells."""
        raw = "|  Header A  |  Header B  |\n|---|---|\n|  val1  |  val2  |"
        out = _build(raw)
        # After compaction, the excess spaces inside cells are removed.
        self.assertNotIn("|  Header A  |", out)

    def test_compacted_table_is_valid_markdown(self) -> None:
        raw = "| A | B |\n|---|---|\n| 1 | 2 |"
        out = _build(raw)
        table_lines = [ln for ln in out.splitlines() if ln.startswith("|")]
        self.assertGreater(len(table_lines), 0)
        for ln in table_lines:
            self.assertTrue(ln.startswith("|"))

    def test_compacted_table_preserves_all_cells(self) -> None:
        raw = "| Alpha | Beta |\n|---|---|\n| 42 | 99 |"
        out = _build(raw)
        self.assertIn("Alpha", out)
        self.assertIn("Beta", out)
        self.assertIn("42", out)
        self.assertIn("99", out)

    def test_empty_cells_preserved_in_table(self) -> None:
        raw = "| A | B |\n|---|---|\n|  |  |"
        out = _build(raw)
        table_lines = [ln for ln in out.splitlines() if ln.startswith("|")]
        self.assertGreater(len(table_lines), 0)

    def test_headings_preserved(self) -> None:
        raw = "# Main Heading\n\nSome text."
        out = _build(raw)
        self.assertIn("# Main Heading", out)

    def test_no_page_heading_injected(self) -> None:
        """The formatter must not inject page-number headings."""
        raw = "Plain content without headings."
        out = _build(raw)
        self.assertNotIn("## Page", out)
        self.assertNotIn("# Page", out)

    def test_duplicate_image_is_not_injected_again(self) -> None:
        image = _make_image_obj("/tmp/repeated.png")
        out = _build(
            "Native content.",
            [image],
            {
                "/tmp/repeated.png": {
                    "duplicate": True,
                    "kind": "image_text",
                    "ocr_text": "IMAGEM OCR: Orcamento local 2026",
                }
            },
        )
        self.assertNotIn("IMAGEM OCR", out)

    def test_long_ocr_already_in_global_text_is_duplicate(self) -> None:
        reference = "Prefixo\nIMAGEM OCR: Orcamento local 2026\nSufixo"
        self.assertTrue(
            liteparse_v2._text_already_present(
                reference,
                "  imagem OCR: Orcamento local 2026  ",
            )
        )

    def test_short_ocr_is_not_suppressed_by_substring_match(self) -> None:
        self.assertFalse(liteparse_v2._text_already_present("ABC", "ABC"))


class LiteParseMetricsContractTests(unittest.TestCase):
    """Tests for metrics schema requirements."""

    def _make_minimal_metrics(self) -> dict:
        return {
            "parser": "liteparse",
            "profile": "native",
            "liteparse_version": "2.13.0",
            "python_version": "3.12.0",
            "tesseract_version": None,
            "ocr_language": None,
            "dpi": 150,
            "num_workers": 4,
            "pages": {
                "total": 1,
                "pages_native": 1,
                "pages_needing_ocr": 0,
                "pages_ocr": 0,
                "pages_rotated": 0,
                "ocr_reason_counts": {},
                "orientation_counts": {},
            },
            "blocks": {},
            "images": {
                "detected": 0,
                "extracted": 0,
                "unique": 0,
                "duplicate": 0,
                "ocr_attempted": 0,
                "with_usable_text": 0,
                "described": 0,
            },
            "timing": {"pipeline_seconds": 0.0},
            "output": {},
        }

    def test_metrics_has_liteparse_version(self) -> None:
        m = self._make_minimal_metrics()
        self.assertIn("liteparse_version", m)
        self.assertIsInstance(m["liteparse_version"], str)

    def test_metrics_has_tesseract_version_field(self) -> None:
        m = self._make_minimal_metrics()
        # Field must be present even when None (non-OCR profile).
        self.assertIn("tesseract_version", m)

    def test_metrics_has_pages_needing_ocr(self) -> None:
        m = self._make_minimal_metrics()
        self.assertIn("pages_needing_ocr", m["pages"])
        self.assertIsInstance(m["pages"]["pages_needing_ocr"], int)

    def test_metrics_has_image_counts(self) -> None:
        m = self._make_minimal_metrics()
        images = m["images"]
        for key in (
            "detected",
            "extracted",
            "unique",
            "duplicate",
            "ocr_attempted",
            "with_usable_text",
            "described",
        ):
            self.assertIn(key, images, f"images.{key} must be present")

    def test_metrics_parser_is_liteparse(self) -> None:
        m = self._make_minimal_metrics()
        self.assertEqual(m["parser"], "liteparse")

    def test_metrics_has_timing(self) -> None:
        m = self._make_minimal_metrics()
        self.assertIn("timing", m)
        self.assertIn("pipeline_seconds", m["timing"])
        self.assertIsInstance(m["timing"]["pipeline_seconds"], float)


if __name__ == "__main__":
    unittest.main()
