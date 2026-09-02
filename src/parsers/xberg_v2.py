from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from src.benchmark.artifact_policy import ArtifactPolicy, ArtifactSelectionError
from src.benchmark.config import (
    BenchmarkConfigurationError,
    get_normalization_config,
    get_profile,
    get_reference_tokenizer,
)
from src.benchmark.preflight import make_check, make_result
from src.benchmark.runtime_io import add_runtime_arguments

PARSER_NAME = "xberg"
PARSER_DISPLAY_NAME = "Xberg"
XBERG_REQUIRED_VERSION = "1.0.14"

# Keys that may appear in benchmark_profiles.json for the xberg parser.
# These are the canonical config keys; _build_xberg_config() translates them
# to the Xberg 1.0.14 object API.
_PROFILE_KEYS = frozenset({
    # Output format
    "output_format", "result_format", "escape_markdown", "table_anchors",
    "include_document_structure",
    # Cache / quality
    "use_cache", "enable_quality_processing",
    # OCR
    "ocr_enabled", "ocr_backend", "ocr_languages", "ocr_strategy",
    "force_ocr", "auto_rotate",
    # Tesseract tuning
    "tesseract_psm", "tesseract_oem", "min_confidence",
    "enable_table_detection", "tesseract_use_cache",
    # Rendering / DPI
    "target_dpi",
    # Image preprocessing
    "deskew", "denoise", "contrast_enhance",
    # PDF extraction features
    "extract_pages", "insert_page_markers",
    "extract_tables", "extract_images", "extract_metadata",
    "extract_annotations", "extract_form_fields",
    "reading_order", "ocr_inline_images",
    # Image extraction tuning
    "run_ocr_on_images", "append_ocr_text", "include_data_base64",
    # Content filter
    "include_headers", "include_footers",
    "strip_repeating_text", "include_watermarks",
    # Layout
    "layout_enabled",
    # Downstream (disabled in primary profiles)
    "chunking_enabled", "token_reduction_mode",
    # Isolation
    "remote_services_enabled", "network_allowed_during_run",
})


class XbergConfigurationError(ValueError):
    """The configured benchmark profile is incompatible with the pinned Xberg API."""


# ---------------------------------------------------------------------------
# Xberg API helpers
# ---------------------------------------------------------------------------

def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _get_tesseract_version() -> str | None:
    try:
        r = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        lines = (r.stdout or r.stderr).splitlines()
        return lines[0].strip() if lines else None
    except Exception:
        return None


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
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix and Path(prefix).is_dir():
        return prefix
    for c in _TESSDATA_CANDIDATES:
        if Path(c).is_dir():
            return c
    return None


