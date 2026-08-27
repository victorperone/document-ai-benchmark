from __future__ import annotations

import argparse
import importlib.metadata
import inspect
import json
import platform
import shutil
import subprocess
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pymupdf
import pymupdf4llm

from pymupdf4llm.ocr import (
    rapidtess_api,
)

from src.benchmark.artifact_policy import (
    ArtifactPolicy,
    ArtifactSelectionError,
)
from src.benchmark.artifacts import (
    finalize_artifacts,
)
from src.benchmark.config import (
    get_normalization_config,
    get_profile,
    get_reference_tokenizer,
)
from src.benchmark.metrics_writer import (
    write_json,
)
from src.benchmark.paths import (
    build_output_paths,
)
from src.benchmark.preflight import (
    make_check,
    make_result,
)
from src.benchmark.resource_monitor import (
    ResourceMonitor,
)
from src.benchmark.runtime_io import (
    add_runtime_arguments,
    parser_output_context,
)
from src.benchmark.source_inventory import (
    analyze_pdf_source,
    calculate_sha256,
)


PARSER_NAME = "pymupdf"

_TESSDATA_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    "/usr/local/share/tessdata",
)


def _find_tessdata_prefix() -> str | None:
    import os
    prefix_env = os.environ.get("TESSDATA_PREFIX")
    if prefix_env and Path(prefix_env).is_dir():
        return prefix_env
    for candidate in _TESSDATA_CANDIDATES:
        if Path(candidate).is_dir():
            return candidate
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "PyMuPDF4LLM benchmark adapter v2."
        )
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
        default="ocr_auto_rapidtess",
    )

    add_runtime_arguments(
        parser
    )

    args = parser.parse_args()

    try:
        args.artifact_policy = (
            ArtifactPolicy.from_cli(
                args.artifacts
            )
        )

    except ArtifactSelectionError as exc:
        parser.error(
            str(exc)
        )

    return args


class OcrTracker:
    """
    Wrap the official RapidTess OCR plugin while tracking
    which pages actually receive OCR.

    PyMuPDF4LLM may provide additional keyword arguments
    depending on its internal extraction path. Only arguments
    supported by the installed OCR plugin are forwarded.
    """

    def __init__(self) -> None:
        self.requested_pages: set[int] = set()
        self.processed_pages: set[int] = set()
        self.failed_pages: set[int] = set()

        self.extra_kwargs_seen: set[str] = set()

        self.plugin_signature = inspect.signature(
            rapidtess_api.exec_ocr
        )

        self.plugin_parameters = set(
            self.plugin_signature.parameters
        )

        self.plugin_accepts_var_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter
            in self.plugin_signature.parameters.values()
        )

    def __call__(
        self,
        page: pymupdf.Page,
        pixmap=None,
        dpi: int = 300,
        language: str = "eng",
        **kwargs,
    ) -> None:
        page_number = (
            page.number + 1
        )

        self.requested_pages.add(
            page_number
        )

        self.extra_kwargs_seen.update(
            kwargs.keys()
        )

        call_kwargs = {
            "pixmap": pixmap,
            "dpi": dpi,
            "language": language,
            **kwargs,
        }

        if not self.plugin_accepts_var_kwargs:
            call_kwargs = {
                key: value
                for key, value
                in call_kwargs.items()
                if key
                in self.plugin_parameters
            }

        try:
            rapidtess_api.exec_ocr(
                page,
                **call_kwargs,
            )

        except Exception:
            self.failed_pages.add(
                page_number
            )
            raise

        else:
            self.processed_pages.add(
                page_number
            )

        return None


