"""Image OCR and visual description tests for LiteParse."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

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
    ) -> str:
        return liteparse_v2._build_page_text_with_enrichments(
            raw,
            page_images or [],
            enrichments or {},
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

    def test_image_description_not_injected_into_markdown(self) -> None:
        """VLM descriptions go to parser_native only — never into compared markdown."""
        img = _make_image_obj("/tmp/img_1.png")
        enrichments = {
            "/tmp/img_1.png": {
                "kind": "image_description",
                "image_description": "A bar chart showing monthly sales.",
            }
        }
        out = self._build("Content.", [img], enrichments)
        self.assertNotIn("bar chart", out)

    def test_image_text_ocr_content_present_without_synthetic_label(self) -> None:
        """OCR text is emitted but without synthetic PT-BR labels."""
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_text",
                "ocr_text": "OCR only text",
            }
        }
        out = self._build("Text.", [img], enrichments)
        self.assertIn("OCR only text", out)
        self.assertNotIn("Texto extraído", out)
        self.assertNotIn("Imagem:", out)

    def test_no_enrichment_means_no_extra_content(self) -> None:
        out = self._build("Before.\n\nAfter.")
        self.assertIn("Before.", out)
        self.assertIn("After.", out)

    def test_image_text_no_synthetic_label_in_output(self) -> None:
        """No Portuguese extraction label is injected into the markdown."""
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_text",
                "ocr_text": "some words here to find",
            }
        }
        out = self._build("", [img], enrichments)
        self.assertNotIn("imagem", out.lower())
        self.assertNotIn("extraído", out)
        self.assertIn("some words here to find", out)

    def test_image_description_no_italic_injected(self) -> None:
        """VLM descriptions must not appear as italic text in the markdown."""
        img = _make_image_obj("/tmp/img_0.png")
        enrichments = {
            "/tmp/img_0.png": {
                "kind": "image_description",
                "image_description": "A pie chart with three segments.",
            }
        }
        out = self._build("", [img], enrichments)
        self.assertNotIn("pie chart", out)
        self.assertNotIn("*Imagem:", out)


class LiteParseImageProfileExecutionTests(unittest.TestCase):
    def test_disabled_rotation_and_image_ocr_are_not_executed(self) -> None:
        with TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "image.png"
            image_path.write_bytes(b"image")
            image = _make_image_obj(str(image_path))
            profile = {
                "orientation_detection": False,
                "image_ocr": False,
                "image_description": False,
                "ocr_failure_fatal": True,
            }

            with (
                patch.object(
                    liteparse_v2,
                    "_detect_and_correct_orientation",
                ) as detect,
                patch.object(liteparse_v2, "_ocr_image_bytes") as ocr,
            ):
                result = liteparse_v2._process_document_images(
                    [image], profile, Path(tmp), Path(tmp)
                )

        detect.assert_not_called()
        ocr.assert_not_called()
        self.assertFalse(result[str(image_path)]["ocr_attempted"])

    def test_profile_controls_are_forwarded_to_image_pipeline(self) -> None:
        with TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "image.png"
            image_path.write_bytes(b"image")
            image = _make_image_obj(str(image_path))
            profile = {
                "orientation_detection": True,
                "image_ocr": True,
                "image_description": True,
                "image_description_fallback_only": False,
                "image_description_model": "org/custom-model",
                "image_description_prompt": "Describe visual facts.",
                "ocr_failure_fatal": True,
            }

            with (
                patch.object(
                    liteparse_v2,
                    "_detect_and_correct_orientation",
                    return_value=(b"corrected", 90),
                ) as detect,
                patch.object(
                    liteparse_v2,
                    "_ocr_image_bytes",
                    return_value="Readable budget total 2026",
                ) as ocr,
                patch.object(
                    liteparse_v2,
                    "_describe_image_with_smolvlm",
                    return_value="A two-column budget table.",
                ) as describe,
            ):
                result = liteparse_v2._process_document_images(
                    [image], profile, Path(tmp), Path(tmp), "por+eng"
                )

        detect.assert_called_once_with(b"image", failure_fatal=True)
        ocr.assert_called_once_with(
            b"corrected", lang="por+eng", failure_fatal=True
        )
        description_args = describe.call_args.args
        self.assertEqual(description_args[3], "org--custom-model")
        self.assertIn("Do not transcribe or repeat", description_args[2])
        self.assertEqual(result[str(image_path)]["model"], "org/custom-model")


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
