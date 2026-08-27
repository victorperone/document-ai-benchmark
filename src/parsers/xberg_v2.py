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


def _build_xberg_config(profile: dict[str, Any], model_root: Path) -> Any:
    """Translate a benchmark profile dict into a Xberg 1.0.14 ExtractionConfig.

    Each sub-object is built explicitly against the pinned API. Any TypeError
    raised by Xberg constructors surfaces as XbergConfigurationError — no
    silent fallback to defaults.
    """
    import xberg

    ExtractionConfig = getattr(xberg, "ExtractionConfig", None)
    if ExtractionConfig is None:
        raise BenchmarkConfigurationError(
            "xberg.ExtractionConfig not found — check Xberg 1.0.14 installation."
        )

    ocr_enabled = bool(profile.get("ocr_enabled", False))
    target_dpi = int(profile.get("target_dpi", 300))

    # --- OcrConfig -----------------------------------------------------------
    ocr_config = None
    if ocr_enabled:
        OcrConfig = getattr(xberg, "OcrConfig", None)
        TesseractConfig = getattr(xberg, "TesseractConfig", None)
        if OcrConfig is None:
            raise XbergConfigurationError(
                "xberg.OcrConfig not found — Xberg 1.0.14 required."
            )

        tess_cfg = None
        if TesseractConfig is not None:
            tess_kwargs: dict[str, Any] = {}
            languages = list(profile.get("ocr_languages", ["por", "eng"]))
            if languages:
                tess_kwargs["language"] = languages
            psm = profile.get("tesseract_psm")
            if psm is not None:
                tess_kwargs["psm"] = int(psm)
            oem = profile.get("tesseract_oem")
            if oem is not None:
                tess_kwargs["oem"] = int(oem)
            min_conf = profile.get("min_confidence")
            if min_conf is not None:
                tess_kwargs["min_confidence"] = float(min_conf)
            tess_kwargs["use_cache"] = bool(profile.get("tesseract_use_cache", False))
            try:
                tess_cfg = TesseractConfig(**tess_kwargs)
            except TypeError as exc:
                raise XbergConfigurationError(
                    f"Xberg 1.0.14 TesseractConfig contract mismatch: {exc}"
                ) from exc

        ocr_kwargs: dict[str, Any] = {
            "enabled": True,
            "backend": str(profile.get("ocr_backend", "tesseract")),
            "auto_rotate": bool(profile.get("auto_rotate", False)),
            "vlm_fallback": "disabled",
            "vlm_config": None,
        }
        if tess_cfg is not None:
            ocr_kwargs["tesseract_config"] = tess_cfg
        ocr_strategy = str(profile.get("ocr_strategy", "auto"))
        if ocr_strategy not in ("disabled",):
            ocr_kwargs["pipeline"] = ocr_strategy
        try:
            ocr_config = OcrConfig(**ocr_kwargs)
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 OcrConfig contract mismatch: {exc}"
            ) from exc

    # --- PdfConfig -----------------------------------------------------------
    PdfConfig = getattr(xberg, "PdfConfig", None)
    pdf_config = None
    if PdfConfig is not None:
        pdf_kwargs: dict[str, Any] = {
            "extract_tables": bool(profile.get("extract_tables", True)),
            "extract_metadata": bool(profile.get("extract_metadata", True)),
            "extract_annotations": bool(profile.get("extract_annotations", False)),
            "extract_form_fields": bool(profile.get("extract_form_fields", True)),
            "reading_order": bool(profile.get("reading_order", False)),
            "ocr_inline_images": bool(profile.get("ocr_inline_images", False)),
        }
        try:
            pdf_config = PdfConfig(**pdf_kwargs)
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 PdfConfig contract mismatch: {exc}"
            ) from exc

    # --- PageConfig ----------------------------------------------------------
    PageConfig = getattr(xberg, "PageConfig", None)
    page_config = None
    if PageConfig is not None:
        page_kwargs: dict[str, Any] = {
            "extract_pages": bool(profile.get("extract_pages", True)),
            "insert_page_markers": bool(profile.get("insert_page_markers", False)),
        }
        try:
            page_config = PageConfig(**page_kwargs)
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 PageConfig contract mismatch: {exc}"
            ) from exc

    # --- ImageExtractionConfig -----------------------------------------------
    ImageExtractionConfig = getattr(xberg, "ImageExtractionConfig", None)
    image_config = None
    extract_images = bool(profile.get("extract_images", False))
    if ImageExtractionConfig is not None and extract_images:
        img_kwargs: dict[str, Any] = {
            "extract_images": True,
            "target_dpi": target_dpi,
            "run_ocr_on_images": bool(profile.get("run_ocr_on_images", ocr_enabled)),
            "append_ocr_text": bool(profile.get("append_ocr_text", ocr_enabled)),
            "include_data_base64": bool(profile.get("include_data_base64", False)),
            "include_page_rasters": False,
        }
        try:
            image_config = ImageExtractionConfig(**img_kwargs)
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 ImageExtractionConfig contract mismatch: {exc}"
            ) from exc

    # --- ContentFilterConfig -------------------------------------------------
    ContentFilterConfig = getattr(xberg, "ContentFilterConfig", None)
    content_filter = None
    if ContentFilterConfig is not None:
        cf_kwargs: dict[str, Any] = {
            "include_headers": bool(profile.get("include_headers", True)),
            "include_footers": bool(profile.get("include_footers", True)),
            "strip_repeating_text": bool(profile.get("strip_repeating_text", False)),
            "include_watermarks": bool(profile.get("include_watermarks", True)),
        }
        try:
            content_filter = ContentFilterConfig(**cf_kwargs)
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 ContentFilterConfig contract mismatch: {exc}"
            ) from exc

    # --- LayoutDetectionConfig -----------------------------------------------
    LayoutDetectionConfig = getattr(xberg, "LayoutDetectionConfig", None)
    layout_config = None
    layout_enabled = bool(profile.get("layout_enabled", False))
    if LayoutDetectionConfig is not None and layout_enabled:
        try:
            layout_config = LayoutDetectionConfig()
        except TypeError as exc:
            raise XbergConfigurationError(
                f"Xberg 1.0.14 LayoutDetectionConfig contract mismatch: {exc}"
            ) from exc

    # --- ExtractionConfig (root) ---------------------------------------------
    root_kwargs: dict[str, Any] = {
        "use_cache": bool(profile.get("use_cache", False)),
        "enable_quality_processing": bool(profile.get("enable_quality_processing", False)),
        "output_format": str(profile.get("output_format", "markdown")),
        "result_format": str(profile.get("result_format", "unified")),
        "include_document_structure": bool(profile.get("include_document_structure", False)),
    }
    if ocr_enabled:
        root_kwargs["ocr"] = ocr_config
        if bool(profile.get("force_ocr", False)):
            root_kwargs["force_ocr"] = True
    else:
        root_kwargs["disable_ocr"] = True
    if pdf_config is not None:
        root_kwargs["pdf_options"] = pdf_config
    if page_config is not None:
        root_kwargs["pages"] = page_config
    if image_config is not None:
        root_kwargs["images"] = image_config
    if content_filter is not None:
        root_kwargs["content_filter"] = content_filter
    if layout_config is not None:
        root_kwargs["layout"] = layout_config

    # Downstream features — always off in primary profiles
    root_kwargs["chunking"] = None
    root_kwargs["token_reduction"] = None

    try:
        return ExtractionConfig(**root_kwargs)
    except TypeError as exc:
        raise XbergConfigurationError(
            f"Xberg 1.0.14 ExtractionConfig contract mismatch: {exc}"
        ) from exc


