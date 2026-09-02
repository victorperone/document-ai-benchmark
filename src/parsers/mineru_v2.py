from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from time import perf_counter
import json
import shutil
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from importlib import metadata
import platform

from collections import Counter
from typing import Any

from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.artifact_contract import ParserArtifactInput, join_page_texts
from src.benchmark.artifacts import finalize_artifacts
from src.benchmark.config import (
    get_normalization_config,
    get_profile,
    get_reference_tokenizer,
)
from src.benchmark.paths import build_output_paths
from src.benchmark.metrics_writer import write_json
from src.benchmark.preflight import make_check, make_result
from src.benchmark.resource_monitor import ResourceMonitor
from src.benchmark.runtime_io import add_runtime_arguments


PARSER_NAME = "mineru"
PARSER_DISPLAY_NAME = "MinerU"


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
        description="MinerU benchmark adapter v2.",
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
        default="auto",
    )

    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help=(
            "Optional thread-count override. "
            "If omitted, the MinerU/runtime default is preserved."
        ),
    )

    add_runtime_arguments(parser)

    args = parser.parse_args()

    args.artifact_policy = ArtifactPolicy.from_cli(
        args.artifacts
    )

    return args


_MINERU_VALID_METHODS: frozenset[str] = frozenset(
    {"txt", "auto", "ocr"}
)


