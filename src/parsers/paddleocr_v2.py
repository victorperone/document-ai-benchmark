from __future__ import annotations

import argparse
import hashlib
import json
import platform
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from time import perf_counter
from typing import Any

from paddleocr import PPStructureV3

from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.artifacts import finalize_artifacts
from src.benchmark.config import (
    get_normalization_config,
    get_profile,
    get_reference_tokenizer,
)
from src.benchmark.metrics_writer import write_json
from src.benchmark.paths import build_output_paths
from src.benchmark.resource_monitor import ResourceMonitor
from src.benchmark.runtime_io import (
    add_runtime_arguments,
    parser_output_context,
)


PARSER_NAME = "paddleocr"
PARSER_DISPLAY_NAME = "PaddleOCR / PPStructureV3"

DEFAULT_MODEL_ROOT = Path(
    "/home/appuser/.paddlex/official_models"
)


MODEL_NAMES = {
    "layout": "PP-DocLayout_plus-L",
    "region": "PP-DocBlockLayout",
    "doc_orientation": "PP-LCNet_x1_0_doc_ori",
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


def resolve_model_paths(
    model_root: Path,
) -> dict[str, Path]:
    paths = {
        key: model_root / model_name
        for key, model_name in MODEL_NAMES.items()
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
    required = {
        "ocr_enabled": True,
        "table_recognition": True,
        "formula_recognition": True,
        "chart_recognition": False,
        "document_orientation_classification": True,
        "textline_orientation": True,
        "document_unwarping": False,
        "region_detection": True,
        "seal_recognition": False,
    }

    mismatches = []

    for key, expected in required.items():
        actual = profile.get(key)

        if actual is not expected:
            mismatches.append(
                f"{key}: expected {expected!r}, "
                f"got {actual!r}"
            )

    if mismatches:
        raise ValueError(
            "Profile does not match the validated "
            "PaddleOCR MVP configuration:\n  - "
            + "\n  - ".join(mismatches)
        )


def build_pipeline(
    model_paths: dict[str, Path],
    profile: dict[str, Any],
) -> PPStructureV3:
    return PPStructureV3(
        layout_detection_model_dir=str(
            model_paths["layout"]
        ),
        region_detection_model_dir=str(
            model_paths["region"]
        ),
        doc_orientation_classify_model_dir=str(
            model_paths["doc_orientation"]
        ),
        text_detection_model_dir=str(
            model_paths["text_detection"]
        ),
        textline_orientation_model_dir=str(
            model_paths["textline_orientation"]
        ),
        text_recognition_model_dir=str(
            model_paths["text_recognition"]
        ),
        table_classification_model_dir=str(
            model_paths["table_classification"]
        ),
        wired_table_structure_recognition_model_dir=str(
            model_paths["wired_table_structure"]
        ),
        wireless_table_structure_recognition_model_dir=str(
            model_paths["wireless_table_structure"]
        ),
        wired_table_cells_detection_model_dir=str(
            model_paths["wired_table_cells"]
        ),
        wireless_table_cells_detection_model_dir=str(
            model_paths["wireless_table_cells"]
        ),
        table_orientation_classify_model_dir=str(
            model_paths["table_orientation"]
        ),
        formula_recognition_model_dir=str(
            model_paths["formula"]
        ),
        use_doc_orientation_classify=profile[
            "document_orientation_classification"
        ],
        use_doc_unwarping=profile[
            "document_unwarping"
        ],
        use_textline_orientation=profile[
            "textline_orientation"
        ],
        use_seal_recognition=profile[
            "seal_recognition"
        ],
        use_table_recognition=profile[
            "table_recognition"
        ],
        use_formula_recognition=profile[
            "formula_recognition"
        ],
        use_chart_recognition=profile[
            "chart_recognition"
        ],
        use_region_detection=profile[
            "region_detection"
        ],
    )



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
        page_idx = result["page_index"]

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

        ocr_result = result[
            "overall_ocr_res"
        ]

        rec_texts = ocr_result[
            "rec_texts"
        ]

        orientations = [
            int(value)
            for value in ocr_result[
                "textline_orientation_angles"
            ]
        ]

        tables = result[
            "table_res_list"
        ]

        formulas = result[
            "formula_res_list"
        ]

        parsing_blocks = result[
            "parsing_res_list"
        ]

        document_angle = int(
            result[
                "doc_preprocessor_res"
            ]["angle"]
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
                "table_count": len(
                    tables
                ),
                "formula_count": len(
                    formulas
                ),
                "parsing_block_count": len(
                    parsing_blocks
                ),
            }
        )

    return (
        page_texts,
        parser_page_elements,
        parser_native_pages,
    )

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
        model_root
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
    print("OCR:          enabled")
    print("Tables:       enabled")
    print("Formulas:     enabled")
    print("Doc orient.:  enabled")
    print("Line orient.: enabled")
    print("Region det.:  enabled")
    print("Chart:        disabled")
    print("Unwarping:    disabled")
    print("Seal:         disabled")
    print("=" * 72)

    monitor = ResourceMonitor()

    pipeline_started = perf_counter()
    monitor.start()

    initialization_seconds = None
    extraction_seconds = None

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

            results = list(
                pipeline.predict(
                    input=str(input_path),
                    use_doc_orientation_classify=profile[
                        "document_orientation_classification"
                    ],
                    use_doc_unwarping=profile[
                        "document_unwarping"
                    ],
                    use_textline_orientation=profile[
                        "textline_orientation"
                    ],
                    use_seal_recognition=profile[
                        "seal_recognition"
                    ],
                    use_table_recognition=profile[
                        "table_recognition"
                    ],
                    use_formula_recognition=profile[
                        "formula_recognition"
                    ],
                    use_chart_recognition=profile[
                        "chart_recognition"
                    ],
                    use_region_detection=profile[
                        "region_detection"
                    ],
                )
            )

            extraction_seconds = (
                perf_counter()
                - extraction_started
            )

        if not results:
            raise RuntimeError(
                "PPStructureV3 returned no pages."
            )

        results.sort(
            key=lambda result: result[
                "page_index"
            ]
        )

        page_indexes = [
            result["page_index"]
            for result in results
        ]

        expected_indexes = list(
            range(page_count)
        )

        if page_indexes != expected_indexes:
            raise RuntimeError(
                "Unexpected PaddleOCR page indexes. "
                f"Expected {expected_indexes}, "
                f"got {page_indexes}."
            )

        (
            page_texts,
            parser_page_elements,
            parser_native_pages,
        ) = build_paddleocr_page_contract(
            results
        )

        artifact_result = finalize_artifacts(
            paths=paths,
            document_id=input_path.stem,
            source_file=input_path.name,
            parser_name=PARSER_NAME,
            profile_name=args.profile,
            page_texts=page_texts,
            parser_page_elements=(
                parser_page_elements
            ),
            parser_native_pages=(
                parser_native_pages
            ),
            tokenizer_name=tokenizer_name,
            normalization_config=(
                normalization_config
            ),
            artifact_policy=(
                args.artifact_policy
            ),
        )

    except Exception:
        monitor.stop()
        raise

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

    total_formulas = sum(
        page["formula_count"]
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
        "layout_boxes": (
            total_parsing_blocks
        ),
        "tables_detected": (
            total_tables
        ),
        "images_detected": None,
        "headings_detected": None,
        "lists_detected": None,
        "formulas_detected": (
            total_formulas
        ),
        "captions_detected": None,
        "page_headers_detected": None,
        "page_footers_detected": None,
        "footnotes_detected": None,
        "text_blocks_detected": None,
        "code_blocks_detected": None,
        "charts_detected": None,
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
    ] = dict(
        MODEL_NAMES
    )

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
            "schema_version": 2,
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

        "output": (
            output_metrics
        ),

        "paddleocr_native": {
            "backend": (
                "PPStructureV3"
            ),
            "native_page_results": (
                len(results)
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
