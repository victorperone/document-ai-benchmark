from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import platform
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import torch
from docling.datamodel.accelerator_options import (
    AcceleratorDevice,
    AcceleratorOptions,
)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    OcrMode,
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
    smolvlm_picture_description,
)
from docling.datamodel.settings import settings
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)

from src.benchmark.artifact_policy import (
    ArtifactPolicy,
    ArtifactSelectionError,
)
from src.benchmark.artifact_contract import ParserArtifactInput, join_page_texts
from src.benchmark.artifacts import finalize_artifacts
from src.benchmark.config import (
    BenchmarkConfigurationError,
    get_normalization_config,
    get_profile,
    get_reference_tokenizer,
)
from src.benchmark.cpu_resources import resolve_parallelism
from src.benchmark.metrics_writer import write_json
from src.benchmark.paths import build_output_paths
from src.benchmark.preflight import make_check, make_result
from src.benchmark.resource_monitor import ResourceMonitor
from src.benchmark.runtime_io import (
    add_runtime_arguments,
    parser_output_context,
)

PARSER_NAME = "docling"
PARSER_DISPLAY_NAME = "Docling"
DEFAULT_MODEL_ARTIFACTS = Path("/home/appuser/.cache/docling/models")

SMOLVLM_ARTIFACT_DIRECTORY = (
    "HuggingFaceTB--SmolVLM-256M-Instruct"
)

GRANITE_CHART_V4_ARTIFACT_DIRECTORY = (
    "ibm-granite--granite-vision-4.1-4b"
)

CODE_FORMULA_ARTIFACT_DIRECTORY = (
    "docling-project--CodeFormulaV2"
)

LAYOUT_ARTIFACT_DIRECTORY = (
    "docling-project--docling-layout-heron"
)

TABLEFORMER_ARTIFACT_DIRECTORY = (
    "docling-project--docling-models"
)

RAPIDOCR_ARTIFACT_DIRECTORY = "RapidOcr"

# Derived from the HF naming convention for
# DocumentPictureClassifierOptions preset
# "document_figure_classifier_v2".
PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY = (
    "docling-project--DocumentFigureClassifier-v2.5"
)

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "docling_models_manifest.json"

FULL_CPU_LOCAL_REQUIRED_CAPABILITIES = (
    "layout",
    "table_structure",
    "ocr",
    "picture_description",
    "picture_classification",
    "chart_extraction",
    "formula_code_enrichment",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Docling benchmark adapter v2.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/outputs"),
    )
    parser.add_argument(
        "--profile",
        default="ocr_auto",
    )
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda", "auto"),
        default=None,
        help=(
            "Optional accelerator override. "
            "Default comes from the selected profile."
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help=(
            "Optional Docling thread-count override. "
            "Default comes from the selected profile."
        ),
    )
    parser.add_argument(
        "--model-artifacts-path",
        type=Path,
        default=None,
        help=(
            "Optional override for pre-downloaded Docling model artifacts."
        ),
    )

    add_runtime_arguments(parser)
    args = parser.parse_args()

    try:
        args.artifact_policy = ArtifactPolicy.from_cli(
            args.artifacts,
        )
    except ArtifactSelectionError as exc:
        parser.error(str(exc))

    return args


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

