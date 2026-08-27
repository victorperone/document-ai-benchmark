"""Tests for the Unstructured Markdown renderer (section 22.2)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers.unstructured_v2 import _render_element, _render_table_html


def _make_el(category: str, text: str = "", **meta_attrs) -> MagicMock:
    el = MagicMock()
    type(el).__name__ = category
    el.text = text
    meta = MagicMock()
    for k, v in meta_attrs.items():
        setattr(meta, k, v)
    el.metadata = meta
    return el


class TestTitleRendering(unittest.TestCase):
    def test_no_depth_renders_h1(self):
        el = _make_el("Title", "Hello", category_depth=None)
        result = _render_element(el)
        self.assertEqual(result, "# Hello")

    def test_depth_0_renders_h1(self):
        el = _make_el("Title", "Hello", category_depth=0)
        result = _render_element(el)
        self.assertEqual(result, "# Hello")

    def test_depth_1_renders_h2(self):
        el = _make_el("Title", "Hello", category_depth=1)
        result = _render_element(el)
        self.assertEqual(result, "## Hello")

    def test_depth_5_renders_h6(self):
        el = _make_el("Title", "Hello", category_depth=5)
        result = _render_element(el)
        self.assertEqual(result, "###### Hello")

    def test_depth_10_capped_at_h6(self):
        el = _make_el("Title", "Hello", category_depth=10)
        result = _render_element(el)
        self.assertEqual(result, "###### Hello")

    def test_empty_title_returns_empty(self):
        el = _make_el("Title", "", category_depth=0)
        result = _render_element(el)
        self.assertEqual(result, "")


class TestParagraphRendering(unittest.TestCase):
    def test_narrative_text_returned_as_is(self):
        el = _make_el("NarrativeText", "Some long paragraph.")
        self.assertEqual(_render_element(el), "Some long paragraph.")

    def test_text_element(self):
        el = _make_el("Text", "Plain text.")
        self.assertEqual(_render_element(el), "Plain text.")


class TestListItemRendering(unittest.TestCase):
    def test_no_depth_renders_dash(self):
        el = _make_el("ListItem", "item", category_depth=None)
        self.assertEqual(_render_element(el), "- item")

    def test_depth_0_renders_dash(self):
        el = _make_el("ListItem", "item", category_depth=0)
        self.assertEqual(_render_element(el), "- item")

    def test_depth_1_indented(self):
        el = _make_el("ListItem", "item", category_depth=1)
        self.assertEqual(_render_element(el), "  - item")

    def test_depth_2_indented(self):
        el = _make_el("ListItem", "item", category_depth=2)
        self.assertEqual(_render_element(el), "    - item")

    def test_empty_returns_empty(self):
        el = _make_el("ListItem", "", category_depth=0)
        self.assertEqual(_render_element(el), "")


class TestPageBreakRendering(unittest.TestCase):
    def test_pagebreak_returns_empty(self):
        el = _make_el("PageBreak", "")
        self.assertEqual(_render_element(el), "")

    def test_pagebreak_with_text_still_empty(self):
        el = _make_el("PageBreak", "anything")
        self.assertEqual(_render_element(el), "")


class TestCodeSnippetRendering(unittest.TestCase):
    def test_code_snippet_gets_fenced(self):
        el = _make_el("CodeSnippet", "x = 1")
        result = _render_element(el)
        self.assertIn("```", result)
        self.assertIn("x = 1", result)

    def test_empty_code_snippet_returns_empty(self):
        el = _make_el("CodeSnippet", "")
        self.assertEqual(_render_element(el), "")


class TestFormulaRendering(unittest.TestCase):
    def test_formula_text_preserved(self):
        el = _make_el("Formula", "E = mc^2")
        self.assertEqual(_render_element(el), "E = mc^2")


class TestHeaderFooterRendering(unittest.TestCase):
    def test_header_text_preserved(self):
        el = _make_el("Header", "Chapter 1")
        self.assertEqual(_render_element(el), "Chapter 1")

    def test_footer_text_preserved(self):
        el = _make_el("Footer", "Page 1 of 10")
        self.assertEqual(_render_element(el), "Page 1 of 10")


class TestImageRendering(unittest.TestCase):
    def test_image_with_path_returns_placeholder(self):
        el = _make_el("Image", "", image_path="/tmp/img_001.png")
        result = _render_element(el)
        self.assertIn("<!-- image:", result)
        self.assertIn("img_001.png", result)

    def test_image_without_path_returns_empty(self):
        el = _make_el("Image", "", image_path=None)
        self.assertEqual(_render_element(el), "")


class TestTableHtmlRendering(unittest.TestCase):
    def test_simple_2x2_table(self):
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        md, mode = _render_table_html(html)
        self.assertEqual(mode, "markdown")
        self.assertIn("| A | B |", md)
        self.assertIn("| 1 | 2 |", md)

    def test_pipe_in_cell_escaped(self):
        html = "<table><tr><th>A|B</th></tr><tr><td>x</td></tr></table>"
        md, mode = _render_table_html(html)
        self.assertIn(r"\|", md)

    def test_empty_cells_preserved(self):
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td></td><td>2</td></tr></table>"
        md, mode = _render_table_html(html)
        self.assertEqual(mode, "markdown")
        self.assertIn("|  |", md)

    def test_rowspan_preserves_html(self):
        html = '<table><tr><th rowspan="2">A</th><th>B</th></tr><tr><td>1</td></tr></table>'
        md, mode = _render_table_html(html)
        self.assertEqual(mode, "html_preserved")
        self.assertIn("<table>", md)

    def test_colspan_preserves_html(self):
        html = '<table><tr><th colspan="2">A</th></tr><tr><td>1</td><td>2</td></tr></table>'
        md, mode = _render_table_html(html)
        self.assertEqual(mode, "html_preserved")

    def test_empty_table_preserves_html(self):
        html = "<table></table>"
        md, mode = _render_table_html(html)
        self.assertEqual(mode, "html_preserved")

    def test_unicode_content(self):
        html = "<table><tr><th>Ação</th></tr><tr><td>Preço</td></tr></table>"
        md, mode = _render_table_html(html)
        self.assertEqual(mode, "markdown")
        self.assertIn("Ação", md)
        self.assertIn("Preço", md)


class TestTableElementRendering(unittest.TestCase):
    def test_table_with_html_uses_renderer(self):
        html = "<table><tr><th>X</th></tr><tr><td>Y</td></tr></table>"
        el = _make_el("Table", "X Y", text_as_html=html)
        result = _render_element(el)
        self.assertIn("| X |", result)

    def test_table_without_html_falls_back_to_text(self):
        el = _make_el("Table", "fallback text", text_as_html=None)
        result = _render_element(el)
        self.assertEqual(result, "fallback text")
