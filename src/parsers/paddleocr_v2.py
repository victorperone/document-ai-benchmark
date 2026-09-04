from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
from tempfile import TemporaryDirectory
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from time import perf_counter
from typing import Any

from paddleocr import PPStructureV3

from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.artifact_contract import ParserArtifactInput, join_page_texts
from src.benchmark.artifacts import finalize_artifacts
from src.benchmark.config import (
    get_normalization_config,
    get_profile,
    get_reference_tokenizer,
)
from src.benchmark.metrics_writer import write_json
from src.benchmark.paths import build_output_paths
from src.benchmark.preflight import make_check, make_result
from src.benchmark.resource_monitor import ResourceMonitor
from src.benchmark.runtime_io import (
    add_runtime_arguments,
    parser_output_context,
)
from src.benchmark.content_validation import inventory_requires_content
from src.benchmark.native_bundle import (
    copy_native_bundle,
    ensure_safe_relative_path,
    prefix_local_markdown_links,
)


PARSER_NAME = "paddleocr"
PARSER_DISPLAY_NAME = "PaddleOCR / PPStructureV3"

PROFILE_BOOL_KEYS = (
    "ocr_enabled",
    "table_recognition",
    "formula_recognition",
    "chart_recognition",
    "document_orientation_classification",
    "textline_orientation",
    "document_unwarping",
    "region_detection",
    "seal_recognition",
)

# Optional bool keys: present in some profiles only; must be bool if present.
PROFILE_OPTIONAL_BOOL_KEYS = frozenset({"format_block_content"})

# Additional known profile keys that are not booleans.
PROFILE_EXTRA_KEYS = frozenset({
    "markdown_ignore_labels",
    # CPU runtime (P1)
    "device",
    "inference_engine",
    "enable_mkldnn",
    "mkldnn_cache_capacity",
    "cpu_threads",
    # Detection/recognition thresholds (P3) — all optional, values passed
    # directly to PPStructureV3 when present; absent = use library defaults
    "layout_threshold",
    "text_det_thresh",
    "text_rec_score_thresh",
    "use_wired_table_cells_trans_to_html",
    "use_e2e_wired_table_rec_model",
    "use_e2e_wireless_table_rec_model",
    # Experimental profile gate (P4)
    "experimental",
    "text_detection_model_dir_override",
    "text_recognition_model_dir_override",
})

DEFAULT_MODEL_ROOT = Path(
    "/home/appuser/.paddlex/official_models"
)


MODEL_NAMES = {
    "layout": "PP-DocLayout_plus-L",
    "region": "PP-DocBlockLayout",
    "doc_orientation": "PP-LCNet_x1_0_doc_ori",
    "doc_unwarping": "UVDoc",
    "text_detection": "PP-OCRv5_server_det",
    "textline_orientation": "PP-LCNet_x1_0_textline_ori",
    "text_recognition": "PP-OCRv5_server_rec",
    "table_classification": "PP-LCNet_x1_0_table_cls",
    "wired_table_structure": "SLANeXt_wired",
    "wireless_table_structure": "SLANet_plus",
    "wired_table_cells": "RT-DETR-L_wired_table_cell_det",
    "wireless_table_cells": "RT-DETR-L_wireless_table_cell_det",
    "table_orientation": "PP-LCNet_x1_0_doc_ori",
    "formula": "PP-FormulaNet_plus-L",
    "chart": "PP-Chart2Table",
    "seal_detection": "PP-OCRv4_server_seal_det",
    "seal_recognition": "PP-OCRv5_server_rec",
}

MODEL_DIRECTORY_CANDIDATES = {
    "PP-Chart2Table": (
        "PP-Chart2Table_safetensors",
        "PP-Chart2Table",
    ),
}


def _calculate_sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def _load_cached_inventory(
    input_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    inventory_path = (
        output_root
        / "_source_inventory"
        / f"{input_path.stem}.json"
    )

    if not inventory_path.is_file():
        raise FileNotFoundError(
            "Cached Source Inventory not found: "
            f"{inventory_path}"
        )

    inventory = json.loads(
        inventory_path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        inventory,
        dict,
    ):
        raise TypeError(
            "Cached Source Inventory must "
            "be a JSON object."
        )

    expected_file = input_path.name

    if inventory.get("file") != expected_file:
        raise ValueError(
            "Source Inventory file mismatch: "
            f"expected {expected_file!r}, "
            f"got {inventory.get('file')!r}."
        )

    actual_sha256 = _calculate_sha256(
        input_path
    )

    cached_sha256 = inventory.get(
        "sha256"
    )

    if cached_sha256 != actual_sha256:
        raise ValueError(
            "Source Inventory SHA256 mismatch: "
            f"cached={cached_sha256!r}, "
            f"actual={actual_sha256!r}."
        )

    return inventory


def _package_version(
    package_name: str,
) -> str | None:
    try:
        return metadata.version(
            package_name
        )
    except metadata.PackageNotFoundError:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PaddleOCR benchmark adapter v2.",
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
        default="mvp_structured",
    )

    parser.add_argument(
        "--model-root",
        type=Path,
        default=DEFAULT_MODEL_ROOT,
    )

    add_runtime_arguments(parser)

    args = parser.parse_args()

    args.artifact_policy = ArtifactPolicy.from_cli(
        args.artifacts
    )

    return args

