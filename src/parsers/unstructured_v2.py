from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
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
from src.benchmark.content_validation import inventory_requires_content
from src.benchmark.process_tree import run_process_tree

PARSER_NAME = "unstructured"
PARSER_DISPLAY_NAME = "Unstructured"
UNSTRUCTURED_REQUIRED_VERSION = "0.27.1"
UNSTRUCTURED_INFERENCE_REQUIRED_VERSION = "1.6.13"
SPACY_MODEL_DISTRIBUTION = "en-core-web-sm"
SPACY_MODEL_REQUIRED_VERSION = "3.8.0"
MODEL_MANIFEST_RELATIVE_PATH = Path("manifests") / "unstructured_models_manifest.json"
MODEL_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_MODEL_ROOT = Path("models/unstructured")

_VALID_STRATEGIES = frozenset({"fast", "auto", "hi_res", "ocr_only"})
_PROFILE_KEYS = frozenset({
    "strategy", "ocr_enabled", "ocr_mode", "ocr_engine",
    "languages", "detect_language_per_element", "infer_table_structure",
    "include_page_breaks", "hi_res_model_name", "extract_image_block_types",
    "extract_image_block_to_payload", "extract_forms", "form_extraction_skip_tables",
    "password", "pdfminer_line_margin", "pdfminer_char_margin",
    "pdfminer_line_overlap", "pdfminer_word_margin",
    "remote_services_enabled", "network_allowed_during_run",
    # U1: explicit OCR agent selection
    "ocr_agent",
    "table_ocr_agent",
    "visual_enrichment_enabled", "visual_ocr_language",
    "visual_description_model", "visual_det_model_dir",
    "visual_rec_model_dir", "visual_failure_fatal",
})

# Constant for Tesseract OCR agent — mirrors unstructured's own constant so
# the adapter compiles even when unstructured is not installed (WSL).
_OCR_AGENT_TESSERACT = "unstructured.partition.utils.ocr_models.tesseract_ocr.OCRAgentTesseract"

from src.benchmark.tessdata import _TESSDATA_CANDIDATES

# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

_PIPE_RE = re.compile(r"\|")
_NEWLINE_IN_CELL_RE = re.compile(r"\n+")


def _escape_pipe(text: str) -> str:
    return _PIPE_RE.sub(r"\\|", text)