async def _extract(input_path: Path, cfg: Any) -> Any:
    import xberg

    extract_fn = getattr(xberg, "extract", None)
    if extract_fn is None:
        raise BenchmarkConfigurationError("xberg.extract not found — check Xberg 1.0.14 installation.")

    ExtractInput = getattr(xberg, "ExtractInput", None)
    if ExtractInput is None:
        raise BenchmarkConfigurationError("xberg.ExtractInput not found — check Xberg 1.0.14 installation.")

    try:
        inp = ExtractInput(source=str(input_path))
    except TypeError as exc:
        raise XbergConfigurationError(
            f"Xberg 1.0.14 ExtractInput contract mismatch: {exc}"
        ) from exc

    return await extract_fn(inp, cfg)


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _get_pages(result: Any) -> list[Any]:
    """Extract per-page result objects from the Xberg 1.0.14 result.

    Primary shape: result.pages (list of PageContent objects).
    Fallback shape: result.documents[0].pages.
    Any other shape returns [] — caller must treat that as FAIL.
    """
    # Primary: result.pages
    pages = getattr(result, "pages", None)
    if isinstance(pages, list) and pages:
        return pages
    # Secondary: result.documents[0].pages
    docs = getattr(result, "documents", None)
    if isinstance(docs, list) and docs:
        doc = docs[0]
        pages = getattr(doc, "pages", None)
        if isinstance(pages, list) and pages:
            return pages
    return []


def _page_text(page_obj: Any) -> str:
    """Extract text from a page result object (no trailing newline added here)."""
    for attr in ("content", "text", "markdown", "output"):
        val = getattr(page_obj, attr, None)
        if isinstance(val, str) and val.strip():
            return val.rstrip()
    return ""


