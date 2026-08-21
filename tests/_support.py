"""
Shared test helpers: make_metrics(), write_metrics(), run_script().

All tests that touch summary scripts or comparisons should use
make_metrics() to build fixtures, so field paths stay in one place.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def make_metrics(
    parser: str,
    profile: str,
    document_file: str,
    *,
    pages: int = 10,
    input_mb: float = 1.0,
    tokens: int = 5000,
    tokens_per_page: float = 500.0,
    markdown_mb: float = 0.1,
    jsonl_mb: float = 0.5,
    size_ratio: float | None = 10.0,
    extraction_seconds: float = 5.0,
    pipeline_seconds: float = 5.5,
    pages_per_second: float | None = 2.0,
    avg_cpu: float = 30.0,
    peak_cpu: float = 60.0,
    peak_ram_mb: float = 400.0,
    empty_output_pages: int = 0,
    tables: int = 3,
    images: int = 2,
    charts: int | None = None,
) -> dict:
    """Return a synthetic v2 metrics.json dict with all fields used by summaries."""
    return {
        "run": {
            "parser": parser,
            "profile": profile,
        },
        "document": {
            "file": document_file,
            "pages": pages,
            "input_size_mb": input_mb,
        },
        "tokens": {
            "reference": {
                "clean_markdown_tokens": tokens,
                "clean_tokens_per_page": tokens_per_page,
            },
        },
        "output": {
            "clean_markdown_mb": markdown_mb,
            "document_jsonl_mb": jsonl_mb,
            "input_to_clean_markdown_size_ratio": size_ratio,
        },
        "processing": {
            "extraction_seconds": extraction_seconds,
            "pipeline_seconds": pipeline_seconds,
            "extraction_pages_per_second": pages_per_second,
            "empty_output_pages": empty_output_pages,
        },
        "resources": {
            "average_cpu_system_capacity_percent": avg_cpu,
            "peak_cpu_system_capacity_percent": peak_cpu,
            "peak_rss_mb": peak_ram_mb,
        },
        "content_elements": {
            "parser_output": {
                "tables_detected": tables,
                "images_detected": images,
                "charts_detected": charts,
            },
        },
    }


def write_metrics(
    root: Path,
    parser: str,
    doc_stem: str,
    profile: str,
    data: dict,
) -> Path:
    """Write data as metrics.json under root/parser/doc_stem/profile/."""
    metrics_dir = root / parser / doc_stem / profile
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = metrics_dir / "metrics.json"
    metrics_path.write_text(json.dumps(data), encoding="utf-8")
    return metrics_path


def run_script(
    script_name: str,
    *args: str,
) -> subprocess.CompletedProcess:
    """Run a script under scripts/ with the given args, capturing output."""
    script_path = ROOT / "scripts" / script_name
    return subprocess.run(
        [sys.executable, str(script_path)] + list(args),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
