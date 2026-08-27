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


def _make_benchmark_sys_modules(
    partition_pdf_func=None,
    write_json_func=None,
    finalize_return=None,
):
    """Build a sys.modules dict that mocks benchmark internals and unstructured.

    main() does local `from src.benchmark.X import Y` — patching source-module
    attributes won't intercept those bindings. Injecting mock modules into
    sys.modules is the only reliable approach.

    src.benchmark.runtime_io is NOT mocked here because add_runtime_arguments
    is imported at module level and must be the real implementation so that
    --artifacts and --verbose CLI args are registered.  parser_output_context
    (the only runtime_io symbol used inside main()) is patched separately via
    patch() after reload.
    """
    if finalize_return is None:
        finalize_return = {
            "timing": {"normalization_seconds": 0.0},
            "empty_output_pages": [],
            "content_elements": {},
            "heuristics": {},
            "tokens": {},
            "normalization": {},
            "output": {"clean_markdown_bytes": 100},
        }

    mock_monitor = MagicMock()
    mock_monitor.stop.return_value = {}

    mock_resource_monitor_mod = MagicMock()
    mock_resource_monitor_mod.ResourceMonitor.return_value = mock_monitor

    mock_artifacts_mod = MagicMock()
    mock_artifacts_mod.finalize_artifacts.return_value = finalize_return

    mock_metrics_writer_mod = MagicMock()
    if write_json_func is not None:
        mock_metrics_writer_mod.write_json.side_effect = write_json_func

    mock_paths_mod = MagicMock()

    mock_pdf_mod = MagicMock()
    if partition_pdf_func is not None:
        mock_pdf_mod.partition_pdf = partition_pdf_func
    else:
        mock_pdf_mod.partition_pdf.return_value = []

    return {
        "src.benchmark.resource_monitor": mock_resource_monitor_mod,
        "src.benchmark.artifacts": mock_artifacts_mod,
        "src.benchmark.metrics_writer": mock_metrics_writer_mod,
        "src.benchmark.paths": mock_paths_mod,
        "unstructured": MagicMock(),
        "unstructured.partition": MagicMock(),
        "unstructured.partition.pdf": mock_pdf_mod,
    }, mock_metrics_writer_mod, mock_paths_mod


_BASE_PROFILE = {
    "strategy": "fast", "ocr_enabled": False,
    "infer_table_structure": False, "include_page_breaks": True,
    "languages": ["por"], "detect_language_per_element": False,
    "extract_image_block_to_payload": False, "extract_forms": False,
    "form_extraction_skip_tables": True, "password": None,
    "pdfminer_line_margin": None, "pdfminer_char_margin": None,
    "pdfminer_line_overlap": None, "pdfminer_word_margin": None,
    "remote_services_enabled": False, "network_allowed_during_run": False,
    "hi_res_model_name": None, "extract_image_block_types": [],
}


def _run_with_sys_modules(tmp_path, profile, sys_modules_extra, inventory):
    """Reload unstructured_v2 with mock sys.modules and call main()."""
    from src.parsers import unstructured_v2
    import importlib
    from contextlib import contextmanager

    args_list = [
        "--input", str(tmp_path / "test.pdf"),
        "--output-root", str(tmp_path / "outputs"),
        "--profile", "fast_native",
    ]

    with (
        patch("src.parsers.unstructured_v2.get_profile", return_value=profile),
        patch("sys.argv", ["unstructured_v2"] + args_list),
        patch("src.parsers.unstructured_v2.get_normalization_config", return_value={}),
        patch("src.parsers.unstructured_v2.get_reference_tokenizer", return_value="o200k_base"),
        patch.dict("sys.modules", sys_modules_extra),
    ):
        importlib.reload(unstructured_v2)
        # parser_output_context is a local import inside main(); patch it now
        # that the module has been reloaded and has the name in its namespace.
        with (
            patch("src.parsers.unstructured_v2._load_cached_inventory",
                  return_value=inventory),
            patch("src.benchmark.runtime_io.parser_output_context"),
        ):
            unstructured_v2.main()