def _page_number(page_obj: Any, fallback: int = 0) -> int:
    for attr in ("page_number", "page", "number", "index"):
        v = getattr(page_obj, attr, None)
        if isinstance(v, int):
            return v
    return fallback


def _page_tables(page_obj: Any) -> list[Any]:
    for attr in ("tables", "table_list", "extracted_tables"):
        val = getattr(page_obj, attr, None)
        if isinstance(val, list):
            return val
    return []


def _table_to_native(table_obj: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "table_type": type(table_obj).__name__,
    }
    for attr in ("data", "rows", "cells", "html", "text", "markdown",
                 "row_count", "col_count", "confidence", "bbox"):
        v = getattr(table_obj, attr, None)
        if v is not None and not isinstance(v, (bytes, bytearray)):
            record[attr] = v if not hasattr(v, "__dict__") else str(v)
    return record


def _page_native(page_obj: Any) -> dict[str, Any]:
    """Extract additional native fields from a PageContent object for retention."""
    record: dict[str, Any] = {}
    for attr in ("elements", "images", "form_fields", "annotations",
                 "hierarchy", "layout_regions", "formulas", "warnings",
                 "ocr_metadata", "reading_order", "document_structure",
                 "language", "quality"):
        v = getattr(page_obj, attr, None)
        if v is None:
            continue
        if isinstance(v, (bytes, bytearray)):
            continue
        if isinstance(v, list):
            record[attr] = [
                (str(item) if isinstance(item, (bytes, bytearray)) else item)
                for item in v
            ]
        else:
            record[attr] = v if not hasattr(v, "__dict__") else str(v)
    return record


def _result_to_page_texts(result: Any, expected_pages: int) -> dict[int, str]:
    """Map Xberg per-page results to {page_number: text}.

    Returns an empty dict if the result contains no per-page data.
    The caller is responsible for treating an empty return as a pipeline FAIL.
    """
    pages = _get_pages(result)
    page_map: dict[int, str] = {}
    for i, pg in enumerate(pages):
        pnum = _page_number(pg, fallback=i + 1)
        page_map[pnum] = _page_text(pg)
    return page_map


def _result_to_artifacts(
    result: Any,
    page_count: int,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert Xberg result to (page_texts, parser_page_elements, parser_native_pages).

    Raises XbergConfigurationError if the result contains no per-page data —
    a flat document cannot be distributed across pages (benchmark page contract).
    """
    pages = _get_pages(result)

    if not pages:
        raise XbergConfigurationError(
            "Xberg returned no per-page data. "
            "Ensure PageConfig.extract_pages=True and the result shape is correct. "
            "A flat document cannot be mapped to pages — this is a FAIL."
        )

    page_map: dict[int, Any] = {}
    for i, pg in enumerate(pages):
        pnum = _page_number(pg, fallback=i + 1)
        page_map[pnum] = pg

    page_texts: list[str] = []
    parser_page_elements: list[dict[str, Any]] = []
    parser_native_pages: list[dict[str, Any]] = []

    for page_num in range(1, page_count + 1):
        pg = page_map.get(page_num)
        if pg is not None:
            raw = _page_text(pg)
            text = (raw + "\n") if raw else ""
            tables = _page_tables(pg)
            native_data = _page_native(pg)
        else:
            text = ""
            tables = []
            native_data = {}

        page_texts.append(text)
        parser_page_elements.append({
            "page_number": page_num,
            "tables_detected": len(tables),
        })
        native_tables = [_table_to_native(t) for t in tables]
        parser_native_pages.append({
            "page_number": page_num,
            "tables": native_tables,
            **native_data,
        })

    return page_texts, parser_page_elements, parser_native_pages


def _count_elements_from_result(
    result: Any,
    page_texts: dict[int, str] | list[str],
) -> dict[str, Any]:
    pages = _get_pages(result)
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

    return {
        "benchmark": {
            "schema_version": 2,
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
            "pages_total": inventory.get("pages"),
            "pages_processed": inventory.get("pages"),
            "failed_pages": 0,
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
            "warnings_count": 0,
            "errors_count": 0,
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
            result = asyncio.run(_extract(input_path, cfg))
            extraction_seconds = perf_counter() - extraction_start

            page_texts, parser_page_elements, parser_native_pages = _result_to_artifacts(
                result, page_count
            )
            element_counts = _count_elements_from_result(result, page_texts)

    except Exception:
        monitor.stop()
        raise

    pipeline_seconds = perf_counter() - pipeline_started

    artifact_result = finalize_artifacts(
        paths=paths,
        document_id=input_path.stem,
        source_file=input_path.name,
        parser_name=PARSER_NAME,
        profile_name=args.profile,
        page_texts=page_texts,
        parser_page_elements=parser_page_elements,
        parser_native_pages=parser_native_pages,
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
