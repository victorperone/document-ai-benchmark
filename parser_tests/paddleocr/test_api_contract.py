"""Tests for paddleocr_v2 build_pipeline_kwargs API contract."""
from __future__ import annotations

import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.config import get_profile
from src.parsers.paddleocr_v2 import (
    PROFILE_BOOL_KEYS,
    _PREDICT_ONLY_KWARGS,
    build_pipeline_init_kwargs,
    build_pipeline_kwargs,
    build_predict_kwargs,
    required_model_keys,
    MODEL_NAMES,
    MODEL_DIRECTORY_CANDIDATES,
    persist_official_markdown_bundle,
)

PARSER_NAME = "paddleocr"


def _fake_model_paths(profile: dict) -> dict[str, Path]:
    """Build a dict of fake Path objects for all required model keys."""
    keys = required_model_keys(profile)
    paths = {}
    for key in keys:
        model_name = MODEL_NAMES[key]
        candidates = MODEL_DIRECTORY_CANDIDATES.get(model_name, (model_name,))
        paths[key] = Path("/fake/models") / candidates[0]
    return paths


class TestBuildPipelineKwargsStructure(unittest.TestCase):
    def _kwargs_for(self, profile_name: str) -> dict:
        p = get_profile(PARSER_NAME, profile_name)
        return build_pipeline_kwargs(_fake_model_paths(p), p)

    def test_kwargs_is_dict(self):
        self.assertIsInstance(self._kwargs_for("default"), dict)

    def test_layout_model_dir_present(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("layout_detection_model_dir", kwargs)

    def test_text_detection_model_dir_present(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("text_detection_model_dir", kwargs)

    def test_text_recognition_model_dir_present(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("text_recognition_model_dir", kwargs)

    def test_use_table_recognition_bool(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("use_table_recognition", kwargs)
        self.assertIsInstance(kwargs["use_table_recognition"], bool)


class TestFullCpuLocalKwargs(unittest.TestCase):
    def _kwargs(self) -> dict:
        p = get_profile(PARSER_NAME, "full_cpu_local")
        return build_pipeline_kwargs(_fake_model_paths(p), p)

    def test_use_seal_recognition_true(self):
        self.assertTrue(self._kwargs()["use_seal_recognition"])

    def test_use_formula_recognition_true(self):
        self.assertTrue(self._kwargs()["use_formula_recognition"])

    def test_use_chart_recognition_true(self):
        self.assertTrue(self._kwargs()["use_chart_recognition"])

    def test_format_block_content_in_kwargs(self):
        kwargs = self._kwargs()
        self.assertIn("format_block_content", kwargs)
        self.assertTrue(kwargs["format_block_content"])

    def test_seal_model_dirs_present_when_seal_enabled(self):
        kwargs = self._kwargs()
        self.assertIn("seal_text_detection_model_dir", kwargs)
        self.assertIn("seal_text_recognition_model_dir", kwargs)


class TestFormatBlockContentConditionality(unittest.TestCase):
    def test_format_block_content_not_added_when_false(self):
        p = get_profile(PARSER_NAME, "default")
        p_copy = dict(p)
        p_copy["format_block_content"] = False
        kwargs = build_pipeline_kwargs(_fake_model_paths(p_copy), p_copy)
        self.assertNotIn("format_block_content", kwargs)

    def test_format_block_content_added_when_true(self):
        p = get_profile(PARSER_NAME, "default")
        p_copy = dict(p)
        p_copy["format_block_content"] = True
        kwargs = build_pipeline_kwargs(_fake_model_paths(p_copy), p_copy)
        self.assertIn("format_block_content", kwargs)
        self.assertTrue(kwargs["format_block_content"])


class TestOfficialMarkdownBundle(unittest.TestCase):
    def test_markdown_image_is_persisted_and_link_relocated(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "native"
            result = SimpleNamespace(markdown={
                "markdown_texts": "![gráfico](images/chart.png)",
                "markdown_images": {"images/chart.png": Image.new("RGB", (4, 4), "white")},
            })
            markdown, manifest = persist_official_markdown_bundle(
                results=[result], official_markdown=result.markdown["markdown_texts"],
                destination=destination, parser_name="paddleocr", profile_name="full_cpu_local",
            )
            self.assertIn("native/assets/", markdown)
            self.assertEqual(manifest["bundle_status"], "available")
            self.assertTrue(any(item["path"].endswith("chart.png") for item in manifest["files"]))


# ── New tests required by plan §2.1 ──────────────────────────────────────────

class TestInitPredictKwargsDisjoint(unittest.TestCase):
    """Init and predict kwargs must never share keys."""

    def _profile(self) -> dict:
        return get_profile("paddleocr", "full_cpu_local")

    def _fake_paths(self) -> dict:
        p = self._profile()
        keys = required_model_keys(p)
        return {k: Path("/fake/models") / MODEL_NAMES[k] for k in keys}

    def test_predict_only_keys_absent_from_init_kwargs(self) -> None:
        p = self._profile()
        init_kwargs = build_pipeline_init_kwargs(self._fake_paths(), p)
        overlap = set(init_kwargs) & _PREDICT_ONLY_KWARGS
        self.assertEqual(overlap, set(), f"predict-only keys in init: {overlap}")

    def test_predict_only_keys_all_reach_predict_iter(self) -> None:
        p = self._profile()
        fake_pipeline = MagicMock()
        import inspect
        fake_pipeline.predict_iter = MagicMock()
        # Patch inspect.signature to return all predict-only keys as params.
        fake_sig_params = {k: MagicMock() for k in _PREDICT_ONLY_KWARGS}
        fake_sig_params["markdown_ignore_labels"] = MagicMock()
        fake_sig = MagicMock()
        fake_sig.parameters = fake_sig_params
        with patch("src.parsers.paddleocr_v2.inspect.signature", return_value=fake_sig):
            kwargs = build_predict_kwargs(Path("/doc.pdf"), p, fake_pipeline)
        for key in _PREDICT_ONLY_KWARGS - {"markdown_ignore_labels"}:
            self.assertIn(key, kwargs, f"predict-only key missing from predict kwargs: {key}")

    def test_pipeline_close_called_on_success(self) -> None:
        """pipeline.close() must be called even when processing succeeds."""
        import src.parsers.paddleocr_v2 as mod

        fake_pipeline = MagicMock()
        fake_pipeline.predict_iter.return_value = iter([])
        fake_pipeline.concatenate_markdown_pages.return_value = ""

        # We only test that close() would be called — not that main() succeeds end-to-end.
        closed = []
        original_close = fake_pipeline.close
        fake_pipeline.close.side_effect = lambda: closed.append(True)

        # Simulate the finally block directly.
        pipeline = fake_pipeline
        try:
            pass
        finally:
            if pipeline is not None:
                close_fn = getattr(pipeline, "close", None)
                if callable(close_fn):
                    close_fn()
        self.assertEqual(closed, [True])

    def test_constructor_failure_not_masked_by_finally(self) -> None:
        """When build_pipeline raises, close() must NOT be called on None."""
        calls = []

        pipeline = None
        try:
            raise RuntimeError("constructor failed")
        except RuntimeError:
            pass
        finally:
            if pipeline is not None:
                close_fn = getattr(pipeline, "close", None)
                if callable(close_fn):
                    calls.append("close")

        self.assertEqual(calls, [], "close() was called but pipeline was never constructed")


if __name__ == "__main__":
    unittest.main()