def preflight_profile(
    profile_name: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def _pkg(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    # --------------------------------------------------
    # Profile configuration
    # --------------------------------------------------

    try:
        profile = get_profile(PARSER_NAME, profile_name)
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
    # Method
    # --------------------------------------------------

    method = str(profile.get("method", ""))
    method_ok = method in _MINERU_VALID_METHODS
    checks.append(
        make_check(
            "method",
            "pass" if method_ok else "fail",
            method if method_ok else (
                f"{method!r} — must be one of "
                f"{sorted(_MINERU_VALID_METHODS)}"
            ),
        )
    )

    # --------------------------------------------------
    # OCR coherence
    # --------------------------------------------------

    ocr_enabled = bool(profile.get("ocr_enabled", True))
    if method == "txt" and ocr_enabled:
        checks.append(
            make_check(
                "ocr coherence",
                "warn",
                "method=txt but ocr_enabled=True",
            )
        )
    elif method in {"auto", "ocr"} and not ocr_enabled:
        checks.append(
            make_check(
                "ocr coherence",
                "warn",
                f"method={method} but ocr_enabled=False",
            )
        )

    # --------------------------------------------------
    # MinerU CLI
    # --------------------------------------------------

    mineru_path = shutil.which("mineru")
    checks.append(
        make_check(
            "mineru CLI",
            "pass" if mineru_path is not None else "fail",
            mineru_path or "not found in PATH",
        )
    )

    # --------------------------------------------------
    # Packages
    # --------------------------------------------------

    for pkg in ("mineru", "torch"):
        ver = _pkg(pkg)
        checks.append(
            make_check(
                pkg,
                "pass" if ver is not None else "fail",
                ver or "not installed",
            )
        )

    # --------------------------------------------------
    # Environment variables
    # --------------------------------------------------

    model_source = os.environ.get("MINERU_MODEL_SOURCE")
    checks.append(
        make_check(
            "MINERU_MODEL_SOURCE",
            "pass" if model_source == "local" else "fail",
            model_source or "not set",
        )
    )

    config_path_str = os.environ.get("MINERU_TOOLS_CONFIG_JSON")
    if config_path_str:
        config_path = Path(config_path_str)
        config_ok = False
        config_data: dict | None = None
        config_detail: str
        try:
            config_text = config_path.read_text(encoding="utf-8")
            config_data = json.loads(config_text)
            config_ok = True
            config_detail = str(config_path)
        except FileNotFoundError:
            config_detail = f"not found: {config_path}"
        except json.JSONDecodeError as exc:
            config_detail = f"invalid JSON: {exc}"
        checks.append(
            make_check(
                "MINERU_TOOLS_CONFIG_JSON",
                "pass" if config_ok else "fail",
                config_detail,
            )
        )

        if config_data is not None:
            models_dir = config_data.get("models-dir")
            if not isinstance(models_dir, dict):
                checks.append(
                    make_check(
                        "MinerU pipeline models",
                        "fail",
                        "models-dir is missing or not a dict in mineru.json",
                    )
                )
            else:
                pipeline_model_dir = models_dir.get("pipeline")
                if (
                    not isinstance(pipeline_model_dir, str)
                    or not pipeline_model_dir.strip()
                ):
                    checks.append(
                        make_check(
                            "MinerU pipeline models",
                            "fail",
                            "models-dir.pipeline is missing or empty",
                        )
                    )
                else:
                    pipeline_path = Path(
                        pipeline_model_dir
                    ).expanduser()
                    checks.append(
                        make_check(
                            "MinerU pipeline models",
                            "pass" if pipeline_path.is_dir() else "fail",
                            str(pipeline_path),
                        )
                    )
    else:
        checks.append(
            make_check(
                "MINERU_TOOLS_CONFIG_JSON",
                "fail",
                "not set",
            )
        )

    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        hf_path = Path(hf_home)
        checks.append(
            make_check(
                "HF_HOME",
                "pass" if hf_path.exists() else "warn",
                hf_home
                + ("" if hf_path.exists() else " (does not exist yet)"),
            )
        )
    else:
        checks.append(
            make_check("HF_HOME", "warn", "not set")
        )

    return make_result(
        PARSER_NAME,
        profile_name,
        checks)


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
        create=False,
    )
    inventory = _load_cached_inventory(
        input_path,
        args.output_root,
    )

    method = str(
        profile.get(
            "method",
            "auto",
        )
    )

    backend = str(
        profile.get(
            "backend",
            "pipeline",
        )
    )

    formula_enabled = bool(
        profile.get("formula", True)
    )
    table_enabled = bool(
        profile.get("table", True)
    )

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:       {PARSER_DISPLAY_NAME}")
    print(f"Input:        {input_path}")
    print(f"Profile:      {args.profile}")
    print(f"Backend:      {backend}")
    print(f"Method:       {method}")
    print(
        "Threads:      "
        + (
            str(args.threads)
            if args.threads is not None
            else "MinerU default"
        )
    )
    print(f"Tokenizer:    {tokenizer_name}")
    print(
        "Native temp:  ephemeral"
    )
    print("=" * 72)

    monitor = ResourceMonitor()

    pipeline_started = perf_counter()
    monitor.start()

    try:
        extraction_started = perf_counter()

        table_merge_enabled = bool(
            profile.get("table_merge", True)
        )

        persist_native = args.artifact_policy.includes("native")

        native_result = run_mineru_native(
            input_path=input_path,
            method=method,
            backend=backend,
            formula_enabled=formula_enabled,
            table_enabled=table_enabled,
            table_merge_enabled=table_merge_enabled,
            threads=args.threads,
            verbose=args.verbose,
            native_bundle_destination=(
                paths.native_dir if persist_native else None
            ),
            parser_name=PARSER_NAME,
            profile_name=args.profile,
        )

        extraction_seconds = (
            perf_counter()
            - extraction_started
        )

        content_list = (
            native_result["content_list"]
        )

        middle = native_result["middle"]

        page_count = get_mineru_page_count(
            middle,
            content_list,
        )

        (
            page_texts,
            parser_page_elements,
            parser_native_pages,
        ) = build_mineru_page_contract(
            content_list,
            page_count,
        )

        artifact_input = ParserArtifactInput(
            native_markdown=native_result["native_markdown"],
            source_page_markdown=page_texts,
            enriched_page_markdown=None,
            page_mapping_status="complete",
            parser_page_elements=parser_page_elements,
            parser_native_pages=parser_native_pages,
            derived_content_by_page=[[] for _ in page_texts],
            raw_origin_kind="parser_native_exact",
            raw_origin_details=f"{input_path.stem}.md",
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

        if args.artifact_policy.includes(
            "run.log"
        ):
            paths.run_log.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            paths.run_log.write_text(
                native_result["log_text"],
                encoding="utf-8",
            )

    except Exception:
        monitor.stop()
        raise

    resources = monitor.stop()

    pipeline_seconds = (
        perf_counter()
        - pipeline_started
    )

    # -----------------------------------------------------------------
    # Benchmark metrics v2
    # -----------------------------------------------------------------

    type_counts = Counter(
        str(
            item.get(
                "type",
                "unknown",
            )
        )
        for item in content_list
    )

    observed_pages = {
        item["page_idx"]
        for item in content_list
        if isinstance(
            item.get("page_idx"),
            int,
        )
    }

    pages_processed = len(
        observed_pages
    )

    failed_pages = max(
        page_count
        - pages_processed,
        0,
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

    warning_messages = [
        line.strip()
        for line
        in native_result[
            "log_text"
        ].splitlines()
        if "warning" in line.lower()
    ]

    parser_log_error_lines = sum(
        "error" in line.lower()
        for line
        in native_result[
            "log_text"
        ].splitlines()
    )

    table_captions = sum(
        bool(
            _text_list(
                item.get(
                    "table_caption"
                )
            )
        )
        for item in content_list
        if item.get("type")
        == "table"
    )

    parser_output = {
        "layout_boxes": None,
        "tables_detected": (
            type_counts.get(
                "table",
                0,
            )
        ),
        "images_detected": (
            type_counts.get(
                "image",
                0,
            )
        ),
        "headings_detected": None,
        "lists_detected": None,
        "formulas_detected": (
            type_counts.get(
                "equation",
                0,
            )
        ),
        "captions_detected": (
            table_captions
        ),
        "page_headers_detected": (
            type_counts.get(
                "header",
                0,
            )
        ),
        "page_footers_detected": (
            type_counts.get(
                "footer",
                0,
            )
        ),
        "footnotes_detected": None,
        "text_blocks_detected": (
            type_counts.get(
                "text",
                0,
            )
        ),
        "code_blocks_detected": (
            type_counts.get(
                "code",
                0,
            )
        ),
        "charts_detected": None,
        "box_class_counts": dict(
            sorted(
                type_counts.items()
            )
        ),
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
    ] = backend

    resolved_config[
        "formula"
    ] = formula_enabled

    resolved_config[
        "table"
    ] = table_enabled

    resolved_config[
        "table_merge"
    ] = table_merge_enabled

    resolved_config[
        "threads"
    ] = args.threads

    resolved_config[
        "capability_exceptions"
    ] = []

    output_metrics = dict(
        artifact_result[
            "output"
        ]
    )

    output_metrics[
        "run_log"
    ] = (
        str(
            paths.run_log
        )
        if args.artifact_policy.includes(
            "run.log"
        )
        else None
    )

    output_metrics[
        "metrics_json"
    ] = (
        str(
            paths.metrics_json
        )
        if args.artifact_policy.includes(
            "metrics.json"
        )
        else None
    )

    output_metrics[
        "input_to_clean_markdown_size_ratio"
    ] = size_ratio

    native_markdown_bytes = len(
        native_result[
            "native_markdown"
        ].encode(
            "utf-8"
        )
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
                "mineru": (
                    _package_version(
                        "mineru"
                    )
                ),
                "torch": (
                    _package_version(
                        "torch"
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
            "initialization_seconds": None,
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
            "pages_total": (
                page_count
            ),
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
                    profile.get(
                        "ocr_enabled",
                        True,
                    )
                ),
                "mode": method,
                "engine": None,
                "backend": (
                    "pipeline"
                ),
                "language": None,
                "scale": None,
                "effective_dpi": None,
                "pages_requested": None,
                "pages_processed": None,
                "fallback_ocr_pages": None,
                "failed_ocr_pages": None,
                "requested_page_numbers": None,
                "failed_page_numbers": None,
                "tracking_note": (
                    "MinerU 3.4.4 auto mode "
                    "does not expose a stable "
                    "per-page OCR callback in "
                    "this adapter. OCR page "
                    "counts are therefore not "
                    "inferred."
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

        "artifacts": artifact_result["artifacts"],

        "quality_eligibility": artifact_result["quality_eligibility"],

        "output": (
            output_metrics
        ),

        "mineru_native": {
            "backend": backend,
            "method": method,
            "formula_enabled": formula_enabled,
            "table_enabled": table_enabled,
            "table_merge_enabled": table_merge_enabled,
            "native_bundle_valid": (
                native_result.get("native_bundle_manifest") is not None
            ),
            "native_content_items": (
                len(
                    content_list
                )
            ),
            "native_markdown_bytes": (
                native_markdown_bytes
            ),
            "content_type_counts": dict(
                sorted(
                    type_counts.items()
                )
            ),
            "intermediate_assets_persisted": (
                native_result.get("native_bundle_manifest") is not None
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
    print("MINERU V2 ARTIFACT RESULT")
    print("=" * 72)

    print(
        f"Pages:                 "
        f"{len(page_texts)}/{page_count}"
    )

    print(
        "Empty pages:           "
        f"{artifact_result['empty_output_pages']}"
    )

    print(
        "Native content items:  "
        f"{len(content_list)}"
    )

    print(
        "Native Markdown bytes: "
        f"{len(native_result['native_markdown'].encode('utf-8'))}"
    )

    print(
        "Image refs in pages:   "
        f"{sum('images/' in text for text in page_texts)}"
    )

    print(
        "Intermediate assets:   "
        "temporary / discarded"
    )

    print(
        f"Pipeline:              "
        f"{pipeline_seconds:.3f} s"
    )

    print(
        f"Average CPU:           "
        f"{resources['average_cpu_percent']:.2f}%"
    )

    print(
        f"Peak CPU:              "
        f"{resources['peak_cpu_percent']:.2f}%"
    )

    print(
        f"Average RAM:           "
        f"{resources['average_rss_mb']:.3f} MB"
    )

    print(
        f"Peak RAM:              "
        f"{resources['peak_rss_mb']:.3f} MB"
    )

    print(
        f"Output:                "
        f"{paths.output_dir}"
    )

    print("=" * 72)


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [
        str(item).strip()
        for item in value
        if str(item).strip()
    ]


def render_mineru_item(
    item: dict[str, Any],
) -> str:
    item_type = str(
        item.get("type", "unknown")
    )

    if item_type in {
        "text",
        "header",
        "footer",
        "page_number",
        "equation",
    }:
        return str(
            item.get("text", "")
        ).strip()

    if item_type == "code":
        blocks: list[str] = []

        blocks.extend(
            _text_list(
                item.get("code_caption")
            )
        )

        code_body = str(
            item.get("code_body", "")
        ).strip()

        if code_body:
            blocks.append(
                "```\n"
                + code_body
                + "\n```"
            )

        blocks.extend(
            _text_list(
                item.get("code_footnote")
            )
        )

        return "\n\n".join(blocks)

    if item_type == "table":
        blocks = []

        blocks.extend(
            _text_list(
                item.get("table_caption")
            )
        )

        table_body = str(
            item.get("table_body", "")
        ).strip()

        if table_body:
            blocks.append(table_body)

        blocks.extend(
            _text_list(
                item.get("table_footnote")
            )
        )

        return "\n\n".join(blocks)

    # Fail-safe for future MinerU item types:
    # preserve an exposed textual field when one exists,
    # but never invent textual content.
    fallback_text = item.get("text")

    if isinstance(fallback_text, str):
        return fallback_text.strip()

    return ""


def build_mineru_page_contract(
    content_list: list[dict[str, Any]],
    page_count: int,
) -> tuple[
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    if page_count < 1:
        raise ValueError(
            "MinerU page_count must be >= 1."
        )

    grouped: list[
        list[dict[str, Any]]
    ] = [
        []
        for _ in range(page_count)
    ]

    for index, item in enumerate(
        content_list
    ):
        if not isinstance(item, dict):
            raise TypeError(
                "MinerU content_list item "
                f"{index} is not a dictionary."
            )

        page_idx = item.get("page_idx")

        if not isinstance(page_idx, int):
            raise ValueError(
                "MinerU content_list item "
                f"{index} has invalid page_idx: "
                f"{page_idx!r}"
            )

        if not 0 <= page_idx < page_count:
            raise ValueError(
                "MinerU content_list item "
                f"{index} has out-of-range "
                f"page_idx={page_idx}; "
                f"page_count={page_count}."
            )

        grouped[page_idx].append(item)

    page_texts: list[str] = []
    parser_page_elements: list[
        dict[str, Any]
    ] = []
    parser_native_pages: list[
        dict[str, Any]
    ] = []

    for page_idx, items in enumerate(
        grouped
    ):
        blocks: list[str] = []

        for item in items:
            rendered = render_mineru_item(
                item
            )

            if rendered:
                blocks.append(rendered)

        page_texts.append(
            "\n\n".join(blocks).strip()
        )

        type_counts = Counter(
            str(
                item.get(
                    "type",
                    "unknown",
                )
            )
            for item in items
        )

        parser_page_elements.append(
            {
                "items": len(items),
                "type_counts": dict(
                    sorted(
                        type_counts.items()
                    )
                ),
            }
        )

        parser_native_pages.append(
            {
                "page_idx": page_idx,
                "items": items,
            }
        )

    return (
        page_texts,
        parser_page_elements,
        parser_native_pages,
    )

def find_mineru_output(
    root: Path,
    exact_name: str,
) -> Path:
    matches = list(
        root.rglob(exact_name)
    )

    if not matches:
        raise FileNotFoundError(
            "MinerU native output not found: "
            f"{exact_name}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            "Multiple MinerU native outputs found "
            f"for {exact_name}: {matches}"
        )

    return matches[0]


def get_mineru_page_count(
    middle: dict[str, Any],
    content_list: list[dict[str, Any]],
) -> int:
    pdf_info = middle.get("pdf_info")

    if isinstance(pdf_info, list) and pdf_info:
        return len(pdf_info)

    page_indexes = [
        item.get("page_idx")
        for item in content_list
        if isinstance(
            item.get("page_idx"),
            int,
        )
    ]

    if page_indexes:
        return max(page_indexes) + 1

    raise ValueError(
        "Unable to determine MinerU page count."
    )


def _copy_mineru_bundle(
    *,
    native_root: Path,
    document_id: str,
    markdown_path: Path,
    content_list_path: Path,
    middle_path: Path,
    destination: Path,
    parser_name: str,
    profile_name: str,
) -> dict[str, Any]:
    """Copy MinerU output bundle to native/ before temp dir is destroyed.

    Returns a manifest dict with schema_version=1 and file entries.
    Never follows symlinks; rejects path traversal.
    """
    import shutil as _shutil

    destination.mkdir(parents=True, exist_ok=True)
    assets_dest = destination / "assets"

    manifest_files: list[dict[str, Any]] = []

    def _copy_entry(src: Path, rel: str) -> None:
        dest_path = destination / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src, dest_path)
        sha = hashlib.sha256(dest_path.read_bytes()).hexdigest()
        manifest_files.append({
            "path": rel,
            "sha256": sha,
            "size_bytes": dest_path.stat().st_size,
            "source": "mineru",
        })

    _copy_entry(markdown_path, f"{document_id}.md")
    _copy_entry(content_list_path, f"{document_id}_content_list.json")
    _copy_entry(middle_path, f"{document_id}_middle.json")

    # Copy assets directory preserving relative structure so markdown links stay valid.
    # MinerU typically outputs images/ under native_root/document_id or native_root.
    assets_src = native_root / document_id / "images"
    if not assets_src.is_dir():
        assets_src = native_root / "images"
    if assets_src.is_dir():
        assets_src_resolved = assets_src.resolve()
        # Determine relative prefix so that destination mirrors source structure.
        # e.g. assets_src = .../auto/<doc_id>/images  →  copy to native/images/
        assets_rel_root = assets_src.name  # "images"
        for asset in assets_src.rglob("*"):
            if asset.is_symlink() or not asset.is_file():
                continue
            # Safety: ensure asset stays inside assets_src tree
            try:
                asset.resolve().relative_to(assets_src_resolved)
            except ValueError:
                continue
            rel_to_assets = asset.relative_to(assets_src)
            rel_in_bundle = Path(assets_rel_root) / rel_to_assets
            dest_asset = destination / rel_in_bundle
            dest_asset.parent.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(asset, dest_asset)
            sha = hashlib.sha256(dest_asset.read_bytes()).hexdigest()
            manifest_files.append({
                "path": rel_in_bundle.as_posix(),
                "sha256": sha,
                "size_bytes": dest_asset.stat().st_size,
                "source": "mineru",
            })

    # Validate relative image links in the official markdown against the bundle
    _validate_mineru_markdown_links(markdown_path, destination, document_id)

    manifest = {
        "schema_version": 1,
        "parser": parser_name,
        "profile": profile_name,
        "bundle_status": "available",
        "files": manifest_files,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


import re as _re

_MD_IMAGE_RE = _re.compile(r'!\[[^\]]*\]\(([^)]+)\)')


def _validate_mineru_markdown_links(
    markdown_path: Path,
    bundle_root: Path,
    document_id: str,
) -> None:
    """Verify that all relative image links in the MinerU markdown exist in the bundle.

    Raises RuntimeError if any declared local asset is missing after bundle copy.
    Ignores http/https/data URIs.
    """
    try:
        content = markdown_path.read_text(encoding="utf-8")
    except Exception:
        return

    bundle_root_resolved = bundle_root.resolve()
    missing: list[str] = []

    for match in _MD_IMAGE_RE.finditer(content):
        href = match.group(1).strip()
        if href.startswith(("http://", "https://", "data:", "#")):
            continue
        # Resolve relative to bundle root (MinerU links are relative to the .md file)
        candidate = (bundle_root / href).resolve()
        try:
            candidate.relative_to(bundle_root_resolved)
        except ValueError:
            missing.append(href)
            continue
        if not candidate.is_file():
            missing.append(href)

    if missing:
        raise RuntimeError(
            f"MinerU native bundle is incomplete — {len(missing)} image link(s) "
            f"declared in {document_id}.md are missing from native/: "
            + ", ".join(missing[:5])
        )


def run_mineru_native(
    *,
    input_path: Path,
    method: str,
    backend: str = "pipeline",
    formula_enabled: bool = True,
    table_enabled: bool = True,
    table_merge_enabled: bool = True,
    threads: int | None,
    verbose: bool,
    native_bundle_destination: Path | None = None,
    parser_name: str = "mineru",
    profile_name: str = "",
) -> dict[str, Any]:
    if method not in {
        "txt",
        "auto",
        "ocr",
    }:
        raise ValueError(
            f"Unsupported MinerU method: {method}"
        )

    environment = os.environ.copy()

    environment["MINERU_FORMULA_ENABLE"] = (
        "true" if formula_enabled else "false"
    )
    environment["MINERU_TABLE_ENABLE"] = (
        "true" if table_enabled else "false"
    )
    environment["MINERU_TABLE_MERGE_ENABLE"] = (
        "true" if table_merge_enabled else "false"
    )

    if threads is not None:
        thread_value = str(threads)

        environment[
            "MINERU_INTRA_OP_NUM_THREADS"
        ] = thread_value

        environment[
            "OMP_NUM_THREADS"
        ] = thread_value

        environment[
            "MKL_NUM_THREADS"
        ] = thread_value

    with tempfile.TemporaryDirectory(
        prefix="mineru_v2_",
    ) as temporary_directory:
        native_root = Path(
            temporary_directory
        )

        command = [
            "mineru",
            "-p",
            str(input_path),
            "-o",
            str(native_root),
            "-b",
            backend,
            "-m",
            method,
            "--formula",
            str(formula_enabled).lower(),
            "--table",
            str(table_enabled).lower(),
        ]

        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            text=True,
            check=False,
        )

        log_text = (
            process.stdout or ""
        )

        if verbose and log_text:
            print(
                log_text,
                end=(
                    ""
                    if log_text.endswith("\n")
                    else "\n"
                ),
            )

        if process.returncode != 0:
            log_tail = "\n".join(
                log_text.splitlines()[-80:]
            )

            raise RuntimeError(
                "MinerU exited with code "
                f"{process.returncode}.\n\n"
                f"{log_tail}"
            )

        document_id = input_path.stem

        markdown_path = find_mineru_output(
            native_root,
            f"{document_id}.md",
        )

        content_list_path = (
            find_mineru_output(
                native_root,
                f"{document_id}_content_list.json",
            )
        )

        middle_path = find_mineru_output(
            native_root,
            f"{document_id}_middle.json",
        )

        try:
            native_markdown = (
                markdown_path.read_text(
                    encoding="utf-8",
                )
            )
        except UnicodeDecodeError as _ude:
            raise RuntimeError(
                f"MinerU produced a non-UTF-8 markdown file: {_ude}"
            ) from _ude

        content_list = json.loads(
            content_list_path.read_text(
                encoding="utf-8",
            )
        )

        middle = json.loads(
            middle_path.read_text(
                encoding="utf-8",
            )
        )

        if not isinstance(
            content_list,
            list,
        ):
            raise TypeError(
                "MinerU content_list must "
                "be a list."
            )

        if not isinstance(
            middle,
            dict,
        ):
            raise TypeError(
                "MinerU middle output must "
                "be a dictionary."
            )

        native_bundle_manifest: dict[str, Any] | None = None
        if native_bundle_destination is not None:
            native_bundle_manifest = _copy_mineru_bundle(
                native_root=native_root,
                document_id=document_id,
                markdown_path=markdown_path,
                content_list_path=content_list_path,
                middle_path=middle_path,
                destination=native_bundle_destination,
                parser_name=parser_name,
                profile_name=profile_name,
            )

        return {
            "command": command,
            "returncode": (
                process.returncode
            ),
            "native_markdown": (
                native_markdown
            ),
            "content_list": (
                content_list
            ),
            "middle": middle,
            "log_text": log_text,
            "native_bundle_manifest": native_bundle_manifest,
        }

if __name__ == "__main__":
    main()