class TestPdfMinerKwargs(unittest.TestCase):
    """Verify partition_pdf receives the exact pdfminer_* kwarg names from the profile."""

    def _kwargs_from_profile(self, profile_overrides: dict) -> dict:
        """Run main() and capture the kwargs passed to partition_pdf."""
        import tempfile, json, hashlib

        captured: dict = {}

        def _fake_partition_pdf(**kwargs):
            captured.update(kwargs)
            return []

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_input = tmp_path / "test.pdf"
            fake_input.write_bytes(b"%PDF-1.4 %%EOF")
            output_root = tmp_path / "outputs"
            output_root.mkdir()
            sha = hashlib.sha256(fake_input.read_bytes()).hexdigest()
            inventory = {"sha256": sha, "pages": 1, "file_size_mb": 0.1}
            (output_root / "_source_inventory").mkdir(parents=True)
            (output_root / "_source_inventory" / "test.json").write_text(
                json.dumps(inventory), encoding="utf-8"
            )

            profile = {**_BASE_PROFILE, **profile_overrides}
            sys_mods, _, mock_paths_mod = _make_benchmark_sys_modules(
                partition_pdf_func=_fake_partition_pdf
            )
            paths_inst = MagicMock()
            paths_inst.output_dir = tmp_path / "out"
            paths_inst.run_log = tmp_path / "run.log"
            paths_inst.metrics_json = tmp_path / "metrics.json"
            mock_paths_mod.build_output_paths.return_value = paths_inst

            _run_with_sys_modules(tmp_path, profile, sys_mods, inventory)

        return captured

    def test_word_margin_uses_pdfminer_kwarg_name(self):
        kwargs = self._kwargs_from_profile({"pdfminer_word_margin": 0.185})
        self.assertIn("pdfminer_word_margin", kwargs,
                      "pdfminer_word_margin must be passed as pdfminer_word_margin to partition_pdf")
        self.assertNotIn("word_margin", kwargs,
                         "word_margin (old name) must NOT be passed to partition_pdf")

    def test_line_margin_passed_when_set(self):
        kwargs = self._kwargs_from_profile({"pdfminer_line_margin": 0.5})
        self.assertIn("pdfminer_line_margin", kwargs)
        self.assertAlmostEqual(kwargs["pdfminer_line_margin"], 0.5)

    def test_char_margin_passed_when_set(self):
        kwargs = self._kwargs_from_profile({"pdfminer_char_margin": 2.0})
        self.assertIn("pdfminer_char_margin", kwargs)

    def test_line_overlap_passed_when_set(self):
        kwargs = self._kwargs_from_profile({"pdfminer_line_overlap": 0.3})
        self.assertIn("pdfminer_line_overlap", kwargs)

    def test_null_pdfminer_kwargs_not_passed(self):
        kwargs = self._kwargs_from_profile({
            "pdfminer_line_margin": None,
            "pdfminer_char_margin": None,
            "pdfminer_line_overlap": None,
            "pdfminer_word_margin": None,
        })
        for k in ("pdfminer_line_margin", "pdfminer_char_margin",
                  "pdfminer_line_overlap", "pdfminer_word_margin"):
            self.assertNotIn(k, kwargs, f"{k} should not be passed when None")


class TestFailedPagesIsInt(unittest.TestCase):
    """processing.failed_pages must be an integer (not a list)."""

    def test_failed_pages_int_in_metrics(self):
        import tempfile, json, hashlib

        captured_metrics: list[dict] = []

        def _fake_write_json(path, data):
            captured_metrics.append(data)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_input = tmp_path / "test.pdf"
            fake_input.write_bytes(b"%PDF-1.4 %%EOF")
            output_root = tmp_path / "outputs"
            output_root.mkdir()
            sha = hashlib.sha256(fake_input.read_bytes()).hexdigest()
            inventory = {"sha256": sha, "pages": 1, "file_size_mb": 0.1}
            (output_root / "_source_inventory").mkdir(parents=True)
            (output_root / "_source_inventory" / "test.json").write_text(
                json.dumps(inventory), encoding="utf-8"
            )

            sys_mods, mock_metrics_writer_mod, mock_paths_mod = _make_benchmark_sys_modules(
                write_json_func=_fake_write_json
            )
            paths_inst = MagicMock()
            paths_inst.output_dir = tmp_path / "out"
            paths_inst.run_log = tmp_path / "run.log"
            paths_inst.metrics_json = tmp_path / "metrics.json"
            mock_paths_mod.build_output_paths.return_value = paths_inst

            _run_with_sys_modules(tmp_path, dict(_BASE_PROFILE), sys_mods, inventory)

        self.assertTrue(len(captured_metrics) > 0, "write_json was not called")
        metrics = captured_metrics[0]
        fp = metrics["processing"]["failed_pages"]
        self.assertIsInstance(fp, int, f"failed_pages must be int, got {type(fp).__name__}: {fp!r}")