def _build_xberg_config(
    profile: dict[str, Any],
    model_root: Path,
) -> dict[str, Any]:
    """Translate a benchmark profile dict into the Xberg 1.0.14 ExtractionConfig dict.

    ExtractionConfig is a TypedDict in the Python package, so the adapter returns
    an explicit dictionary. Every nested object uses a public Xberg dataclass.
    Any TypeError raised by Xberg constructors surfaces as XbergConfigurationError.
    """
    import xberg

    ocr_enabled = bool(profile.get("ocr_enabled", False))
    languages = [str(lang) for lang in profile.get("ocr_languages", ["por", "eng"])]
    target_dpi = int(profile.get("target_dpi", 300))

    # --- OcrConfig -----------------------------------------------------------
    ocr_config = None
    if ocr_enabled:
        if not languages:
            raise XbergConfigurationError(
                "OCR is enabled but ocr_languages is empty"
            )

        strategy = str(profile.get("ocr_strategy", "auto"))
        if strategy not in {"auto", "scanned_pages"}:
            raise XbergConfigurationError(
                "Xberg 1.0.14 ocr_strategy must be 'auto' or 'scanned_pages' "
                f"when OCR is enabled; got {strategy!r}"
            )

        ImagePreprocessingConfig = getattr(xberg, "ImagePreprocessingConfig", None)
        if ImagePreprocessingConfig is None:
            raise XbergConfigurationError(
                "xberg.ImagePreprocessingConfig not found — Xberg 1.0.14 required."
            )
        try:
            preprocessing = ImagePreprocessingConfig(
                target_dpi=target_dpi,
                auto_rotate=bool(profile.get("auto_rotate", False)),
                deskew=bool(profile.get("deskew", False)),
                denoise=bool(profile.get("denoise", False)),
                contrast_enhance=bool(profile.get("contrast_enhance", False)),
                binarization_method="otsu",
                invert_colors=False,
            )
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 ImagePreprocessingConfig contract mismatch: {exc}"
            ) from exc

        TesseractConfig = getattr(xberg, "TesseractConfig", None)
        if TesseractConfig is None:
            raise XbergConfigurationError(
                "xberg.TesseractConfig not found — Xberg 1.0.14 required."
            )
        try:
            tess_cfg = TesseractConfig(
                language=languages,
                psm=int(profile.get("tesseract_psm", 3)),
                output_format="markdown",
                oem=int(profile.get("tesseract_oem", 3)),
                min_confidence=float(profile.get("min_confidence", 0.0)),
                preprocessing=preprocessing,
                enable_table_detection=bool(profile.get("enable_table_detection", True)),
                use_cache=bool(profile.get("tesseract_use_cache", False)),
            )
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 TesseractConfig contract mismatch: {exc}"
            ) from exc

        tessdata_path = _find_tessdata_prefix()
        if tessdata_path is None:
            raise XbergConfigurationError(
                "Tesseract tessdata directory not found"
            )

        OcrConfig = getattr(xberg, "OcrConfig", None)
        if OcrConfig is None:
            raise XbergConfigurationError(
                "xberg.OcrConfig not found — Xberg 1.0.14 required."
            )
        try:
            ocr_config = OcrConfig(
                enabled=True,
                backend=str(profile.get("ocr_backend", "tesseract")),
                language=languages,
                tesseract_config=tess_cfg,
                output_format="markdown",
                pipeline=None,
                auto_rotate=bool(profile.get("auto_rotate", False)),
                vlm_fallback="disabled",
                vlm_config=None,
                tessdata_path=tessdata_path,
            )
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 OcrConfig contract mismatch: {exc}"
            ) from exc

    # --- PdfConfig -----------------------------------------------------------
    PdfConfig = getattr(xberg, "PdfConfig", None)
    if PdfConfig is None:
        raise XbergConfigurationError(
            "xberg.PdfConfig not found — Xberg 1.0.14 required."
        )
    include_headers = bool(profile.get("include_headers", True))
    include_footers = bool(profile.get("include_footers", True))
    try:
        pdf_config = PdfConfig(
            extract_images=bool(profile.get("extract_images", False)),
            extract_tables=bool(profile.get("extract_tables", True)),
            passwords=None,
            extract_metadata=bool(profile.get("extract_metadata", True)),
            hierarchy=None,
            extract_annotations=bool(profile.get("extract_annotations", False)),
            top_margin_fraction=0.0 if include_headers else None,
            bottom_margin_fraction=0.0 if include_footers else None,
            allow_single_column_tables=False,
            ocr_inline_images=bool(profile.get("ocr_inline_images", False)),
            extract_form_fields=bool(profile.get("extract_form_fields", True)),
            reading_order=bool(profile.get("reading_order", False)),
        )
    except TypeError as exc:
        raise XbergConfigurationError(
            f"Xberg 1.0.14 PdfConfig contract mismatch: {exc}"
        ) from exc

    # --- PageConfig ----------------------------------------------------------
    PageConfig = getattr(xberg, "PageConfig", None)
    if PageConfig is None:
        raise XbergConfigurationError(
            "xberg.PageConfig not found — Xberg 1.0.14 required."
        )
    try:
        page_config = PageConfig(
            extract_pages=bool(profile.get("extract_pages", True)),
            insert_page_markers=bool(profile.get("insert_page_markers", False)),
        )
    except TypeError as exc:
        raise XbergConfigurationError(
            f"Xberg 1.0.14 PageConfig contract mismatch: {exc}"
        ) from exc

    # --- ImageExtractionConfig -----------------------------------------------
    image_config = None
    extract_images = bool(profile.get("extract_images", False))
    if extract_images:
        ImageExtractionConfig = getattr(xberg, "ImageExtractionConfig", None)
        if ImageExtractionConfig is None:
            raise XbergConfigurationError(
                "xberg.ImageExtractionConfig not found — Xberg 1.0.14 required."
            )
        try:
            image_config = ImageExtractionConfig(
                extract_images=True,
                target_dpi=target_dpi,
                inject_placeholders=True,
                auto_adjust_dpi=False,
                include_page_rasters=False,
                run_ocr_on_images=bool(profile.get("run_ocr_on_images", ocr_enabled)),
                ocr_text_only=False,
                append_ocr_text=bool(profile.get("append_ocr_text", False)),
                output_format="native",
                include_data_base64=bool(profile.get("include_data_base64", False)),
            )
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 ImageExtractionConfig contract mismatch: {exc}"
            ) from exc

    # --- ContentFilterConfig -------------------------------------------------
    ContentFilterConfig = getattr(xberg, "ContentFilterConfig", None)
    if ContentFilterConfig is None:
        raise XbergConfigurationError(
            "xberg.ContentFilterConfig not found — Xberg 1.0.14 required."
        )
    try:
        content_filter = ContentFilterConfig(
            include_headers=include_headers,
            include_footers=include_footers,
            strip_repeating_text=bool(profile.get("strip_repeating_text", False)),
            include_watermarks=bool(profile.get("include_watermarks", True)),
        )
    except TypeError as exc:
        raise XbergConfigurationError(
            f"Xberg 1.0.14 ContentFilterConfig contract mismatch: {exc}"
        ) from exc

    # --- Layout guard --------------------------------------------------------
    if bool(profile.get("layout_enabled", False)):
        raise XbergConfigurationError(
            "Xberg layout_enabled=True is not yet offline-certified in this branch. "
            "Prepare and manifest the Xberg layout/table models before enabling this profile."
        )

    # --- Root config dict (ExtractionConfig is a TypedDict in 1.0.14) --------
    root_config: dict[str, Any] = {
        "use_cache": bool(profile.get("use_cache", False)),
        "enable_quality_processing": bool(profile.get("enable_quality_processing", False)),
        "ocr": ocr_config,
        "force_ocr": bool(profile.get("force_ocr", False)),
        "force_ocr_pages": None,
        "disable_ocr": not ocr_enabled,
        "chunking": None,
        "content_filter": content_filter,
        "images": image_config,
        "pdf_options": pdf_config,
        "token_reduction": None,
        "language_detection": None,
        "pages": page_config,
        "keywords": None,
        "output_format": str(profile.get("output_format", "markdown")),
        "result_format": str(profile.get("result_format", "unified")),
        "escape_markdown": bool(profile.get("escape_markdown", True)),
        "table_anchors": bool(profile.get("table_anchors", False)),
        "layout": None,
        "use_layout_for_markdown": False,
        "include_document_structure": bool(profile.get("include_document_structure", False)),
        "max_concurrent_extractions": 1,
        "structured_extraction": None,
        "ner": None,
        "redaction": None,
        "summarization": None,
        "translation": None,
        "captioning": None,
        "qr_codes": False,
    }

    if ocr_enabled:
        root_config["ocr_strategy"] = str(profile.get("ocr_strategy", "auto"))

    return root_config


