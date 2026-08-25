"""Image OCR and visual description tests for LiteParse."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers import liteparse_v2


def _make_image_obj(path: str, page_num: int = 1) -> MagicMock:
    """Return a mock image object as liteparse produces."""
    img = MagicMock()
    img.path = path
    img.page_num = page_num
    img.name = path.split("/")[-1]
    return img


class LiteParseUsableTextTests(unittest.TestCase):
    """Tests for _is_usable_text() — min 10 alphanumeric chars, ≥0.30 ratio."""

    def test_empty_string_is_not_usable(self) -> None:
        self.assertFalse(liteparse_v2._is_usable_text(""))

    def test_whitespace_only_is_not_usable(self) -> None:
        self.assertFalse(liteparse_v2._is_usable_text("   \n\t  "))

    def test_single_char_is_not_usable(self) -> None:
        # 1 alnum char — well below minimum of 10.
        self.assertFalse(liteparse_v2._is_usable_text("A"))

    def test_short_random_chars_is_not_usable(self) -> None:
        # 4 alnum chars — below minimum of 10.
        self.assertFalse(liteparse_v2._is_usable_text("ab cd"))

    def test_repeated_characters_is_not_usable(self) -> None:
        # "aaaaaaaaaa" — set size ≤ 2, length > 4 → rejected.
        self.assertFalse(liteparse_v2._is_usable_text("aaaaaaaaaa"))

    def test_valid_paragraph_is_usable(self) -> None:
        text = (
            "This document describes the quarterly revenue "
            "figures for the fiscal year 2024."
        )
        self.assertTrue(liteparse_v2._is_usable_text(text))

    def test_valid_sentence_is_usable(self) -> None:
        # 25 alnum chars, ratio ≈ 0.89 — passes both checks.
        self.assertTrue(
            liteparse_v2._is_usable_text("Revenue grew by 12 percent.")
        )

    def test_mixed_valid_text_is_usable(self) -> None:
        self.assertTrue(
            liteparse_v2._is_usable_text(
                "Table 3: Summary of operating costs (BRL)"
            )
        )

    def test_low_alphanumeric_ratio_is_not_usable(self) -> None:
        # Many non-alnum chars make ratio < 0.30.
        self.assertFalse(liteparse_v2._is_usable_text("... --- ??? !!! ~~~"))

    def test_minimum_threshold_boundaries(self) -> None:
        # 10 alnum chars ("Helloworld") and ratio ≈ 0.91 — meets threshold.
        self.assertTrue(liteparse_v2._is_usable_text("Hello world"))


class LiteParseImageMarkdownTests(unittest.TestCase):
    """Tests for image enrichment via _build_page_text_with_enrichments."""

    def _build(
        self,
        raw: str,
        page_images: list | None = None,
        enrichments: dict | None = None,
        *,
        image_description: bool = False,
    ) -> str:
        return liteparse_v2._build_page_text_with_enrichments(
            raw,
            page_images or [],
            enrichments or {},
            image_description=image_description,
        )

    def test_image_text_appears_in_page_text(self) -> None:
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_text",
                "ocr_text": "extracted text here",
            }
        }
        out = self._build("Paragraph one.", [img], enrichments)
        self.assertIn("extracted text here", out)

    def test_image_description_appears_in_page_text(self) -> None:
        img = _make_image_obj("/tmp/img_1.png")
        enrichments = {
            "/tmp/img_1.png": {
                "kind": "image_description",
                "image_description": "A bar chart showing monthly sales.",
            }
        }
        out = self._build("Content.", [img], enrichments, image_description=True)
        self.assertIn("bar chart", out)

    def test_image_text_and_description_not_both_emitted(self) -> None:
        # When image_description=False only image_text kind is emitted.
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_text",
                "ocr_text": "OCR only text",
            }
        }
        out = self._build("Text.", [img], enrichments, image_description=False)
        self.assertIn("OCR only text", out)
        self.assertNotIn("image_description", out)

    def test_no_enrichment_means_no_extra_content(self) -> None:
        out = self._build("Before.\n\nAfter.")
        self.assertIn("Before.", out)
        self.assertIn("After.", out)

    def test_image_text_uses_extraction_label(self) -> None:
        """Image OCR output uses a Portuguese extraction label."""
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_text",
                "ocr_text": "some words",
            }
        }
        out = self._build("", [img], enrichments)
        self.assertIn("imagem", out.lower())

    def test_image_description_has_italic_format(self) -> None:
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_description",
                "image_description": "A pie chart with three segments.",
            }
        }
        out = self._build("", [img], enrichments, image_description=True)
        self.assertIn("*", out)


class LiteParseMarkdownBlockParserTests(unittest.TestCase):
    """Tests for _parse_markdown_blocks() — blocks use the 'kind' key."""

    def _blocks(self, text: str) -> list[dict]:
        return liteparse_v2._parse_markdown_blocks(text)

    def _kinds(self, text: str) -> list[str]:
        return [b["kind"] for b in self._blocks(text)]

    def test_heading_level_1_detected(self) -> None:
        blocks = self._blocks("# Introduction")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["kind"], "heading")
        self.assertEqual(blocks[0]["level"], 1)

    def test_heading_level_2_detected(self) -> None:
        blocks = self._blocks("## Section 2")
        self.assertEqual(blocks[0]["kind"], "heading")
        self.assertEqual(blocks[0]["level"], 2)

    def test_heading_level_3_detected(self) -> None:
        blocks = self._blocks("### Subsection")
        self.assertEqual(blocks[0]["kind"], "heading")
        self.assertEqual(blocks[0]["level"], 3)

    def test_paragraph_detected(self) -> None:
        blocks = self._blocks("This is a paragraph of text.")
        self.assertEqual(blocks[0]["kind"], "paragraph")

    def test_table_detected(self) -> None:
        text = "| Col A | Col B |\n|---|---|\n| val1 | val2 |"
        self.assertIn("table", self._kinds(text))

    def test_list_item_detected_dash(self) -> None:
        blocks = self._blocks("- list item one")
        self.assertEqual(blocks[0]["kind"], "list_item")

    def test_list_item_detected_star(self) -> None:
        blocks = self._blocks("* list item two")
        self.assertEqual(blocks[0]["kind"], "list_item")

    def test_code_block_detected(self) -> None:
        text = "```\nsome code\n```"
        self.assertIn("code", self._kinds(text))

    def test_rule_detected(self) -> None:
        blocks = self._blocks("---")
        self.assertEqual(blocks[0]["kind"], "rule")

    def test_empty_string_returns_empty_list(self) -> None:
        self.assertEqual(self._blocks(""), [])

    def test_mixed_content_detects_all_types(self) -> None:
        text = (
            "# Heading\n\n"
            "A paragraph.\n\n"
            "- list item\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "---\n"
        )
        kinds = self._kinds(text)
        self.assertIn("heading", kinds)
        self.assertIn("paragraph", kinds)
        self.assertIn("list_item", kinds)
        self.assertIn("table", kinds)
        self.assertIn("rule", kinds)


if __name__ == "__main__":
    unittest.main()
