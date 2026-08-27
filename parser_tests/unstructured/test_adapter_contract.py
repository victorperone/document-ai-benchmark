"""Tests for unstructured_v2 adapter contract with mocked partition_pdf (section 22.6)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PARSER_NAME = "unstructured"


def _make_mock_element(category: str = "NarrativeText", text: str = "hello", page: int = 1):
    el = MagicMock()
    type(el).__name__ = category
    el.text = text
    el.id = "el-001"
    meta = MagicMock()
    meta.page_number = page
    meta.text_as_html = None
    meta.parent_id = None
    meta.category_depth = None
    meta.detection_class_prob = None
    meta.detection_origin = None
    meta.languages = None
    meta.coordinates = None
    meta.links = None
    meta.image_path = None
    el.metadata = meta
    return el


def _make_inventory(pages: int = 2) -> dict:
    return {
        "sha256": "aabbcc",
        "pages": pages,
        "file_size_mb": 0.1,
        "has_text_layer": True,
    }


class TestAdapterContract(unittest.TestCase):
    def _run_main(self, tmp_path: Path, profile: str = "fast_native", extra_args=None):
        from src.parsers import unstructured_v2

        fake_input = tmp_path / "test.pdf"
        fake_input.write_bytes(b"%PDF-1.4 %%EOF")
        output_root = tmp_path / "outputs"
        output_root.mkdir()

        inventory = _make_inventory(pages=1)
        (output_root / "_source_inventory").mkdir(parents=True)
        import json, hashlib
        sha = hashlib.sha256(fake_input.read_bytes()).hexdigest()
        inventory["sha256"] = sha
        (output_root / "_source_inventory" / "test.json").write_text(
            json.dumps(inventory), encoding="utf-8"
        )

        args_list = [
            "--input", str(fake_input),
            "--output-root", str(output_root),
            "--profile", profile,
        ]
        if extra_args:
            args_list.extend(extra_args)

        mock_el = _make_mock_element()

        with (
            patch("src.parsers.unstructured_v2.get_profile", return_value={
                "strategy": "fast", "ocr_enabled": False,
                "infer_table_structure": False, "include_page_breaks": True,
                "languages": ["por", "eng"], "detect_language_per_element": False,
                "extract_image_block_to_payload": False, "extract_forms": False,
                "form_extraction_skip_tables": True, "password": None,
                "pdfminer_word_margin": None, "remote_services_enabled": False,
                "network_allowed_during_run": False, "hi_res_model_name": None,
                "extract_image_block_types": [],
            }),
            patch("sys.argv", ["unstructured_v2"] + args_list),
            patch("src.parsers.unstructured_v2.get_normalization_config", return_value={}),
            patch("src.parsers.unstructured_v2.get_reference_tokenizer", return_value="o200k_base"),
            patch("src.parsers.unstructured_v2.ResourceMonitor") as MockMonitor,
            patch("src.parsers.unstructured_v2.finalize_artifacts") as mock_finalize,
            patch("src.parsers.unstructured_v2.write_json") as mock_write,
            patch("src.parsers.unstructured_v2.build_output_paths") as mock_paths,
            patch("src.parsers.unstructured_v2.parser_output_context"),
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

            # Patch partition_pdf inside the module at import time
            with patch.dict("sys.modules", {
                "unstructured": MagicMock(),
                "unstructured.partition": MagicMock(),
                "unstructured.partition.pdf": MagicMock(partition_pdf=MagicMock(return_value=[mock_el])),
            }):
                import importlib
                importlib.reload(unstructured_v2)
                with patch("src.parsers.unstructured_v2._load_cached_inventory",
                           return_value=inventory):
                    unstructured_v2.main()

            return mock_monitor_instance, mock_finalize, mock_write, MockMonitor

    def test_finalize_artifacts_called_once(self):
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
