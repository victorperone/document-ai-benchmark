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
  8. Skip semantics (validate_docling_models.py)
  9. Preflight manifest check
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
_stub_if_missing(
    "psutil",
    Process=MagicMock,
    AccessDenied=RuntimeError,
    NoSuchProcess=RuntimeError,
    cpu_count=MagicMock(return_value=1),
)
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

# Stubs for docling.models.stages (RapidOCR internal API)
_RAPID_OCR_RESOLVED = MagicMock()
_RAPID_OCR_RESOLVED.ppocr_version = "v6"
_RAPID_OCR_RESOLVED.rapidocr_lang_token = "pt"

_RAPID_OCR_MODULE = MagicMock()
_RAPID_OCR_MODULE.RapidOcrModel._model_repo_folder = "RapidOcr"
_RAPID_OCR_MODULE._resolve_rapidocr.return_value = _RAPID_OCR_RESOLVED
_RAPID_OCR_MODULE._backend_to_engine_type.return_value = MagicMock()
_RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {}  # Overridden per test

sys.modules["docling.models"] = MagicMock()
sys.modules["docling.models.stages"] = MagicMock()
sys.modules["docling.models.stages.ocr"] = MagicMock()
sys.modules["docling.models.stages.ocr.rapid_ocr_model"] = _RAPID_OCR_MODULE

# Update pipeline options stub with proper preset result
_PRESET_RESULT = MagicMock()
_PRESET_RESULT.repo_id = "docling-project/DocumentFigureClassifier-v2.5"
_PRESET_RESULT.repo_cache_folder = ("docling-project--DocumentFigureClassifier-v2.5")
_PIPELINE_OPTIONS_MODULE = sys.modules["docling.datamodel.pipeline_options"]
_PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions = MagicMock()
_PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.return_value = _PRESET_RESULT

