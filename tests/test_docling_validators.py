"""
Unit tests for Docling artifact validators and capability gating.

All tests use temporary directories and mocks — no real models, no network.
Groups:
  1. _validate_granite_chart_v4_artifacts
  2. New validators (SmolVLM, CodeFormula, classifier, TableFormer, RapidOCR, layout)
  3. Capability gating in _build_pipeline_options
  4. Runtime environment isolation
  5. Downloader selection (download_models call)
  6. ValidateOnly flow
  7. Manifest validation
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub optional runtime dependencies that are absent in the WSL test env.
# The validators under test only use stdlib (pathlib, json) so these stubs
# are safe.  _build_pipeline_options gating tests patch the relevant symbols
# themselves; Group 4 (runtime_specs) is skipped if the registration is absent.
# ---------------------------------------------------------------------------
def _make_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _stub_if_missing(name: str, **attrs) -> None:
    if name not in sys.modules:
        sys.modules[name] = _make_module(name, **attrs)


_stub_if_missing("torch")
_stub_if_missing("tiktoken")
_stub_if_missing("docling")
_stub_if_missing("docling.datamodel")
_stub_if_missing("docling.datamodel.accelerator_options",
                 AcceleratorDevice=MagicMock(), AcceleratorOptions=MagicMock())
_stub_if_missing("docling.datamodel.base_models",
                 InputFormat=MagicMock())
_stub_if_missing("docling.datamodel.pipeline_options",
                 OcrMode=MagicMock(),
                 PdfPipelineOptions=MagicMock(),
                 RapidOcrOptions=MagicMock(),
                 TableFormerMode=MagicMock(),
                 TableStructureOptions=MagicMock(),
                 PictureDescriptionVlmOptions=MagicMock(),
                 smolvlm_picture_description=MagicMock(),
                 DocumentPictureClassifierOptions=MagicMock(),
                 CodeEnricherOptions=MagicMock(),
                 FormulaEnricherOptions=MagicMock(),
                 granite_picture_description=MagicMock())
_stub_if_missing("docling.datamodel.settings", settings=MagicMock())
_stub_if_missing("docling.document_converter",
                 DocumentConverter=MagicMock(),
                 PdfFormatOption=MagicMock())
_stub_if_missing("docling.utils")
_stub_if_missing("docling.utils.model_downloader",
                 download_models=MagicMock())

# Also stub transformers which docling_v2 may pull in indirectly
_stub_if_missing("transformers")

from src.parsers.docling_v2 import (
    CODE_FORMULA_ARTIFACT_DIRECTORY,
    GRANITE_CHART_V4_ARTIFACT_DIRECTORY,
    LAYOUT_ARTIFACT_DIRECTORY,
    PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY,
    RAPIDOCR_ARTIFACT_DIRECTORY,
    SMOLVLM_ARTIFACT_DIRECTORY,
    TABLEFORMER_ARTIFACT_DIRECTORY,
    _validate_code_formula_artifacts,
    _validate_granite_chart_v4_artifacts,
    _validate_layout_artifacts,
    _validate_picture_classifier_artifacts,
    _validate_rapidocr_artifacts,
    _validate_smolvlm_artifacts,
    _validate_tableformer_artifacts,
)
from src.benchmark.config import BenchmarkConfigurationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_index_json(model_dir: Path, shards: list[str]) -> None:
    """Write a minimal model.safetensors.index.json with the given shard names."""
    weight_map = {f"layer.{i}.weight": s for i, s in enumerate(shards)}
    (model_dir / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {}, "weight_map": weight_map}),
        encoding="utf-8",
    )


def _touch(path: Path, size: int = 1024) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _make_full_smolvlm(model_dir: Path) -> None:
    _touch(model_dir / "config.json")
    _touch(model_dir / "preprocessor_config.json")
    _touch(model_dir / "model.safetensors")


def _make_full_code_formula(model_dir: Path) -> None:
    _touch(model_dir / "config.json")
    _touch(model_dir / "model.safetensors")


def _make_full_classifier(model_dir: Path) -> None:
    _touch(model_dir / "config.json")
    _touch(model_dir / "model.safetensors")


def _make_full_tableformer(artifacts_path: Path, mode: str = "accurate") -> None:
    mode_dir = (
        artifacts_path
        / TABLEFORMER_ARTIFACT_DIRECTORY
        / "model_artifacts"
        / "tableformer"
        / mode
    )
    mode_dir.mkdir(parents=True, exist_ok=True)
    _touch(mode_dir / "tm_config.json", 512)
    _touch(mode_dir / f"tableformer_{mode}.safetensors")


def _make_full_rapidocr(model_dir: Path) -> None:
    _touch(model_dir / "PP-OCRv6_det_small.pth")
    _touch(model_dir / "PP-OCRv6_rec_small.pth")
    _touch(model_dir / "ch_ptocr_mobile_v2.0_cls_mobile.pth")
    _touch(model_dir / "ppocrv6_dict.txt")


def _make_full_layout(model_dir: Path) -> None:
    _touch(model_dir / "config.json")
    _touch(model_dir / "preprocessor_config.json")
    _touch(model_dir / "model.safetensors")


def _make_full_granite(model_dir: Path) -> None:
    """Create a minimal but structurally valid Granite sharded model."""
    _touch(model_dir / "config.json")
    _touch(model_dir / "preprocessor_config.json")
    shards = [
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    ]
    _make_index_json(model_dir, shards)
    for s in shards:
        _touch(model_dir / s)


def _make_full_artifacts(base: Path) -> None:
    """Create all model directories under base with minimal valid content."""
    _make_full_layout(base / LAYOUT_ARTIFACT_DIRECTORY)
    _make_full_tableformer(base, "accurate")
    _make_full_rapidocr(base / RAPIDOCR_ARTIFACT_DIRECTORY)
    _make_full_smolvlm(base / SMOLVLM_ARTIFACT_DIRECTORY)
    _make_full_classifier(base / PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY)
    _make_full_code_formula(base / CODE_FORMULA_ARTIFACT_DIRECTORY)
    _make_full_granite(base / GRANITE_CHART_V4_ARTIFACT_DIRECTORY)


# ---------------------------------------------------------------------------
# Group 1: _validate_granite_chart_v4_artifacts
# ---------------------------------------------------------------------------

class TestGraniteValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.model_dir = self.base / GRANITE_CHART_V4_ARTIFACT_DIRECTORY

    def tearDown(self):
        self._tmp.cleanup()

    def _full_model(self) -> None:
        _make_full_granite(self.model_dir)

    def test_missing_directory(self):
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_missing_config_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "preprocessor_config.json")
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("config.json", detail)

    def test_missing_preprocessor_config(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("preprocessor_config.json", detail)

    def test_missing_index_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("model.safetensors.index.json", detail)

    def test_invalid_index_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        (self.model_dir / "model.safetensors.index.json").write_text(
            "not valid json", encoding="utf-8"
        )
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("invalid", detail.lower())

    def test_missing_weight_map(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        (self.model_dir / "model.safetensors.index.json").write_text(
            json.dumps({"metadata": {}}), encoding="utf-8"
        )
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("weight_map", detail)

    def test_empty_weight_map(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        _make_index_json(self.model_dir, [])
        (self.model_dir / "model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {}}), encoding="utf-8"
        )
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("weight_map", detail)

    def test_missing_shard(self):
        self._full_model()
        (self.model_dir / "model-00001-of-00002.safetensors").unlink()
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("model-00001-of-00002.safetensors", detail)

    def test_zero_byte_shard(self):
        self._full_model()
        (self.model_dir / "model-00001-of-00002.safetensors").write_bytes(b"")
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("empty", detail.lower())

    def test_all_present_returns_pass(self):
        self._full_model()
        ok, detail = _validate_granite_chart_v4_artifacts(self.base)
        self.assertTrue(ok)
        self.assertIn("shard", detail)


# ---------------------------------------------------------------------------
# Group 2: New validators
# ---------------------------------------------------------------------------

class TestSmolVLMValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.model_dir = self.base / SMOLVLM_ARTIFACT_DIRECTORY

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_directory(self):
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_missing_config_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "preprocessor_config.json")
        _touch(self.model_dir / "model.safetensors")
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("config.json", detail)

    def test_missing_preprocessor_config(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "model.safetensors")
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("preprocessor_config.json", detail)

    def test_missing_weights(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("no model weights found", detail)

    def test_single_safetensors_pass(self):
        _make_full_smolvlm(self.model_dir)
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertTrue(ok)

    def test_sharded_pass(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        _make_index_json(
            self.model_dir,
            ["model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"],
        )
        _touch(self.model_dir / "model-00001-of-00002.safetensors")
        _touch(self.model_dir / "model-00002-of-00002.safetensors")
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertTrue(ok)

    def test_sharded_missing_shard_fails(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        _touch(self.model_dir / "preprocessor_config.json")
        _make_index_json(
            self.model_dir,
            ["model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"],
        )
        _touch(self.model_dir / "model-00002-of-00002.safetensors")
        ok, detail = _validate_smolvlm_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("model-00001-of-00002.safetensors", detail)


class TestCodeFormulaValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.model_dir = self.base / CODE_FORMULA_ARTIFACT_DIRECTORY

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_directory(self):
        ok, detail = _validate_code_formula_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_missing_config_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "model.safetensors")
        ok, detail = _validate_code_formula_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("config.json", detail)

    def test_missing_weights(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "config.json")
        ok, detail = _validate_code_formula_artifacts(self.base)
        self.assertFalse(ok)

    def test_pass(self):
        _make_full_code_formula(self.model_dir)
        ok, _ = _validate_code_formula_artifacts(self.base)
        self.assertTrue(ok)


class TestPictureClassifierValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.model_dir = self.base / PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_directory(self):
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_missing_config_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "model.safetensors")
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("config.json", detail)

    def test_pass(self):
        _make_full_classifier(self.model_dir)
        ok, _ = _validate_picture_classifier_artifacts(self.base)
        self.assertTrue(ok)


class TestTableFormerValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_repo_directory(self):
        ok, detail = _validate_tableformer_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing repository directory", detail)

    def test_missing_mode_directory(self):
        (self.base / TABLEFORMER_ARTIFACT_DIRECTORY).mkdir(parents=True)
        ok, detail = _validate_tableformer_artifacts(self.base, mode="accurate")
        self.assertFalse(ok)
        self.assertIn("accurate", detail)

    def test_missing_tm_config(self):
        mode_dir = (
            self.base
            / TABLEFORMER_ARTIFACT_DIRECTORY
            / "model_artifacts"
            / "tableformer"
            / "accurate"
        )
        mode_dir.mkdir(parents=True)
        _touch(mode_dir / "tableformer_accurate.safetensors")
        ok, detail = _validate_tableformer_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("tm_config.json", detail)

    def test_missing_safetensors(self):
        mode_dir = (
            self.base
            / TABLEFORMER_ARTIFACT_DIRECTORY
            / "model_artifacts"
            / "tableformer"
            / "accurate"
        )
        mode_dir.mkdir(parents=True)
        _touch(mode_dir / "tm_config.json", 512)
        ok, detail = _validate_tableformer_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("safetensors", detail.lower())

    def test_zero_byte_weights(self):
        _make_full_tableformer(self.base, "accurate")
        weight = (
            self.base
            / TABLEFORMER_ARTIFACT_DIRECTORY
            / "model_artifacts"
            / "tableformer"
            / "accurate"
            / "tableformer_accurate.safetensors"
        )
        weight.write_bytes(b"")
        ok, detail = _validate_tableformer_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("empty", detail.lower())

    def test_pass_accurate(self):
        _make_full_tableformer(self.base, "accurate")
        ok, _ = _validate_tableformer_artifacts(self.base, mode="accurate")
        self.assertTrue(ok)

    def test_pass_fast(self):
        _make_full_tableformer(self.base, "fast")
        ok, _ = _validate_tableformer_artifacts(self.base, mode="fast")
        self.assertTrue(ok)


class TestRapidOCRValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.model_dir = self.base / RAPIDOCR_ARTIFACT_DIRECTORY

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_directory(self):
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_no_pth_files(self):
        self.model_dir.mkdir(parents=True)
        (self.model_dir / "ppocrv6_dict.txt").write_text("dict", encoding="utf-8")
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn(".pth", detail)

    def test_missing_detection_model(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "PP-OCRv6_rec_small.pth")
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("detection", detail.lower())

    def test_missing_recognition_model(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "PP-OCRv6_det_small.pth")
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("recognition", detail.lower())

    def test_zero_byte_pth(self):
        _make_full_rapidocr(self.model_dir)
        (self.model_dir / "PP-OCRv6_det_small.pth").write_bytes(b"")
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("empty", detail.lower())

    def test_pass(self):
        _make_full_rapidocr(self.model_dir)
        ok, _ = _validate_rapidocr_artifacts(self.base)
        self.assertTrue(ok)


class TestLayoutValidator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.model_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_directory(self):
        ok, detail = _validate_layout_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_missing_config_json(self):
        self.model_dir.mkdir(parents=True)
        _touch(self.model_dir / "preprocessor_config.json")
        _touch(self.model_dir / "model.safetensors")
        ok, detail = _validate_layout_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("config.json", detail)

    def test_pass(self):
        _make_full_layout(self.model_dir)
        ok, _ = _validate_layout_artifacts(self.base)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Group 3: Capability gating in _build_pipeline_options
# ---------------------------------------------------------------------------

class TestCapabilityGating(unittest.TestCase):
    """Verify that validators are called (and raise) according to profile flags."""

    def _make_minimal_profile(self, **overrides) -> dict:
        base = {
            "model_artifacts_path": "",  # set per test
            "accelerator_device": "cpu",
            "threads": 2,
            "threads_configured": 2,
            "available_logical_cpus": 2,
            "parallelism_source": "os.cpu_count",
            "ocr_enabled": False,
            "ocr_mode": "disabled",
            "table_structure": False,
            "picture_description": False,
            "picture_classification": False,
            "chart_extraction": False,
            "formula_enrichment": False,
            "code_enrichment": False,
            "generate_picture_images": False,
            "images_scale": 1.0,
            "remote_services_enabled": False,
            "table_mode": "accurate",
            "table_cell_matching": True,
        }
        base.update(overrides)
        return base

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_build(self, profile: dict):
        from src.parsers.docling_v2 import _build_pipeline_options
        _build_pipeline_options(profile)

    def test_chart_off_granite_not_required(self):
        _make_full_artifacts(self.base)
        # Remove Granite — chart_extraction=False so it should not fail
        import shutil
        shutil.rmtree(self.base / GRANITE_CHART_V4_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            chart_extraction=False,
        )
        # Should NOT raise even without Granite
        try:
            self._run_build(profile)
        except BenchmarkConfigurationError as exc:
            self.fail(f"Should not raise when chart_extraction=False: {exc}")
        except Exception:
            pass  # pipeline option errors from missing imports are expected in WSL

    def test_chart_on_granite_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / GRANITE_CHART_V4_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            chart_extraction=True,
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("Granite", str(ctx.exception))

    def test_picture_description_off_smolvlm_not_required(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / SMOLVLM_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            picture_description=False,
        )
        try:
            self._run_build(profile)
        except BenchmarkConfigurationError as exc:
            self.fail(f"Should not raise when picture_description=False: {exc}")
        except Exception:
            pass

    def test_picture_description_on_smolvlm_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / SMOLVLM_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            picture_description=True,
            picture_description_preset="smolvlm",
            picture_description_prompt="Describe this image.",
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("SmolVLM", str(ctx.exception))

    def test_picture_classification_off_classifier_not_required(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            picture_classification=False,
        )
        try:
            self._run_build(profile)
        except BenchmarkConfigurationError as exc:
            self.fail(f"Should not raise when picture_classification=False: {exc}")
        except Exception:
            pass

    def test_picture_classification_on_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            picture_classification=True,
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("classifier", str(ctx.exception).lower())

    def test_formula_off_code_formula_not_required(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / CODE_FORMULA_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            formula_enrichment=False,
            code_enrichment=False,
        )
        try:
            self._run_build(profile)
        except BenchmarkConfigurationError as exc:
            self.fail(f"Should not raise when formula/code off: {exc}")
        except Exception:
            pass

    def test_formula_on_code_formula_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / CODE_FORMULA_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            formula_enrichment=True,
            code_enrichment=False,
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("CodeFormula", str(ctx.exception))

    def test_code_enrichment_on_code_formula_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / CODE_FORMULA_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            formula_enrichment=False,
            code_enrichment=True,
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("CodeFormula", str(ctx.exception))

    def test_ocr_off_rapidocr_not_required(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / RAPIDOCR_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            ocr_enabled=False,
        )
        try:
            self._run_build(profile)
        except BenchmarkConfigurationError as exc:
            self.fail(f"Should not raise when ocr_enabled=False: {exc}")
        except Exception:
            pass

    def test_ocr_on_rapidocr_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / RAPIDOCR_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            ocr_enabled=True,
            ocr_mode="pdf_aware_layout_regions",
            ocr_engine="rapidocr",
            ocr_backend="torch",
            ocr_language="pt",
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("RapidOCR", str(ctx.exception))

    def test_table_off_tableformer_not_required(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / TABLEFORMER_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            table_structure=False,
        )
        try:
            self._run_build(profile)
        except BenchmarkConfigurationError as exc:
            self.fail(f"Should not raise when table_structure=False: {exc}")
        except Exception:
            pass

    def test_table_on_tableformer_missing_raises(self):
        _make_full_artifacts(self.base)
        import shutil
        shutil.rmtree(self.base / TABLEFORMER_ARTIFACT_DIRECTORY)
        profile = self._make_minimal_profile(
            model_artifacts_path=str(self.base),
            table_structure=True,
            table_mode="accurate",
        )
        with self.assertRaises(BenchmarkConfigurationError) as ctx:
            self._run_build(profile)
        self.assertIn("TableFormer", str(ctx.exception))


# ---------------------------------------------------------------------------
# Group 4: Runtime environment isolation
# ---------------------------------------------------------------------------

class TestRuntimeEnvironmentIsolation(unittest.TestCase):

    def test_docling_hf_offline_is_set(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS
        spec = PARSER_RUNTIME_SPECS.get("docling")
        self.assertIsNotNone(spec, "docling spec not registered")
        env = spec.model_env
        self.assertIn("HF_HUB_OFFLINE", env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertIn("TRANSFORMERS_OFFLINE", env)
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")

    def test_docling_hf_home_is_templated(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS
        spec = PARSER_RUNTIME_SPECS.get("docling")
        self.assertIsNotNone(spec)
        env = spec.model_env
        hf_home = env.get("HF_HOME", "")
        hf_cache = env.get("HF_HUB_CACHE", "")
        # Must use model_root template so each parser gets its own cache
        self.assertIn("{model_root}", hf_home + hf_cache)

    def test_docling_hf_telemetry_disabled(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS
        spec = PARSER_RUNTIME_SPECS.get("docling")
        env = spec.model_env
        self.assertEqual(env.get("HF_HUB_DISABLE_TELEMETRY"), "1")
        self.assertEqual(env.get("DO_NOT_TRACK"), "1")
        self.assertEqual(env.get("SCARF_NO_ANALYTICS"), "1")


# ---------------------------------------------------------------------------
# Group 5: Downloader selection
# ---------------------------------------------------------------------------

class TestDownloaderSelection(unittest.TestCase):
    """Verify that prepare_docling_models.ps1 acquisition script
    calls download_models with exactly the right arguments for full_cpu_local.

    We test the Python acquisition snippet that is embedded in the PS1
    by reading it and verifying the tokens it contains.
    """

    @classmethod
    def setUpClass(cls):
        ps1_path = (
            ROOT / "scripts" / "windows" / "prepare_docling_models.ps1"
        )
        cls.available = ps1_path.exists()
        cls.text = ps1_path.read_text(encoding="utf-8") if cls.available else ""

    def setUp(self):
        if not self.available:
            self.skipTest("prepare_docling_models.ps1 not found")

    def test_uses_download_models_api(self):
        self.assertIn("download_models", self.text)
        self.assertNotIn("hf_hub_download", self.text)

    def test_layout_enabled(self):
        self.assertIn("with_layout=True", self.text)

    def test_tableformer_enabled(self):
        self.assertIn("with_tableformer=True", self.text)

    def test_tableformer_v2_disabled(self):
        self.assertIn("with_tableformer_v2=False", self.text)

    def test_code_formula_enabled(self):
        self.assertIn("with_code_formula=True", self.text)

    def test_picture_classifier_enabled(self):
        self.assertIn("with_picture_classifier=True", self.text)

    def test_smolvlm_enabled(self):
        self.assertIn("with_smolvlm=True", self.text)

    def test_granite_chart_extraction_v4_enabled(self):
        self.assertIn("with_granite_chart_extraction_v4=True", self.text)

    def test_rapidocr_enabled(self):
        self.assertIn("with_rapidocr=True", self.text)

    def test_rapidocr_torch_pt_explicit(self):
        self.assertIn('rapidocr_models=["torch:pt"]', self.text)

    def test_force_false_is_default(self):
        # The download call must use force=False to preserve partial downloads
        self.assertIn("force=False", self.text)

    def test_unused_models_disabled(self):
        self.assertIn("with_granitedocling=False", self.text)
        self.assertIn("with_easyocr=False", self.text)
        self.assertIn("with_nemotron_ocr=False", self.text)


# ---------------------------------------------------------------------------
# Group 6: ValidateOnly flow (PS1 structure)
# ---------------------------------------------------------------------------

class TestPrepareDoclingPs1Structure(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ps1_path = (
            ROOT / "scripts" / "windows" / "prepare_docling_models.ps1"
        )
        cls.available = ps1_path.exists()
        cls.text = ps1_path.read_text(encoding="utf-8") if cls.available else ""

    def setUp(self):
        if not self.available:
            self.skipTest("prepare_docling_models.ps1 not found")

    def test_has_required_header(self):
        self.assertTrue(
            self.text.startswith("#Requires -Version 5.1"),
            "Script must begin with #Requires -Version 5.1",
        )
        self.assertIn("Set-StrictMode -Version Latest", self.text)
        self.assertIn("$ErrorActionPreference = 'Stop'", self.text)

    def test_has_phases(self):
        self.assertIn("PHASE 1", self.text)
        self.assertIn("PHASE 2", self.text)
        self.assertIn("PHASE 3", self.text)

    def test_acquisition_precedes_offline_validation(self):
        p1 = self.text.find("PHASE 1")
        p2 = self.text.find("PHASE 2")
        p3 = self.text.find("PHASE 3")
        self.assertGreaterEqual(p1, 0)
        self.assertLess(p1, p2)
        self.assertLess(p2, p3)

    def test_validate_only_skips_acquisition(self):
        self.assertIn("ValidateOnly", self.text)
        self.assertIn("if (-not $ValidateOnly)", self.text)

    def test_offline_variables_set(self):
        self.assertIn("HF_HUB_OFFLINE", self.text)
        self.assertIn("TRANSFORMERS_OFFLINE", self.text)

    def test_env_isolation_with_finally(self):
        self.assertIn("finally", self.text.lower())
        self.assertIn("OriginalEnvironment", self.text)

    def test_force_parameter_exists(self):
        self.assertIn("[switch]$Force", self.text)
        self.assertIn("if ($Force", self.text)

    def test_invokes_validate_script(self):
        self.assertIn("validate_docling_models.py", self.text)

    def test_hf_cache_is_docling_specific(self):
        self.assertIn("HF_HOME", self.text)
        self.assertIn("HF_HUB_CACHE", self.text)
        self.assertIn("HF_XET_CACHE", self.text)

    def test_uses_invoke_python_script_checked(self):
        self.assertIn("Invoke-PythonScriptChecked", self.text)

    def test_no_python_c_heredoc(self):
        # Spec §35: must not use python -c @"..."@
        import re
        self.assertNotRegex(
            self.text,
            re.compile(r"-c\s*@\"", re.IGNORECASE),
        )

    def test_manifest_verified_after_generation(self):
        self.assertIn("docling_models_manifest.json", self.text)
        self.assertIn("Test-Path $ManifestPath", self.text)


# ---------------------------------------------------------------------------
# Group 7: Manifest validation (validate_docling_models.py)
# ---------------------------------------------------------------------------

class TestManifestValidation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.manifest_path = self.base / "manifest.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _import_validate_manifest(self):
        from scripts.validate_docling_models import validate_manifest
        return validate_manifest

    def _write_manifest(self, **overrides) -> dict:
        base_manifest = {
            "schema_version": 1,
            "parser": "docling",
            "docling_version": "2.122.0",
            "profile": "full_cpu_local",
            "offline_validation": {
                "passed": True,
                "pipeline_initialized": True,
            },
            "capabilities": {
                "layout": {
                    "enabled": True,
                    "directory": LAYOUT_ARTIFACT_DIRECTORY,
                    "present": True,
                }
            },
        }
        base_manifest.update(overrides)
        self.manifest_path.write_text(
            json.dumps(base_manifest, indent=2), encoding="utf-8"
        )
        return base_manifest

    def test_manifest_not_found(self):
        validate_manifest = self._import_validate_manifest()
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("not found", detail)

    def test_invalid_json(self):
        validate_manifest = self._import_validate_manifest()
        self.manifest_path.write_text("not json", encoding="utf-8")
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)

    def test_wrong_schema_version(self):
        validate_manifest = self._import_validate_manifest()
        self._write_manifest(schema_version=99)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("schema_version", detail)

    def test_wrong_parser(self):
        validate_manifest = self._import_validate_manifest()
        self._write_manifest(parser="unstructured")
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("parser", detail)

    def test_offline_validation_false(self):
        validate_manifest = self._import_validate_manifest()
        self._write_manifest(
            offline_validation={"passed": False, "pipeline_initialized": False}
        )
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)

    def test_pipeline_initialized_false(self):
        validate_manifest = self._import_validate_manifest()
        self._write_manifest(
            offline_validation={"passed": True, "pipeline_initialized": False}
        )
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("pipeline_initialized", detail)

    def test_model_directory_removed(self):
        validate_manifest = self._import_validate_manifest()
        # Point to directory that doesn't exist
        self._write_manifest(
            capabilities={
                "layout": {
                    "enabled": True,
                    "directory": "nonexistent--model-dir",
                    "present": True,
                }
            }
        )
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("nonexistent--model-dir", detail)

    def test_valid_manifest_with_existing_dirs(self):
        validate_manifest = self._import_validate_manifest()
        # Create the model dir so the check passes
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        layout_dir.mkdir(parents=True)
        self._write_manifest()
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertTrue(ok, f"Expected pass but got: {detail}")


if __name__ == "__main__":
    unittest.main()
