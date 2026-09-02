from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkPaths:
    output_dir: Path

    raw_markdown: Path
    clean_markdown: Path
    enriched_markdown: Path
    document_jsonl: Path
    metrics_json: Path
    removed_content_jsonl: Path
    run_log: Path

    native_dir: Path
    native_manifest_json: Path
    native_assets_dir: Path


def build_output_paths(
    output_root: Path,
    parser_name: str,
    document_id: str,
    profile_name: str,
    *,
    create: bool = True,
) -> BenchmarkPaths:
    output_dir = (
        output_root
        / parser_name
        / document_id
        / profile_name
    )

    if create:
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    native_dir = output_dir / "native"

    return BenchmarkPaths(
        output_dir=output_dir,

        raw_markdown=(
            output_dir / "raw.md"
        ),

        clean_markdown=(
            output_dir / "document.md"
        ),

        enriched_markdown=(
            output_dir / "document.enriched.md"
        ),

        document_jsonl=(
            output_dir / "document.jsonl"
        ),

        metrics_json=(
            output_dir / "metrics.json"
        ),

        removed_content_jsonl=(
            output_dir
            / "removed_content.jsonl"
        ),

        run_log=(
            output_dir / "run.log"
        ),

        native_dir=native_dir,

        native_manifest_json=(
            native_dir / "manifest.json"
        ),

        native_assets_dir=(
            native_dir / "assets"
        ),
    )