def required_model_keys(
    profile: dict[str, Any],
) -> set[str]:
    # PPStructureV3 may instantiate its text-line orientation
    # component even when use_textline_orientation=False.
    # Always resolving this model locally prevents PaddleX from
    # falling back to an official model download at runtime.
    keys = {
        "layout",
        "text_detection",
        "textline_orientation",
        "text_recognition",
    }

    if profile["region_detection"]:
        keys.add(
            "region"
        )

    if profile[
        "document_orientation_classification"
    ]:
        keys.add(
            "doc_orientation"
        )

    if profile[
        "document_unwarping"
    ]:
        keys.add(
            "doc_unwarping"
        )


    if profile[
        "table_recognition"
    ]:
        keys.update(
            {
                "table_classification",
                "wired_table_structure",
                "wireless_table_structure",
                "wired_table_cells",
                "wireless_table_cells",
                "table_orientation",
            }
        )

    if profile[
        "formula_recognition"
    ]:
        keys.add(
            "formula"
        )

    if profile[
        "chart_recognition"
    ]:
        keys.add(
            "chart"
        )

    if profile[
        "seal_recognition"
    ]:
        keys.update(
            {
                "seal_detection",
                "seal_recognition",
            }
        )

    return keys


def _resolve_model_path(
    model_root: Path,
    model_name: str,
) -> Path:
    directory_names = MODEL_DIRECTORY_CANDIDATES.get(
        model_name,
        (model_name,),
    )

    candidates = tuple(
        model_root / directory_name
        for directory_name in directory_names
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    return candidates[0]


def resolve_model_paths(
    model_root: Path,
    profile: dict[str, Any],
) -> dict[str, Path]:
    required_keys = required_model_keys(
        profile
    )

    paths = {
        key: _resolve_model_path(
            model_root,
            MODEL_NAMES[key],
        )
        for key in sorted(
            required_keys
        )
    }

    missing = [
        path
        for path in paths.values()
        if not path.is_dir()
    ]

    if missing:
        formatted = "\n".join(
            f"  - {path}"
            for path in missing
        )

        raise FileNotFoundError(
            "Required local PaddleOCR models "
            "are missing:\n"
            f"{formatted}"
        )

    return paths


def validate_profile(
    profile: dict[str, Any],
) -> None:
    errors: list[str] = []

    expected_keys = set(
        PROFILE_BOOL_KEYS
    )
    all_known_keys = (
        expected_keys
        | PROFILE_OPTIONAL_BOOL_KEYS
        | PROFILE_EXTRA_KEYS
    )
    actual_keys = set(
        profile
    )

    missing_keys = sorted(
        expected_keys - actual_keys
    )
    unknown_keys = sorted(
        actual_keys - all_known_keys
    )

    if missing_keys:
        errors.append(
            "missing keys: "
            + ", ".join(
                missing_keys
            )
        )

    if unknown_keys:
        errors.append(
            "unknown keys: "
            + ", ".join(
                unknown_keys
            )
        )

    for key in (
        *PROFILE_BOOL_KEYS,
        *PROFILE_OPTIONAL_BOOL_KEYS,
    ):
        if key not in profile:
            continue

        value = profile[key]

        if type(value) is not bool:
            errors.append(
                f"{key} must be bool, "
                f"got {type(value).__name__}"
            )

    if (
        "ocr_enabled" in profile
        and profile["ocr_enabled"] is not True
    ):
        errors.append(
            "ocr_enabled must be true for "
            "the PPStructureV3 adapter"
        )

    if (
        profile.get("chart_recognition") is True
        and profile.get("inference_engine")
        == "paddle_static"
    ):
        errors.append(
            "chart_recognition=true is incompatible "
            "with inference_engine='paddle_static': "
            "PP-Chart2Table requires paddle_dynamic "
            "or another supported engine; use "
            "inference_engine='paddle' for automatic "
            "per-model engine resolution"
        )

    if errors:
        raise ValueError(
            "Invalid PaddleOCR profile:\n  - "
            + "\n  - ".join(errors)
        )


_PREDICT_ONLY_KWARGS = frozenset({
    "use_wired_table_cells_trans_to_html",
    "use_wireless_table_cells_trans_to_html",
    "use_table_orientation_classify",
    "use_ocr_results_with_table_cells",
    "use_e2e_wired_table_rec_model",
    "use_e2e_wireless_table_rec_model",
    "markdown_ignore_labels",
})

_PPSTRUCTURE_COMMON_INIT_KWARGS = frozenset(
    {
        "device",
        "engine",
        "engine_config",
        "enable_hpi",
        "use_tensorrt",
        "precision",
        "enable_mkldnn",
        "mkldnn_cache_capacity",
        "cpu_threads",
        "enable_cinn",
    }
)

def build_pipeline_init_kwargs(
    model_paths: dict[str, Path],
    profile: dict[str, Any],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "layout_detection_model_dir": str(
            model_paths["layout"]
        ),
        "text_detection_model_dir": str(
            model_paths[
                "text_detection"
            ]
        ),
        "text_recognition_model_dir": str(
            model_paths[
                "text_recognition"
            ]
        ),
        "use_doc_orientation_classify": profile[
            "document_orientation_classification"
        ],
        "use_doc_unwarping": profile[
            "document_unwarping"
        ],
        "use_textline_orientation": profile[
            "textline_orientation"
        ],
        "use_seal_recognition": profile[
            "seal_recognition"
        ],
        "use_table_recognition": profile[
            "table_recognition"
        ],
        "use_formula_recognition": profile[
            "formula_recognition"
        ],
        "use_chart_recognition": profile[
            "chart_recognition"
        ],
        "use_region_detection": profile[
            "region_detection"
        ],
    }

    optional_model_args = {
        "region": (
            "region_detection_model_dir"
        ),
        "doc_orientation": (
            "doc_orientation_classify_model_dir"
        ),
        "doc_unwarping": (
            "doc_unwarping_model_dir"
        ),
        "textline_orientation": (
            "textline_orientation_model_dir"
        ),
        "table_classification": (
            "table_classification_model_dir"
        ),
        "wired_table_structure": (
            "wired_table_structure_recognition_model_dir"
        ),
        "wireless_table_structure": (
            "wireless_table_structure_recognition_model_dir"
        ),
        "wired_table_cells": (
            "wired_table_cells_detection_model_dir"
        ),
        "wireless_table_cells": (
            "wireless_table_cells_detection_model_dir"
        ),
        "table_orientation": (
            "table_orientation_classify_model_dir"
        ),
        "formula": (
            "formula_recognition_model_dir"
        ),
        "chart": (
            "chart_recognition_model_dir"
        ),
        "seal_detection": (
            "seal_text_detection_model_dir"
        ),
        "seal_recognition": (
            "seal_text_recognition_model_dir"
        ),
    }

    for (
        model_key,
        argument_name,
    ) in optional_model_args.items():
        if model_key in model_paths:
            kwargs[
                argument_name
            ] = str(
                model_paths[
                    model_key
                ]
            )

    if profile.get("format_block_content") is True:
        kwargs["format_block_content"] = True

    # Detection/recognition thresholds passed to constructor (P3).
    # The 7 predict-only kwargs are intentionally excluded here — see build_predict_kwargs.
    _threshold_map = {
        "layout_threshold": "layout_threshold",
        "text_det_thresh": "text_det_thresh",
        "text_rec_score_thresh": "text_rec_score_thresh",
    }
    for profile_key, kwarg_name in _threshold_map.items():
        if profile.get(profile_key) is not None:
            kwargs[kwarg_name] = profile[profile_key]

    # CPU inference runtime settings (P1)
    # Only passed when the profile explicitly declares them, so existing
    # profiles without these keys continue to use PPStructureV3 defaults.
    if "device" in profile:
        kwargs["device"] = str(profile["device"])

    if "inference_engine" in profile:
        kwargs["engine"] = str(profile["inference_engine"])

    if "enable_mkldnn" in profile:
        kwargs["enable_mkldnn"] = bool(profile["enable_mkldnn"])

    if "mkldnn_cache_capacity" in profile:
        kwargs["mkldnn_cache_capacity"] = int(
            profile["mkldnn_cache_capacity"]
        )

    if "cpu_threads" in profile and profile["cpu_threads"] is not None:
        kwargs["cpu_threads"] = int(profile["cpu_threads"])

    # HPI is always disabled for the benchmark (no accelerator hardware)
    kwargs["enable_hpi"] = False
    # CINN causes nondeterminism; disabled for reproducibility
    kwargs["enable_cinn"] = False

    # Experimental model dir overrides (P4)
    # Allow profiles to point text_detection / text_recognition at a
    # different model directory (e.g. PP-OCRv6) without changing the
    # default model root resolution for other components.
    if profile.get("text_detection_model_dir_override"):
        kwargs["text_detection_model_dir"] = str(
            profile["text_detection_model_dir_override"]
        )
    if profile.get("text_recognition_model_dir_override"):
        kwargs["text_recognition_model_dir"] = str(
            profile["text_recognition_model_dir_override"]
        )

    return kwargs


_PREDICT_CERTIFIED_DEFAULTS: dict[str, Any] = {
    "use_wired_table_cells_trans_to_html": False,
    "use_wireless_table_cells_trans_to_html": False,
    "use_table_orientation_classify": True,
    "use_ocr_results_with_table_cells": True,
    "use_e2e_wired_table_rec_model": False,
    "use_e2e_wireless_table_rec_model": True,
}


def build_predict_kwargs(
    input_path: Path,
    profile: dict[str, Any],
    pipeline: Any,
) -> dict[str, Any]:
    """Build kwargs for PPStructureV3.predict_iter — disjoint from init kwargs."""
    kwargs: dict[str, Any] = {
        "input": str(input_path),
        "use_doc_orientation_classify": profile["document_orientation_classification"],
        "use_doc_unwarping": profile["document_unwarping"],
        "use_textline_orientation": profile["textline_orientation"],
        "use_seal_recognition": profile["seal_recognition"],
        "use_table_recognition": profile["table_recognition"],
        "use_formula_recognition": profile["formula_recognition"],
        "use_chart_recognition": profile["chart_recognition"],
        "use_region_detection": profile["region_detection"],
    }
    # Add certified predict-only defaults for full_cpu_local profile.
    for key, default in _PREDICT_CERTIFIED_DEFAULTS.items():
        profile_val = profile.get(key)
        kwargs[key] = profile_val if profile_val is not None else default

    # markdown_ignore_labels requires signature detection.
    ignore_labels = profile.get("markdown_ignore_labels")
    if ignore_labels is not None:
        try:
            predict_sig = inspect.signature(pipeline.predict_iter)
            if "markdown_ignore_labels" in predict_sig.parameters:
                kwargs["markdown_ignore_labels"] = ignore_labels
        except Exception:
            pass

    return kwargs


def build_pipeline(
    model_paths: dict[str, Path],
    profile: dict[str, Any],
) -> PPStructureV3:
    return PPStructureV3(
        **build_pipeline_init_kwargs(
            model_paths,
            profile,
        )
    )


def _result_value(
    result: Any,
    key: str,
    default: Any,
) -> Any:
    try:
        value = result[key]
    except (
        KeyError,
        TypeError,
    ):
        return default

    if value is None:
        return default

    return value


def _json_safe(obj: Any, _depth: int = 0) -> Any:
    """Recursively convert PPStructureV3 result objects to JSON-serializable form.

    Drops image bytes (bytes/bytearray) and limits recursion to avoid excessive
    nesting. Unknown objects are converted to their type name to preserve
    structure visibility without crashing serialization.
    """
    if _depth > 8:
        return f"<truncated:{type(obj).__name__}>"

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, (bytes, bytearray)):
        return f"<bytes:{len(obj)}>"

    if isinstance(obj, dict):
        return {
            str(k): _json_safe(v, _depth + 1)
            for k, v in obj.items()
            if k not in ("img", "image", "img_path", "input_path")
        }

    if isinstance(obj, (list, tuple)):
        return [_json_safe(item, _depth + 1) for item in obj]

    # numpy arrays and similar — convert via tolist() if available
    to_list = getattr(obj, "tolist", None)
    if callable(to_list):
        try:
            return _json_safe(to_list(), _depth + 1)
        except Exception:
            pass

    # Pydantic / dataclass — try model_dump first, then __dict__
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(
                model_dump(mode="json", exclude_none=True), _depth + 1
            )
        except Exception:
            pass

    obj_dict = getattr(obj, "__dict__", None)
    if obj_dict is not None:
        return _json_safe(
            {k: v for k, v in obj_dict.items() if not k.startswith("_")},
            _depth + 1,
        )

    return f"<{type(obj).__name__}>"


