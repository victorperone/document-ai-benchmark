"""Canonical output-path structure for a single benchmark run.

``build_output_paths`` computes every file path that the artifact pipeline
may write, so all modules share a single, consistent layout:

    <output_root>/<parser>/<document_id>/<profile>/
        raw.md
        document.md
        document.enriched.md
        document.jsonl
        metrics.json
        removed_content.jsonl
        run.log
        native/
            manifest.json
            assets/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkPaths:
    """All resolved filesystem paths for one parser/document/profile run.

    Attributes:
        output_dir: The run-specific output directory
            ``<output_root>/<parser>/<document_id>/<profile>``.
        raw_markdown: Path to ``raw.md`` (parser native output).
        clean_markdown: Path to ``document.md`` (normalised output).
        enriched_markdown: Path to ``document.enriched.md``.
        document_jsonl: Path to ``document.jsonl`` (per-page records).
        metrics_json: Path to ``metrics.json``.
        removed_content_jsonl: Path to ``removed_content.jsonl``.
        run_log: Path to ``run.log`` (parser stdout/stderr).
        native_dir: Root directory of the native bundle (``native/``).
        native_manifest_json: Path to ``native/manifest.json``.
        native_assets_dir: Path to ``native/assets/`` (relocated images).
    """

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
    """Compute all output paths for a single parser/document/profile run.

    Args:
        output_root: Root directory under which parser outputs are stored.
        parser_name: Parser identifier (e.g. ``"pymupdf"``).
        document_id: Document stem (filename without extension).
        profile_name: Profile identifier (e.g. ``"default"``).
        create: When ``True`` the output directory is created if absent.

    Returns:
        Frozen ``BenchmarkPaths`` with every relevant path resolved.
    """
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