async def _extract(input_path: Path, cfg: Any) -> Any:
    import xberg

    extract_fn = getattr(xberg, "extract", None)
    if extract_fn is None:
        raise BenchmarkConfigurationError("xberg.extract not found — check Xberg 1.0.14 installation.")

    ExtractInput = getattr(xberg, "ExtractInput", None)
    if ExtractInput is None:
        raise BenchmarkConfigurationError("xberg.ExtractInput not found — check Xberg 1.0.14 installation.")

    try:
        inp = ExtractInput(
            kind="uri",
            uri=str(input_path),
            mime_type="application/pdf",
            filename=input_path.name,
        )
    except TypeError as exc:
        raise XbergConfigurationError(
            f"Xberg 1.0.14 ExtractInput contract mismatch: {exc}"
        ) from exc

    return await extract_fn(inp, cfg)


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _unwrap_extraction_result(envelope: Any) -> tuple[Any, Any]:
    """Validate and unwrap a Xberg ExtractionResult envelope.

    Returns (document, summary). Raises XbergConfigurationError on any
    deviation from the expected single-document contract.
    """
    errors = list(getattr(envelope, "errors", None) or [])
    results = list(getattr(envelope, "results", None) or [])
    summary = getattr(envelope, "summary", None)

    if errors:
        details = "; ".join(str(e) for e in errors)
        raise XbergConfigurationError(
            "Xberg returned extraction errors: " + details
        )

    if summary is None:
        raise XbergConfigurationError(
            "Xberg ExtractionResult.summary is missing"
        )

    if getattr(summary, "inputs", None) != 1:
        raise XbergConfigurationError(
            "Xberg summary.inputs must equal 1"
        )

    if getattr(summary, "errors", None) != 0:
        raise XbergConfigurationError(
            "Xberg summary reports extraction errors"
        )

    if getattr(summary, "results", None) != 1:
        raise XbergConfigurationError(
            "Xberg summary.results must equal 1"
        )

    if len(results) != 1:
        raise XbergConfigurationError(
            f"Xberg must return exactly one ExtractedDocument; got {len(results)}"
        )

    document = results[0]

    if not hasattr(document, "content"):
        raise XbergConfigurationError(
            "Xberg result item is not an ExtractedDocument-compatible object"
        )

    return document, summary