def _render_table_html(html: str) -> tuple[str, str]:
    """Convert table HTML to GFM Markdown. Returns (markdown, render_mode)."""
    try:
        from html.parser import HTMLParser

        class _TableParser(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.rows: list[list[str]] = []
                self._current_row: list[str] = []
                self._current_cell: list[str] = []
                self._in_cell = False
                self._has_span = False

            def handle_starttag(self, tag: str, attrs: list) -> None:
                attr_dict = dict(attrs)
                if tag in ("td", "th"):
                    self._in_cell = True
                    self._current_cell = []
                    if attr_dict.get("rowspan", "1") != "1" or attr_dict.get("colspan", "1") != "1":
                        self._has_span = True
                elif tag == "tr":
                    self._current_row = []

            def handle_endtag(self, tag: str) -> None:
                if tag in ("td", "th"):
                    self._current_row.append(" ".join(self._current_cell).strip())
                    self._in_cell = False
                elif tag == "tr":
                    if self._current_row:
                        self.rows.append(self._current_row)

            def handle_data(self, data: str) -> None:
                if self._in_cell:
                    cleaned = _NEWLINE_IN_CELL_RE.sub(" ", data).strip()
                    if cleaned:
                        self._current_cell.append(cleaned)

        parser = _TableParser()
        parser.feed(html)
        rows = parser.rows

        if not rows:
            return html, "html_preserved"

        if parser._has_span:
            return f"```html\n{html.strip()}\n```", "html_fenced"

        col_count = max(len(r) for r in rows)
        # Pad rows to uniform width
        rows = [r + [""] * (col_count - len(r)) for r in rows]

        lines: list[str] = []
        header = rows[0]
        lines.append("| " + " | ".join(_escape_pipe(c) for c in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(_escape_pipe(c) for c in row) + " |")
        return "\n".join(lines), "markdown"

    except Exception:
        return f"```html\n{html.strip()}\n```", "html_fenced"


def _render_element(element: Any, *, image_description: bool = False) -> str:
    category = type(element).__name__
    text = str(getattr(element, "text", "") or "").strip()
    meta = getattr(element, "metadata", None)

    if category == "Title":
        depth = getattr(meta, "category_depth", None) if meta else None
        level = min(int(depth) + 1, 6) if isinstance(depth, int) else 1
        prefix = "#" * level
        return f"{prefix} {text}" if text else ""

    if category == "ListItem":
        depth = getattr(meta, "category_depth", None) if meta else None
        indent = "  " * int(depth) if isinstance(depth, int) else ""
        return f"{indent}- {text}" if text else ""

    if category == "Table":
        html = getattr(meta, "text_as_html", None) if meta else None
        if html:
            md, _mode = _render_table_html(html)
            return md
        return text

    if category == "PageBreak":
        return ""

    if category == "Header":
        return text

    if category == "Footer":
        return text

    if category == "Formula":
        return text

    if category in ("Image",):
        # Preserve parser-provided text, but never persist a temporary crop path.
        return text

    if category == "CodeSnippet":
        return f"```\n{text}\n```" if text else ""

    # NarrativeText, Text, UncategorizedText, Paragraph, etc.
    return text


def _elements_to_page_texts(
    elements: list[Any],
    page_count: int,
) -> tuple[list[str], dict[int, list[dict[str, Any]]], set[int]]:
    """Group elements by page and render each page's Markdown text.

    Returns (page_texts, native_pages, observed_pages) where:
    - native_pages maps page_num → list of element records; key 0 holds unassigned elements
    - observed_pages is the set of page numbers that had at least one useful (non-PageBreak) element
    """
    page_buckets: dict[int, list[Any]] = {i + 1: [] for i in range(page_count)}
    no_page_elements: list[Any] = []      # genuinely unassignable (no page at all)
    redistributed_elements: list[Any] = []  # cross-page elements reassigned to last page
    last_seen_page: int = 1

    for el in elements:
        if type(el).__name__ == "PageBreak":
            continue
        meta = getattr(el, "metadata", None)
        page_num = getattr(meta, "page_number", None) if meta else None
        if isinstance(page_num, int) and 1 <= page_num <= page_count:
            last_seen_page = page_num
            page_buckets[page_num].append(el)
        else:
            # Elements without a valid page_number (e.g. cross-page tables from hi_res)
            # are reassigned to the last known page for rendering; tracked separately
            # so native_pages[0] only holds truly unassignable elements.
            redistributed_elements.append(el)
            page_buckets[last_seen_page].append(el)

    page_texts: list[str] = []
    native_pages: dict[int, list[dict[str, Any]]] = {
        0: [_element_to_native(el) for el in redistributed_elements],
    }
    observed_pages: set[int] = set()

    for page_num in range(1, page_count + 1):
        page_els = page_buckets[page_num]
        parts: list[str] = []
        native_records: list[dict[str, Any]] = []

        for el in page_els:
            observed_pages.add(page_num)
            rendered = _render_element(el)
            if rendered:
                parts.append(rendered)
            native_records.append(_element_to_native(el))

        text = "\n\n".join(p for p in parts if p).rstrip() + "\n" if parts else ""
        page_texts.append(text)
        native_pages[page_num] = native_records

    return page_texts, native_pages, observed_pages


def _check_missing_pages(
    observed_pages: set[int],
    page_count: int,
    inventory: dict[str, Any],
    profile_name: str,
) -> tuple[set[int], set[int]]:
    """Classify pages absent from parser output.

    Returns (legitimately_empty, suspect_missing).
    Raises BenchmarkConfigurationError for full_cpu_local profiles when
    a missing page has evidence of content or an incomplete measurement.
    """
    all_pages = set(range(1, page_count + 1))
    missing = all_pages - observed_pages
    if not missing:
        return set(), set()

    per_page = inventory.get("per_page", {})
    legitimately_empty: set[int] = set()
    suspect_missing: set[int] = set()

    for page_num in missing:
        page_inv = per_page.get(str(page_num)) or per_page.get(page_num)
        if page_inv is None:
            # Inventory has no entry for this page — measurement is incomplete
            if profile_name == "full_cpu_local":
                raise BenchmarkConfigurationError(
                    f"Page {page_num} absent from parser output and source_inventory "
                    "has no per-page entry (incomplete measurement). "
                    f"Profile '{profile_name}' requires complete page coverage."
                )
            suspect_missing.add(page_num)
            continue

        measurement_complete = bool(page_inv.get("measurement_complete", True))
        text_chars = int(page_inv.get("text_chars", 0) or 0)
        image_count = int(page_inv.get("image_count", 0) or 0)
        drawing_count = int(page_inv.get("drawing_count", 0) or 0)
        has_content = text_chars > 0 or image_count > 0 or drawing_count > 0

        if not measurement_complete:
            if profile_name == "full_cpu_local":
                raise BenchmarkConfigurationError(
                    f"Page {page_num} absent from parser output and its source_inventory "
                    "measurement is incomplete. "
                    f"Profile '{profile_name}' requires complete page coverage."
                )
            suspect_missing.add(page_num)
        elif has_content:
            if profile_name == "full_cpu_local":
                raise BenchmarkConfigurationError(
                    f"Page {page_num} absent from parser output but source_inventory "
                    f"shows content (text_chars={text_chars}, images={image_count}, "
                    f"drawings={drawing_count}). "
                    f"Profile '{profile_name}' requires all content pages to be processed."
                )
            suspect_missing.add(page_num)
        else:
            # measurement_complete AND no content → legitimately empty
            legitimately_empty.add(page_num)

    return legitimately_empty, suspect_missing


def _element_to_native(element: Any) -> dict[str, Any]:
    meta = getattr(element, "metadata", None)

    def _safe_coords(coords: Any) -> dict[str, Any] | None:
        if coords is None:
            return None
        try:
            return {
                "points": getattr(coords, "points", None),
                "system": str(getattr(coords, "system", None)),
            }
        except Exception:
            return None

    record: dict[str, Any] = {
        "element_id": str(getattr(element, "id", "") or ""),
        "category": type(element).__name__,
        "text": str(getattr(element, "text", "") or ""),
        "page_number": getattr(meta, "page_number", None) if meta else None,
        "parent_id": getattr(meta, "parent_id", None) if meta else None,
        "category_depth": getattr(meta, "category_depth", None) if meta else None,
        "detection_class_prob": getattr(meta, "detection_class_prob", None) if meta else None,
        "detection_origin": getattr(meta, "detection_origin", None) if meta else None,
        "languages": getattr(meta, "languages", None) if meta else None,
        "coordinates": _safe_coords(getattr(meta, "coordinates", None) if meta else None),
        "text_as_html": getattr(meta, "text_as_html", None) if meta else None,
        "links": getattr(meta, "links", None) if meta else None,
    }
    # Remove None values to keep native compact
    return {k: v for k, v in record.items() if v is not None}


def _process_visual_crops(
    elements: list[Any],
    *,
    crop_root: Path,
    page_count: int,
    profile: dict[str, Any],
    resource_monitor: Any,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Describe transient Image/Table crops while their temp directory exists."""
    by_page: list[list[dict[str, Any]]] = [[] for _ in range(page_count)]
    unassigned: list[dict[str, Any]] = []
    if not profile.get("visual_enrichment_enabled", False):
        return by_page, unassigned

    from PIL import Image
    from src.enrichment.visual_contract import VisualRequest
    from src.enrichment.visual_worker_client import VisualWorkerClient

    repo_root = Path(__file__).resolve().parents[2]

    def resolved_profile_path(key: str) -> str:
        value = Path(str(profile.get(key, "")))
        return str((repo_root / value).resolve() if not value.is_absolute() else value.resolve())

    worker_python = repo_root / ".venvs" / "visual-enrichment" / "Scripts" / "python.exe"
    seen_hashes: set[str] = set()
    crop_root_resolved = crop_root.resolve()

    with VisualWorkerClient(
        language=str(profile.get("visual_ocr_language", "pt")),
        smolvlm_model_path=resolved_profile_path("visual_description_model"),
        python_executable=str(worker_python),
        resource_monitor=resource_monitor,
        det_model_dir=resolved_profile_path("visual_det_model_dir"),
        rec_model_dir=resolved_profile_path("visual_rec_model_dir"),
    ) as worker:
        for index, element in enumerate(elements):
            category = type(element).__name__
            if category not in {"Image", "Table"}:
                continue
            metadata = getattr(element, "metadata", None)
            raw_path = getattr(metadata, "image_path", None) if metadata else None
            if not raw_path:
                continue
            path = Path(raw_path).resolve()
            try:
                path.relative_to(crop_root_resolved)
            except ValueError as exc:
                raise RuntimeError(f"Unstructured crop escaped its temp root: {path}") from exc
            image_bytes = path.read_bytes()
            digest = hashlib.sha256(image_bytes).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            with Image.open(path) as image:
                width, height = image.size

            page_number_raw = getattr(metadata, "page_number", None) if metadata else None
            page_number = page_number_raw if isinstance(page_number_raw, int) else None
            region_id = f"p{page_number or 0}-{category.lower()}-{index}-{digest[:8]}"
            response = worker.process(VisualRequest(
                request_id=region_id,
                operation="ocr_and_describe",
                image_base64=base64.b64encode(image_bytes).decode("ascii"),
                language=str(profile.get("visual_ocr_language", "pt")),
                prompt="Descreva objetivamente esta região documental.",
                page_number=page_number or 0,
                region_id=region_id,
            ))
            coords = getattr(metadata, "coordinates", None) if metadata else None
            record = {
                "type": "visual_crop",
                "category": category,
                "region_id": region_id,
                "page_number": page_number,
                "sha256": digest,
                "width": width,
                "height": height,
                "bbox": getattr(coords, "points", None),
                "storage_policy": "transient",
                "deleted_after_processing": True,
                "cleanup_state": "scheduled",
                "status": response.status,
                "ocr_engine": response.ocr_engine,
                "description_model": response.description_model,
                "ocr_text": response.ocr_text.strip() or None,
                "text": response.description.strip() or response.ocr_text.strip() or None,
            }
            if response.error_detail:
                record["error_detail"] = response.error_detail
            if profile.get("visual_failure_fatal", False) and (
                response.status != "success" or response.error_detail
            ):
                raise RuntimeError(
                    f"visual crop {region_id} failed: "
                    f"{response.error_detail or response.status}"
                )
            if page_number and page_number <= len(by_page):
                by_page[page_number - 1].append(record)
            else:
                unassigned.append(record)
    return by_page, unassigned


def _render_visual_items(base: str, items: list[dict[str, Any]]) -> str:
    blocks = []
    for item in items:
        text = str(item.get("text") or "").strip()
        ocr_text = str(item.get("ocr_text") or "").strip()
        if not text and not ocr_text:
            continue
        lines = [
            "<!-- derived:start",
            "type=visual_crop",
            f"page={item.get('page_number') or 0}",
            f"region_id={item['region_id']}",
            "-->",
        ]
        normalized_base = " ".join(base.casefold().split())
        normalized_ocr = " ".join(ocr_text.casefold().split())
        normalized_text = " ".join(text.casefold().split())
        payload_added = False
        if (
            normalized_ocr
            and normalized_ocr not in normalized_base
            and normalized_ocr not in normalized_text
        ):
            lines.append(f"> **Texto OCR:** {ocr_text}")
            payload_added = True
        if normalized_text and normalized_text not in normalized_base:
            lines.append(f"> **Descrição visual:** {text}")
            payload_added = True
        if not payload_added:
            continue
        lines.append("<!-- derived:end -->")
        blocks.append("\n".join(lines))
    return base.rstrip() + (("\n\n" + "\n\n".join(blocks)) if blocks else "")


def _count_elements(elements: list[Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter(type(el).__name__ for el in elements)
    return {
        "layout_boxes": len(elements),
        "tables_detected": counts.get("Table", 0),
        "images_detected": counts.get("Image", 0),
        "headings_detected": counts.get("Title", 0),
        "lists_detected": counts.get("ListItem", 0),
        "formulas_detected": counts.get("Formula", 0),
        "captions_detected": counts.get("FigureCaption", 0),
        "page_headers_detected": counts.get("Header", 0),
        "page_footers_detected": counts.get("Footer", 0),
        "footnotes_detected": 0,
        "text_blocks_detected": counts.get("NarrativeText", 0) + counts.get("Text", 0),
        "code_blocks_detected": counts.get("CodeSnippet", 0),
        "charts_detected": None,
        "box_class_counts": dict(counts),
    }


def _count_elements_by_page(
    elements: list[Any],
    page_count: int,
) -> list[dict[str, Any]]:
    """Return per-page element counts. Fixes the prior bug that accumulated
    all counts on page 1 (index 0) instead of distributing by page_number."""
    page_counters: list[Counter[str]] = [Counter() for _ in range(page_count)]
    unassigned: list[Any] = []

    for el in elements:
        if type(el).__name__ == "PageBreak":
            continue
        meta = getattr(el, "metadata", None)
        page_num = getattr(meta, "page_number", None) if meta else None
        if isinstance(page_num, int) and 1 <= page_num <= page_count:
            page_counters[page_num - 1][type(el).__name__] += 1
        else:
            unassigned.append(el)

    result: list[dict[str, Any]] = []
    for page_num, counts in enumerate(page_counters, start=1):
        result.append({
            "page_number": page_num,
            "tables_detected": counts.get("Table", 0),
            "images_detected": counts.get("Image", 0),
            "headings_detected": counts.get("Title", 0),
            "lists_detected": counts.get("ListItem", 0),
            "formulas_detected": counts.get("Formula", 0),
            "captions_detected": counts.get("FigureCaption", 0),
            "page_headers_detected": counts.get("Header", 0),
            "page_footers_detected": counts.get("Footer", 0),
            "text_blocks_detected": (
                counts.get("NarrativeText", 0) + counts.get("Text", 0)
            ),
            "layout_boxes": sum(counts.values()),
        })

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _get_tesseract_version() -> str | None:
    try:
        r = run_process_tree(
            ["tesseract", "--version"],
            capture_output=True, timeout=5,
        )
        lines = (r.stdout or r.stderr).splitlines()
        return lines[0].strip() if lines else None
    except Exception:
        return None


def _get_poppler_version() -> str | None:
    for tool in ("pdfinfo", "pdftoppm"):
        path = shutil.which(tool)
        if path:
            try:
                r = run_process_tree(
                    [path, "-v"],
                    capture_output=True, timeout=5,
                )
                lines = (r.stdout or r.stderr).splitlines()
                return lines[0].strip() if lines else tool
            except Exception:
                return tool
    return None


def _find_tessdata_prefix() -> str | None:
    import os
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix and Path(prefix).is_dir():
        return prefix
    for c in _TESSDATA_CANDIDATES:
        if Path(c).is_dir():
            return c
    return None

_FULL_CPU_THREAD_LIMIT_VARS = (
    "OMP_THREAD_LIMIT",
    "KMP_DEVICE_THREAD_LIMIT",
    "KMP_ALL_THREADS",
    "KMP_TEAMS_THREAD_LIMIT",
)


def _single_thread_environment_limits() -> dict[str, str]:
    """
    Return OpenMP/KMP environment variables that explicitly
    restrict the current process to one thread.

    full_cpu_local must fail closed instead of silently
    benchmarking with a single CPU thread.
    """
    import os

    restricted: dict[str, str] = {}

    for name in _FULL_CPU_THREAD_LIMIT_VARS:
        value = os.environ.get(name)

        if value is not None and value.strip() == "1":
            restricted[name] = value

    return restricted

# ---------------------------------------------------------------------------
# Source inventory
# ---------------------------------------------------------------------------

def _load_cached_inventory(input_path: Path, output_root: Path) -> dict[str, Any]:
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
    elements: list[Any],
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
    ocr_agent_effective: str | None = None,
    strategy_effective: str | None = None,
    images_extracted_total: int = 0,
    unassigned_elements_count: int = 0,
) -> dict[str, Any]:
    source_summary = {k: v for k, v in inventory.items() if k != "per_page"}
    input_bytes = input_path.stat().st_size
    clean_bytes = artifact_result.get("output", {}).get("clean_markdown_bytes")
    size_ratio = round(input_bytes / clean_bytes, 6) if clean_bytes else None
    ocr_enabled = bool(profile.get("ocr_enabled", False))
    strategy = str(profile.get("strategy", "fast"))

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
                "unstructured": _package_version("unstructured"),
                "unstructured_inference": _package_version("unstructured-inference"),
                "onnxruntime": _package_version("onnxruntime"),
                "pdfminer_six": _package_version("pdfminer.six"),
                "unstructured_pytesseract": _package_version("unstructured-pytesseract"),
                "tiktoken": _package_version("tiktoken"),
                "tesseract": _get_tesseract_version(),
                "poppler": _get_poppler_version(),
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
                "strategy_requested": strategy,
                "strategy_effective": strategy_effective or strategy,
                "engine": profile.get("ocr_engine"),
                "ocr_agent_requested": profile.get("ocr_agent"),
                "ocr_agent_effective": ocr_agent_effective,
                "table_ocr_agent_requested": profile.get("table_ocr_agent"),
                "languages": profile.get("languages"),
                "infer_table_structure": profile.get("infer_table_structure", False),
                "hi_res_model_name": profile.get("hi_res_model_name"),
                "images_extracted_transient": images_extracted_total,
                "unassigned_elements": unassigned_elements_count,
                # Public API in 0.27.1 does not expose stable per-page OCR tracking
                "pages_requested": None,
                "pages_processed": None,
                "requested_page_numbers": None,
                "failed_page_numbers": None,
                "tracking_note": (
                    "A API publica da versao fixada nao expoe "
                    "rastreamento por pagina de forma estavel."
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
        "artifacts": artifact_result["artifacts"],
        "quality_eligibility": artifact_result["quality_eligibility"],
        "content_validation": artifact_result["content_validation"],
        "output": {
            **artifact_result["output"],
            "run_log": str(run_log_path) if run_log_path else None,
            "metrics_json": str(metrics_json_path) if metrics_json_path else None,
            "input_to_clean_markdown_size_ratio": size_ratio,
        },
    }


# ---------------------------------------------------------------------------
# Model manifest helpers
# ---------------------------------------------------------------------------

def _spacy_tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
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
        count += 1
    return digest.hexdigest(), count


def _verify_model_file_record(
    *,
    model_root: Path,
    record: dict[str, Any],
    label: str,
) -> tuple[bool, str]:
    try:
        relative_path = record["path"]
        expected_size = record["size_bytes"]
        expected_sha = record["sha256"]
    except KeyError as exc:
        return False, f"{label}: missing manifest key {exc}"

    resolved = (model_root / relative_path).resolve()
    try:
        resolved.relative_to(model_root.resolve())
    except ValueError:
        return False, f"{label}: path escapes model root"

    if not resolved.is_file():
        return False, f"{label}: file not found: {resolved}"

    actual_size = resolved.stat().st_size
    if actual_size != expected_size:
        return False, f"{label}: size mismatch (expected {expected_size}, got {actual_size})"

    actual_sha = _sha256_file(resolved)
    if actual_sha != expected_sha:
        return False, f"{label}: SHA-256 mismatch"

    return True, f"{label}: OK"


def _validate_unstructured_model_manifest(
    model_root: Path,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    manifest_path = model_root / MODEL_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        checks.append(make_check(
            "Unstructured model manifest",
            "fail",
            f"not found: {manifest_path}",
        ))
        return checks

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        checks.append(make_check("Unstructured model manifest", "fail", str(exc)))
        return checks

    if manifest.get("schema_version") != MODEL_MANIFEST_SCHEMA_VERSION:
        checks.append(make_check(
            "Unstructured model manifest",
            "fail",
            f"unexpected schema_version: {manifest.get('schema_version')!r}",
        ))
        return checks

    if not manifest.get("offline_validation"):
        checks.append(make_check(
            "Unstructured model manifest",
            "fail",
            "offline_validation is not True",
        ))
        return checks

    checks.append(make_check("Unstructured model manifest", "pass", str(manifest_path)))

    resources = manifest.get("resources", {})

    layout = resources.get("layout", {})
    layout_file = layout.get("file", {})
    ok, detail = _verify_model_file_record(
        model_root=model_root, record=layout_file, label="YOLOX layout"
    )
    checks.append(make_check("YOLOX layout file", "pass" if ok else "fail", detail))

    table = resources.get("table", {})
    table_files = table.get("files", [])
    weight_files = [
        r for r in table_files
        if Path(r.get("path", "")).suffix.lower() in {".bin", ".safetensors"}
    ]
    if not weight_files:
        checks.append(make_check(
            "Table Transformer weights", "fail", "no .bin/.safetensors in manifest"
        ))
    else:
        all_ok = True
        for record in table_files:
            ok, detail = _verify_model_file_record(
                model_root=model_root, record=record, label="table"
            )
            if not ok:
                all_ok = False
                checks.append(make_check("Table Transformer weights", "fail", detail))
                break
        if all_ok:
            checks.append(make_check(
                "Table Transformer weights", "pass", f"{len(table_files)} files verified"
            ))

    spacy_record = resources.get("spacy", {})
    wheel_record = spacy_record.get("wheel", {})
    ok, detail = _verify_model_file_record(
        model_root=model_root, record=wheel_record, label="spaCy wheel"
    )
    checks.append(make_check("spaCy wheel", "pass" if ok else "fail", detail))

    spec = importlib.util.find_spec("en_core_web_sm")
    if spec is None or not spec.submodule_search_locations:
        checks.append(make_check("spaCy installed model", "fail", "en_core_web_sm not found"))
    else:
        spacy_root = Path(next(iter(spec.submodule_search_locations))).resolve()
        actual_tree_sha, _ = _spacy_tree_digest(spacy_root)
        expected_tree_sha = spacy_record.get("installed_tree_sha256", "")
        if actual_tree_sha == expected_tree_sha:
            checks.append(make_check("spaCy installed model", "pass", str(spacy_root)))
        else:
            checks.append(make_check(
                "spaCy installed model", "fail", "installed tree SHA-256 mismatch"
            ))

    return checks


def _assert_unstructured_models_ready(model_root: Path) -> None:
    checks = _validate_unstructured_model_manifest(model_root)
    failures = [c for c in checks if c.get("status") == "fail"]
    if failures:
        details = "; ".join(c.get("detail", c.get("name", "")) for c in failures)
        raise BenchmarkConfigurationError(
            f"Unstructured model manifest validation failed: {details}"
        )


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

    # Strategy
    strategy = str(profile.get("strategy", ""))
    if strategy in _VALID_STRATEGIES:
        checks.append(make_check("strategy", "pass", strategy))
    else:
        checks.append(make_check("strategy", "fail", f"unknown strategy: {strategy!r}"))

    # No remote services
    if bool(profile.get("remote_services_enabled", False)):
        checks.append(make_check("remote services disabled", "fail", "remote_services_enabled=true"))
    else:
        checks.append(make_check("remote services disabled", "pass"))

    if bool(profile.get("network_allowed_during_run", False)):
        checks.append(make_check("network during run", "fail", "network_allowed_during_run=true"))
    else:
        checks.append(make_check("network during run", "pass"))

    # Form extraction — unstructured==0.27.1 declares the parameter but never implemented it
    if bool(profile.get("extract_forms", False)):
        checks.append(make_check(
            "form extraction support",
            "fail",
            "unstructured==0.27.1 declares extract_forms in partition_pdf() but "
            "its implementation raises NotImplementedError. Disable extract_forms.",
        ))
    else:
        checks.append(make_check(
            "form extraction support",
            "pass",
            "disabled — unsupported by pinned unstructured==0.27.1",
        ))

    # full_cpu_local must not silently run with a one-thread
    # OpenMP/KMP environment inherited from the parent process.
    if profile_name == "full_cpu_local":
        single_thread_limits = (
            _single_thread_environment_limits()
        )

        if single_thread_limits:
            detail = ", ".join(
                f"{name}={value}"
                for name, value
                in sorted(single_thread_limits.items())
            )

            checks.append(
                make_check(
                    "CPU thread environment",
                    "fail",
                    (
                        "full_cpu_local is restricted to one "
                        f"thread by: {detail}"
                    ),
                )
            )
        else:
            checks.append(
                make_check(
                    "CPU thread environment",
                    "pass",
                    (
                        "no single-thread OpenMP/KMP "
                        "limit detected"
                    ),
                )
            )

    # Telemetria desabilitada — validada via env vars que o runtime seta
    import os as _os
    for _env_var in ("DO_NOT_TRACK", "SCARF_NO_ANALYTICS"):
        val = _os.environ.get(_env_var)
        if val == "1":
            checks.append(make_check(f"telemetry {_env_var}", "pass", "1"))
        else:
            # Only warn during preflight — main() sets these before import
            checks.append(make_check(
                f"telemetry {_env_var}", "warn",
                f"{_env_var}={val!r} (will be set to '1' by main() before import)",
            ))

    # Table structure only with compatible strategy
    if bool(profile.get("infer_table_structure")) and strategy not in ("hi_res", "auto"):
        checks.append(make_check(
            "table structure strategy",
            "fail",
            f"infer_table_structure=true requires hi_res or auto, got {strategy!r}",
        ))
    else:
        checks.append(make_check("table structure strategy", "pass"))

    # Unstructured version
    installed = _package_version("unstructured")
    if installed is None:
        checks.append(make_check("unstructured version", "fail", "unstructured not installed"))
    elif installed != UNSTRUCTURED_REQUIRED_VERSION:
        checks.append(make_check(
            "unstructured version", "fail",
            f"expected {UNSTRUCTURED_REQUIRED_VERSION!r}, got {installed!r}",
        ))
    else:
        checks.append(make_check("unstructured version", "pass", installed))

    inference_version = _package_version("unstructured-inference")
    if inference_version is None:
        checks.append(make_check(
            "unstructured-inference version", "fail", "unstructured-inference not installed"
        ))
    elif inference_version != UNSTRUCTURED_INFERENCE_REQUIRED_VERSION:
        checks.append(make_check(
            "unstructured-inference version", "fail",
            f"expected {UNSTRUCTURED_INFERENCE_REQUIRED_VERSION!r}, got {inference_version!r}",
        ))
    else:
        checks.append(make_check(
            "unstructured-inference version", "pass", inference_version
        ))

    # Python version
    if sys.version_info[:2] != (3, 12):
        checks.append(make_check(
            "python version", "fail",
            f"expected 3.12, got {platform.python_version()}",
        ))
    else:
        checks.append(make_check("python version", "pass", platform.python_version()))

    # OCR-specific checks
    ocr_enabled = bool(profile.get("ocr_enabled", False))
    if ocr_enabled:
        # Tesseract
        tess_bin = shutil.which("tesseract")
        checks.append(make_check(
            "tesseract executable",
            "pass" if tess_bin else "fail",
            tess_bin or "not found in PATH",
        ))
        tess_v = _get_tesseract_version()
        checks.append(make_check(
            "tesseract version",
            "pass" if tess_v else "warn",
            tess_v or "unavailable",
        ))
        tessdata = _find_tessdata_prefix()
        profile_langs = profile.get("languages", ["por", "eng"])
        for lang in profile_langs:
            if tessdata:
                td_file = Path(tessdata) / f"{lang}.traineddata"
                checks.append(make_check(
                    f"tessdata {lang}",
                    "pass" if td_file.is_file() else "fail",
                    str(td_file),
                ))
            else:
                checks.append(make_check(f"tessdata {lang}", "fail", "tessdata directory not found"))
        # osd is recommended but not blocking
        if tessdata:
            osd_file = Path(tessdata) / "osd.traineddata"
            checks.append(make_check(
                "tessdata osd",
                "pass" if osd_file.is_file() else "warn",
                str(osd_file) if not osd_file.is_file() else "present",
            ))

        # Poppler (needed by unstructured for pdf→image conversion)
        pdfinfo = shutil.which("pdfinfo")
        pdftoppm = shutil.which("pdftoppm")
        checks.append(make_check(
            "poppler pdfinfo",
            "pass" if pdfinfo else "fail",
            pdfinfo or "not in PATH",
        ))
        checks.append(make_check(
            "poppler pdftoppm",
            "pass" if pdftoppm else "fail",
            pdftoppm or "not in PATH",
        ))

    # model manifest check for profiles that require full local models
    needs_full_models = (
        profile_name == "full_cpu_local"
        or strategy in {"hi_res", "auto"}
        or profile.get("infer_table_structure") is True
    )
    if needs_full_models:
        effective_model_root = model_root_override or DEFAULT_MODEL_ROOT
        checks.extend(_validate_unstructured_model_manifest(effective_model_root))

    # adapter import
    try:
        import unstructured.partition.pdf  # noqa: F401
        checks.append(make_check("adapter import", "pass", "unstructured.partition.pdf"))
    except Exception as exc:
        checks.append(make_check("adapter import", "fail", f"{type(exc).__name__}: {exc}"))

    return make_result(PARSER_NAME, profile_name, checks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unstructured benchmark adapter v2.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/outputs"))
    parser.add_argument("--profile", default="fast_native")
    parser.add_argument(
        "--model-root", type=Path, default=None,
        help="Override for model artifacts directory (models/unstructured).",
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
    if args.profile == "full_cpu_local":
        single_thread_limits = (
            _single_thread_environment_limits()
        )

        if single_thread_limits:
            detail = ", ".join(
                f"{name}={value}"
                for name, value
                in sorted(single_thread_limits.items())
            )

            raise BenchmarkConfigurationError(
                "Unstructured full_cpu_local cannot run "
                "with a single-thread OpenMP/KMP limit: "
                f"{detail}"
            )
    normalization_config = get_normalization_config()
    tokenizer_name = get_reference_tokenizer()

    paths = build_output_paths(
        args.output_root, PARSER_NAME, input_path.stem, args.profile
    )

    inventory = _load_cached_inventory(input_path, args.output_root)
    page_count = int(inventory["pages"])

    model_root = args.model_root if args.model_root is not None else Path("models/unstructured")
    strategy = str(profile.get("strategy", "fast"))
    ocr_enabled = bool(profile.get("ocr_enabled", False))
    languages = list(profile.get("languages", ["por", "eng"]))

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:    {PARSER_DISPLAY_NAME}")
    print(f"Version:   {_package_version('unstructured')}")
    print(f"Input:     {input_path}")
    print(f"Profile:   {args.profile}")
    print(f"Strategy:  {strategy}")
    print(f"OCR:       {ocr_enabled}")
    print(f"Languages: {languages}")
    print(f"Tokenizer: {tokenizer_name}")
    print(f"Output:    {paths.output_dir}")
    print("=" * 72)

    # Set offline env before importing unstructured to prevent telemetry
    import os
    os.environ["HF_HOME"] = str(model_root / "huggingface")
    os.environ["HF_HUB_CACHE"] = str(model_root / "huggingface" / "hub")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["SCARF_NO_ANALYTICS"] = "1"
    os.environ["UNSTRUCTURED_DEFAULT_MODEL_NAME"] = "yolox"
    os.environ["UNSTRUCTURED_HI_RES_MODEL_NAME"] = "yolox"

    # Build partition kwargs from profile
    partition_kwargs: dict[str, Any] = {
        "filename": str(input_path),
        "strategy": strategy,
        "include_page_breaks": bool(profile.get("include_page_breaks", True)),
        "languages": languages,
        "detect_language_per_element": bool(profile.get("detect_language_per_element", False)),
        "extract_image_block_to_payload": bool(profile.get("extract_image_block_to_payload", False)),
        "extract_forms": bool(profile.get("extract_forms", False)),
        "form_extraction_skip_tables": bool(profile.get("form_extraction_skip_tables", True)),
    }

    # U1: explicit OCR agent — use profile value or fall back to Tesseract constant.
    # Import the library constant when available so the value stays in sync with
    # whatever version is installed; fall back to the string we know from 0.27.x.
    _ocr_agent_requested = profile.get("ocr_agent")
    if ocr_enabled and _ocr_agent_requested:
        try:
            from unstructured.partition.utils.constants import (  # type: ignore  # noqa: PLC0415
                OCR_AGENT_TESSERACT,
            )
            _resolved_ocr_agent = OCR_AGENT_TESSERACT if _ocr_agent_requested == "tesseract" else _ocr_agent_requested
        except ImportError:
            _resolved_ocr_agent = _OCR_AGENT_TESSERACT
        partition_kwargs["ocr_agent"] = _resolved_ocr_agent

        _table_ocr_agent = profile.get("table_ocr_agent", _ocr_agent_requested)
        try:
            from unstructured.partition.utils.constants import (  # type: ignore  # noqa: PLC0415
                OCR_AGENT_TESSERACT,
            )
            _resolved_table_agent = OCR_AGENT_TESSERACT if _table_ocr_agent == "tesseract" else _table_ocr_agent
        except ImportError:
            _resolved_table_agent = _OCR_AGENT_TESSERACT
        partition_kwargs["table_ocr_agent"] = _resolved_table_agent

    infer_table_structure = bool(profile.get("infer_table_structure", False))
    if infer_table_structure:
        partition_kwargs["infer_table_structure"] = True

    if strategy == "hi_res":
        model_name = profile.get("hi_res_model_name") or "yolox"
        partition_kwargs["hi_res_model_name"] = model_name

    image_block_types = list(
        profile.get("extract_image_block_types", [])
    )

    image_temp_dir: TemporaryDirectory | None = None
    unassigned_elements: list[Any] = []
    derived_content_by_page: list[list[dict[str, Any]]] = [
        [] for _ in range(page_count)
    ]
    unassigned_derived: list[dict[str, Any]] = []
    unassigned_markdown = ""

    if image_block_types:
        image_temp_dir = TemporaryDirectory(
            prefix="unstructured_images_",
        )

        partition_kwargs[
            "extract_image_block_types"
        ] = image_block_types
        partition_kwargs[
            "extract_image_block_output_dir"
        ] = image_temp_dir.name

    for _pm_kwarg in (
        "pdfminer_line_margin", "pdfminer_char_margin",
        "pdfminer_line_overlap", "pdfminer_word_margin",
    ):
        _val = profile.get(_pm_kwarg)
        if _val is not None:
            partition_kwargs[_pm_kwarg] = float(_val)

    password = profile.get("password")
    if password:
        partition_kwargs["password"] = password

    needs_full_models = (
        args.profile == "full_cpu_local"
        or strategy in {"hi_res", "auto"}
        or profile.get("infer_table_structure") is True
    )
    if needs_full_models:
        _assert_unstructured_models_ready(model_root)

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
            # Import here so model loading (lazy, happens on first import) is captured
            from unstructured.partition.pdf import partition_pdf  # noqa: PLC0415
            initialization_seconds = perf_counter() - init_start

            extraction_start = perf_counter()
            elements = partition_pdf(**partition_kwargs)
            extraction_seconds = perf_counter() - extraction_start

            page_texts, native_pages, observed_pages = _elements_to_page_texts(elements, page_count)
            _legitimately_empty, _suspect_missing = _check_missing_pages(
                observed_pages, page_count, inventory, args.profile
            )
            element_counts = _count_elements(elements)
            # U3: per-page counts (fixes prior bug that put all counts on page 1)
            per_page_counts = _count_elements_by_page(elements, page_count)

            parser_page_elements = per_page_counts

            parser_native_pages = [
                {
                    "page_number": i + 1,
                    "elements": native_pages.get(i + 1, []),
                    # U2: count images extracted to temp dir (never persist paths)
                    "images_extracted": sum(
                        1 for el in native_pages.get(i + 1, [])
                        if el.get("category") == "Image"
                    ),
                }
                for i in range(page_count)
            ]

            # U2: all elements without a page_number are redistributed to the last
            # known page inside _elements_to_page_texts(), so there are no genuinely
            # unassigned elements remaining at this point.
            unassigned_elements = []
            unassigned_source_elements = []
            unassigned_markdown = "\n\n".join(
                rendered for rendered in (
                    _render_element(element) for element in unassigned_source_elements
                ) if rendered
            )

            if image_temp_dir is not None:
                derived_content_by_page, unassigned_derived = _process_visual_crops(
                    elements,
                    crop_root=Path(image_temp_dir.name),
                    page_count=page_count,
                    profile=profile,
                    resource_monitor=monitor,
                )

    except Exception:
        monitor.stop()
        raise
    finally:
        # U2: always cleanup — even on exception — so no temp images linger on disk
        if image_temp_dir is not None:
            image_temp_dir.cleanup()
            image_temp_dir = None
        for item in [
            entry
            for page_items in derived_content_by_page
            for entry in page_items
        ] + unassigned_derived:
            item["cleanup_state"] = "cleaned"

    pipeline_seconds = perf_counter() - pipeline_started

    mapping_complete = (
        not unassigned_elements
        and not unassigned_derived
        and not _suspect_missing
    )
    native_markdown = join_page_texts(page_texts)
    if unassigned_markdown:
        native_markdown = native_markdown.rstrip() + "\n\n" + unassigned_markdown + "\n"
    enriched_pages = [
        _render_visual_items(page_texts[index], derived_content_by_page[index])
        for index in range(page_count)
    ]
    has_derived = any(derived_content_by_page) or bool(unassigned_derived)
    enriched_global = None
    if has_derived and not mapping_complete:
        enriched_global = join_page_texts(enriched_pages)
        if unassigned_markdown:
            enriched_global = enriched_global.rstrip() + "\n\n" + unassigned_markdown
        enriched_global = _render_visual_items(enriched_global, unassigned_derived)

    artifact_input = ParserArtifactInput(
        native_markdown=native_markdown,
        source_page_markdown=page_texts if mapping_complete else None,
        enriched_page_markdown=enriched_pages if has_derived and mapping_complete else None,
        enriched_document_markdown=enriched_global,
        page_mapping_status="complete" if mapping_complete else "unavailable",
        parser_page_elements=parser_page_elements,
        parser_native_pages=parser_native_pages,
        derived_content_by_page=derived_content_by_page,
        raw_origin_kind="adapter_assembled_declared",
        raw_origin_details="page_texts join",
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
        normalization_config=normalization_config,
        artifact_policy=artifact_policy,
    )

    resources = monitor.stop()

    images_extracted_total = sum(
        p.get("images_extracted", 0) for p in parser_native_pages
    )

    metrics = _build_metrics(
        input_path=input_path,
        profile=profile,
        profile_name=args.profile,
        inventory=inventory,
        artifact_result=artifact_result,
        elements=elements,
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
        ocr_agent_effective=partition_kwargs.get("ocr_agent"),
        strategy_effective=strategy,
        images_extracted_total=images_extracted_total,
        unassigned_elements_count=len(unassigned_elements),
    )

    if artifact_policy.includes("metrics.json"):
        write_json(paths.metrics_json, metrics)


if __name__ == "__main__":
    main()