from src.parsers.docling_v2 import (
    CODE_FORMULA_ARTIFACT_DIRECTORY,
    FULL_CPU_LOCAL_REQUIRED_CAPABILITIES,
    GRANITE_CHART_V4_ARTIFACT_DIRECTORY,
    LAYOUT_ARTIFACT_DIRECTORY,
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    PARSER_NAME,
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
    tree_digest as _tree_digest,
    validate_manifest,
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


_CAP_SUBDIRS: dict[str, str] = {
    "layout": LAYOUT_ARTIFACT_DIRECTORY,
    "table_structure": TABLEFORMER_ARTIFACT_DIRECTORY,
    "ocr": RAPIDOCR_ARTIFACT_DIRECTORY,
    "picture_description": SMOLVLM_ARTIFACT_DIRECTORY,
    "picture_classification": PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY,
    "chart_extraction": GRANITE_CHART_V4_ARTIFACT_DIRECTORY,
    "formula_code_enrichment": CODE_FORMULA_ARTIFACT_DIRECTORY,
}


def _build_full_valid_manifest(base: Path, manifest_path: Path) -> None:
    """Create all 7 capability dirs and write a manifest with correct digests."""
    _make_full_artifacts(base)
    try:
        docling_ver = importlib.metadata.version("docling")
    except Exception:
        docling_ver = "2.122.0"
    capabilities: dict = {}
    for cap_name in FULL_CPU_LOCAL_REQUIRED_CAPABILITIES:
        subdir = _CAP_SUBDIRS[cap_name]
        cap_dir = base / subdir
        digest, count = _tree_digest(cap_dir)
        capabilities[cap_name] = {
            "enabled": True,
            "directory": subdir,
            "present": True,
            "tree_digest": digest,
            "file_count": count,
            "weight_files": [],
        }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "parser": PARSER_NAME,
        "docling_version": docling_ver,
        "profile": "full_cpu_local",
        "offline_validation": {
            "passed": True,
            "structural_pass": True,
            "component_pass": True,
            "pipeline_initialized": True,
        },
        "capabilities": capabilities,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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
        # Default: preset returns known repo_id
        _PRESET_RESULT.repo_id = "docling-project/DocumentFigureClassifier-v2.5"
        _PRESET_RESULT.repo_cache_folder = ("docling-project--DocumentFigureClassifier-v2.5")
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.side_effect = None
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.return_value = _PRESET_RESULT

    def tearDown(self):
        self._tmp.cleanup()

    def _resolved_dir(self) -> Path:
        return self.base / "docling-project--DocumentFigureClassifier-v2.5"

    def test_missing_directory(self):
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_fallback_when_preset_raises(self):
        # If preset raises, fall back to constant
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.side_effect = ImportError("no docling")
        fallback_dir = self.base / PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY
        fallback_dir.mkdir(parents=True)
        _touch(fallback_dir / "config.json")
        _touch(fallback_dir / "model.safetensors")
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertTrue(ok)

    def test_missing_config_json(self):
        d = self._resolved_dir()
        d.mkdir(parents=True)
        _touch(d / "model.safetensors")
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("config.json", detail)

    def test_pass(self):
        d = self._resolved_dir()
        _make_full_classifier(d)
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertTrue(ok)

    def test_directory_name_derived_from_preset(self):
        # Preset returns a different repo_id → different directory expected
        _PRESET_RESULT.repo_id = "myorg/MyClassifier-v3"
        _PRESET_RESULT.repo_cache_folder = ("myorg--MyClassifier-v3")
        d = self.base / "myorg--MyClassifier-v3"
        _make_full_classifier(d)
        ok, detail = _validate_picture_classifier_artifacts(self.base)
        self.assertTrue(ok)
        self.assertIn("myorg--MyClassifier-v3", detail)


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
        self.model_dir = self.base / "RapidOcr"
        # Reset rapidocr module mock to known state
        _RAPID_OCR_MODULE._resolve_rapidocr.return_value = _RAPID_OCR_RESOLVED
        _RAPID_OCR_MODULE._backend_to_engine_type.return_value = MagicMock()
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {}
        _RAPID_OCR_MODULE._rapidocr_artifacts.side_effect = None

    def tearDown(self):
        self._tmp.cleanup()

    def _make_artifact(self, *file_paths: Path):
        art = MagicMock()
        art.files = list(file_paths)
        return art

    def _setup_full_pass(self):
        """Create files and configure mocks for a full PASS."""
        self.model_dir.mkdir(parents=True)
        det = self.model_dir / "det_model.pth"
        cls_ = self.model_dir / "cls_model.pth"
        rec = self.model_dir / "rec_model.pth"
        for f in (det, cls_, rec):
            f.write_bytes(b"x" * 1024)
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {
            "det": self._make_artifact(det),
            "cls": self._make_artifact(cls_),
            "rec": self._make_artifact(rec),
        }

    def test_missing_directory(self):
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing model directory", detail)

    def test_resolve_failure(self):
        self.model_dir.mkdir(parents=True)
        _RAPID_OCR_MODULE._rapidocr_artifacts.side_effect = RuntimeError("resolve failed")
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("failed to resolve", detail)
        _RAPID_OCR_MODULE._rapidocr_artifacts.side_effect = None

    def test_missing_det_role(self):
        self.model_dir.mkdir(parents=True)
        cls_ = self.model_dir / "cls_model.pth"
        rec = self.model_dir / "rec_model.pth"
        for f in (cls_, rec):
            f.write_bytes(b"x" * 1024)
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {
            "cls": self._make_artifact(cls_),
            "rec": self._make_artifact(rec),
        }
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing roles", detail)
        self.assertIn("det", detail)

    def test_missing_rec_role(self):
        self.model_dir.mkdir(parents=True)
        det = self.model_dir / "det_model.pth"
        cls_ = self.model_dir / "cls_model.pth"
        for f in (det, cls_):
            f.write_bytes(b"x" * 1024)
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {
            "det": self._make_artifact(det),
            "cls": self._make_artifact(cls_),
        }
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing roles", detail)
        self.assertIn("rec", detail)

    def test_missing_file(self):
        self._setup_full_pass()
        # Remove det file after setting up mocks
        (self.model_dir / "det_model.pth").unlink()
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("missing", detail)
        self.assertIn("det_model.pth", detail)

    def test_empty_file(self):
        self._setup_full_pass()
        (self.model_dir / "cls_model.pth").write_bytes(b"")
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertFalse(ok)
        self.assertIn("empty", detail)
        self.assertIn("cls_model.pth", detail)

    def test_pass_with_dictionary(self):
        self.model_dir.mkdir(parents=True)
        det = self.model_dir / "det.pth"
        cls_ = self.model_dir / "cls.pth"
        rec = self.model_dir / "rec.pth"
        dict_f = self.model_dir / "dict.txt"
        for f in (det, cls_, rec, dict_f):
            f.write_bytes(b"x" * 1024)
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {
            "det": self._make_artifact(det),
            "cls": self._make_artifact(cls_),
            "rec": self._make_artifact(rec, dict_f),
        }
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertTrue(ok)
        self.assertIn("torch:pt", detail)

    def test_pass_backend_lang_in_message(self):
        self._setup_full_pass()
        ok, detail = _validate_rapidocr_artifacts(self.base)
        self.assertTrue(ok)
        self.assertIn("backend=torch", detail)
        self.assertIn("lang=pt", detail)


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
        # Reset rapidocr mock state
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {}
        _RAPID_OCR_MODULE._rapidocr_artifacts.side_effect = None
        _PRESET_RESULT.repo_id = "docling-project/DocumentFigureClassifier-v2.5"
        _PRESET_RESULT.repo_cache_folder = ("docling-project--DocumentFigureClassifier-v2.5")
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.side_effect = None
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.return_value = _PRESET_RESULT

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
        self.assertIn("--check-manifest", self.text)


# ---------------------------------------------------------------------------
# Group 7: Manifest validation (fail-closed for full_cpu_local)
# ---------------------------------------------------------------------------

class TestManifestValidation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.manifest_path = self.base / "manifest.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_raw(self, content: dict) -> None:
        self.manifest_path.write_text(json.dumps(content, indent=2), encoding="utf-8")

    def _base_valid_header(self) -> dict:
        try:
            docling_ver = importlib.metadata.version("docling")
        except Exception:
            docling_ver = "2.122.0"
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "parser": PARSER_NAME,
            "docling_version": docling_ver,
            "profile": "full_cpu_local",
            "offline_validation": {
                "passed": True,
                "structural_pass": True,
                "component_pass": True,
                "pipeline_initialized": True,
            },
        }

    # --- header-level failures (before capability checks) ---

    def test_manifest_not_found(self):
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("not found", detail)

    def test_invalid_json(self):
        self.manifest_path.write_text("not json", encoding="utf-8")
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)

    def test_wrong_schema_version(self):
        m = self._base_valid_header()
        m["schema_version"] = 99
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("schema_version", detail)

    def test_wrong_parser(self):
        m = self._base_valid_header()
        m["parser"] = "unstructured"
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("parser", detail)

    def test_wrong_profile(self):
        m = self._base_valid_header()
        m["profile"] = "minimal"
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("profile", detail)

    def test_offline_validation_passed_false(self):
        m = self._base_valid_header()
        m["offline_validation"]["passed"] = False
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("passed", detail)

    def test_structural_pass_false(self):
        m = self._base_valid_header()
        m["offline_validation"]["structural_pass"] = False
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("structural_pass", detail)

    def test_component_pass_false(self):
        m = self._base_valid_header()
        m["offline_validation"]["component_pass"] = False
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("component_pass", detail)

    def test_pipeline_initialized_false(self):
        m = self._base_valid_header()
        m["offline_validation"]["pipeline_initialized"] = False
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("pipeline_initialized", detail)

    # --- capability-level failures ---

    def test_capabilities_empty(self):
        m = self._base_valid_header()
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("required capability missing", detail)

    def test_required_capability_missing(self):
        # Remove "layout" (first in required list) → immediate fail
        m = self._base_valid_header()
        m["capabilities"] = {}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("required capability missing", detail)
        self.assertIn("layout", detail)

    def test_capability_entry_not_dict(self):
        m = self._base_valid_header()
        m["capabilities"] = {"layout": "not-a-dict"}
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("entry is not an object", detail)

    def test_capability_enabled_false(self):
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {"enabled": False, "directory": LAYOUT_ARTIFACT_DIRECTORY, "present": True}
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("enabled is not true", detail)

    def test_capability_present_false(self):
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {"enabled": True, "directory": LAYOUT_ARTIFACT_DIRECTORY, "present": False}
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("present is not true", detail)

    def test_capability_directory_empty(self):
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {"enabled": True, "directory": "", "present": True}
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("directory is missing", detail)

    def test_capability_directory_not_existing(self):
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {"enabled": True, "directory": "nonexistent--dir", "present": True}
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("nonexistent--dir", detail)

    def test_capability_tree_digest_missing(self):
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        _make_full_layout(layout_dir)
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {
                "enabled": True,
                "directory": LAYOUT_ARTIFACT_DIRECTORY,
                "present": True,
                # no tree_digest
            }
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("tree_digest is missing", detail)

    def test_capability_file_count_missing(self):
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        _make_full_layout(layout_dir)
        real_digest, _ = _tree_digest(layout_dir)
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {
                "enabled": True,
                "directory": LAYOUT_ARTIFACT_DIRECTORY,
                "present": True,
                "tree_digest": real_digest,
                # no file_count
            }
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("file_count is missing", detail)

    def test_capability_file_count_zero(self):
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        _make_full_layout(layout_dir)
        real_digest, _ = _tree_digest(layout_dir)
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {
                "enabled": True,
                "directory": LAYOUT_ARTIFACT_DIRECTORY,
                "present": True,
                "tree_digest": real_digest,
                "file_count": 0,
            }
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("file_count must be > 0", detail)

    def test_tree_digest_mismatch(self):
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        _make_full_layout(layout_dir)
        _, real_count = _tree_digest(layout_dir)
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {
                "enabled": True,
                "directory": LAYOUT_ARTIFACT_DIRECTORY,
                "present": True,
                "tree_digest": "deadbeef" * 8,
                "file_count": real_count,
            }
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("tree digest mismatch", detail)
        self.assertIn("layout", detail)

    def test_file_count_mismatch(self):
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        _make_full_layout(layout_dir)
        real_digest, real_count = _tree_digest(layout_dir)
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {
                "enabled": True,
                "directory": LAYOUT_ARTIFACT_DIRECTORY,
                "present": True,
                "tree_digest": real_digest,
                "file_count": real_count + 99,
            }
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("file_count mismatch", detail)

    def test_missing_certified_weight(self):
        layout_dir = self.base / LAYOUT_ARTIFACT_DIRECTORY
        _make_full_layout(layout_dir)
        real_digest, real_count = _tree_digest(layout_dir)
        m = self._base_valid_header()
        m["capabilities"] = {
            "layout": {
                "enabled": True,
                "directory": LAYOUT_ARTIFACT_DIRECTORY,
                "present": True,
                "tree_digest": real_digest,
                "file_count": real_count,
                "weight_files": [
                    f"{LAYOUT_ARTIFACT_DIRECTORY}/model.safetensors",
                    f"{LAYOUT_ARTIFACT_DIRECTORY}/nonexistent_shard.safetensors",
                ],
            }
        }
        self._write_raw(m)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertFalse(ok)
        self.assertIn("missing certified weight", detail)

    def test_valid_manifest_all_capabilities(self):
        _build_full_valid_manifest(self.base, self.manifest_path)
        ok, detail = validate_manifest(self.manifest_path, self.base)
        self.assertTrue(ok, f"Expected PASS but got: {detail}")


