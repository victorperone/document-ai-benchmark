"""
Shared test helpers: make_metrics(), write_metrics(), run_script(),
load_run_batch_module(), make_valid_job_output().

All tests that touch summary scripts or comparisons should use
make_metrics() to build fixtures, so field paths stay in one place.
Use make_valid_job_output() to create complete post-execution fixtures.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from src.benchmark.artifact_policy import ArtifactPolicy


ROOT = Path(__file__).resolve().parents[1]


def load_run_batch_module():
    """Load scripts/run_batch.py as a module without executing main().

    Must register in sys.modules before exec_module so that @dataclass
    can resolve the module namespace via sys.modules[cls.__module__]
    (required on Python 3.14+). Returns a fresh module object each call.
    """
    spec = importlib.util.spec_from_file_location(
        "scripts_run_batch",
        ROOT / "scripts" / "run_batch.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["scripts_run_batch"] = module
    spec.loader.exec_module(module)
    return module


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


_ARTIFACT_OUTPUT_KEY = {
    "raw.md": "raw_markdown",
    "document.md": "clean_markdown",
    "document.jsonl": "document_jsonl",
    "metrics.json": "metrics_json",
    "removed_content.jsonl": "removed_content_jsonl",
    "run.log": "run_log",
}
_ARTIFACT_BYTES_KEY = {
    "raw.md": "raw_markdown_bytes",
    "document.md": "clean_markdown_bytes",
    "document.jsonl": "document_jsonl_bytes",
    "removed_content.jsonl": "removed_content_jsonl_bytes",
}


def make_valid_job_output(
    output_root: Path,
    parser: str = "pymupdf",
    profile: str = "native",
    doc_stem: str = "A",
    doc_sha256: str = "abc123",
    pages: int = 3,
    artifact_policy: ArtifactPolicy | None = None,
    removed_records: int = 2,
) -> tuple[Path, Path]:
    """Write a complete valid job output structure under output_root.

    Returns (document_path, source_inventory_path). document_path is a
    synthetic Path with correct .name/.stem; it does not need to exist on disk.
    """
    if artifact_policy is None:
        artifact_policy = ArtifactPolicy.from_cli(["all"])

    doc_name = f"{doc_stem}.pdf"
    out_dir = output_root / parser / doc_stem / profile
    out_dir.mkdir(parents=True, exist_ok=True)

    inv_dir = output_root / "_source_inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)
    inv_path = inv_dir / f"{doc_stem}.json"
    inv_path.write_text(
        json.dumps({"file": doc_name, "sha256": doc_sha256, "pages": pages}),
        encoding="utf-8",
    )

    written: dict[str, Path] = {}

    if artifact_policy.includes("raw.md"):
        p = out_dir / "raw.md"
        p.write_text("# Raw content\n", encoding="utf-8")
        written["raw.md"] = p

    if artifact_policy.includes("document.md"):
        p = out_dir / "document.md"
        p.write_text("# Clean document\n", encoding="utf-8")
        written["document.md"] = p

    if artifact_policy.includes("run.log"):
        p = out_dir / "run.log"
        p.write_text("Extraction complete.\n", encoding="utf-8")
        written["run.log"] = p

    if artifact_policy.includes("document.jsonl"):
        p = out_dir / "document.jsonl"
        records = [
            json.dumps({
                "page_number": i,
                "source_file": doc_name,
                "parser": parser,
                "profile": profile,
                "clean_markdown": "" if i == pages else f"Page {i}.",
            })
            for i in range(1, pages + 1)
        ]
        p.write_text("\n".join(records) + "\n", encoding="utf-8")
        written["document.jsonl"] = p

    if artifact_policy.includes("removed_content.jsonl"):
        p = out_dir / "removed_content.jsonl"
        lines = [json.dumps({"removed_item": i}) for i in range(removed_records)]
        p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        written["removed_content.jsonl"] = p

    artifact_sel = artifact_policy.as_list()
    out_block: dict = {"selected_artifacts": artifact_sel}
    for artifact in artifact_sel:
        out_key = _ARTIFACT_OUTPUT_KEY.get(artifact)
        if out_key:
            out_block[out_key] = f"/outputs/{parser}/{doc_stem}/{profile}/{artifact}"
        bytes_key = _ARTIFACT_BYTES_KEY.get(artifact)
        if bytes_key and artifact in written:
            out_block[bytes_key] = written[artifact].stat().st_size

    if artifact_policy.includes("metrics.json"):
        metrics_data = {
            "benchmark": {"schema_version": 2},
            "run": {
                "parser": parser,
                "profile": profile,
                "artifact_selection": artifact_sel,
            },
            "document": {
                "file": doc_name,
                "id": doc_stem,
                "sha256": doc_sha256,
                "pages": pages,
            },
            "processing": {
                "pages_total": pages,
                "pages_processed": pages,
                "failed_pages": 0,
                "empty_output_pages": 0,
                "errors_count": 0,
            },
            "output": out_block,
            "normalization": {
                "removed_records": removed_records
                if artifact_policy.includes("removed_content.jsonl")
                else 0,
            },
        }
        mp = out_dir / "metrics.json"
        mp.write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")
        written["metrics.json"] = mp

    doc_path = Path(f"/fake/data/{doc_name}")
    return doc_path, inv_path


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
