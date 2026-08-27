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

_VALID_STRATEGIES = frozenset({"fast", "hi_res", "ocr_only"})
_PROFILE_KEYS = frozenset({
    "strategy", "ocr_enabled", "ocr_engine", "languages",
    "infer_table_structure", "detect_tables", "table_output_format",
    "extract_images", "image_description", "output_format",
    "detect_language", "language_hint", "max_pages",
    "password", "dpi", "hi_res_dpi", "fast_dpi",
    "remote_services_enabled", "network_allowed_during_run",
})

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
    """Build Xberg ExtractionConfig from a benchmark profile dict."""
    import xberg

    strategy = str(profile.get("strategy", "fast"))
    ocr_enabled = bool(profile.get("ocr_enabled", False))
    languages = list(profile.get("languages", ["por", "eng"]))
    infer_tables = bool(profile.get("infer_table_structure", True))
    detect_tables = bool(profile.get("detect_tables", True))

    # Build OCR config if OCR is enabled
    ocr_config = None
    if ocr_enabled:
        OcrConfig = getattr(xberg, "OcrConfig", None)
        TesseractConfig = getattr(xberg, "TesseractConfig", None)
        if OcrConfig is not None:
            try:
                tess_cfg = TesseractConfig(languages=languages) if TesseractConfig else None
                if tess_cfg is not None:
                    ocr_config = OcrConfig(engine="tesseract", tesseract=tess_cfg)
                else:
                    ocr_config = OcrConfig(languages=languages)
            except TypeError:
                try:
                    ocr_config = OcrConfig()
                except Exception:
                    ocr_config = None

    # DPI for rendering
    dpi_key = "hi_res_dpi" if strategy == "hi_res" else "fast_dpi"
    dpi = int(profile.get(dpi_key, profile.get("dpi", 150 if strategy == "hi_res" else 72)))

    ExtractionConfig = getattr(xberg, "ExtractionConfig", None)
    if ExtractionConfig is None:
        raise BenchmarkConfigurationError("xberg.ExtractionConfig not found — check Xberg version.")

    try:
        cfg = ExtractionConfig(
            extract_tables=detect_tables,
            infer_table_structure=infer_tables,
            ocr=ocr_config,
            dpi=dpi,
            strategy=strategy,
        )
    except TypeError:
        # Fall back to minimal config if signature differs
        try:
            cfg = ExtractionConfig(extract_tables=detect_tables, ocr=ocr_config)
        except TypeError:
            cfg = ExtractionConfig()

    return cfg


async def _extract(input_path: Path, cfg: Any) -> Any:
    import xberg

    extract_fn = getattr(xberg, "extract", None)
    if extract_fn is None:
        raise BenchmarkConfigurationError("xberg.extract not found — check Xberg version.")

    ExtractInput = getattr(xberg, "ExtractInput", None)
    if ExtractInput is not None:
        try:
            inp = ExtractInput(source=str(input_path))
            return await extract_fn(inp, cfg)
        except (TypeError, AttributeError):
            pass
    return await extract_fn(str(input_path), cfg)


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _get_pages(result: Any) -> list[Any]:
    """Extract per-page result objects from whatever structure Xberg returns."""
    # Common shapes tried in order
    for attr in ("documents", "results"):
        docs = getattr(result, attr, None)
        if isinstance(docs, list) and docs:
            doc = docs[0]
            # doc may have .pages
            pages = getattr(doc, "pages", None)
            if isinstance(pages, list):
                return pages
            # or the doc itself may be a page list
            return docs
    # result.pages at top level
    pages = getattr(result, "pages", None)
    if isinstance(pages, list):
        return pages
    return []


def _page_text(page_obj: Any) -> str:
    """Extract text from a page result object."""
    for attr in ("content", "text", "markdown", "output"):
        val = getattr(page_obj, attr, None)
        if isinstance(val, str) and val.strip():
            return val.rstrip() + "\n"
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
        if v is not None:
            record[attr] = v if not hasattr(v, "__dict__") else str(v)
    return record


