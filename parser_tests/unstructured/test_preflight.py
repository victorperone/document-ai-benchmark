"""Tests for unstructured_v2.preflight_profile (section 22.5)."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import MagicMock, patch

from src.parsers.unstructured_v2 import (
    preflight_profile,
    UNSTRUCTURED_REQUIRED_VERSION,
    UNSTRUCTURED_INFERENCE_REQUIRED_VERSION,
)


def _status(result: dict, check_name: str) -> str | None:
    for item in result.get("checks", []):
        if item.get("name") == check_name:
            return item.get("status")
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix.lower() not in {".pyc", ".pyo"}
    ):
        relative = path.relative_to(root).as_posix()
        file_hash = _sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


class TestPreflightVersion(unittest.TestCase):
    def test_correct_version_passes(self):
        with patch("src.parsers.unstructured_v2._package_version",
                   side_effect=lambda n: UNSTRUCTURED_REQUIRED_VERSION if n == "unstructured" else UNSTRUCTURED_INFERENCE_REQUIRED_VERSION):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured version"), "pass")

    def test_wrong_version_fails(self):
        with patch("src.parsers.unstructured_v2._package_version",
                   side_effect=lambda n: "0.1.0" if n == "unstructured" else None):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured version"), "fail")

    def test_missing_package_fails(self):
        with patch("src.parsers.unstructured_v2._package_version", return_value=None):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured version"), "fail")


class TestPreflightRemoteRejection(unittest.TestCase):
    def test_remote_services_enabled_true_fails(self):
        with patch("src.parsers.unstructured_v2.get_profile",
                   return_value={
                       "strategy": "fast",
                       "ocr_enabled": False,
                       "remote_services_enabled": True,
                       "network_allowed_during_run": False,
                       "infer_table_structure": False,
                       "languages": ["por"],
                       "ocr_mode": None, "ocr_engine": None,
                       "detect_language_per_element": False,
                       "include_page_breaks": True,
                       "hi_res_model_name": None,
                       "extract_image_block_types": [],
                       "extract_image_block_to_payload": False,
                       "extract_forms": False,
                       "form_extraction_skip_tables": True,
                       "password": None,
                       "pdfminer_line_margin": None,
                       "pdfminer_char_margin": None,
                       "pdfminer_line_overlap": None,
                       "pdfminer_word_margin": 0.185,
                   }):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "remote services disabled"), "fail")


class TestPreflightTesseractCheck(unittest.TestCase):
    def test_missing_tesseract_in_ocr_profile_fails(self):
        with patch("src.parsers.unstructured_v2.shutil.which", return_value=None):
            result = preflight_profile("auto_ocr")
        self.assertEqual(_status(result, "tesseract executable"), "fail")


class TestPreflightTableStrategyCompat(unittest.TestCase):
    def test_infer_table_with_fast_strategy_fails(self):
        with patch("src.parsers.unstructured_v2.get_profile",
                   return_value={
                       "strategy": "fast",
                       "ocr_enabled": False,
                       "remote_services_enabled": False,
                       "network_allowed_during_run": False,
                       "infer_table_structure": True,
                       "languages": ["por"],
                       "ocr_mode": None, "ocr_engine": None,
                       "detect_language_per_element": False,
                       "include_page_breaks": True,
                       "hi_res_model_name": None,
                       "extract_image_block_types": [],
                       "extract_image_block_to_payload": False,
                       "extract_forms": False,
                       "form_extraction_skip_tables": True,
                       "password": None,
                       "pdfminer_line_margin": None,
                       "pdfminer_char_margin": None,
                       "pdfminer_line_overlap": None,
                       "pdfminer_word_margin": 0.185,
                   }):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "table structure strategy"), "fail")


class TestPreflightInferenceVersion(unittest.TestCase):
    def test_inference_version_mismatch_fails(self):
        with patch("src.parsers.unstructured_v2._package_version",
                   side_effect=lambda n: (
                       UNSTRUCTURED_REQUIRED_VERSION if n == "unstructured"
                       else "0.0.0"
                   )):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured-inference version"), "fail")

    def test_inference_version_correct_passes(self):
        with patch("src.parsers.unstructured_v2._package_version",
                   side_effect=lambda n: (
                       UNSTRUCTURED_REQUIRED_VERSION if n == "unstructured"
                       else UNSTRUCTURED_INFERENCE_REQUIRED_VERSION
                   )):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "unstructured-inference version"), "pass")


class TestPreflightFormExtraction(unittest.TestCase):
    def _fake_profile(self, extract_forms: bool) -> dict:
        return {
            "strategy": "fast",
            "ocr_enabled": False,
            "remote_services_enabled": False,
            "network_allowed_during_run": False,
            "infer_table_structure": False,
            "languages": ["por"],
            "ocr_mode": None,
            "ocr_engine": None,
            "detect_language_per_element": False,
            "include_page_breaks": True,
            "hi_res_model_name": None,
            "extract_image_block_types": [],
            "extract_image_block_to_payload": False,
            "extract_forms": extract_forms,
            "form_extraction_skip_tables": not extract_forms,
            "password": None,
            "pdfminer_line_margin": None,
            "pdfminer_char_margin": None,
            "pdfminer_line_overlap": None,
            "pdfminer_word_margin": 0.185,
        }

    def test_extract_forms_true_fails(self):
        with patch("src.parsers.unstructured_v2.get_profile",
                   return_value=self._fake_profile(extract_forms=True)):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "form extraction support"), "fail")

    def test_extract_forms_false_passes(self):
        with patch("src.parsers.unstructured_v2.get_profile",
                   return_value=self._fake_profile(extract_forms=False)):
            result = preflight_profile("fast_native")
        self.assertEqual(_status(result, "form extraction support"), "pass")


class TestPreflightModelManifest(unittest.TestCase):
    def test_missing_manifest_fails(self):
        with TemporaryDirectory() as tmp:
            result = preflight_profile(
                "full_cpu_local",
                model_root_override=Path(tmp),
            )
        self.assertEqual(_status(result, "Unstructured model manifest"), "fail")

    def test_valid_manifest_passes(self):
        with TemporaryDirectory() as tmp:
            model_root = Path(tmp)

            # YOLOX fake
            yolox_dir = model_root / "huggingface" / "hub" / "models--unstructuredio--yolo_x_layout"
            yolox_dir.mkdir(parents=True)
            yolox_file = yolox_dir / "yolox_l0.05.onnx"
            yolox_file.write_bytes(b"\x00" * 64)

            # Table Transformer fake
            table_dir = (
                model_root / "huggingface" / "hub"
                / "models--microsoft--table-transformer-structure-recognition"
                / "snapshots" / "abc123"
            )
            table_dir.mkdir(parents=True)
            table_bin = table_dir / "model.safetensors"
            table_bin.write_bytes(b"\x01" * 128)
            table_cfg = table_dir / "config.json"
            table_cfg.write_bytes(b"{}")

            # spaCy fake wheel
            spacy_wheel_dir = model_root / "spacy"
            spacy_wheel_dir.mkdir(parents=True)
            spacy_wheel = spacy_wheel_dir / "en_core_web_sm-3.8.0-py3-none-any.whl"
            spacy_wheel.write_bytes(b"\x02" * 32)

            # spaCy fake installed tree
            spacy_pkg_root = model_root / "en_core_web_sm" / "en_core_web_sm-3.8.0"
            spacy_pkg_root.mkdir(parents=True)
            (spacy_pkg_root / "meta.json").write_bytes(b'{"version":"3.8.0"}')

            tree_sha = _tree_digest(spacy_pkg_root)

            def _rel(path: Path) -> str:
                return path.resolve().relative_to(model_root.resolve()).as_posix()

            manifest = {
                "schema_version": 1,
                "offline_validation": True,
                "packages": {
                    "unstructured": UNSTRUCTURED_REQUIRED_VERSION,
                    "unstructured-inference": UNSTRUCTURED_INFERENCE_REQUIRED_VERSION,
                },
                "resources": {
                    "layout": {
                        "name": "yolox",
                        "file": {
                            "path": _rel(yolox_file),
                            "size_bytes": yolox_file.stat().st_size,
                            "sha256": _sha256_file(yolox_file),
                        },
                    },
                    "table": {
                        "name": "microsoft/table-transformer-structure-recognition",
                        "files": [
                            {
                                "path": _rel(table_bin),
                                "size_bytes": table_bin.stat().st_size,
                                "sha256": _sha256_file(table_bin),
                            },
                            {
                                "path": _rel(table_cfg),
                                "size_bytes": table_cfg.stat().st_size,
                                "sha256": _sha256_file(table_cfg),
                            },
                        ],
                    },
                    "spacy": {
                        "name": "en_core_web_sm",
                        "wheel": {
                            "path": _rel(spacy_wheel),
                            "size_bytes": spacy_wheel.stat().st_size,
                            "sha256": _sha256_file(spacy_wheel),
                        },
                        "installed_package_root": str(spacy_pkg_root),
                        "installed_tree_sha256": tree_sha,
                        "installed_file_count": 1,
                    },
                },
            }

            manifest_dir = model_root / "manifests"
            manifest_dir.mkdir(parents=True)
            manifest_path = manifest_dir / "unstructured_models_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

            # Mock spaCy spec since it's not installed in WSL
            fake_spacy = ModuleType("spacy")
            fake_spacy.__spec__ = MagicMock()

            fake_spec = MagicMock()
            fake_spec.submodule_search_locations = [str(spacy_pkg_root)]

            with (
                patch.dict(sys.modules, {"spacy": fake_spacy}),
                patch(
                    "src.parsers.unstructured_v2.importlib.util.find_spec",
                    return_value=fake_spec,
                ),
            ):
                result = preflight_profile(
                    "full_cpu_local",
                    model_root_override=model_root,
                )

        self.assertEqual(_status(result, "Unstructured model manifest"), "pass")
        self.assertEqual(_status(result, "YOLOX layout file"), "pass")
        self.assertEqual(_status(result, "Table Transformer weights"), "pass")
        self.assertEqual(_status(result, "spaCy wheel"), "pass")
        self.assertEqual(_status(result, "spaCy installed model"), "pass")
