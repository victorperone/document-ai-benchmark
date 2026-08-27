"""Tests for xberg_v2 adapter contract with mocked extract (section 36.8)."""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_page(text: str = "Mock page content", page_num: int = 1):
    page = MagicMock()
    page.content = text
    page.page_number = page_num
    page.tables = []
    return page


def _make_mock_result(pages=None):
    result = MagicMock()
    result.errors = []
    result.warnings = []
    doc = MagicMock()
    doc.pages = pages or [_make_mock_page()]
    result.documents = [doc]
    return result


def _make_inventory(pages: int = 1) -> dict:
    return {
        "sha256": "aabbcc",
        "pages": pages,
        "file_size_mb": 0.1,
        "has_text_layer": True,
    }


class TestAdapterContract(unittest.TestCase):
    def _run_main(self, tmp_path: Path, profile: str = "native_markdown"):
        from src.parsers import xberg_v2

        fake_input = tmp_path / "test.pdf"
        fake_input.write_bytes(b"%PDF-1.4 %%EOF")
        output_root = tmp_path / "outputs"
        output_root.mkdir()

        inventory = _make_inventory(pages=1)
        inv_dir = output_root / "_source_inventory"
        inv_dir.mkdir(parents=True)
        import hashlib
        sha = hashlib.sha256(fake_input.read_bytes()).hexdigest()
        inventory["sha256"] = sha
        (inv_dir / "test.json").write_text(json.dumps(inventory), encoding="utf-8")

        mock_result = _make_mock_result()

        args_list = [
            "--input", str(fake_input),
            "--output-root", str(output_root),
            "--profile", profile,
        ]

        mock_xberg = MagicMock()
        mock_xberg.extract = AsyncMock(return_value=mock_result)
        mock_xberg.ExtractionConfig = MagicMock(return_value=MagicMock())
        mock_xberg.OcrConfig = MagicMock(return_value=MagicMock())
        mock_xberg.TesseractConfig = MagicMock(return_value=MagicMock())
        mock_xberg.__version__ = "1.0.14"

        with (
            patch("sys.argv", ["xberg_v2"] + args_list),
            patch("src.parsers.xberg_v2.get_profile", return_value={
                "strategy": "fast",
                "ocr_enabled": False,
                "ocr_backend": None,
                "ocr_languages": [],
                "ocr_strategy": "disabled",
                "force_ocr": False,
                "auto_rotate": False,
                "target_dpi": 150,
                "deskew": False,
                "denoise": False,
                "contrast_enhance": False,
                "extract_tables": True,
                "extract_images": False,
                "extract_pages": True,
                "insert_page_markers": False,
                "include_headers": True,
                "include_footers": True,
                "strip_repeating_text": False,
                "chunking_enabled": False,
                "token_reduction_mode": "off",
                "layout_enabled": False,
                "use_cache": False,
                "enable_quality_processing": False,
                "reading_order": False,
                "remote_services_enabled": False,
                "network_allowed_during_run": False,
                "output_format": "markdown",
                "result_format": "unified",
                "escape_markdown": True,
                "table_anchors": False,
                "include_document_structure": False,
                "extract_metadata": True,
                "extract_annotations": False,
                "extract_form_fields": True,
                "include_watermarks": True,
            }),
            patch("src.parsers.xberg_v2.get_normalization_config", return_value={}),
            patch("src.parsers.xberg_v2.get_reference_tokenizer", return_value="o200k_base"),
            patch("src.parsers.xberg_v2.ResourceMonitor") as MockMonitor,
            patch("src.parsers.xberg_v2.finalize_artifacts") as mock_finalize,
            patch("src.parsers.xberg_v2.write_json") as mock_write,
            patch("src.parsers.xberg_v2.build_output_paths") as mock_paths,
            patch("src.parsers.xberg_v2.parser_output_context"),
            patch("src.parsers.xberg_v2._load_cached_inventory", return_value=inventory),
            patch.dict("sys.modules", {"xberg": mock_xberg}),
        ):
            mock_monitor_instance = MockMonitor.return_value
            mock_monitor_instance.stop.return_value = {"cpu_percent": 0.0}

            mock_paths_instance = MagicMock()
            mock_paths_instance.output_dir = tmp_path / "out"
            mock_paths_instance.run_log = tmp_path / "run.log"
            mock_paths_instance.metrics_json = tmp_path / "metrics.json"
            mock_paths.return_value = mock_paths_instance

            mock_finalize.return_value = {
                "timing": {"normalization_seconds": 0.0},
                "empty_output_pages": [],
                "content_elements": {},
                "heuristics": {},
                "tokens": {},
                "normalization": {},
                "output": {"clean_markdown_bytes": 100},
            }

            import importlib
            importlib.reload(xberg_v2)
            xberg_v2.main()

        return mock_monitor_instance, mock_finalize, mock_write, MockMonitor

    def test_finalize_artifacts_called(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _, mock_finalize, _, _ = self._run_main(Path(tmp))
            mock_finalize.assert_called_once()

    def test_monitor_started_and_stopped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mock_mon, _, _, MockMonitor = self._run_main(Path(tmp))
            MockMonitor.return_value.start.assert_called_once()
            mock_mon.stop.assert_called()

    def test_write_json_called_for_metrics(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _, _, mock_write, _ = self._run_main(Path(tmp))
            mock_write.assert_called()