def build_paddleocr_page_contract(
    results: list[Any],
) -> tuple[
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    page_texts: list[str] = []

    parser_page_elements: list[
        dict[str, Any]
    ] = []

    parser_native_pages: list[
        dict[str, Any]
    ] = []

    for result in results:
        page_idx = _result_value(result, "page_index", None)

        if not isinstance(page_idx, int):
            raise TypeError(
                "PaddleOCR page_index must "
                f"be int, got {page_idx!r}."
            )

        markdown_data = result.markdown

        markdown_text = markdown_data[
            "markdown_texts"
        ]

        if not isinstance(
            markdown_text,
            str,
        ):
            raise TypeError(
                "PaddleOCR markdown_texts "
                "must be a string."
            )

        ocr_result = _result_value(
            result,
            "overall_ocr_res",
            {},
        )

        rec_texts = _result_value(
            ocr_result,
            "rec_texts",
            [],
        )

        orientations = [
            int(value)
            for value in _result_value(
                ocr_result,
                "textline_orientation_angles",
                [],
            )
        ]

        tables = _result_value(
            result,
            "table_res_list",
            [],
        )

        formulas = _result_value(
            result,
            "formula_res_list",
            [],
        )

        parsing_blocks = result[
            "parsing_res_list"
        ]

        doc_preprocessor = _result_value(
        result,
        "doc_preprocessor_res",
        {},
        )

        document_angle_value = (
            _result_value(
                doc_preprocessor,
                "angle",
                None,
            )
        )

        document_angle = (
            int(
                document_angle_value
            )
            if document_angle_value
            is not None
            else None
        )

        orientation_counts = Counter(
            orientations
        )

        page_texts.append(
            markdown_text
        )

        parser_page_elements.append(
            {
                "items": len(
                    parsing_blocks
                ),
                "ocr_texts": len(
                    rec_texts
                ),
                "tables": len(
                    tables
                ),
                "formulas": len(
                    formulas
                ),
            }
        )

        # Serialized native results (P2)
        tables_with_html = sum(
            1
            for t in tables
            if _result_value(t, "html", None)
        )

        seal_list = _result_value(result, "seal_res_list", [])
        chart_list = _result_value(result, "chart_res_list", [])

        serialized_parsing = _json_safe(parsing_blocks)
        serialized_ocr = _json_safe(ocr_result)

        parser_native_pages.append(
            {
                "page_idx": page_idx,
                "document_angle": (
                    document_angle
                ),
                "ocr_text_count": len(
                    rec_texts
                ),
                "textline_orientation_counts": (
                    dict(
                        sorted(
                            orientation_counts.items()
                        )
                    )
                ),
                "table_count": len(tables),
                "tables_with_html": tables_with_html,
                "formula_count": len(formulas),
                "chart_count": len(chart_list),
                "seal_count": len(seal_list),
                "parsing_block_count": len(parsing_blocks),
                "parsing_res_list": serialized_parsing,
                "overall_ocr_res": serialized_ocr,
                "table_res_list": _json_safe(tables),
                "formula_res_list": _json_safe(formulas),
                "chart_res_list": _json_safe(chart_list),
                "seal_res_list": _json_safe(seal_list),
                "doc_preprocessor_res": _json_safe(doc_preprocessor),
            }
        )

    return (
        page_texts,
        parser_page_elements,
        parser_native_pages,
    )


def persist_official_markdown_bundle(
    *,
    results: list[Any],
    official_markdown: str,
    destination: Path,
    parser_name: str,
    profile_name: str,
) -> tuple[str, dict[str, Any]]:
    """Persist PPStructureV3 Markdown and every official markdown image."""
    with TemporaryDirectory(prefix="paddleocr_markdown_") as temporary:
        source_root = Path(temporary)
        markdown_path = source_root / "document.md"
        markdown_path.write_text(official_markdown, encoding="utf-8")
        image_paths: list[Path] = []
        for result in results:
            markdown_data = result.markdown
            markdown_images = _result_value(markdown_data, "markdown_images", {}) or {}
            if not isinstance(markdown_images, dict):
                raise TypeError("PaddleOCR markdown_images must be a mapping")
            for relative_value, image in markdown_images.items():
                relative = ensure_safe_relative_path(str(relative_value))
                image_path = source_root / Path(*relative.parts)
                image_path.parent.mkdir(parents=True, exist_ok=True)
                if image_path.exists():
                    continue
                save = getattr(image, "save", None)
                if callable(save):
                    save(image_path)
                elif isinstance(image, (bytes, bytearray)):
                    image_path.write_bytes(bytes(image))
                else:
                    raise TypeError(
                        "PaddleOCR markdown image must expose save() or bytes; "
                        f"got {type(image).__name__}"
                    )
                image_paths.append(image_path)

        bundle = copy_native_bundle(
            source_root=source_root,
            source_markdown_path=markdown_path,
            destination=destination,
            parser=parser_name,
            profile=profile_name,
            extra_files=image_paths,
        )
        return prefix_local_markdown_links(bundle.markdown, "native"), bundle.manifest


def enabled_text(
    value: bool,
) -> str:
    return (
        "enabled"
        if value
        else "disabled"
    )

def preflight_profile(
    profile_name: str,
    *,
    model_root_override: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # --------------------------------------------------
    # Profile configuration
    # --------------------------------------------------

    try:
        profile = get_profile(
            PARSER_NAME,
            profile_name,
        )
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
        make_check(
            "profile configuration",
            "pass",
            profile_name,
        )
    )

    # --------------------------------------------------
    # Experimental gate
    # --------------------------------------------------

    if profile.get("experimental"):
        checks.append(
            make_check(
                "experimental profile",
                "warn",
                "This profile is experimental and not eligible for formal "
                "benchmark ranking. Results must not be compared directly "
                "with non-experimental profiles.",
            )
        )

    # --------------------------------------------------
    # Profile contract
    # --------------------------------------------------

    try:
        validate_profile(profile)
    except Exception as exc:
        checks.append(
            make_check(
                "profile contract",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )
    else:
        checks.append(
            make_check("profile contract", "pass")
        )

    # --------------------------------------------------
    # Model root
    # --------------------------------------------------

    model_root = (
        model_root_override
        if model_root_override is not None
        else DEFAULT_MODEL_ROOT
    )

    checks.append(
        make_check(
            "model root",
            "pass" if model_root.is_dir() else "fail",
            str(model_root),
        )
    )

    # --------------------------------------------------
    # Required models
    # --------------------------------------------------

    try:
        required_keys = required_model_keys(profile)
    except Exception as exc:
        checks.append(
            make_check(
                "model selection",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )
        required_keys = set()
    else:
        checks.append(
            make_check(
                "model selection",
                "pass",
                f"{len(required_keys)} required model(s)",
            )
        )

    candidate_paths: dict[str, Path] = {}

    for key in sorted(required_keys):
        model_name = MODEL_NAMES[key]
        model_path = _resolve_model_path(
            model_root,
            model_name,
        )
        candidate_paths[key] = model_path
        checks.append(
            make_check(
                f"model {model_name}",
                "pass" if model_path.is_dir() else "fail",
                str(model_path),
            )
        )

    # --------------------------------------------------
    # PPStructureV3 API compatibility
    # --------------------------------------------------

    try:
        pipeline_kwargs = build_pipeline_init_kwargs(
            candidate_paths,
            profile,
        )

        signature = inspect.signature(
            PPStructureV3.__init__
        )

        known_parameters = set(
            signature.parameters
        )

        has_var_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter
            in signature.parameters.values()
        )

        unknown_kwargs = sorted(
            key
            for key in pipeline_kwargs
            if (
                key not in known_parameters
                and not (
                    has_var_kwargs
                    and key
                    in _PPSTRUCTURE_COMMON_INIT_KWARGS
                )
            )
        )

        if unknown_kwargs:
            checks.append(
                make_check(
                    "PPStructureV3 API",
                    "fail",
                    "Unknown constructor arguments: "
                    + ", ".join(unknown_kwargs),
                )
            )
        else:
            checks.append(
                make_check(
                    "PPStructureV3 API",
                    "pass",
                    f"{len(pipeline_kwargs)} argument(s) validated",
                )
            )

        # Verify init and predict-only kwargs sets are disjoint.
        predict_only_in_init = sorted(
            key for key in pipeline_kwargs if key in _PREDICT_ONLY_KWARGS
        )
        if predict_only_in_init:
            checks.append(
                make_check(
                    "PPStructureV3 init/predict kwargs disjoint",
                    "fail",
                    "Predict-only kwargs found in constructor args: "
                    + ", ".join(predict_only_in_init),
                )
            )
        else:
            checks.append(
                make_check(
                    "PPStructureV3 init/predict kwargs disjoint",
                    "pass",
                )
            )

        # Check streaming inference signature for markdown_ignore_labels.
        ignore_labels = profile.get("markdown_ignore_labels")
        if ignore_labels is not None:
            try:
                predict_sig = inspect.signature(
                    PPStructureV3.predict_iter
                )
                predict_params = set(predict_sig.parameters)
                if "markdown_ignore_labels" in predict_params:
                    checks.append(
                        make_check(
                            "PPStructureV3 predict API (markdown_ignore_labels)",
                            "pass",
                        )
                    )
                else:
                    checks.append(
                        make_check(
                            "PPStructureV3 predict API (markdown_ignore_labels)",
                            "warn",
                            "markdown_ignore_labels not in predict_iter() signature "
                            "for this paddleocr version; kwarg will be skipped at runtime",
                        )
                    )
            except Exception as exc:
                checks.append(
                    make_check(
                        "PPStructureV3 predict API (markdown_ignore_labels)",
                        "warn",
                        f"Signature check failed: {exc}",
                    )
                )

    except Exception as exc:
        checks.append(
            make_check(
                "PPStructureV3 API",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )

    return make_result(PARSER_NAME, profile_name, checks)


def main() -> None:
    args = parse_args()

    input_path = args.input.resolve()

    if not input_path.is_file():
        raise SystemExit(
            f"Input not found: {input_path}"
        )

    profile = get_profile(
        PARSER_NAME,
        args.profile,
    )

    validate_profile(profile)

    normalization_config = (
        get_normalization_config()
    )

    tokenizer_name = (
        get_reference_tokenizer()
    )

    model_root = args.model_root.resolve()

    model_paths = resolve_model_paths(
    model_root,
    profile,
    )

    paths = build_output_paths(
        args.output_root,
        PARSER_NAME,
        input_path.stem,
        args.profile,
        create=False,
    )

    inventory = _load_cached_inventory(
        input_path,
        args.output_root,
    )

    page_count = inventory.get(
        "pages"
    )

    if not isinstance(
        page_count,
        int,
    ) or page_count < 1:
        raise ValueError(
            "Source Inventory contains "
            f"invalid page count: {page_count!r}"
        )

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:       {PARSER_DISPLAY_NAME}")
    print(f"Input:        {input_path}")
    print(f"Profile:      {args.profile}")
    print(f"Model root:   {model_root}")
    print(f"Tokenizer:    {tokenizer_name}")
    print(f"Output:       {paths.output_dir}")
    print(
        "Artifacts:    "
        + ", ".join(
            args.artifact_policy.as_list()
        )
    )
    print(
    "OCR:          "
    + enabled_text(
        profile[
            "ocr_enabled"
        ]
    )
    )
    print(
        "Tables:       "
        + enabled_text(
            profile[
                "table_recognition"
            ]
        )
    )
    print(
        "Formulas:     "
        + enabled_text(
            profile[
                "formula_recognition"
            ]
        )
    )
    print(
        "Doc orient.:  "
        + enabled_text(
            profile[
                "document_orientation_classification"
            ]
        )
    )
    print(
        "Line orient.: "
        + enabled_text(
            profile[
                "textline_orientation"
            ]
        )
    )
    print(
        "Region det.:  "
        + enabled_text(
            profile[
                "region_detection"
            ]
        )
    )
    print(
        "Chart:        "
        + enabled_text(
            profile[
                "chart_recognition"
            ]
        )
    )
    print(
        "Unwarping:    "
        + enabled_text(
            profile[
                "document_unwarping"
            ]
        )
    )
    print(
        "Seal:         "
        + enabled_text(
            profile[
                "seal_recognition"
            ]
        )
    )
    print("=" * 72)

    monitor = ResourceMonitor()

    pipeline_started = perf_counter()
    monitor.start()

    initialization_seconds = None
    extraction_seconds = None

    # Declared before try so finally can safely test truthiness.
    pipeline = None
    try:
        with parser_output_context(
            run_log_path=paths.run_log,
            keep_run_log=(
                args.artifact_policy.includes(
                    "run.log"
                )
            ),
            verbose=args.verbose,
        ):
            initialization_started = (
                perf_counter()
            )

            pipeline = build_pipeline(
                model_paths,
                profile,
            )

            initialization_seconds = (
                perf_counter()
                - initialization_started
            )

            extraction_started = perf_counter()

            predict_iter_fn = getattr(pipeline, "predict_iter", None)
            if not callable(predict_iter_fn):
                raise RuntimeError("PPStructureV3.predict_iter is unavailable")

            predict_kwargs = build_predict_kwargs(input_path, profile, pipeline)

            # Process pages one at a time — never materialise the full iterator.
            page_texts: list[str] = []
            parser_page_elements: list[dict[str, Any]] = []
            parser_native_pages: list[dict[str, Any]] = []
            markdown_pages_for_concat: list[Any] = []
            seen_indexes: set[int] = set()

            for result in predict_iter_fn(**predict_kwargs):
                page_idx = _result_value(result, "page_index", None)
                if not isinstance(page_idx, int):
                    raise TypeError(
                        f"PaddleOCR page_index must be int, got {page_idx!r}."
                    )
                if page_idx < 0 or page_idx >= page_count:
                    raise RuntimeError(
                        f"PaddleOCR page_index {page_idx} out of range "
                        f"[0, {page_count - 1}]."
                    )
                if page_idx in seen_indexes:
                    raise RuntimeError(
                        f"Duplicate PaddleOCR page_index: {page_idx}."
                    )
                seen_indexes.add(page_idx)

                # Build per-page contract immediately and release heavy refs.
                (
                    p_texts,
                    p_elements,
                    p_native,
                ) = build_paddleocr_page_contract([result])
                page_texts.extend(p_texts)
                parser_page_elements.extend(p_elements)
                parser_native_pages.extend(p_native)
                markdown_pages_for_concat.append(result.markdown)

            extraction_seconds = (
                perf_counter()
                - extraction_started
            )

        if not page_texts:
            raise RuntimeError(
                "PPStructureV3 returned no pages."
            )

        received_indexes = sorted(seen_indexes)
        expected_indexes = list(range(page_count))
        if received_indexes != expected_indexes:
            # Detect 1-based indexing: if all received indexes are offset by 1
            # from the expected 0-based range, normalise silently.
            offset_indexes = [i - 1 for i in received_indexes]
            if offset_indexes == expected_indexes:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "PPStructureV3 returned 1-based page indexes; normalising to 0-based."
                )
            else:
                raise RuntimeError(
                    "Unexpected PaddleOCR page indexes. "
                    f"Expected {expected_indexes}, "
                    f"got {received_indexes}."
                )

        # Official aggregation — called exactly once after full iteration.
        concatenate = getattr(pipeline, "concatenate_markdown_pages", None)
        if not callable(concatenate):
            raise RuntimeError("PPStructureV3.concatenate_markdown_pages is unavailable")
        combined = concatenate(markdown_pages_for_concat)
        if isinstance(combined, str):
            official_markdown = combined
        else:
            official_markdown = None
            for key in ("markdown_texts", "markdown", "content", "text"):
                value = _result_value(combined, key, None)
                if isinstance(value, str):
                    official_markdown = value
                    break
            if official_markdown is None:
                raise TypeError(
                    "PPStructureV3 official Markdown aggregator returned "
                    f"{type(combined).__name__}, expected str or mapping"
                )

        native_bundle_manifest: dict[str, Any] | None = None
        native_markdown = official_markdown
        if args.artifact_policy.includes("native"):
            # persist_official_markdown_bundle needs the markdown_images from results;
            # since we cleared result refs, reconstruct from markdown_pages_for_concat.
            # The function only needs result.markdown — wrap the collected pages.
            class _MarkdownOnly:
                def __init__(self, md: Any) -> None:
                    self.markdown = md
            wrapped = [_MarkdownOnly(md) for md in markdown_pages_for_concat]
            native_markdown, native_bundle_manifest = persist_official_markdown_bundle(
                results=wrapped,
                official_markdown=official_markdown,
                destination=paths.native_dir,
                parser_name=PARSER_NAME,
                profile_name=args.profile,
            )
        raw_origin_kind = (
            "parser_native_links_relocated"
            if native_markdown != official_markdown
            else "parser_native_exact"
        )

        artifact_input = ParserArtifactInput(
            native_markdown=native_markdown,
            source_page_markdown=page_texts,
            enriched_page_markdown=None,
            page_mapping_status="complete",
            parser_page_elements=parser_page_elements,
            parser_native_pages=parser_native_pages,
            derived_content_by_page=[[] for _ in page_texts],
            raw_origin_kind=raw_origin_kind,
            raw_origin_details=(
                "PPStructureV3.concatenate_markdown_pages with only local asset links "
                "relocated into native/assets"
                if raw_origin_kind == "parser_native_links_relocated"
                else "PPStructureV3.concatenate_markdown_pages"
            ),
            content_expected=inventory_requires_content(inventory)[0],
            content_expectation_reason=inventory_requires_content(inventory)[1],
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
            artifact_policy=(
                args.artifact_policy
            ),
        )

    finally:
        # Close only if the constructor succeeded; preserves the original exception
        # when pipeline is None (constructor failure).
        if pipeline is not None:
            close_fn = getattr(pipeline, "close", None)
            if callable(close_fn):
                close_fn()

    resources = monitor.stop()

    pipeline_seconds = (
        perf_counter()
        - pipeline_started
    )

    pages_processed = len(
        page_texts
    )

    failed_pages = max(
        page_count
        - pages_processed,
        0,
    )

    total_tables = sum(
        page["table_count"]
        for page in parser_native_pages
    )

    total_tables_with_html = sum(
        page.get("tables_with_html", 0)
        for page in parser_native_pages
    )

    total_formulas = sum(
        page["formula_count"]
        for page in parser_native_pages
    )

    total_charts = sum(
        page.get("chart_count", 0)
        for page in parser_native_pages
    )

    total_seals = sum(
        page.get("seal_count", 0)
        for page in parser_native_pages
    )

    total_ocr_texts = sum(
        page["ocr_text_count"]
        for page in parser_native_pages
    )

    total_parsing_blocks = sum(
        page["parsing_block_count"]
        for page in parser_native_pages
    )

    document_angles: Counter[int] = Counter(
        page["document_angle"]
        for page in parser_native_pages
        if page[
            "document_angle"
        ] is not None
    )

    line_angles: Counter[int] = Counter()

    for page in parser_native_pages:
        for angle, count in page[
            "textline_orientation_counts"
        ].items():
            line_angles[int(angle)] += int(
                count
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
            ][
                "drawing_groups"
            ]
        ),
        "pages_without_native_text": (
            inventory[
                "native_text"
            ][
                "pages_without_native_text"
            ]
        ),
    }

    log_text = ""

    if (
        args.artifact_policy.includes(
            "run.log"
        )
        and paths.run_log.is_file()
    ):
        log_text = paths.run_log.read_text(
            encoding="utf-8",
            errors="replace",
        )

    warning_messages = [
        line.strip()
        for line in log_text.splitlines()
        if "warning" in line.lower()
    ]

    parser_log_error_lines = sum(
        "error" in line.lower()
        for line in log_text.splitlines()
    )

    parser_output = {
        "layout_boxes": total_parsing_blocks,
        "tables_detected": total_tables,
        "tables_with_html": total_tables_with_html,
        "images_detected": None,
        "headings_detected": None,
        "lists_detected": None,
        "formulas_detected": total_formulas,
        "charts_detected": total_charts,
        "seals_detected": total_seals,
        "captions_detected": None,
        "page_headers_detected": None,
        "page_footers_detected": None,
        "footnotes_detected": None,
        "text_blocks_detected": None,
        "code_blocks_detected": None,
        "box_class_counts": None,
    }

    input_bytes = (
        input_path.stat().st_size
    )

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

    resolved_config = dict(
        profile
    )

    resolved_config[
        "backend"
    ] = "PPStructureV3"

    resolved_config[
        "model_root"
    ] = str(
        model_root
    )

    resolved_config[
        "models"
    ] = {
        key: MODEL_NAMES[key]
        for key in sorted(
            model_paths
        )
    }

    resolved_config[
        "model_paths"
    ] = {
        key: str(
            model_paths[key]
        )
        for key in sorted(
            model_paths
        )
    }

    output_metrics = dict(
        artifact_result[
            "output"
        ]
    )

    output_metrics[
        "run_log"
    ] = (
        str(paths.run_log)
        if args.artifact_policy.includes(
            "run.log"
        )
        else None
    )

    output_metrics[
        "metrics_json"
    ] = (
        str(paths.metrics_json)
        if args.artifact_policy.includes(
            "metrics.json"
        )
        else None
    )

    output_metrics[
        "input_to_clean_markdown_size_ratio"
    ] = size_ratio

    native_page_markdown_bytes = sum(
        len(
            text.encode(
                "utf-8"
            )
        )
        for text in page_texts
    )

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
                args.artifact_policy
                .as_list()
            ),
            "resolved_config": (
                resolved_config
            ),
            "versions": {
                "paddleocr": (
                    _package_version(
                        "paddleocr"
                    )
                ),
                "paddlepaddle": (
                    _package_version(
                        "paddlepaddle"
                    )
                ),
                "paddlex": (
                    _package_version(
                        "paddlex"
                    )
                ),
                "tiktoken": (
                    _package_version(
                        "tiktoken"
                    )
                ),
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

        "source_pdf": (
            source_summary
        ),

        "processing": {
            "initialization_seconds": round(
                initialization_seconds,
                6,
            ),
            "extraction_seconds": round(
                extraction_seconds,
                6,
            ),
            "normalization_seconds": (
                artifact_result[
                    "timing"
                ][
                    "normalization_seconds"
                ]
            ),
            "common_metrics_seconds": (
                artifact_result[
                    "timing"
                ][
                    "common_metrics_seconds"
                ]
            ),
            "artifact_write_seconds": (
                artifact_result[
                    "timing"
                ][
                    "artifact_write_seconds"
                ]
            ),
            "pipeline_seconds": round(
                pipeline_seconds,
                6,
            ),
            "pages_total": page_count,
            "pages_processed": (
                pages_processed
            ),
            "failed_pages": (
                failed_pages
            ),
            "partial_pages": None,
            "empty_output_pages": (
                artifact_result[
                    "empty_output_pages"
                ]
            ),
            "extraction_pages_per_second": (
                round(
                    page_count
                    / extraction_seconds,
                    6,
                )
                if extraction_seconds
                else None
            ),
            "pipeline_pages_per_second": (
                round(
                    page_count
                    / pipeline_seconds,
                    6,
                )
                if pipeline_seconds
                else None
            ),
            "conversion_status": (
                "success"
            ),
            "ocr": {
                "enabled": bool(
                    profile[
                        "ocr_enabled"
                    ]
                ),
                "mode": (
                    "structured_document"
                ),
                "engine": (
                    "PP-OCRv5_server"
                ),
                "backend": (
                    "PPStructureV3"
                ),
                "language": None,
                "scale": None,
                "effective_dpi": None,
                "pages_requested": (
                    page_count
                ),
                "pages_processed": (
                    pages_processed
                ),
                "fallback_ocr_pages": None,
                "failed_ocr_pages": None,
                "requested_page_numbers": (
                    list(
                        range(
                            1,
                            page_count + 1,
                        )
                    )
                ),
                "failed_page_numbers": None,
                "tracking_note": (
                    "PPStructureV3 returned an "
                    "overall_ocr_res object for "
                    "each returned page. Explicit "
                    "per-page OCR failure callbacks "
                    "are not inferred."
                ),
            },
            "paddle_runtime": {
                "device": str(
                    profile.get("device", "cpu")
                ),
                "engine_requested": str(
                    profile.get(
                        "inference_engine", "paddle_static"
                    )
                ),
                "mkldnn_enabled": bool(
                    profile.get("enable_mkldnn", False)
                ),
                "mkldnn_cache_capacity": int(
                    profile.get("mkldnn_cache_capacity", 10)
                ),
                "cpu_threads_requested": (
                    int(profile["cpu_threads"])
                    if profile.get("cpu_threads") is not None
                    else None
                ),
                "hpi_enabled": False,
                "cinn_enabled": False,
            },
            "warnings_count": len(
                warning_messages
            ),
            "warning_messages": (
                warning_messages
            ),
            "parser_log_warning_lines": (
                len(
                    warning_messages
                )
            ),
            "parser_log_error_lines": (
                parser_log_error_lines
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
                parser_output
            ),
            "raw_markdown": (
                artifact_result[
                    "content_elements"
                ][
                    "raw_markdown"
                ]
            ),
            "clean_markdown": (
                artifact_result[
                    "content_elements"
                ][
                    "clean_markdown"
                ]
            ),
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
        "content_validation": artifact_result["content_validation"],

        "output": (
            output_metrics
        ),

        "paddleocr_native": {
            "backend": (
                "PPStructureV3"
            ),
            "native_page_results": (
                len(parser_native_pages)
            ),
            "native_page_markdown_bytes": (
                native_page_markdown_bytes
            ),
            "ocr_texts": (
                total_ocr_texts
            ),
            "tables": (
                total_tables
            ),
            "formulas": (
                total_formulas
            ),
            "layout_blocks": (
                total_parsing_blocks
            ),
            "document_angle_counts": (
                dict(
                    sorted(
                        document_angles.items()
                    )
                )
            ),
            "textline_orientation_counts": (
                dict(
                    sorted(
                        line_angles.items()
                    )
                )
            ),
            "region_detection": bool(
                profile[
                    "region_detection"
                ]
            ),
            "chart_recognition": bool(
                profile[
                    "chart_recognition"
                ]
            ),
            "document_unwarping": bool(
                profile[
                    "document_unwarping"
                ]
            ),
            "seal_recognition": bool(
                profile[
                    "seal_recognition"
                ]
            ),
            "intermediate_assets_persisted": (
                False
            ),
            "official_markdown_bundle_available": native_bundle_manifest is not None,
            "official_markdown_bundle_files": (
                len(native_bundle_manifest.get("files", []))
                if native_bundle_manifest is not None else 0
            ),
        },
    }

    if args.artifact_policy.includes(
        "metrics.json"
    ):
        write_json(
            paths.metrics_json,
            metrics,
        )

    print()
    print("=" * 72)
    print("PADDLEOCR V2 ARTIFACT RESULT")
    print("=" * 72)

    print(
        f"Pages:                 "
        f"{pages_processed}/{page_count}"
    )

    print(
        f"Tables:                "
        f"{total_tables}"
    )

    print(
        f"Formulas:              "
        f"{total_formulas}"
    )

    print(
        "Document angles:       "
        f"{dict(sorted(document_angles.items()))}"
    )

    print(
        "Text-line angles:      "
        f"{dict(sorted(line_angles.items()))}"
    )

    print(
        "Raw tokens:            "
        f"{artifact_result['tokens']['reference']['raw_markdown_tokens']}"
    )

    print(
        "Clean tokens:          "
        f"{artifact_result['tokens']['reference']['clean_markdown_tokens']}"
    )

    print(
        "Empty pages:           "
        f"{artifact_result['empty_output_pages']}"
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
        "Average CPU:           "
        f"{resources['average_cpu_system_capacity_percent']}%"
    )

    print(
        "Peak CPU:              "
        f"{resources['peak_cpu_system_capacity_percent']}%"
    )

    print(
        "Average RAM:           "
        f"{resources['average_rss_mb']} MB"
    )

    print(
        "Peak RAM:              "
        f"{resources['peak_rss_mb']} MB"
    )

    print(
        "Metrics:               "
        + (
            str(paths.metrics_json)
            if args.artifact_policy.includes(
                "metrics.json"
            )
            else "not selected"
        )
    )

    print(
        "Artifacts written:     "
        + ", ".join(
            args.artifact_policy.as_list()
        )
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