# ---------------------------------------------------------------------------
# Group 8: Skip semantics (validate_docling_models.py)
# ---------------------------------------------------------------------------

class TestSkipSemantics(unittest.TestCase):
    """Verify that skip flags cannot produce component_pass=True or pipeline_initialized=True."""

    @classmethod
    def setUpClass(cls):
        cls.script_path = ROOT / "scripts" / "validate_docling_models.py"
        cls.available = cls.script_path.exists()
        cls.text = cls.script_path.read_text(encoding="utf-8") if cls.available else ""

    def setUp(self):
        if not self.available:
            self.skipTest("validate_docling_models.py not found")

    def test_skip_component_sets_pass_false_not_true(self):
        # When Level B is skipped, component_pass must NOT be set to True
        # The text must NOT contain code that sets component_pass = True when skipped
        # The allowed pattern is component_pass = False when skipped
        self.assertNotIn(
            "component_pass = True  # when skipped",
            self.text,
        )
        # The guard must be present
        self.assertIn("skip_component_load", self.text)

    def test_skip_pipeline_sets_false(self):
        self.assertIn("skip_pipeline_init", self.text)

    def test_manifest_generation_blocked_with_skips(self):
        # The script must have a guard that aborts manifest generation when skips are used
        self.assertIn("sys.exit(4)", self.text)

    def test_check_manifest_flag_exists(self):
        self.assertIn("--check-manifest", self.text)
        self.assertIn("check_manifest", self.text)

    def test_level_b_documented_as_lightweight(self):
        self.assertIn("lightweight", self.text.lower())