def _validate_granite_chart_v4_artifacts(
    artifacts_path: Path,
) -> tuple[bool, str]:
    model_dir = (
        artifacts_path
        / GRANITE_CHART_V4_ARTIFACT_DIRECTORY
    )

    if not model_dir.is_dir():
        return (
            False,
            f"missing model directory: {model_dir}",
        )

    required_files = (
        "config.json",
        "preprocessor_config.json",
        "model.safetensors.index.json",
    )

    missing_files = [
        name
        for name in required_files
        if not (model_dir / name).is_file()
    ]

    if missing_files:
        return (
            False,
            "missing required file(s): "
            + ", ".join(missing_files),
        )

    index_path = (
        model_dir
        / "model.safetensors.index.json"
    )

    try:
        index_data = json.loads(
            index_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        return (
            False,
            (
                "invalid model.safetensors.index.json: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    weight_map = index_data.get("weight_map")

    if not isinstance(weight_map, dict) or not weight_map:
        return (
            False,
            (
                "model.safetensors.index.json "
                "does not contain a valid weight_map"
            ),
        )

    shards = sorted(
        {
            str(value)
            for value in weight_map.values()
            if value
        }
    )

    if not shards:
        return (
            False,
            "no model shards declared by weight_map",
        )

    missing_shards = [
        shard
        for shard in shards
        if not (model_dir / shard).is_file()
    ]

    if missing_shards:
        return (
            False,
            "missing shard(s): "
            + ", ".join(missing_shards),
        )

    empty_shards = [
        shard
        for shard in shards
        if (model_dir / shard).stat().st_size <= 0
    ]

    if empty_shards:
        return (
            False,
            "empty shard(s): "
            + ", ".join(empty_shards),
        )

    return (
        True,
        (
            f"{len(shards)} shard(s) verified "
            f"at {model_dir}"
        ),
    )

def _validate_sharded_safetensors(
    model_dir: Path,
    index_path: Path,
) -> tuple[bool, str]:
    try:
        index_data = json.loads(
            index_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return (
            False,
            (
                f"invalid {index_path.name}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    weight_map = index_data.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        return (
            False,
            (
                f"{index_path.name} does not "
                "contain a valid weight_map"
            ),
        )

    shards = sorted(
        {str(v) for v in weight_map.values() if v}
    )

    if not shards:
        return False, "no model shards declared by weight_map"

    missing = [
        s for s in shards
        if not (model_dir / s).is_file()
    ]
    if missing:
        return (
            False,
            "missing shard(s): " + ", ".join(missing),
        )

    empty = [
        s for s in shards
        if (model_dir / s).stat().st_size <= 0
    ]
    if empty:
        return (
            False,
            "empty shard(s): " + ", ".join(empty),
        )

    return (
        True,
        f"{len(shards)} shard(s) verified at {model_dir}",
    )


def _validate_model_weights(
    model_dir: Path,
) -> tuple[bool, str]:
    index_path = model_dir / "model.safetensors.index.json"
    single_path = model_dir / "model.safetensors"

    if index_path.is_file():
        return _validate_sharded_safetensors(
            model_dir,
            index_path,
        )

    if single_path.is_file():
        if single_path.stat().st_size <= 0:
            return False, "model.safetensors is empty"
        return (
            True,
            f"model.safetensors verified at {model_dir}",
        )

    return (
        False,
        (
            "no model weights found "
            "(model.safetensors or "
            "model.safetensors.index.json)"
        ),
    )


def _validate_smolvlm_artifacts(
    artifacts_path: Path,
) -> tuple[bool, str]:
    model_dir = (
        artifacts_path / SMOLVLM_ARTIFACT_DIRECTORY
    )

    if not model_dir.is_dir():
        return (
            False,
            f"missing model directory: {model_dir}",
        )

    for name in (
        "config.json",
        "preprocessor_config.json",
    ):
        if not (model_dir / name).is_file():
            return False, f"missing required file: {name}"

    return _validate_model_weights(model_dir)


def _validate_code_formula_artifacts(
    artifacts_path: Path,
) -> tuple[bool, str]:
    model_dir = (
        artifacts_path / CODE_FORMULA_ARTIFACT_DIRECTORY
    )

    if not model_dir.is_dir():
        return (
            False,
            f"missing model directory: {model_dir}",
        )

    if not (model_dir / "config.json").is_file():
        return False, "missing required file: config.json"

    return _validate_model_weights(model_dir)


def _validate_picture_classifier_artifacts(
    artifacts_path: Path,
) -> tuple[bool, str]:
    try:
        from docling.datamodel.pipeline_options import (  # type: ignore
            DocumentPictureClassifierOptions,
        )
        opts = DocumentPictureClassifierOptions.from_preset(
            "document_figure_classifier_v2"
        )
        repo_cache_folder = getattr(
            opts,
            "repo_cache_folder",
            None,
        )

        dir_name = (
            repo_cache_folder
            if isinstance(repo_cache_folder, str)
            and repo_cache_folder
            else PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY
        )
    except Exception:
        dir_name = PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY

    model_dir = artifacts_path / dir_name

    if not model_dir.is_dir():
        return False, f"missing model directory: {dir_name}"

    if not (model_dir / "config.json").is_file():
        return False, f"missing required file: config.json in {dir_name}"

    ok, detail = _validate_model_weights(model_dir)
    if not ok:
        return False, f"{dir_name}: {detail}"
    return True, f"picture classifier verified: {dir_name}"


def _validate_tableformer_artifacts(
    artifacts_path: Path,
    mode: str = "accurate",
) -> tuple[bool, str]:
    repo_dir = (
        artifacts_path / TABLEFORMER_ARTIFACT_DIRECTORY
    )

    if not repo_dir.is_dir():
        return (
            False,
            f"missing repository directory: {repo_dir}",
        )

    mode_dir = (
        repo_dir / "model_artifacts" / "tableformer" / mode
    )

    if not mode_dir.is_dir():
        return (
            False,
            (
                f"missing tableformer/{mode} "
                f"directory: {mode_dir}"
            ),
        )

    config_path = mode_dir / "tm_config.json"
    if not config_path.is_file():
        return (
            False,
            f"missing tm_config.json in {mode_dir}",
        )

    weights = sorted(mode_dir.glob("*.safetensors"))
    if not weights:
        return (
            False,
            f"no .safetensors weights in {mode_dir}",
        )

    empty = [
        w.name
        for w in weights
        if w.stat().st_size <= 0
    ]
    if empty:
        return (
            False,
            "empty weight(s): " + ", ".join(empty),
        )

    return (
        True,
        f"{len(weights)} weight(s) verified at {mode_dir}",
    )


def _validate_rapidocr_artifacts(
    artifacts_path: Path,
) -> tuple[bool, str]:
    try:
        from docling.models.stages.ocr.rapid_ocr_model import (  # type: ignore
            RapidOcrModel,
            _backend_to_engine_type,
            _rapidocr_artifacts,
            _resolve_rapidocr,
        )
    except ImportError as exc:
        return False, f"cannot import RapidOCR internals: {exc}"

    backend = "torch"
    lang = "pt"

    try:
        model_folder = RapidOcrModel._model_repo_folder
    except AttributeError:
        model_folder = RAPIDOCR_ARTIFACT_DIRECTORY

    target_dir = artifacts_path / model_folder

    if not target_dir.is_dir():
        return False, f"missing model directory: {model_folder}"

    try:
        resolved = _resolve_rapidocr(lang, backend)
        engine = _backend_to_engine_type(backend)
        artifacts = _rapidocr_artifacts(
            target_dir,
            engine,
            resolved.ppocr_version,
            resolved.rapidocr_lang_token,
            need_det=True,
            need_cls=True,
            need_rec=True,
        )
    except Exception as exc:
        return False, f"failed to resolve RapidOCR torch:pt artifacts: {exc}"

    required_roles = {"det", "cls", "rec"}
    missing_roles = required_roles - set(artifacts)
    if missing_roles:
        return False, (
            f"RapidOCR artifacts incomplete for backend={backend} lang={lang}: "
            f"missing roles: {sorted(missing_roles)}"
        )

    missing_files: list[str] = []
    empty_files: list[str] = []
    for _role, artifact in artifacts.items():
        for path in artifact.files:
            if not path.is_file():
                missing_files.append(path.name)
            elif path.stat().st_size == 0:
                empty_files.append(path.name)

    if missing_files:
        return False, (
            f"RapidOCR artifacts incomplete for backend={backend} lang={lang}\n"
            f"missing: {', '.join(missing_files)}"
        )
    if empty_files:
        return False, (
            f"RapidOCR artifacts have empty files for backend={backend} lang={lang}\n"
            f"empty: {', '.join(empty_files)}"
        )

    ppocr_version = getattr(resolved, "ppocr_version", "unknown")
    rec_lang = getattr(resolved, "rapidocr_lang_token", "unknown")
    return True, (
        f"RapidOCR torch:pt artifacts verified: backend={backend} lang={lang} "
        f"ppocr_version={ppocr_version} rec_lang={rec_lang}"
    )


def _validate_layout_artifacts(
    artifacts_path: Path,
) -> tuple[bool, str]:
    model_dir = (
        artifacts_path / LAYOUT_ARTIFACT_DIRECTORY
    )

    if not model_dir.is_dir():
        return (
            False,
            f"missing model directory: {model_dir}",
        )

    for name in (
        "config.json",
        "preprocessor_config.json",
    ):
        if not (model_dir / name).is_file():
            return False, f"missing required file: {name}"

    return _validate_model_weights(model_dir)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    excluded_parts = {".cache", "_hf_runtime", "xet", "__pycache__"}
    excluded_suffixes = {".pyc", ".pyo", ".lock", ".tmp"}
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and not any(p in excluded_parts for p in item.parts)
        and item.suffix.lower() not in excluded_suffixes
    ):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def validate_manifest(
    manifest_path: Path,
    model_root: Path,
) -> tuple[bool, str]:
    if not manifest_path.is_file():
        return False, f"manifest not found: {manifest_path}"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read manifest: {exc}"

    schema = manifest.get("schema_version")
    if schema != MANIFEST_SCHEMA_VERSION:
        return False, f"schema_version mismatch: {schema!r} != {MANIFEST_SCHEMA_VERSION}"

    if manifest.get("parser") != PARSER_NAME:
        return False, f"parser mismatch: {manifest.get('parser')!r}"

    try:
        installed_version = importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        installed_version = None

    manifest_version = manifest.get("docling_version")
    if installed_version and manifest_version != installed_version:
        return False, (
            f"docling_version mismatch: "
            f"manifest={manifest_version!r}, installed={installed_version!r}"
        )

    if manifest.get("profile") != "full_cpu_local":
        return False, f"profile mismatch: {manifest.get('profile')!r}"

    offline = manifest.get("offline_validation", {})
    if not offline.get("passed"):
        return False, "offline_validation.passed is not True"
    if not offline.get("structural_pass"):
        return False, "offline_validation.structural_pass is not True"
    if not offline.get("component_pass"):
        return False, "offline_validation.component_pass is not True"
    if not offline.get("pipeline_initialized"):
        return False, "offline_validation.pipeline_initialized is not True"

    capabilities = manifest.get("capabilities", {})

    for cap_name in FULL_CPU_LOCAL_REQUIRED_CAPABILITIES:
        if cap_name not in capabilities:
            return False, f"required capability missing: {cap_name}"

        cap_data = capabilities[cap_name]
        if not isinstance(cap_data, dict):
            return False, f"capability {cap_name}: entry is not an object"

        if not cap_data.get("enabled"):
            return False, f"capability {cap_name}: enabled is not true"

        if not cap_data.get("present"):
            return False, f"capability {cap_name}: present is not true"

        subdir = cap_data.get("directory")
        if not subdir or not isinstance(subdir, str):
            return False, f"capability {cap_name}: directory is missing"

        cap_dir = model_root / subdir
        if not cap_dir.is_dir():
            return False, f"capability {cap_name}: model directory removed: {subdir}"

        stored_digest = cap_data.get("tree_digest")
        if not stored_digest or not isinstance(stored_digest, str):
            return False, f"capability {cap_name}: tree_digest is missing"

        stored_count = cap_data.get("file_count")
        if stored_count is None:
            return False, f"capability {cap_name}: file_count is missing"
        if not isinstance(stored_count, int) or stored_count <= 0:
            return False, f"capability {cap_name}: file_count must be > 0"

        current_digest, current_count = tree_digest(cap_dir)
        if current_digest != stored_digest:
            return False, f"tree digest mismatch for {cap_name}"
        if current_count != stored_count:
            return False, f"file_count mismatch for {cap_name}"

        stored_weight_files = cap_data.get("weight_files", [])
        for rel_path in stored_weight_files:
            abs_path = model_root / rel_path
            if not abs_path.is_file():
                return False, f"missing certified weight: {rel_path}"

    return True, "manifest valid"


def _normalize_device(value: str) -> AcceleratorDevice:
    if value == "cpu":
        return AcceleratorDevice.CPU
    if value == "cuda":
        return AcceleratorDevice.CUDA
    if value == "auto":
        return AcceleratorDevice.AUTO
    raise BenchmarkConfigurationError(
        f"Unsupported Docling accelerator device: {value!r}"
    )


def _effective_device(requested: str) -> str:
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _resolve_ocr_mode(value: str) -> OcrMode:
    mapping = {
        "auto": OcrMode.PDF_AWARE_LAYOUT_REGIONS,
        "pdf_aware_layout_regions": OcrMode.PDF_AWARE_LAYOUT_REGIONS,
        "layout_regions": OcrMode.LAYOUT_REGIONS,
        "forced": OcrMode.FULL_PAGE,
        "full_page": OcrMode.FULL_PAGE,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise BenchmarkConfigurationError(
            f"Unsupported Docling OCR mode: {value!r}"
        ) from exc


def _resolve_table_mode(value: str) -> TableFormerMode:
    mapping = {
        "accurate": TableFormerMode.ACCURATE,
        "fast": TableFormerMode.FAST,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise BenchmarkConfigurationError(
            f"Unsupported Docling TableFormer mode: {value!r}"
        ) from exc


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _cref_value(value: Any) -> str | None:
    if value is None:
        return None

    candidate = getattr(value, "cref", None)
    if candidate is not None:
        return str(candidate)

    return str(value)


def _bbox_to_dict(bbox: Any) -> dict[str, Any] | None:
    if bbox is None:
        return None

    result: dict[str, Any] = {}
    for name in ("l", "t", "r", "b"):
        value = getattr(bbox, name, None)
        if value is not None:
            result[name] = float(value)

    origin = getattr(bbox, "coord_origin", None)
    if origin is not None:
        result["coord_origin"] = str(
            _enum_value(origin)
        )

    return result or None


def _serialize_item_for_page(
    item: Any,
    level: int,
    page_number: int,
) -> dict[str, Any]:
    label = _enum_value(
        getattr(item, "label", None)
    )
    content_layer = _enum_value(
        getattr(item, "content_layer", None)
    )

    provenance: list[dict[str, Any]] = []

    for prov in getattr(item, "prov", None) or []:
        if getattr(prov, "page_no", None) != page_number:
            continue

        provenance.append(
            {
                "page_no": int(prov.page_no),
                "bbox": _bbox_to_dict(
                    getattr(prov, "bbox", None)
                ),
                "charspan": (
                    list(prov.charspan)
                    if getattr(prov, "charspan", None)
                    is not None
                    else None
                ),
            }
        )

    text = getattr(item, "text", None)

    payload = {
        "class": type(item).__name__,
        "level": int(level),
        "label": (
            str(label)
            if label is not None
            else None
        ),
        "text": (
            str(text)
            if text is not None
            else None
        ),
        "content_layer": (
            str(content_layer)
            if content_layer is not None
            else None
        ),
        "parent": _cref_value(
            getattr(item, "parent", None)
        ),
        "self_ref": _cref_value(
            getattr(item, "self_ref", None)
        ),
        "provenance": provenance,
    }

    # Picture classification is enrichment metadata. Preserve it only when
    # Docling actually produced a classification, keeping existing profiles'
    # parser-native contract unchanged when classification is disabled.
    if type(item).__name__ == "PictureItem":
        meta = getattr(item, "meta", None)
        classification = (
            getattr(meta, "classification", None)
            if meta is not None
            else None
        )

        if classification is not None:
            if not hasattr(classification, "model_dump"):
                raise TypeError(
                    "Picture classification metadata does not expose "
                    "model_dump(); refusing to serialize unknown schema."
                )

            payload["picture_classification"] = (
                classification.model_dump(
                    mode="json",
                    exclude_none=True,
                )
            )

        description = (
            getattr(meta, "description", None)
            if meta is not None
            else None
        )

        if description is not None:
            if not hasattr(
                description,
                "model_dump",
            ):
                raise TypeError(
                    "Picture description metadata does "
                    "not expose model_dump(); refusing to "
                    "serialize unknown schema."
                )

            payload["picture_description"] = (
                description.model_dump(
                    mode="json",
                    exclude_none=True,
                )
            )

    return payload


def _new_page_summary(
    page_number: int,
) -> dict[str, Any]:
    return {
        "page_number": page_number,
        "layout_boxes": 0,
        "tables_detected": 0,
        "images_detected": 0,
        "headings_detected": 0,
        "lists_detected": 0,
        "formulas_detected": 0,
        "captions_detected": 0,
        "page_headers_detected": 0,
        "page_footers_detected": 0,
        "footnotes_detected": 0,
        "text_blocks_detected": 0,
        "code_blocks_detected": 0,
        "box_class_counts": {},
    }


def _summary_from_counts(
    counts: Counter[str],
) -> dict[str, Any]:
    return {
        "layout_boxes": sum(counts.values()),
        "tables_detected": counts["table"],
        "images_detected": counts["picture"],
        "headings_detected": (
            counts["title"]
            + counts["section_header"]
        ),
        "lists_detected": counts["list_item"],
        "formulas_detected": counts["formula"],
        "captions_detected": counts["caption"],
        "page_headers_detected": counts["page_header"],
        "page_footers_detected": counts["page_footer"],
        "footnotes_detected": counts["footnote"],
        "text_blocks_detected": (
            counts["text"]
            + counts["paragraph"]
        ),
        "code_blocks_detected": counts["code"],
        "charts_detected": None,
        "box_class_counts": dict(
            sorted(counts.items())
        ),
    }


def build_docling_page_contract(
    document: Any,
    page_count: int,
) -> tuple[
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    set[int],
]:
    page_texts: list[str] = []
    native_pages: list[dict[str, Any]] = [
        {
            "page_number": page_number,
            "items": [],
            "label_counts": {},
        }
        for page_number in range(1, page_count + 1)
    ]
    page_counts: list[Counter[str]] = [
        Counter()
        for _ in range(page_count)
    ]
    global_counts: Counter[str] = Counter()

    document_pages = getattr(
        document,
        "pages",
        {},
    )
    observed_pages: set[int] = set()

    if isinstance(document_pages, dict):
        for key in document_pages:
            try:
                page_number = int(key)
            except (TypeError, ValueError):
                continue

            if 1 <= page_number <= page_count:
                observed_pages.add(page_number)

    for page_number in range(1, page_count + 1):
        if (
            observed_pages
            and page_number not in observed_pages
        ):
            page_texts.append("")
            continue

        try:
            page_text = document.export_to_markdown(
                page_no=page_number,
                # Picture descriptions are stored in parser_native only;
                # block them from the compared markdown (adendo §2, §9).
                blocked_meta_names={"description"},
            )
        except Exception:
            page_text = ""
        else:
            observed_pages.add(page_number)

        page_texts.append(
            str(page_text or "")
        )

    for item, level in document.iterate_items():
        provenance = getattr(
            item,
            "prov",
            None,
        ) or []

        page_numbers = {
            int(prov.page_no)
            for prov in provenance
            if (
                getattr(prov, "page_no", None)
                is not None
                and 1
                <= int(prov.page_no)
                <= page_count
            )
        }

        if not page_numbers:
            continue

        label_value = _enum_value(
            getattr(item, "label", None)
        )
        label = (
            str(label_value)
            if label_value is not None
            else type(item).__name__
        )

        global_counts[label] += 1

        for page_number in sorted(page_numbers):
            page_counts[
                page_number - 1
            ][label] += 1

            native_pages[
                page_number - 1
            ]["items"].append(
                _serialize_item_for_page(
                    item,
                    level,
                    page_number,
                )
            )

    parser_page_elements: list[
        dict[str, Any]
    ] = []

    for page_number, counts in enumerate(
        page_counts,
        start=1,
    ):
        summary = _new_page_summary(
            page_number
        )
        summary.update(
            _summary_from_counts(counts)
        )
        parser_page_elements.append(
            summary
        )
        native_pages[
            page_number - 1
        ]["label_counts"] = dict(
            sorted(counts.items())
        )

    parser_summary = _summary_from_counts(
        global_counts
    )

    return (
        page_texts,
        parser_page_elements,
        native_pages,
        parser_summary,
        observed_pages,
    )


def calculate_sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def load_cached_inventory(
    input_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """
    Load the parser-independent Source Inventory.

    Docling intentionally does not build this inventory itself because
    the common inventory implementation uses PyMuPDF. Keeping inventory
    generation outside the Docling process avoids adding a second PDF
    parser dependency to the measured Docling runtime.
    """
    destination = (
        output_root
        / "_source_inventory"
        / f"{input_path.stem}.json"
    )

    if not destination.is_file():
        raise BenchmarkConfigurationError(
            "Source Inventory not found for Docling run: "
            f"{destination}. Build the common Source Inventory "
            "before running the parser benchmark."
        )

    inventory = json.loads(
        destination.read_text(
            encoding="utf-8",
        )
    )

    current_sha = calculate_sha256(
        input_path
    )
    inventory_sha = inventory.get(
        "sha256"
    )

    if inventory_sha != current_sha:
        raise BenchmarkConfigurationError(
            "Source Inventory SHA-256 does not match the input PDF. "
            f"Inventory: {destination}. "
            "Rebuild the common Source Inventory before benchmarking."
        )

    return inventory

def count_log_lines(
    path: Path,
    word: str,
) -> int:
    if not path.is_file():
        return 0

    folded = word.casefold()

    return sum(
        folded in line.casefold()
        for line in path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    )


def _resolve_profile_runtime(
    profile: dict[str, Any],
    device_override: str | None = None,
    threads_override: int | None = None,
    model_artifacts_override: Path | None = None,
) -> dict[str, Any]:
    resolved = dict(profile)

    requested_device = (
        device_override
        or str(
            resolved.get(
                "accelerator_device",
                "cpu",
            )
        )
    )

    configured_threads = (
        threads_override
        if threads_override is not None
        else int(
            resolved.get(
                "threads",
                2,
            )
        )
    )

    if configured_threads <= 0:
        raise BenchmarkConfigurationError(
            "Docling threads must be greater than zero."
        )

    try:
        parallelism = resolve_parallelism(
            configured_threads
        )
    except ValueError as exc:
        raise BenchmarkConfigurationError(
            str(exc)
        ) from exc

    if threads_override is not None:
        effective_threads = configured_threads
        parallelism_source = "cli_override"
    else:
        effective_threads = int(
            parallelism["effective"]
        )
        parallelism_source = str(
            parallelism["source"]
        )

    model_artifacts_path = (
        model_artifacts_override
        if model_artifacts_override is not None
        else Path(
            resolved.get("model_artifacts_path")
            or DEFAULT_MODEL_ARTIFACTS
        )
    )

    resolved["accelerator_device"] = requested_device
    resolved["threads_configured"] = configured_threads
    resolved["available_logical_cpus"] = int(
        parallelism["available_logical_cpus"]
    )
    resolved["threads"] = effective_threads
    resolved["parallelism_source"] = (
        parallelism_source
    )
    resolved["model_artifacts_path"] = str(
        model_artifacts_path
    )

    return resolved

def _resolve_picture_area_threshold(
    profile: dict[str, Any],
    default: float,
) -> float:
    raw_threshold = profile.get(
        "picture_area_threshold",
        default,
    )

    try:
        picture_area_threshold = float(
            raw_threshold
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkConfigurationError(
            "picture_area_threshold must be numeric."
        ) from exc

    if not 0.0 <= picture_area_threshold <= 1.0:
        raise BenchmarkConfigurationError(
            "picture_area_threshold must be between "
            "0.0 and 1.0."
        )

    return picture_area_threshold


def _configure_picture_description(
    options: PdfPipelineOptions,
    profile: dict[str, Any],
) -> None:
    if not options.do_picture_description:
        return

    preset = str(
        profile.get(
            "picture_description_preset",
            "",
        )
    )

    if preset != "smolvlm":
        raise BenchmarkConfigurationError(
            "Unsupported Docling picture-description "
            f"preset: {preset!r}. "
            "Supported preset: 'smolvlm'."
        )

    prompt = str(
        profile.get(
            "picture_description_prompt",
            "",
        )
    ).strip()

    if not prompt:
        raise BenchmarkConfigurationError(
            "picture_description_prompt must be "
            "non-empty when picture description "
            "is enabled."
        )

    description_options = copy.deepcopy(
        smolvlm_picture_description
    )

    picture_area_threshold = (
        _resolve_picture_area_threshold(
            profile,
            default=float(
                description_options
                .picture_area_threshold
            ),
        )
    )

    description_options.prompt = prompt
    description_options.picture_area_threshold = (
        picture_area_threshold
    )

    options.picture_description_options = (
        description_options
    )


def _build_pipeline_options(
    profile: dict[str, Any],
) -> PdfPipelineOptions:
    model_artifacts_path = Path(
        profile["model_artifacts_path"]
    )

    if not model_artifacts_path.is_dir():
        raise BenchmarkConfigurationError(
            "Docling model artifacts directory does not exist: "
            f"{model_artifacts_path}"
        )

    layout_ok, layout_detail = _validate_layout_artifacts(
        model_artifacts_path
    )
    if not layout_ok:
        raise BenchmarkConfigurationError(
            "Docling layout model artifacts are incomplete: "
            f"{layout_detail}"
        )

    if bool(
        profile.get(
            "picture_description",
            False,
        )
    ):
        (
            smolvlm_ok,
            smolvlm_detail,
        ) = _validate_smolvlm_artifacts(
            model_artifacts_path
        )
        if not smolvlm_ok:
            raise BenchmarkConfigurationError(
                "Docling SmolVLM artifacts are incomplete: "
                f"{smolvlm_detail}"
            )

    if bool(
        profile.get(
            "picture_classification",
            False,
        )
    ):
        (
            classifier_ok,
            classifier_detail,
        ) = _validate_picture_classifier_artifacts(
            model_artifacts_path
        )
        if not classifier_ok:
            raise BenchmarkConfigurationError(
                "Docling picture classifier artifacts "
                f"are incomplete: {classifier_detail}"
            )

    if bool(
        profile.get("formula_enrichment", False)
    ) or bool(
        profile.get("code_enrichment", False)
    ):
        (
            formula_ok,
            formula_detail,
        ) = _validate_code_formula_artifacts(
            model_artifacts_path
        )
        if not formula_ok:
            raise BenchmarkConfigurationError(
                "Docling CodeFormulaV2 artifacts are incomplete: "
                f"{formula_detail}"
            )

    if bool(
        profile.get(
            "table_structure",
            True,
        )
    ):
        table_mode = str(
            profile.get("table_mode", "accurate")
        )
        (
            tableformer_ok,
            tableformer_detail,
        ) = _validate_tableformer_artifacts(
            model_artifacts_path,
            mode=table_mode,
        )
        if not tableformer_ok:
            raise BenchmarkConfigurationError(
                "Docling TableFormer artifacts are incomplete: "
                f"{tableformer_detail}"
            )

    if bool(
        profile.get(
            "ocr_enabled",
            False,
        )
    ):
        (
            rapidocr_ok,
            rapidocr_detail,
        ) = _validate_rapidocr_artifacts(
            model_artifacts_path
        )
        if not rapidocr_ok:
            raise BenchmarkConfigurationError(
                "Docling RapidOCR artifacts are incomplete: "
                f"{rapidocr_detail}"
            )

    if bool(
        profile.get(
            "chart_extraction",
            False,
        )
    ):
        (
            granite_ok,
            granite_detail,
        ) = _validate_granite_chart_v4_artifacts(
            model_artifacts_path
        )

        if not granite_ok:
            raise BenchmarkConfigurationError(
                (
                    "Docling Granite Vision V4 "
                    "artifacts are incomplete: "
                    f"{granite_detail}"
                )
            )

    options = PdfPipelineOptions(
        artifacts_path=model_artifacts_path,
    )

    requested_device = str(
        profile["accelerator_device"]
    )
    options.accelerator_options = (
        AcceleratorOptions(
            num_threads=int(
                profile["threads"]
            ),
            device=_normalize_device(
                requested_device
            ),
        )
    )

    options.do_ocr = bool(
        profile["ocr_enabled"]
    )

    if options.do_ocr:
        engine = str(
            profile.get(
                "ocr_engine",
                "",
            )
        )
        if engine != "rapidocr":
            raise BenchmarkConfigurationError(
                "Docling v2 phase-1 supports the formal "
                "RapidOCR profile only. "
                f"Received engine={engine!r}."
            )

        backend = str(
            profile.get(
                "ocr_backend",
                "",
            )
        )
        language = str(
            profile.get(
                "ocr_language",
                "",
            )
        )

        options.ocr_options = (
            RapidOcrOptions(
                lang=[language],
                backend=backend,
                mode=_resolve_ocr_mode(
                    str(
                        profile[
                            "ocr_mode"
                        ]
                    )
                ),
                scale=float(
                    profile.get(
                        "ocr_scale",
                        3.0,
                    )
                ),
                print_verbose=False,
            )
        )

    options.do_table_structure = bool(
        profile.get(
            "table_structure",
            True,
        )
    )

    if options.do_table_structure:
        options.table_structure_options = (
            TableStructureOptions(
                do_cell_matching=bool(
                    profile.get(
                        "table_cell_matching",
                        True,
                    )
                ),
                mode=_resolve_table_mode(
                    str(
                        profile.get(
                            "table_mode",
                            "accurate",
                        )
                    )
                ),
            )
        )

    options.do_picture_description = bool(
        profile.get(
            "picture_description",
            False,
        )
    )
    options.do_picture_classification = bool(
        profile.get(
            "picture_classification",
            False,
        )
    )
    options.do_chart_extraction = bool(
        profile.get(
            "chart_extraction",
            False,
        )
    )
    options.do_code_enrichment = bool(
        profile.get(
            "code_enrichment",
            False,
        )
    )
    options.do_formula_enrichment = bool(
        profile.get(
            "formula_enrichment",
            False,
        )
    )
    options.generate_picture_images = bool(
        profile.get(
            "generate_picture_images",
            False,
        )
    )
    options.images_scale = float(
        profile.get(
            "images_scale",
            1.0,
        )
    )
    options.enable_remote_services = bool(
        profile.get(
            "remote_services_enabled",
            False,
        )
    )

    # Heading hierarchy — introduced in docling ≥2.15; guarded import so the
    # adapter compiles without docling installed (WSL dev environment).
    if bool(profile.get("heading_hierarchy", False)):
        try:
            from docling.datamodel.pipeline_options import (  # type: ignore
                HeadingHierarchyOptions,
            )
            heading_opts = HeadingHierarchyOptions(
                enabled=True,
                use_bookmarks=bool(
                    profile.get("heading_use_bookmarks", True)
                ),
                use_numbering=bool(
                    profile.get("heading_use_numbering", True)
                ),
                use_style=bool(
                    profile.get("heading_use_style", True)
                ),
                use_font_style=bool(
                    profile.get("heading_use_font_style", True)
                ),
                style_size_tolerance=float(
                    profile.get("heading_style_size_tolerance", 0.05)
                ),
                max_level=int(
                    profile.get("heading_max_level", 6)
                ),
                bookmark_match_threshold=float(
                    profile.get("heading_bookmark_match_threshold", 0.8)
                ),
            )
            options.heading_hierarchy_options = heading_opts
            # use_style requires parsed page images for font-size analysis
            if bool(profile.get("heading_use_style", True)):
                options.generate_parsed_pages = True
        except ImportError:
            pass  # not available in this docling version; skip silently

    # TableFormer V2 — experimental; only activated when table_engine is
    # explicitly set to "tableformer_v2" in the profile.
    table_engine = str(
        profile.get("table_engine", "tableformer_v1")
    )
    if (
        options.do_table_structure
        and table_engine == "tableformer_v2"
    ):
        try:
            from docling.datamodel.pipeline_options import (  # type: ignore
                TableStructureV2Options,
            )
            options.table_structure_options = TableStructureV2Options(
                do_cell_matching=bool(
                    profile.get("table_cell_matching", True)
                )
            )
        except ImportError:
            pass  # V2 not available; V1 options already set above

    _configure_picture_description(
        options,
        profile,
    )

    return options


def preflight_profile(
    profile_name: str,
    *,
    model_artifacts_override: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # --------------------------------------------------
    # Profile configuration
    # --------------------------------------------------

    try:
        raw_profile = get_profile(PARSER_NAME, profile_name)
    except Exception as exc:
        checks.append(
            make_check(
                "profile configuration",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )
        return make_result(PARSER_NAME, profile_name, checks)

    checks.append(
        make_check("profile configuration", "pass", profile_name)
    )

    # --------------------------------------------------
    # Runtime resolution (model_artifacts_override takes precedence)
    # --------------------------------------------------

    try:
        profile = _resolve_profile_runtime(
            raw_profile,
            model_artifacts_override=model_artifacts_override,
        )
    except Exception as exc:
        checks.append(
            make_check(
                "profile resolution",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )
        return make_result(PARSER_NAME, profile_name, checks)

    # --------------------------------------------------
    # Threads
    # --------------------------------------------------

    configured_threads = int(
        profile["threads_configured"]
    )
    available_cpus = int(
        profile["available_logical_cpus"]
    )
    effective_threads = int(
        profile["threads"]
    )

    checks.append(
        make_check(
            "threads configured fallback",
            "pass",
            str(configured_threads),
        )
    )
    checks.append(
        make_check(
            "logical CPUs available",
            "pass" if available_cpus > 0 else "fail",
            str(available_cpus),
        )
    )
    checks.append(
        make_check(
            "threads effective",
            "pass" if effective_threads > 0 else "fail",
            str(effective_threads),
        )
    )

    # --------------------------------------------------
    # Accelerator device
    # --------------------------------------------------

    device = str(profile.get("accelerator_device", ""))
    valid_devices = {"cpu", "cuda", "auto"}
    if device in valid_devices:
        checks.append(make_check("accelerator_device", "pass", device))
    else:
        checks.append(
            make_check(
                "accelerator_device",
                "fail",
                f"must be one of {sorted(valid_devices)}, got {device!r}",
            )
        )

    # --------------------------------------------------
    # Model artifacts path
    # --------------------------------------------------

    artifacts_path = Path(
        profile.get("model_artifacts_path", "")
    )
    checks.append(
        make_check(
            "model artifacts path",
            "pass" if artifacts_path.is_dir() else "fail",
            str(artifacts_path),
        )
    )

    if bool(
        profile.get(
            "chart_extraction",
            False,
        )
    ):
        (
            granite_ok,
            granite_detail,
        ) = _validate_granite_chart_v4_artifacts(
            artifacts_path
        )

        checks.append(
            make_check(
                "chart extraction Granite Vision V4",
                "pass" if granite_ok else "fail",
                granite_detail,
            )
        )

    # --------------------------------------------------
    # Layout model (always required for PDF pipeline)
    # --------------------------------------------------

    (
        layout_ok,
        layout_detail,
    ) = _validate_layout_artifacts(artifacts_path)
    checks.append(
        make_check(
            "layout model",
            "pass" if layout_ok else "fail",
            layout_detail,
        )
    )

    # --------------------------------------------------
    # OCR
    # --------------------------------------------------

    ocr_enabled = bool(
        profile.get(
            "ocr_enabled",
            False,
        )
    )

    ocr_mode = str(
        profile.get(
            "ocr_mode",
            "disabled",
        )
    )

    if not ocr_enabled:
        if ocr_mode != "disabled":
            checks.append(
                make_check(
                    "ocr_mode",
                    "fail",
                    (
                        "ocr_enabled is false "
                        f"but ocr_mode={ocr_mode!r}"
                    ),
                )
            )
        else:
            checks.append(
                make_check(
                    "ocr_mode",
                    "pass",
                    "disabled",
                )
            )

    else:
        if ocr_mode == "disabled":
            checks.append(
                make_check(
                    "ocr_mode",
                    "fail",
                    (
                        "ocr_enabled is true "
                        "but ocr_mode is disabled"
                    ),
                )
            )
        else:
            try:
                _resolve_ocr_mode(
                    ocr_mode
                )
            except Exception as exc:
                checks.append(
                    make_check(
                        "ocr_mode",
                        "fail",
                        (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    )
                )
            else:
                checks.append(
                    make_check(
                        "ocr_mode",
                        "pass",
                        ocr_mode,
                    )
                )

    if ocr_enabled:
        ocr_engine = str(profile.get("ocr_engine", ""))
        if ocr_engine != "rapidocr":
            checks.append(
                make_check(
                    "ocr_engine",
                    "fail",
                    f"only 'rapidocr' is supported, got {ocr_engine!r}",
                )
            )
        else:
            checks.append(make_check("ocr_engine", "pass", ocr_engine))

        ocr_backend = str(profile.get("ocr_backend", ""))
        checks.append(
            make_check(
                "ocr_backend",
                "pass" if ocr_backend else "fail",
                ocr_backend or "empty",
            )
        )

        (
            rapidocr_ok,
            rapidocr_detail,
        ) = _validate_rapidocr_artifacts(artifacts_path)
        checks.append(
            make_check(
                "ocr model RapidOCR",
                "pass" if rapidocr_ok else "fail",
                rapidocr_detail,
            )
        )

    # --------------------------------------------------
    # Table mode
    # --------------------------------------------------

    table_mode_str = str(profile.get("table_mode", "accurate"))
    try:
        _resolve_table_mode(table_mode_str)
        checks.append(make_check("table_mode", "pass", table_mode_str))
    except Exception as exc:
        checks.append(
            make_check(
                "table_mode",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )

    if bool(profile.get("table_structure", True)):
        (
            tableformer_ok,
            tableformer_detail,
        ) = _validate_tableformer_artifacts(
            artifacts_path,
            mode=table_mode_str,
        )
        checks.append(
            make_check(
                "table structure model",
                "pass" if tableformer_ok else "fail",
                tableformer_detail,
            )
        )

    # --------------------------------------------------
    # Heading hierarchy
    # --------------------------------------------------

    if bool(profile.get("heading_hierarchy", False)):
        try:
            from docling.datamodel.pipeline_options import (  # type: ignore
                HeadingHierarchyOptions,
            )
            checks.append(
                make_check(
                    "heading hierarchy support",
                    "pass",
                    "HeadingHierarchyOptions available",
                )
            )
        except ImportError:
            checks.append(
                make_check(
                    "heading hierarchy support",
                    "fail",
                    "HeadingHierarchyOptions not available in this docling version",
                )
            )

    # --------------------------------------------------
    # Table engine
    # --------------------------------------------------

    table_engine_str = str(profile.get("table_engine", "tableformer_v1"))
    if table_engine_str == "tableformer_v2":
        try:
            from docling.datamodel.pipeline_options import (  # type: ignore
                TableStructureV2Options,
            )
            checks.append(
                make_check(
                    "table engine v2 support",
                    "pass",
                    "TableStructureV2Options available",
                )
            )
        except ImportError:
            checks.append(
                make_check(
                    "table engine v2 support",
                    "fail",
                    "TableStructureV2Options not available in this docling version",
                )
            )
    else:
        checks.append(
            make_check("table engine", "pass", table_engine_str)
        )

    # --------------------------------------------------
    # CUDA
    # --------------------------------------------------

    if device == "cuda":
        cuda_ok = torch.cuda.is_available()
        checks.append(
            make_check(
                "CUDA availability",
                "pass" if cuda_ok else "fail",
                "available" if cuda_ok else "torch.cuda.is_available() returned False",
            )
        )
    elif device == "auto":
        resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        checks.append(
            make_check(
                "CUDA availability",
                "pass",
                f"auto → {resolved_device}",
            )
        )

    # --------------------------------------------------
    # Picture description
    # --------------------------------------------------

    if bool(profile.get("picture_description", False)):
        preset = str(
            profile.get(
                "picture_description_preset",
                "",
            )
        )

        checks.append(
            make_check(
                "picture description preset",
                "pass" if preset == "smolvlm" else "fail",
                preset or "empty",
            )
        )

        prompt = str(
            profile.get(
                "picture_description_prompt",
                "",
            )
        ).strip()

        checks.append(
            make_check(
                "picture description prompt",
                "pass" if prompt else "fail",
                "configured" if prompt else "empty",
            )
        )

        try:
            picture_area_threshold = (
                _resolve_picture_area_threshold(
                    profile,
                    default=float(
                        smolvlm_picture_description
                        .picture_area_threshold
                    ),
                )
            )
        except BenchmarkConfigurationError as exc:
            checks.append(
                make_check(
                    "picture area threshold",
                    "fail",
                    str(exc),
                )
            )
        else:
            checks.append(
                make_check(
                    "picture area threshold",
                    "pass",
                    str(picture_area_threshold),
                )
            )

        remote_services = bool(
            profile.get(
                "remote_services_enabled",
                False,
            )
        )

        checks.append(
            make_check(
                "picture description locality",
                "pass" if not remote_services else "fail",
                "local" if not remote_services else "remote services enabled",
            )
        )

        (
            smolvlm_ok,
            smolvlm_detail,
        ) = _validate_smolvlm_artifacts(artifacts_path)
        checks.append(
            make_check(
                "picture description model SmolVLM",
                "pass" if smolvlm_ok else "fail",
                smolvlm_detail,
            )
        )

    # --------------------------------------------------
    # Picture classification
    # --------------------------------------------------

    if bool(profile.get("picture_classification", False)):
        (
            classifier_ok,
            classifier_detail,
        ) = _validate_picture_classifier_artifacts(
            artifacts_path
        )
        checks.append(
            make_check(
                "picture classification model",
                "pass" if classifier_ok else "fail",
                classifier_detail,
            )
        )

    # --------------------------------------------------
    # Formula / code enrichment
    # --------------------------------------------------

    if bool(
        profile.get("formula_enrichment", False)
    ) or bool(
        profile.get("code_enrichment", False)
    ):
        (
            formula_ok,
            formula_detail,
        ) = _validate_code_formula_artifacts(
            artifacts_path
        )
        checks.append(
            make_check(
                "formula/code model CodeFormulaV2",
                "pass" if formula_ok else "fail",
                formula_detail,
            )
        )

    # --------------------------------------------------
    # Certified manifest
    # --------------------------------------------------

    if profile_name == "full_cpu_local":
        manifest_path = (
            artifacts_path.parent.parent
            / "manifests"
            / MANIFEST_FILENAME
        )

        manifest_ok, manifest_detail = validate_manifest(
            manifest_path,
            artifacts_path,
        )

        checks.append(
            make_check(
                "certified manifest",
                "pass" if manifest_ok else "fail",
                manifest_detail,
            )
        )

    return make_result(PARSER_NAME, profile_name, checks)


def main() -> None:
    args = parse_args()

    artifact_policy: ArtifactPolicy = (
        args.artifact_policy
    )

    input_path = args.input.resolve()

    if not input_path.is_file():
        raise SystemExit(
            f"Input not found: {input_path}"
        )

    profile = _resolve_profile_runtime(
        get_profile(
            PARSER_NAME,
            args.profile,
        ),
        device_override=args.device,
        threads_override=args.threads,
        model_artifacts_override=args.model_artifacts_path,
    )

    normalization_config = (
        get_normalization_config()
    )
    tokenizer_name = (
        get_reference_tokenizer()
    )

    paths = build_output_paths(
        args.output_root,
        PARSER_NAME,
        input_path.stem,
        args.profile,
    )

    inventory = load_cached_inventory(
        input_path,
        args.output_root,
    )
    page_count = int(
        inventory["pages"]
    )

    parser_version = _package_version(
        "docling"
    )
    docling_core_version = (
        _package_version(
            "docling-core"
        )
    )
    rapidocr_version = (
        _package_version(
            "rapidocr"
        )
    )

    requested_device = str(
        profile["accelerator_device"]
    )
    resolved_device = _effective_device(
        requested_device
    )

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:       {PARSER_DISPLAY_NAME}")
    print(f"Version:      {parser_version}")
    print(f"Input:        {input_path}")
    print(f"Profile:      {args.profile}")
    print(
        "OCR enabled:  "
        f"{profile['ocr_enabled']}"
    )
    print(
        "OCR mode:     "
        f"{profile['ocr_mode']}"
    )
    print(
        "OCR engine:   "
        f"{profile.get('ocr_engine')}"
    )
    print(
        "OCR backend:  "
        f"{profile.get('ocr_backend')}"
    )
    print(
        "OCR language: "
        f"{profile.get('ocr_language')}"
    )
    print(
        "OCR scale:    "
        f"{profile.get('ocr_scale')}"
    )
    print(
        "Tables:       "
        f"{profile.get('table_structure')}"
    )
    print(
        "Table mode:   "
        f"{profile.get('table_mode')}"
    )
    print(
        "Device:       "
        f"{requested_device}"
    )
    print(
        "Resolved:     "
        f"{resolved_device}"
    )
    print(
        "Threads:      "
        f"{profile['threads']} "
        f"(configured={profile['threads_configured']}, "
        f"available={profile['available_logical_cpus']}, "
        f"source={profile['parallelism_source']})"
    )
    print(
        "Models:       "
        f"{profile['model_artifacts_path']}"
    )
    print(
        f"Tokenizer:    {tokenizer_name}"
    )
    print(
        f"Output:       {paths.output_dir}"
    )
    print(
        "Artifacts:    "
        + ", ".join(
            artifact_policy.as_list()
        )
    )
    print(f"Verbose:      {args.verbose}")
    print("=" * 72)

    pipeline_options = (
        _build_pipeline_options(
            profile
        )
    )

    converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF
        ],
        format_options={
            InputFormat.PDF: (
                PdfFormatOption(
                    pipeline_options=(
                        pipeline_options
                    ),
                )
            )
        },
    )

    monitor = ResourceMonitor()
    pipeline_started = perf_counter()
    monitor.start()

    captured_warning_messages: list[str] = []

    try:
        with parser_output_context(
            run_log_path=paths.run_log,
            keep_run_log=(
                artifact_policy.includes(
                    "run.log"
                )
            ),
            verbose=args.verbose,
        ):
            with warnings.catch_warnings(
                record=True
            ) as warning_records:
                warnings.simplefilter(
                    "always"
                )

                initialization_started = (
                    perf_counter()
                )

                converter.initialize_pipeline(
                    InputFormat.PDF
                )

                initialization_seconds = (
                    perf_counter()
                    - initialization_started
                )

                extraction_started = (
                    perf_counter()
                )

                conversion_result = (
                    converter.convert(
                        input_path,
                        raises_on_error=True,
                    )
                )

                extraction_seconds = (
                    perf_counter()
                    - extraction_started
                )

                captured_warning_messages = [
                    str(record.message)
                    for record in warning_records
                ]
    except Exception:
        monitor.stop()
        raise

    document = conversion_result.document

    (
        page_texts,
        parser_page_elements,
        parser_native_pages,
        parser_summary,
        observed_pages,
    ) = build_docling_page_contract(
        document,
        page_count,
    )

    artifact_input = ParserArtifactInput(
        native_markdown=join_page_texts(page_texts),
        source_page_markdown=page_texts,
        enriched_page_markdown=None,
        page_mapping_status="complete",
        parser_page_elements=parser_page_elements,
        parser_native_pages=parser_native_pages,
        derived_content_by_page=[[] for _ in page_texts],
        raw_origin_kind="adapter_assembled_declared",
        raw_origin_details="page_texts join",
    )

    artifact_result = finalize_artifacts(
        paths=paths,
        document_id=input_path.stem,
        source_file=input_path.name,
        parser_name=PARSER_NAME,
        profile_name=args.profile,
        artifact_input=artifact_input,
        tokenizer_name=tokenizer_name,
        normalization_config=(
            normalization_config
        ),
        artifact_policy=artifact_policy,
    )

    resources = monitor.stop()

    pipeline_seconds = (
        perf_counter()
        - pipeline_started
    )

    source_summary = dict(
        inventory
    )
    source_summary.pop(
        "per_page",
        None,
    )

    source_objective = {
        "native_text_blocks": (
            inventory[
                "native_text"
            ]["text_blocks"]
        ),
        "embedded_image_occurrences": (
            inventory[
                "images"
            ][
                "embedded_image_occurrences"
            ]
        ),
        "unique_embedded_image_xrefs": (
            inventory[
                "images"
            ][
                "unique_embedded_image_xrefs"
            ]
        ),
        "drawing_groups": (
            inventory[
                "vector_content"
            ]["drawing_groups"]
        ),
        "pages_without_native_text": (
            inventory[
                "native_text"
            ][
                "pages_without_native_text"
            ]
        ),
    }

    input_bytes = input_path.stat().st_size
    clean_bytes = (
        artifact_result[
            "output"
        ][
            "clean_markdown_bytes"
        ]
    )
    size_ratio = (
        round(
            input_bytes
            / clean_bytes,
            6,
        )
        if clean_bytes
        else None
    )

    pages_processed = len(
        observed_pages
    )
    failed_pages = max(
        page_count
        - pages_processed,
        0,
    )

    if artifact_policy.includes(
        "run.log"
    ):
        log_warning_lines = (
            count_log_lines(
                paths.run_log,
                "warning",
            )
        )
        log_error_lines = (
            count_log_lines(
                paths.run_log,
                "error",
            )
        )
    else:
        log_warning_lines = None
        log_error_lines = None

    conversion_status = _enum_value(
        conversion_result.status
    )

    document_collections = {
        "texts": len(
            getattr(
                document,
                "texts",
                [],
            )
        ),
        "tables": len(
            getattr(
                document,
                "tables",
                [],
            )
        ),
        "pictures": len(
            getattr(
                document,
                "pictures",
                [],
            )
        ),
        "key_value_items": len(
            getattr(
                document,
                "key_value_items",
                [],
            )
        ),
        "groups": len(
            getattr(
                document,
                "groups",
                [],
            )
        ),
        "pages": len(
            getattr(
                document,
                "pages",
                {},
            )
        ),
    }

    metrics = {
        "benchmark": {
            "schema_version": 3,
            "timestamp_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "reference_tokenizer": (
                tokenizer_name
            ),
        },
        "run": {
            "parser": PARSER_NAME,
            "parser_display_name": (
                PARSER_DISPLAY_NAME
            ),
            "profile": args.profile,
            "verbose": args.verbose,
            "artifact_selection": (
                artifact_policy.as_list()
            ),
            "resolved_config": profile,
            "versions": {
                "docling": parser_version,
                "docling_core": (
                    docling_core_version
                ),
                "rapidocr": (
                    rapidocr_version
                ),
                "torch": torch.__version__,
            },
            "python_version": (
                platform.python_version()
            ),
            "platform": (
                platform.platform()
            ),
        },
        "document": {
            "id": input_path.stem,
            "file": input_path.name,
            "sha256": (
                inventory["sha256"]
            ),
            "pages": page_count,
            "input_size_mb": (
                inventory[
                    "file_size_mb"
                ]
            ),
        },
        "source_pdf": source_summary,
        "processing": {
            "initialization_seconds": round(
                initialization_seconds,
                6,
            ),
            "extraction_seconds": round(
                extraction_seconds,
                6,
            ),
            **artifact_result["timing"],
            "pipeline_seconds": round(
                pipeline_seconds,
                6,
            ),
            "pages_total": page_count,
            "pages_processed": (
                pages_processed
            ),
            "failed_pages": failed_pages,
            "partial_pages": None,
            "empty_output_pages": (
                artifact_result[
                    "empty_output_pages"
                ]
            ),
            "extraction_pages_per_second": (
                round(
                    pages_processed
                    / extraction_seconds,
                    6,
                )
                if extraction_seconds > 0
                else None
            ),
            "pipeline_pages_per_second": (
                round(
                    pages_processed
                    / pipeline_seconds,
                    6,
                )
                if pipeline_seconds > 0
                else None
            ),
            "conversion_status": str(
                conversion_status
            ),
            "ocr": {
                "enabled": bool(
                    profile[
                        "ocr_enabled"
                    ]
                ),
                "mode": (
                    profile[
                        "ocr_mode"
                    ]
                ),
                "engine": (
                    profile.get(
                        "ocr_engine"
                    )
                ),
                "backend": (
                    profile.get(
                        "ocr_backend"
                    )
                ),
                "language": (
                    profile.get(
                        "ocr_language"
                    )
                ),
                "scale": (
                    profile.get(
                        "ocr_scale"
                    )
                ),
                "effective_dpi": (
                    round(
                        72
                        * float(
                            profile[
                                "ocr_scale"
                            ]
                        ),
                        3,
                    )
                    if (
                        profile[
                            "ocr_enabled"
                        ]
                        and profile.get(
                            "ocr_scale"
                        )
                        is not None
                    )
                    else None
                ),
                "pages_requested": None,
                "pages_processed": None,
                "fallback_ocr_pages": None,
                "failed_ocr_pages": None,
                "requested_page_numbers": None,
                "failed_page_numbers": None,
                "tracking_note": (
                    "Docling 2.119.0 does not expose "
                    "a stable per-page OCR callback "
                    "equivalent to the PyMuPDF adapter. "
                    "OCR page counts are therefore not "
                    "inferred."
                ),
            },
            "warnings_count": len(
                captured_warning_messages
            ),
            "warning_messages": (
                captured_warning_messages
            ),
            "parser_log_warning_lines": (
                log_warning_lines
            ),
            "parser_log_error_lines": (
                log_error_lines
            ),
            "errors_count": 0,
            "retry_count": 0,
        },
        "resources": resources,
        "content_elements": {
            "source_pdf_objective": (
                source_objective
            ),
            "parser_output": (
                parser_summary
            ),
            "docling_collections": (
                document_collections
            ),
            **artifact_result[
                "content_elements"
            ],
        },
        "heuristics": (
            artifact_result[
                "heuristics"
            ]
        ),
        "tokens": (
            artifact_result[
                "tokens"
            ]
        ),
        "normalization": (
            artifact_result[
                "normalization"
            ]
        ),
        "artifacts": artifact_result["artifacts"],
        "quality_eligibility": artifact_result["quality_eligibility"],
        "output": {
            **artifact_result["output"],
            "run_log": (
                str(paths.run_log)
                if artifact_policy.includes(
                    "run.log"
                )
                else None
            ),
            "metrics_json": (
                str(
                    paths.metrics_json
                )
                if artifact_policy.includes(
                    "metrics.json"
                )
                else None
            ),
            "input_to_clean_markdown_size_ratio": (
                size_ratio
            ),
        },
        "docling_native": {
            "conversion_status": (
                str(conversion_status)
            ),
            "accelerator": {
                "device_requested": (
                    requested_device
                ),
                "device_resolved": (
                    resolved_device
                ),
                "threads_configured": int(
                    profile["threads_configured"]
                ),
                "available_logical_cpus": int(
                    profile["available_logical_cpus"]
                ),
                "threads": int(
                    profile["threads"]
                ),
                "parallelism_source": str(
                    profile["parallelism_source"]
                ),
                "cuda_available": (
                    torch.cuda.is_available()
                ),
                "torch_compile_enabled": (
                    settings.inference
                    .compile_torch_models
                ),
            },
            "collections": (
                document_collections
            ),
        },
    }

    if artifact_policy.includes(
        "metrics.json"
    ):
        write_json(
            paths.metrics_json,
            metrics,
        )

    reference_tokens = (
        artifact_result[
            "tokens"
        ]["reference"]
    )

    print()
    print("=" * 72)
    print("RESULT V2")
    print("=" * 72)
    print(
        "Pages:                 "
        f"{pages_processed}/{page_count}"
    )
    print(
        "Initialization:        "
        f"{initialization_seconds:.3f} s"
    )
    print(
        "Extraction:            "
        f"{extraction_seconds:.3f} s"
    )
    print(
        "Pipeline:              "
        f"{pipeline_seconds:.3f} s"
    )
    print(
        "Tables detected:       "
        f"{parser_summary['tables_detected']}"
    )
    print(
        "Pictures detected:     "
        f"{parser_summary['images_detected']}"
    )
    print(
        "Headings detected:     "
        f"{parser_summary['headings_detected']}"
    )
    print(
        "Lists detected:        "
        f"{parser_summary['lists_detected']}"
    )
    print(
        "Formulas detected:     "
        f"{parser_summary['formulas_detected']}"
    )
    print(
        "Raw tokens:            "
        f"{reference_tokens['raw_markdown_tokens']}"
    )
    print(
        "Clean tokens:          "
        f"{reference_tokens['clean_markdown_tokens']}"
    )
    print(
        "Token reduction:       "
        f"{reference_tokens['token_reduction_percent']:.3f}%"
    )
    print(
        "Removed records:       "
        f"{artifact_result['normalization']['removed_records']}"
    )

    if resources.get(
        "average_cpu_system_capacity_percent"
    ) is not None:
        print(
            "Average CPU:           "
            f"{resources['average_cpu_system_capacity_percent']:.2f}%"
        )

    if resources.get(
        "peak_cpu_system_capacity_percent"
    ) is not None:
        print(
            "Peak CPU:              "
            f"{resources['peak_cpu_system_capacity_percent']:.2f}%"
        )

    if resources.get(
        "peak_rss_mb"
    ) is not None:
        print(
            "Peak RAM:              "
            f"{resources['peak_rss_mb']:.3f} MB"
        )

    print(
        "Conversion status:      "
        f"{conversion_status}"
    )
    print(
        "Output:                 "
        f"{paths.output_dir}"
    )
    print("=" * 72)


if __name__ == "__main__":
    main()