def _tesseract_version() -> str | None:
    try:
        result = subprocess.run(
            [
                "tesseract",
                "--version",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        first_line = (
            result.stdout
            .splitlines()[0]
            .strip()
        )

        return first_line or None

    except Exception:
        return None


def load_or_build_inventory(
    input_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    destination = (
        output_root
        / "_source_inventory"
        / f"{input_path.stem}.json"
    )

    current_sha = (
        calculate_sha256(
            input_path
        )
    )

    if destination.is_file():
        cached = json.loads(
            destination.read_text(
                encoding="utf-8"
            )
        )

        if (
            cached.get("sha256")
            == current_sha
        ):
            return cached

    inventory = analyze_pdf_source(
        input_path
    )

    write_json(
        destination,
        inventory,
    )

    return inventory


def align_chunks(
    chunks: list[dict[str, Any]],
    page_count: int,
) -> tuple[
    list[str],
    list[dict[str, Any]],
    set[int],
]:
    page_texts = [
        ""
        for _ in range(page_count)
    ]

    native_pages = [
        {}
        for _ in range(page_count)
    ]

    observed_pages: set[int] = set()

    for fallback_page, chunk in enumerate(
        chunks,
        start=1,
    ):
        metadata = chunk.get(
            "metadata",
            {},
        )

        page_number = fallback_page

        if isinstance(metadata, dict):
            candidate = metadata.get(
                "page_number"
            )

            try:
                if candidate is not None:
                    page_number = int(
                        candidate
                    )
            except (
                TypeError,
                ValueError,
            ):
                page_number = (
                    fallback_page
                )

        if not (
            1
            <= page_number
            <= page_count
        ):
            continue

        observed_pages.add(
            page_number
        )

        page_texts[
            page_number - 1
        ] = str(
            chunk.get(
                "text",
                "",
            )
        )

        native_pages[
            page_number - 1
        ] = {
            "metadata": (
                metadata
                if isinstance(
                    metadata,
                    dict,
                )
                else {}
            ),

            "toc_items": (
                chunk.get(
                    "toc_items",
                    [],
                )
            ),

            "page_boxes": (
                chunk.get(
                    "page_boxes",
                    [],
                )
            ),
        }

    return (
        page_texts,
        native_pages,
        observed_pages,
    )


def summarize_page_boxes(
    native_pages: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:
    total_classes: Counter[str] = (
        Counter()
    )

    per_page = []

    for page_number, native in enumerate(
        native_pages,
        start=1,
    ):
        classes: Counter[str] = (
            Counter()
        )

        boxes = native.get(
            "page_boxes",
            [],
        )

        if not isinstance(boxes, list):
            boxes = []

        for box in boxes:
            if not isinstance(
                box,
                dict,
            ):
                continue

            box_class = str(
                box.get(
                    "class",
                    "<missing>",
                )
            )

            classes[
                box_class
            ] += 1

            total_classes[
                box_class
            ] += 1

        per_page.append(
            {
                "page_number": (
                    page_number
                ),

                "layout_boxes": sum(
                    classes.values()
                ),

                "tables_detected": (
                    classes["table"]
                ),

                "images_detected": (
                    classes["picture"]
                ),

                "headings_detected": (
                    classes["title"]
                    + classes[
                        "section-header"
                    ]
                ),

                "lists_detected": (
                    classes["list-item"]
                ),

                "formulas_detected": (
                    classes["formula"]
                ),

                "captions_detected": (
                    classes["caption"]
                ),

                "page_headers_detected": (
                    classes["page-header"]
                ),

                "page_footers_detected": (
                    classes["page-footer"]
                ),

                "footnotes_detected": (
                    classes["footnote"]
                ),

                "text_blocks_detected": (
                    classes["text"]
                ),

                "box_class_counts": dict(
                    sorted(
                        classes.items()
                    )
                ),
            }
        )

    summary = {
        "layout_boxes": sum(
            total_classes.values()
        ),

        "tables_detected": (
            total_classes["table"]
        ),

        "images_detected": (
            total_classes["picture"]
        ),

        "headings_detected": (
            total_classes["title"]
            + total_classes[
                "section-header"
            ]
        ),

        "lists_detected": (
            total_classes["list-item"]
        ),

        "formulas_detected": (
            total_classes["formula"]
        ),

        "captions_detected": (
            total_classes["caption"]
        ),

        "page_headers_detected": (
            total_classes[
                "page-header"
            ]
        ),

        "page_footers_detected": (
            total_classes[
                "page-footer"
            ]
        ),

        "footnotes_detected": (
            total_classes["footnote"]
        ),

        "text_blocks_detected": (
            total_classes["text"]
        ),

        "charts_detected": None,

        "box_class_counts": dict(
            sorted(
                total_classes.items()
            )
        ),
    }

    return {
        "summary": summary,
        "per_page": per_page,
    }


def count_log_lines(
    path: Path,
    word: str,
) -> int:
    if not path.is_file():
        return 0

    word = word.casefold()

    return sum(
        word in line.casefold()
        for line in path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    )


_PYMUPDF_PROFILE_KEYS: frozenset[str] = frozenset(
    {
        "layout_module",
        "ocr_enabled",
        "ocr_mode",
        "ocr_engine",
        "ocr_language",
        "ocr_dpi",
        "parser_header",
        "parser_footer",
        "force_text",
        "write_images",
        "embed_images",
        "page_separators",
    }
)

_TO_MARKDOWN_ARGS: frozenset[str] = frozenset(
    {
        "page_chunks",
        "use_ocr",
        "force_ocr",
        "ocr_function",
        "ocr_language",
        "ocr_dpi",
        "header",
        "footer",
        "force_text",
        "write_images",
        "embed_images",
        "page_separators",
        "show_progress",
    }
)


def preflight_profile(
    profile_name: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def _pkg(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
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
    # Profile keys
    # --------------------------------------------------

    missing_keys = sorted(_PYMUPDF_PROFILE_KEYS - set(profile))
    unknown_keys = sorted(set(profile) - _PYMUPDF_PROFILE_KEYS)
    key_errors: list[str] = []
    if missing_keys:
        key_errors.append("missing: " + ", ".join(missing_keys))
    if unknown_keys:
        key_errors.append("unknown: " + ", ".join(unknown_keys))

    if key_errors:
        checks.append(
            make_check("profile keys", "fail", "; ".join(key_errors))
        )
    else:
        checks.append(make_check("profile keys", "pass"))

    # --------------------------------------------------
    # OCR coherence
    # --------------------------------------------------

    ocr_enabled = bool(profile.get("ocr_enabled"))
    ocr_mode = str(profile.get("ocr_mode", ""))
    valid_ocr_modes = {"disabled", "auto", "forced"}

    if ocr_mode not in valid_ocr_modes:
        checks.append(
            make_check(
                "ocr_mode",
                "fail",
                f"must be one of {sorted(valid_ocr_modes)}, got {ocr_mode!r}",
            )
        )
    else:
        checks.append(make_check("ocr_mode", "pass", ocr_mode))

    if not ocr_enabled and ocr_mode != "disabled":
        checks.append(
            make_check(
                "ocr coherence",
                "fail",
                f"ocr_enabled=False but ocr_mode={ocr_mode!r} (expected 'disabled')",
            )
        )
    elif ocr_enabled:
        ocr_engine = str(profile.get("ocr_engine", ""))
        ocr_language = str(profile.get("ocr_language", ""))
        ocr_dpi = profile.get("ocr_dpi", 0)
        coherence_errors: list[str] = []
        if not ocr_engine:
            coherence_errors.append("ocr_engine is empty")
        if not ocr_language:
            coherence_errors.append("ocr_language is empty")
        if not isinstance(ocr_dpi, int) or ocr_dpi <= 0:
            coherence_errors.append(
                f"ocr_dpi must be int > 0, got {ocr_dpi!r}"
            )
        if coherence_errors:
            checks.append(
                make_check(
                    "ocr coherence",
                    "fail",
                    "; ".join(coherence_errors),
                )
            )
        else:
            checks.append(
                make_check(
                    "ocr coherence",
                    "pass",
                    f"engine={ocr_engine} language={ocr_language} dpi={ocr_dpi}",
                )
            )

    # --------------------------------------------------
    # Required packages
    # --------------------------------------------------

    for pkg in ("pymupdf", "pymupdf4llm", "pymupdf-layout"):
        ver = _pkg(pkg)
        checks.append(
            make_check(
                pkg,
                "pass" if ver is not None else "fail",
                ver or "not installed",
            )
        )

    if ocr_enabled:
        for pkg in ("rapidocr", "onnxruntime"):
            ver = _pkg(pkg)
            checks.append(
                make_check(
                    pkg,
                    "pass" if ver is not None else "fail",
                    ver or "not installed",
                )
            )

        try:
            is_callable = callable(rapidtess_api.exec_ocr)
            checks.append(
                make_check(
                    "rapidtess_api.exec_ocr",
                    "pass" if is_callable else "fail",
                )
            )
        except Exception as exc:
            checks.append(
                make_check(
                    "rapidtess_api.exec_ocr",
                    "fail",
                    f"{type(exc).__name__}: {exc}",
                )
            )

    # --------------------------------------------------
    # pymupdf4llm.to_markdown API
    # --------------------------------------------------

    try:
        signature = inspect.signature(pymupdf4llm.to_markdown)
        parameters = signature.parameters

        has_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if has_var_kwargs:
            api_status = "pass"
            api_detail = (
                "to_markdown exposes **kwargs; "
                "keyword arguments are accepted "
                "through the public wrapper"
            )
        else:
            missing_args = sorted(
                _TO_MARKDOWN_ARGS - set(parameters)
            )
            if missing_args:
                api_status = "fail"
                api_detail = (
                    "missing args: " + ", ".join(missing_args)
                )
            else:
                api_status = "pass"
                api_detail = (
                    f"{len(_TO_MARKDOWN_ARGS)} argument(s) validated"
                )

        checks.append(
            make_check(
                "pymupdf4llm.to_markdown API",
                api_status,
                api_detail,
            )
        )

    except Exception as exc:
        checks.append(
            make_check(
                "pymupdf4llm.to_markdown API",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )

    # --------------------------------------------------
    # Tesseract binary (required when ocr_engine=rapidtess)
    # --------------------------------------------------

    tess_path = shutil.which("tesseract")
    rapidtess_engine = (
        ocr_enabled
        and str(profile.get("ocr_engine", "")) == "rapidtess"
    )
    checks.append(
        make_check(
            "tesseract binary",
            "pass" if tess_path else ("fail" if rapidtess_engine else "warn"),
            tess_path or "not found in PATH",
        )
    )

    if rapidtess_engine and tess_path:
        ocr_language_val = str(profile.get("ocr_language", ""))
        if ocr_language_val:
            tessdata_prefix = _find_tessdata_prefix()
            if tessdata_prefix:
                lang_ok = (
                    Path(tessdata_prefix)
                    / f"{ocr_language_val}.traineddata"
                ).exists()
            else:
                lang_ok = False
            checks.append(
                make_check(
                    f"tessdata:{ocr_language_val}",
                    "pass" if lang_ok else "fail",
                    f"{ocr_language_val}.traineddata",
                )
            )

    return make_result(PARSER_NAME, profile_name, checks)


def main() -> None:
    args = parse_args()

    artifact_policy: ArtifactPolicy = (
        args.artifact_policy
    )

    input_path = (
        args.input.resolve()
    )

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
    )

    paths.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    inventory = (
        load_or_build_inventory(
            input_path,
            args.output_root,
        )
    )

    page_count = int(
        inventory["pages"]
    )

    parser_version = (
        importlib.metadata.version(
            "pymupdf4llm"
        )
    )

    pymupdf_version = (
        importlib.metadata.version(
            "pymupdf"
        )
    )

    layout_version = (
        importlib.metadata.version(
            "pymupdf-layout"
        )
    )

    if profile["ocr_enabled"]:
        rapidocr_version = (
            importlib.metadata.version(
                "rapidocr"
            )
        )
        onnx_version = (
            importlib.metadata.version(
                "onnxruntime"
            )
        )
    else:
        rapidocr_version = None
        onnx_version = None

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print("Parser:       PyMuPDF4LLM")
    print(f"Version:      {parser_version}")
    print(f"Input:        {input_path}")
    print(f"Profile:      {args.profile}")
    print(
        "Layout:       "
        f"{profile['layout_module']}"
    )
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
        f"{profile['ocr_engine']}"
    )
    print(
        "OCR language: "
        f"{profile['ocr_language']}"
    )
    print(
        "OCR DPI:      "
        f"{profile['ocr_dpi']}"
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

    print(
        f"Verbose:      {args.verbose}"
    )

    print("=" * 72)

    ocr_tracker = OcrTracker()

    monitor = ResourceMonitor()

    pipeline_started = perf_counter()

    monitor.start()

    initialization_started = (
        perf_counter()
    )

    pymupdf4llm.use_layout(
        bool(
            profile[
                "layout_module"
            ]
        )
    )

    document = pymupdf.open(
        input_path
    )

    initialization_seconds = (
        perf_counter()
        - initialization_started
    )

    extraction_started = (
        perf_counter()
    )

    captured_warning_messages = []

    try:
        with parser_output_context(
            run_log_path=(
                paths.run_log
            ),
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

                chunks = (
                    pymupdf4llm.to_markdown(
                        document,

                        page_chunks=True,

                        use_ocr=bool(
                            profile[
                                "ocr_enabled"
                            ]
                        ),

                        force_ocr=(
                            profile[
                                "ocr_mode"
                            ]
                            == "forced"
                        ),

                        ocr_function=(
                            ocr_tracker
                            if profile[
                                "ocr_enabled"
                            ]
                            else None
                        ),

                        ocr_language=(
                            profile.get(
                                "ocr_language"
                            )
                            or "eng"
                        ),

                        ocr_dpi=int(
                            profile.get(
                                "ocr_dpi"
                            )
                            or 300
                        ),

                        header=bool(
                            profile[
                                "parser_header"
                            ]
                        ),

                        footer=bool(
                            profile[
                                "parser_footer"
                            ]
                        ),

                        force_text=bool(
                            profile[
                                "force_text"
                            ]
                        ),

                        write_images=bool(
                            profile[
                                "write_images"
                            ]
                        ),

                        embed_images=bool(
                            profile[
                                "embed_images"
                            ]
                        ),

                        page_separators=bool(
                            profile[
                                "page_separators"
                            ]
                        ),

                        show_progress=args.verbose,
                    )
                )

                captured_warning_messages = [
                    str(
                        record.message
                    )
                    for record
                    in warning_records
                ]

    finally:
        document.close()

    extraction_seconds = (
        perf_counter()
        - extraction_started
    )

    if not isinstance(chunks, list):
        raise RuntimeError(
            "Expected list from page_chunks=True"
        )

    (
        page_texts,
        native_pages,
        observed_pages,
    ) = align_chunks(
        chunks,
        page_count,
    )

    parser_elements = (
        summarize_page_boxes(
            native_pages
        )
    )

    artifact_result = (
        finalize_artifacts(
            paths=paths,
            document_id=(
                input_path.stem
            ),
            source_file=(
                input_path.name
            ),
            parser_name=PARSER_NAME,
            profile_name=(
                args.profile
            ),
            page_texts=page_texts,
            parser_page_elements=(
                parser_elements[
                    "per_page"
                ]
            ),
            parser_native_pages=(
                native_pages
            ),
            tokenizer_name=(
                tokenizer_name
            ),
            normalization_config=(
                normalization_config
            ),
            artifact_policy=(
                artifact_policy
            ),
        )
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
        if clean_bytes > 0
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
                "PyMuPDF4LLM"
            ),

            "profile": (
                args.profile
            ),

            "verbose": (
                args.verbose
            ),

            "artifact_selection": (
                artifact_policy
                .as_list()
            ),

            "resolved_config": (
                profile
            ),

            "versions": {
                "pymupdf4llm": (
                    parser_version
                ),

                "pymupdf": (
                    pymupdf_version
                ),

                "pymupdf_layout": (
                    layout_version
                ),

                "rapidocr": (
                    rapidocr_version
                ),

                "onnxruntime": (
                    onnx_version
                ),

                "tesseract": (
                    _tesseract_version()
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

            **artifact_result[
                "timing"
            ],

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
                    profile[
                        "ocr_engine"
                    ]
                ),

                "language": (
                    profile[
                        "ocr_language"
                    ]
                ),

                "dpi": (
                    profile[
                        "ocr_dpi"
                    ]
                ),

                "pages_requested": len(
                    ocr_tracker
                    .requested_pages
                ),

                "pages_processed": len(
                    ocr_tracker
                    .processed_pages
                ),

                "fallback_ocr_pages": None,

                "failed_ocr_pages": len(
                    ocr_tracker
                    .failed_pages
                ),

                "requested_page_numbers": sorted(
                    ocr_tracker
                    .requested_pages
                ),

                "failed_page_numbers": sorted(
                    ocr_tracker
                    .failed_pages
                ),

                "plugin_signature": str(
                    ocr_tracker
                    .plugin_signature
                ),

                "callback_extra_kwargs_observed": sorted(
                    ocr_tracker
                    .extra_kwargs_seen
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

        "resources": (
            resources
        ),

        "content_elements": {
            "source_pdf_objective": (
                source_objective
            ),

            "parser_output": (
                parser_elements[
                    "summary"
                ]
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

        "output": {
            **artifact_result[
                "output"
            ],

            "run_log": (
                str(
                    paths.run_log
                )
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
    }

    # Correctness invariant for the OCR tracker.
    if not (
        ocr_tracker.failed_pages
        <= ocr_tracker.requested_pages
    ):
        raise RuntimeError(
            "Invalid OCR tracker state."
        )

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
        f"Pages:                 "
        f"{pages_processed}/{page_count}"
    )

    print(
        f"Extraction:            "
        f"{extraction_seconds:.3f} s"
    )

    print(
        f"Pipeline:              "
        f"{pipeline_seconds:.3f} s"
    )

    print(
        f"OCR pages:             "
        f"{len(ocr_tracker.processed_pages)}"
    )

    print(
        f"OCR page numbers:      "
        f"{sorted(ocr_tracker.processed_pages)}"
    )

    print(
        f"Tables detected:       "
        f"{parser_elements['summary']['tables_detected']}"
    )

    print(
        f"Pictures detected:     "
        f"{parser_elements['summary']['images_detected']}"
    )

    print(
        f"Headings detected:     "
        f"{parser_elements['summary']['headings_detected']}"
    )

    print(
        f"Lists detected:        "
        f"{parser_elements['summary']['lists_detected']}"
    )

    print(
        f"Raw tokens:            "
        f"{reference_tokens['raw_markdown_tokens']}"
    )

    print(
        f"Clean tokens:          "
        f"{reference_tokens['clean_markdown_tokens']}"
    )

    print(
        f"Token reduction:       "
        f"{reference_tokens['token_reduction_percent']:.3f}%"
    )

    print(
        f"Removed records:       "
        f"{artifact_result['normalization']['removed_records']}"
    )

    print(
        f"Average CPU:           "
        f"{resources['average_cpu_system_capacity_percent']}%"
    )

    print(
        f"Peak CPU:              "
        f"{resources['peak_cpu_system_capacity_percent']}%"
    )

    print(
        f"CPU time:              "
        f"{resources['process_cpu_time_seconds']} s"
    )

    print(
        f"Average RAM:           "
        f"{resources['average_rss_mb']} MB"
    )

    print(
        f"Peak RAM:              "
        f"{resources['peak_rss_mb']} MB"
    )

    if artifact_policy.includes(
        "metrics.json"
    ):
        print(
            f"Metrics:               "
            f"{paths.metrics_json}"
        )

    else:
        print(
            "Metrics:               "
            "<not requested>"
        )

    print(
        "Artifacts written:      "
        + ", ".join(
            artifact_policy.as_list()
        )
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