# ---------------------------------------------------------------------------
# Group 9: Preflight manifest check
# ---------------------------------------------------------------------------

class TestPreflightManifest(unittest.TestCase):
    """Verify that preflight_profile checks the certified manifest."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        # Artifacts live at base/docling/docling/models so that
        # artifacts_path.parent.parent = base/docling (writable in tests)
        self.artifacts = self.base / "docling" / "docling" / "models"
        self.artifacts.mkdir(parents=True, exist_ok=True)
        # Reset mocks to known state for preflight tests
        _RAPID_OCR_MODULE._rapidocr_artifacts.return_value = {}
        _RAPID_OCR_MODULE._rapidocr_artifacts.side_effect = None
        _PRESET_RESULT.repo_id = "docling-project/DocumentFigureClassifier-v2.5"
        _PRESET_RESULT.repo_cache_folder = "docling-project--DocumentFigureClassifier-v2.5"
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.side_effect = None
        _PIPELINE_OPTIONS_MODULE.DocumentPictureClassifierOptions.from_preset.return_value = _PRESET_RESULT

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest_path(self) -> Path:
        """Return the manifest path that preflight_profile will compute."""
        return self.artifacts.parent.parent / "manifests" / MANIFEST_FILENAME

    def _write_invalid_manifest(self, manifest_path: Path, **overrides) -> None:
        """Write a structurally invalid manifest (for tests that check early failures)."""
        try:
            docling_ver = importlib.metadata.version("docling")
        except Exception:
            docling_ver = "2.122.0"
        content: dict = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "parser": PARSER_NAME,
            "docling_version": docling_ver,
            "profile": "full_cpu_local",
            "offline_validation": {
                "passed": True,
                "structural_pass": True,
                "component_pass": True,
                "pipeline_initialized": True,
            },
            "capabilities": {},
        }
        content.update(overrides)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(content, indent=2), encoding="utf-8")

    def test_preflight_result_has_certified_manifest_check(self):
        from src.parsers.docling_v2 import preflight_profile
        _make_full_artifacts(self.artifacts)
        result = preflight_profile("full_cpu_local", model_artifacts_override=self.artifacts)
        check_names = [c["name"] for c in result.get("checks", [])]
        self.assertIn("certified manifest", check_names)

    def test_preflight_fails_without_manifest(self):
        from src.parsers.docling_v2 import preflight_profile
        _make_full_artifacts(self.artifacts)
        result = preflight_profile("full_cpu_local", model_artifacts_override=self.artifacts)
        manifest_check = next(
            (c for c in result.get("checks", []) if c["name"] == "certified manifest"),
            None,
        )
        self.assertIsNotNone(manifest_check)
        self.assertEqual(manifest_check["status"], "fail")
        self.assertIn("manifest not found", manifest_check.get("detail", ""))

    def test_preflight_passes_with_valid_manifest(self):
        from src.parsers.docling_v2 import preflight_profile
        manifest_path = self._manifest_path()
        _build_full_valid_manifest(self.artifacts, manifest_path)
        result = preflight_profile("full_cpu_local", model_artifacts_override=self.artifacts)
        manifest_check = next(
            (c for c in result.get("checks", []) if c["name"] == "certified manifest"),
            None,
        )
        self.assertIsNotNone(manifest_check)
        self.assertEqual(manifest_check["status"], "pass")

    def test_preflight_fails_with_wrong_profile_in_manifest(self):
        from src.parsers.docling_v2 import preflight_profile
        _make_full_artifacts(self.artifacts)
        manifest_path = self._manifest_path()
        self._write_invalid_manifest(manifest_path, profile="minimal")
        result = preflight_profile("full_cpu_local", model_artifacts_override=self.artifacts)
        manifest_check = next(
            (c for c in result.get("checks", []) if c["name"] == "certified manifest"),
            None,
        )
        self.assertIsNotNone(manifest_check)
        self.assertEqual(manifest_check["status"], "fail")


if __name__ == "__main__":
    unittest.main()