def _result_to_page_texts(
    result: Any,
    page_count: int,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert Xberg result to (page_texts, parser_page_elements, parser_native_pages)."""
    pages = _get_pages(result)

    # Build a mapping from page_number → page_obj
    page_map: dict[int, Any] = {}
    for i, pg in enumerate(pages):
        pnum = _page_number(pg, fallback=i + 1)
        page_map[pnum] = pg

    # If Xberg returns a single unified document without per-page, check for text attr on result
    if not page_map:
        docs = getattr(result, "documents", None) or getattr(result, "results", None)
        if isinstance(docs, list) and docs:
            doc = docs[0]
            full_text = getattr(doc, "content", None) or getattr(doc, "text", None) or getattr(doc, "markdown", None)
            if isinstance(full_text, str):
                # Can't map to pages — put all on page 1
                page_texts = [full_text.rstrip() + "\n"] + [""] * (page_count - 1)
                parser_page_elements = [{"page_number": i + 1} for i in range(page_count)]
                parser_native_pages = [{"page_number": i + 1, "elements": []} for i in range(page_count)]
                return page_texts, parser_page_elements, parser_native_pages

    page_texts: list[str] = []
    parser_page_elements: list[dict[str, Any]] = []
    parser_native_pages: list[dict[str, Any]] = []

    for page_num in range(1, page_count + 1):
        pg = page_map.get(page_num)
        if pg is not None:
            text = _page_text(pg)
            tables = _page_tables(pg)
            table_count = len(tables)
        else:
            text = ""
            tables = []
            table_count = 0

        page_texts.append(text)
        parser_page_elements.append({
            "page_number": page_num,
            "tables_detected": table_count,
        })
        native_tables = [_table_to_native(t) for t in tables]
        parser_native_pages.append({
            "page_number": page_num,
            "tables": native_tables,
        })

    return page_texts, parser_page_elements, parser_native_pages


def _count_elements_from_result(result: Any, page_texts: list[str]) -> dict[str, Any]:
    pages = _get_pages(result)
    total_tables = sum(len(_page_tables(pg)) for pg in pages)
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
    strategy = str(profile.get("strategy", "fast"))

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
            "failed_pages": [],
            "partial_pages": None,
            "empty_output_pages": artifact_result["empty_output_pages"],
            "pipeline_pages_per_second": (
                round(int(inventory.get("pages", 0)) / pipeline_seconds, 6)
                if pipeline_seconds > 0 and inventory.get("pages") else None
            ),
            "ocr": {
                "enabled": ocr_enabled,
                "strategy": strategy,
                "engine": profile.get("ocr_backend"),
                "languages": profile.get("ocr_languages"),
                "infer_table_structure": profile.get("extract_tables", True),
                "force_ocr": profile.get("force_ocr", False),
                "auto_rotate": profile.get("auto_rotate", False),
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
        # Tessdata language files
        tessdata = _find_tessdata_prefix()
        for lang in ("por", "eng"):
            if tessdata:
                td_file = Path(tessdata) / f"{lang}.traineddata"
                checks.append(make_check(
                    f"tessdata {lang}",
                    "pass" if td_file.is_file() else "fail",
                    str(td_file),
                ))
            else:
                checks.append(make_check(f"tessdata {lang}", "fail", "tessdata directory not found"))
        # osd required when auto_rotate=true
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

    # adapter import
    try:
        import xberg  # noqa: F401
        checks.append(make_check("adapter import", "pass", "xberg"))

        extract_fn = getattr(xberg, "extract", None)
        if extract_fn is None or not asyncio.iscoroutinefunction(extract_fn):
            checks.append(make_check("xberg.extract async", "fail", "not an async function"))
        else:
            checks.append(make_check("xberg.extract async", "pass"))

        ExtractionConfig = getattr(xberg, "ExtractionConfig", None)
        checks.append(make_check(
            "ExtractionConfig",
            "pass" if ExtractionConfig else "fail",
            "found" if ExtractionConfig else "not found",
        ))
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
    parser.add_argument("--profile", default="fast_native")
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
    strategy = str(profile.get("strategy", "fast"))
    ocr_enabled = bool(profile.get("ocr_enabled", False))

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:    {PARSER_DISPLAY_NAME}")
    print(f"Version:   {_package_version('xberg')}")
    print(f"Input:     {input_path}")
    print(f"Profile:   {args.profile}")
    print(f"Strategy:  {strategy}")
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

            page_texts, parser_page_elements, parser_native_pages = _result_to_page_texts(
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
