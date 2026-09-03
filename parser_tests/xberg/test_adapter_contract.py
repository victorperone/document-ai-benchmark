"""Tests for xberg_v2 adapter contract with mocked extract (section 36.8)."""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_page(text: str = "Mock page content", page_num: int = 1):
    page = MagicMock()
    page.content = text
    page.page_number = page_num
    page.tables = []
    return page


def _make_mock_envelope(pages=None):
    """Return a mock ExtractionResult envelope compatible with _unwrap_extraction_result."""
    document = MagicMock()
    document.content = "text"
    document.pages = pages or [_make_mock_page()]
    document.tables = []
    document.processing_warnings = []

    summary = SimpleNamespace(inputs=1, results=1, errors=0)

    envelope = MagicMock()
    envelope.results = [document]
    envelope.errors = []
    envelope.summary = summary
    return envelope


def _make_inventory(pages: int = 1) -> dict:
    return {
        "sha256": "aabbcc",
        "pages": pages,
        "file_size_mb": 0.1,
        "has_text_layer": True,
    }


class TestAdapterContract(unittest.TestCase):
    def _run_main(self, tmp_path: Path, profile: str = "native_markdown"):
        import hashlib
        import importlib
        import sys
        from src.parsers import xberg_v2

        fake_input = tmp_path / "test.pdf"
        fake_input.write_bytes(b"%PDF-1.4 %%EOF")
        output_root = tmp_path / "outputs"
        output_root.mkdir()

        inventory = _make_inventory(pages=1)
        inv_dir = output_root / "_source_inventory"
        inv_dir.mkdir(parents=True)
        sha = hashlib.sha256(fake_input.read_bytes()).hexdigest()
        inventory["sha256"] = sha
        (inv_dir / "test.json").write_text(json.dumps(inventory), encoding="utf-8")

        mock_envelope = _make_mock_envelope()

        args_list = [
            "--input", str(fake_input),
            "--output-root", str(output_root),
            "--profile", profile,
            "--artifacts", "all",
        ]

        mock_xberg = MagicMock()
        mock_xberg.extract = AsyncMock(return_value=mock_envelope)
        # _build_xberg_config now returns a dict — xberg classes are used as
        # dataclass constructors inside the function.
        for cls_name in (
            "OcrConfig", "TesseractConfig", "ImagePreprocessingConfig",
            "PdfConfig", "PageConfig", "ImageExtractionConfig", "ContentFilterConfig",
        ):
            mock_cls = MagicMock()
            mock_cls.return_value = MagicMock()
            setattr(mock_xberg, cls_name, mock_cls)
        mock_xberg.__version__ = "1.0.14"

        # main() imports benchmark helpers lazily inside the function body.
        # We need to pre-import those modules so patch() can find their attributes.
        # tiktoken may not be installed in WSL — mock it first so the imports succeed.
        sys_extras: dict = {"xberg": mock_xberg}
        if "tiktoken" not in sys.modules:
            sys_extras["tiktoken"] = MagicMock()

        # Use a nested context: outer ensures tiktoken mock is active during pre-imports;
        # inner applies all functional patches.
        with patch.dict("sys.modules", sys_extras):
            import src.benchmark.artifacts  # noqa: F401
            import src.benchmark.metrics_writer  # noqa: F401
            import src.benchmark.paths  # noqa: F401
            import src.benchmark.resource_monitor  # noqa: F401
            import src.benchmark.runtime_io  # noqa: F401

            with (
                patch("sys.argv", ["xberg_v2"] + args_list),
                patch("src.parsers.xberg_v2.get_profile", return_value={
                    "output_format": "markdown",
                    "result_format": "unified",
                    "escape_markdown": True,
                    "table_anchors": False,
                    "include_document_structure": False,
                    "use_cache": False,
                    "enable_quality_processing": False,
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
                    "include_watermarks": True,
                    "chunking_enabled": False,
                    "token_reduction_mode": "off",
                    "layout_enabled": False,
                    "reading_order": False,
                    "remote_services_enabled": False,
                    "network_allowed_during_run": False,
                    "extract_metadata": True,
                    "extract_annotations": False,
                    "extract_form_fields": True,
                }),
                patch("src.parsers.xberg_v2.get_normalization_config", return_value={}),
                patch("src.parsers.xberg_v2.get_reference_tokenizer", return_value="o200k_base"),
                patch("src.benchmark.resource_monitor.ResourceMonitor") as MockMonitor,
                patch("src.benchmark.artifacts.finalize_artifacts") as mock_finalize,
                patch("src.benchmark.metrics_writer.write_json") as mock_write,
                patch("src.benchmark.paths.build_output_paths") as mock_paths,
                patch("src.benchmark.runtime_io.parser_output_context"),
                patch("src.parsers.xberg_v2._load_cached_inventory", return_value=inventory),
                patch("src.parsers.xberg_v2._find_tessdata_prefix", return_value=None),
            ):
                mock_monitor_instance = MockMonitor.return_value
                mock_monitor_instance.stop.return_value = {"cpu_percent": 0.0}

                mock_paths_instance = MagicMock()
                mock_paths_instance.output_dir = tmp_path / "out"
                mock_paths_instance.run_log = tmp_path / "run.log"
                mock_paths_instance.metrics_json = tmp_path / "metrics.json"
                mock_paths_instance.native_dir = tmp_path / "native"
                mock_paths.return_value = mock_paths_instance

                mock_finalize.return_value = {
                    "timing": {"normalization_seconds": 0.0},
                    "empty_output_pages": [],
                    "content_elements": {},
                    "heuristics": {},
                    "tokens": {},
                    "normalization": {},
                    "artifacts": {},
                    "quality_eligibility": {},
                    "content_validation": {},
                    "output": {"clean_markdown_bytes": 100},
                }

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


class TestXbergExtractInput(unittest.TestCase):
    def test_local_pdf_uses_uri_contract(self) -> None:
        fake_result = object()
        fake_extract = AsyncMock(return_value=fake_result)

        fake_ExtractInput = MagicMock()
        mock_xberg = MagicMock()
        mock_xberg.extract = fake_extract
        mock_xberg.ExtractInput = fake_ExtractInput

        with patch.dict("sys.modules", {"xberg": mock_xberg}):
            from src.parsers.xberg_v2 import _extract
            result = asyncio.run(
                _extract(Path("/benchmark/document.pdf"), {})
            )

        self.assertIs(result, fake_result)

        call_kwargs = fake_ExtractInput.call_args.kwargs
        self.assertEqual(call_kwargs.get("kind"), "uri")
        self.assertEqual(call_kwargs.get("uri"), "/benchmark/document.pdf")
        self.assertEqual(call_kwargs.get("mime_type"), "application/pdf")
        self.assertEqual(call_kwargs.get("filename"), "document.pdf")


if __name__ == "__main__":
    unittest.main()