def _get_pages(document: Any) -> list[Any]:
    pages = getattr(document, "pages", None)

    if pages is None:
        return []

    if not isinstance(pages, (list, tuple)):
        raise XbergConfigurationError(
            f"ExtractedDocument.pages must be a sequence; got {type(pages).__name__}"
        )

    return list(pages)


def _page_text(page_obj: Any) -> str:
    """Extract text from a page result object (no trailing newline added here)."""
    for attr in ("content", "text", "markdown", "output"):
        val = getattr(page_obj, attr, None)
        if isinstance(val, str) and val.strip():
            return val.rstrip()
    return ""


def _page_number(page_obj: Any, fallback: int) -> int:
    value = getattr(page_obj, "page_number", None)
    if isinstance(value, int):
        return value
    return fallback


def _page_tables(page_obj: Any) -> list[Any]:
    for attr in ("tables", "table_list", "extracted_tables"):
        val = getattr(page_obj, attr, None)
        if isinstance(val, list):
            return val
    return []


_JSON_PRIMITIVES = (bool, int, float, str, type(None))


def _to_json_safe(v: Any) -> Any:
    """Recursively convert a Xberg result value to a JSON-serializable form.

    Xberg dataclasses may use __slots__ (no __dict__) or C extensions,
    so hasattr(v, '__dict__') is not a reliable proxy for 'is complex object'.
    Any value that is not a primitive, list, or dict is stringified.
    Binary data is dropped (returns None).
    """
    if isinstance(v, _JSON_PRIMITIVES):
        return v
    if isinstance(v, (bytes, bytearray)):
        return None
    if isinstance(v, dict):
        return {str(k): _to_json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        result = [_to_json_safe(item) for item in v]
        return [item for item in result if item is not None]
    return str(v)


def _table_to_native(table_obj: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "table_type": type(table_obj).__name__,
    }
    for attr in ("data", "rows", "cells", "html", "text", "markdown",
                 "row_count", "col_count", "confidence", "bbox"):
        v = getattr(table_obj, attr, None)
        safe = _to_json_safe(v)
        if safe is not None:
            record[attr] = safe
    return record


def _page_native(page_obj: Any) -> dict[str, Any]:
    """Extract additional native fields from a PageContent object for retention."""
    record: dict[str, Any] = {}
    for attr in ("elements", "images", "form_fields", "annotations",
                 "hierarchy", "layout_regions", "formulas", "warnings",
                 "ocr_metadata", "reading_order", "document_structure",
                 "language", "quality"):
        v = getattr(page_obj, attr, None)
        safe = _to_json_safe(v)
        if safe is not None:
            record[attr] = safe
    return record


def _result_to_page_texts(document: Any, expected_pages: int) -> dict[int, str]:
    """Map Xberg per-page results to {page_number: text}.

    Returns an empty dict if the document contains no per-page data.
    """
    pages = _get_pages(document)
    page_map: dict[int, str] = {}
    for i, pg in enumerate(pages):
        pnum = _page_number(pg, fallback=i + 1)
        page_map[pnum] = _page_text(pg)
    return page_map


def _result_to_artifacts(
    document: Any,
    page_count: int,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert an unwrapped Xberg ExtractedDocument to benchmark artifacts.

    Raises XbergConfigurationError if no per-page data, duplicate page numbers,
    or out-of-range page numbers are detected.
    """
    pages = _get_pages(document)

    if not pages:
        raise XbergConfigurationError(
            "Xberg returned no per-page data. "
            "PageConfig.extract_pages=True is required by the benchmark contract."
        )

    page_map: dict[int, Any] = {}
    for index, page in enumerate(pages, start=1):
        page_number = _page_number(page, fallback=index)

        if not 1 <= page_number <= page_count:
            raise XbergConfigurationError(
                f"Xberg page number is outside the source inventory: {page_number}"
            )

        if page_number in page_map:
            raise XbergConfigurationError(
                f"Xberg returned duplicate page number: {page_number}"
            )

        page_map[page_number] = page

    # Collect global table list from the document (may complement per-page tables)
    global_tables_by_page: dict[int, list[Any]] = {}
    for table in (getattr(document, "tables", None) or []):
        table_page = int(getattr(table, "page_number", 0) or 0)
        if 1 <= table_page <= page_count:
            global_tables_by_page.setdefault(table_page, []).append(table)

    page_texts: list[str] = []
    parser_page_elements: list[dict[str, Any]] = []
    parser_native_pages: list[dict[str, Any]] = []

    for page_num in range(1, page_count + 1):
        page = page_map.get(page_num)

        if page is None:
            page_texts.append("")
            parser_page_elements.append({
                "page_number": page_num,
                "tables_detected": 0,
            })
            parser_native_pages.append({
                "page_number": page_num,
                "missing_from_parser_result": True,
                "tables": [],
            })
            continue

        raw_text = _page_text(page)
        page_texts.append((raw_text + "\n") if raw_text else "")

        page_tables = list(_page_tables(page))
        for table in global_tables_by_page.get(page_num, []):
            if all(table is not existing for existing in page_tables):
                page_tables.append(table)

        parser_page_elements.append({
            "page_number": page_num,
            "tables_detected": len(page_tables),
        })
        parser_native_pages.append({
            "page_number": page_num,
            "missing_from_parser_result": False,
            "tables": [_table_to_native(t) for t in page_tables],
            **_page_native(page),
        })

    return page_texts, parser_page_elements, parser_native_pages


def _count_elements_from_result(
    document: Any,
    page_texts: dict[int, str] | list[str],
) -> dict[str, Any]:
    pages = _get_pages(document)
    total_tables = sum(len(_page_tables(pg)) for pg in pages)
    if isinstance(page_texts, dict):
        non_empty_pages = sum(1 for t in page_texts.values() if t.strip())
    else:
        non_empty_pages = sum(1 for t in page_texts if t.strip())
    return {
        "layout_boxes": None,
        "tables_detected": total_tables,
        "images_detected": None,
        "headings_detected": None,
        "lists_detected": None,
        "formulas_detected": None,
        "captions_detected": None,
        "page_headers_detected": None,
        "page_footers_detected": None,
        "footnotes_detected": None,
        "text_blocks_detected": non_empty_pages,
        "code_blocks_detected": None,
        "charts_detected": None,
        "box_class_counts": None,
    }


# ---------------------------------------------------------------------------
# Source inventory
# ---------------------------------------------------------------------------

def _load_cached_inventory(input_path: Path, output_root: Path) -> dict[str, Any]:
    import hashlib
    import json

    destination = output_root / "_source_inventory" / f"{input_path.stem}.json"
    if not destination.is_file():
        raise BenchmarkConfigurationError(
            f"Source Inventory not found: {destination}. "
            "Build the common Source Inventory before running the parser benchmark."
        )
    inventory = json.loads(destination.read_text(encoding="utf-8"))
    current_sha = _sha256_file(input_path)
    if inventory.get("sha256") != current_sha:
        raise BenchmarkConfigurationError(
            "Source Inventory SHA-256 does not match the input PDF. "
            f"Inventory: {destination}. Rebuild the Source Inventory."
        )
    return inventory


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _build_metrics(
    *,
    input_path: Path,
    profile: dict[str, Any],
    profile_name: str,
    inventory: dict[str, Any],
    document: Any,
    extraction_summary: Any,
    artifact_result: dict[str, Any],
    element_counts: dict[str, Any],
    initialization_seconds: float,
    extraction_seconds: float,
    pipeline_seconds: float,
    resources: dict[str, Any],
    tokenizer_name: str,
    artifact_selected_list: list[str],
    run_log_path: Path | None,
    metrics_json_path: Path | None,
    verbose: bool = False,
) -> dict[str, Any]:
    source_summary = {k: v for k, v in inventory.items() if k != "per_page"}
    input_bytes = input_path.stat().st_size
    clean_bytes = artifact_result.get("output", {}).get("clean_markdown_bytes")
    size_ratio = round(input_bytes / clean_bytes, 6) if clean_bytes else None
    ocr_enabled = bool(profile.get("ocr_enabled", False))

    pages_total = int(inventory.get("pages", 0))
    observed_page_numbers = {
        _page_number(page, fallback=index)
        for index, page in enumerate(_get_pages(document), start=1)
    }
    valid_observed = {pn for pn in observed_page_numbers if 1 <= pn <= pages_total}
    pages_processed = len(valid_observed)
    failed_pages = max(pages_total - pages_processed, 0)

    processing_warnings = list(getattr(document, "processing_warnings", None) or [])
    errors_count = int(getattr(extraction_summary, "errors", 0) or 0)

    return {
        "benchmark": {
            "schema_version": 3,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "reference_tokenizer": tokenizer_name,
        },
        "run": {
            "parser": PARSER_NAME,
            "parser_display_name": PARSER_DISPLAY_NAME,
            "profile": profile_name,
            "verbose": verbose,
            "artifact_selection": artifact_selected_list,
            "resolved_config": profile,
            "versions": {
                "xberg": _package_version("xberg"),
                "tiktoken": _package_version("tiktoken"),
                "tesseract": _get_tesseract_version(),
            },
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "document": {
            "id": input_path.stem,
            "file": input_path.name,
            "sha256": inventory.get("sha256"),
            "pages": inventory.get("pages"),
            "input_size_mb": inventory.get("file_size_mb"),
        },
        "source_pdf": source_summary,
        "processing": {
            **artifact_result["timing"],
            "initialization_seconds": round(initialization_seconds, 6),
            "extraction_seconds": round(extraction_seconds, 6),
            "pipeline_seconds": round(pipeline_seconds, 6),
            "pages_total": pages_total,
            "pages_processed": pages_processed,
            "failed_pages": failed_pages,
            "partial_pages": None,
            "empty_output_pages": artifact_result["empty_output_pages"],
            "pipeline_pages_per_second": (
                round(int(inventory.get("pages", 0)) / pipeline_seconds, 6)
                if pipeline_seconds > 0 and inventory.get("pages") else None
            ),
            "ocr": {
                "enabled": ocr_enabled,
                "strategy": str(profile.get("ocr_strategy", "disabled")),
                "engine": profile.get("ocr_backend"),
                "languages": profile.get("ocr_languages"),
                "force_ocr": bool(profile.get("force_ocr", False)),
                "auto_rotate": bool(profile.get("auto_rotate", False)),
                "pages_requested": None,
                "pages_processed": None,
                "tracking_note": (
                    "Xberg 1.0.14 nao expoe rastreamento "
                    "por pagina de OCR na API publica."
                ),
            },
            "warnings_count": len(processing_warnings),
            "warning_messages": [
                {
                    "source": getattr(w, "source", None),
                    "message": getattr(w, "message", str(w)),
                }
                for w in processing_warnings
            ],
            "errors_count": errors_count,
            "retry_count": 0,
        },
        "resources": resources,
        "content_elements": {
            **artifact_result["content_elements"],
            "parser_output": element_counts,
        },
        "heuristics": artifact_result["heuristics"],
        "tokens": artifact_result["tokens"],
        "normalization": artifact_result["normalization"],
        "artifacts": artifact_result["artifacts"],
        "quality_eligibility": artifact_result["quality_eligibility"],
        "output": {
            **artifact_result["output"],
            "run_log": str(run_log_path) if run_log_path else None,
            "metrics_json": str(metrics_json_path) if metrics_json_path else None,
            "input_to_clean_markdown_size_ratio": size_ratio,
        },
    }


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight_profile(
    profile_name: str,
    *,
    model_root_override: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # Profile exists
    try:
        profile = get_profile(PARSER_NAME, profile_name)
    except Exception as exc:
        checks.append(make_check("profile configuration", "fail", f"{type(exc).__name__}: {exc}"))
        return make_result(PARSER_NAME, profile_name, checks)
    checks.append(make_check("profile configuration", "pass", profile_name))

    # Key contract
    unknown = set(profile) - _PROFILE_KEYS
    if unknown:
        checks.append(make_check("profile keys", "fail", f"unknown keys: {sorted(unknown)}"))
    else:
        checks.append(make_check("profile keys", "pass"))

    # No remote services
    if bool(profile.get("remote_services_enabled", False)):
        checks.append(make_check("remote services disabled", "fail", "remote_services_enabled=true"))
    else:
        checks.append(make_check("remote services disabled", "pass"))

    if bool(profile.get("network_allowed_during_run", False)):
        checks.append(make_check("network during run", "fail", "network_allowed_during_run=true"))
    else:
        checks.append(make_check("network during run", "pass"))

    # Xberg version
    installed = _package_version("xberg")
    if installed is None:
        checks.append(make_check("xberg version", "fail", "xberg not installed"))
    elif installed != XBERG_REQUIRED_VERSION:
        checks.append(make_check(
            "xberg version", "fail",
            f"expected {XBERG_REQUIRED_VERSION!r}, got {installed!r}",
        ))
    else:
        checks.append(make_check("xberg version", "pass", installed))

    # Python version
    if sys.version_info[:2] != (3, 12):
        checks.append(make_check(
            "python version", "fail",
            f"expected 3.12, got {platform.python_version()}",
        ))
    else:
        checks.append(make_check("python version", "pass", platform.python_version()))

    # OCR checks
    ocr_enabled = bool(profile.get("ocr_enabled", False))
    if ocr_enabled:
        tess_bin = shutil.which("tesseract")
        checks.append(make_check(
            "tesseract executable",
            "pass" if tess_bin else "fail",
            tess_bin or "not found in PATH",
        ))
        tessdata = _find_tessdata_prefix()
        for lang in profile.get("ocr_languages", ["por", "eng"]):
            if tessdata:
                td_file = Path(tessdata) / f"{lang}.traineddata"
                checks.append(make_check(
                    f"tessdata {lang}",
                    "pass" if td_file.is_file() else "fail",
                    str(td_file),
                ))
            else:
                checks.append(make_check(f"tessdata {lang}", "fail", "tessdata directory not found"))
        if bool(profile.get("auto_rotate", False)):
            if tessdata:
                osd_file = Path(tessdata) / "osd.traineddata"
                checks.append(make_check(
                    "tessdata osd (auto_rotate)",
                    "pass" if osd_file.is_file() else "fail",
                    str(osd_file) if not osd_file.is_file() else "present",
                ))
            else:
                checks.append(make_check("tessdata osd (auto_rotate)", "fail", "tessdata directory not found"))

    # adapter import + API object probes
    try:
        import xberg  # noqa: F401
        checks.append(make_check("adapter import", "pass", "xberg"))

        extract_fn = getattr(xberg, "extract", None)
        if extract_fn is None or not asyncio.iscoroutinefunction(extract_fn):
            checks.append(make_check("xberg.extract async", "fail", "not an async function"))
        else:
            checks.append(make_check("xberg.extract async", "pass"))

        for cls_name in (
            "ExtractionConfig", "ExtractInput",
            "OcrConfig", "TesseractConfig",
            "PdfConfig", "PageConfig",
            "ImageExtractionConfig", "ContentFilterConfig",
        ):
            obj = getattr(xberg, cls_name, None)
            checks.append(make_check(
                cls_name,
                "pass" if obj is not None else "fail",
                "found" if obj is not None else "not found in xberg 1.0.14",
            ))

        # Validate that _build_xberg_config does not raise on this profile
        model_root = model_root_override or Path("models/xberg")
        try:
            _build_xberg_config(profile, model_root)
            checks.append(make_check("config builder", "pass"))
        except XbergConfigurationError as exc:
            checks.append(make_check("config builder", "fail", str(exc)))
        except Exception as exc:
            checks.append(make_check("config builder", "fail", f"{type(exc).__name__}: {exc}"))

    except Exception as exc:
        checks.append(make_check("adapter import", "fail", f"{type(exc).__name__}: {exc}"))

    return make_result(PARSER_NAME, profile_name, checks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xberg benchmark adapter v2.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/outputs"))
    parser.add_argument("--profile", default="native_markdown")
    parser.add_argument(
        "--model-root", type=Path, default=None,
        help="Override for model artifacts directory (models/xberg).",
    )
    add_runtime_arguments(parser)
    args = parser.parse_args()
    try:
        args.artifact_policy = ArtifactPolicy.from_cli(args.artifacts)
    except ArtifactSelectionError as exc:
        parser.error(str(exc))
    return args


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    from src.benchmark.artifact_contract import ParserArtifactInput, join_page_texts
    from src.benchmark.artifacts import finalize_artifacts
    from src.benchmark.metrics_writer import write_json
    from src.benchmark.paths import build_output_paths
    from src.benchmark.resource_monitor import ResourceMonitor
    from src.benchmark.runtime_io import parser_output_context

    args = parse_args()
    artifact_policy: ArtifactPolicy = args.artifact_policy
    input_path = args.input.resolve()

    if not input_path.is_file():
        raise SystemExit(f"Input not found: {input_path}")

    profile = get_profile(PARSER_NAME, args.profile)
    normalization_config = get_normalization_config()
    tokenizer_name = get_reference_tokenizer()

    paths = build_output_paths(
        args.output_root, PARSER_NAME, input_path.stem, args.profile
    )

    inventory = _load_cached_inventory(input_path, args.output_root)
    page_count = int(inventory["pages"])

    model_root = args.model_root if args.model_root is not None else Path("models/xberg")
    ocr_enabled = bool(profile.get("ocr_enabled", False))

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:    {PARSER_DISPLAY_NAME}")
    print(f"Version:   {_package_version('xberg')}")
    print(f"Input:     {input_path}")
    print(f"Profile:   {args.profile}")
    print(f"OCR:       {ocr_enabled}")
    print(f"Tokenizer: {tokenizer_name}")
    print(f"Output:    {paths.output_dir}")
    print("=" * 72)

    import os
    os.environ.setdefault("HF_HOME", str(model_root / "huggingface"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["SCARF_NO_ANALYTICS"] = "1"

    monitor = ResourceMonitor()
    pipeline_started = perf_counter()
    monitor.start()

    try:
        with parser_output_context(
            run_log_path=paths.run_log,
            keep_run_log=artifact_policy.includes("run.log"),
            verbose=args.verbose,
        ):
            init_start = perf_counter()
            import xberg  # noqa: F401 — triggers native module load
            cfg = _build_xberg_config(profile, model_root)
            initialization_seconds = perf_counter() - init_start

            extraction_start = perf_counter()
            envelope = asyncio.run(_extract(input_path, cfg))
            extraction_seconds = perf_counter() - extraction_start

            document, extraction_summary = _unwrap_extraction_result(envelope)

            page_texts, parser_page_elements, parser_native_pages = _result_to_artifacts(
                document, page_count
            )
            element_counts = _count_elements_from_result(document, page_texts)

    except Exception:
        monitor.stop()
        raise

    pipeline_seconds = perf_counter() - pipeline_started

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
        normalization_config=normalization_config,
        artifact_policy=artifact_policy,
    )

    resources = monitor.stop()

    metrics = _build_metrics(
        input_path=input_path,
        profile=profile,
        profile_name=args.profile,
        inventory=inventory,
        document=document,
        extraction_summary=extraction_summary,
        artifact_result=artifact_result,
        element_counts=element_counts,
        initialization_seconds=initialization_seconds,
        extraction_seconds=extraction_seconds,
        pipeline_seconds=pipeline_seconds,
        resources=resources,
        tokenizer_name=tokenizer_name,
        artifact_selected_list=artifact_policy.as_list(),
        verbose=args.verbose,
        run_log_path=paths.run_log if artifact_policy.includes("run.log") else None,
        metrics_json_path=paths.metrics_json if artifact_policy.includes("metrics.json") else None,
    )

    if artifact_policy.includes("metrics.json"):
        write_json(paths.metrics_json, metrics)


if __name__ == "__main__":
    main()
