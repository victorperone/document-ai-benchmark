from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from src.benchmark.artifact_contract import (
    ParserArtifactInput,
    join_page_texts,
)
from src.benchmark.artifact_policy import (
    ArtifactPolicy,
)
from src.benchmark.content_metrics import (
    analyze_markdown_content,
)
from src.benchmark.metrics_writer import (
    write_jsonl,
)
from src.benchmark.noise_metrics import (
    analyze_noise,
)
from src.benchmark.normalizer import (
    normalize_pages,
)
from src.benchmark.paths import (
    BenchmarkPaths,
)
from src.benchmark.token_metrics import (
    build_token_metrics,
)


MB = 1024 * 1024


def _mb(
    value: int | None,
) -> float | None:
    if value is None:
        return None

    return round(
        value / MB,
        6,
    )


def _written_size(
    *,
    selected: bool,
    path: Path,
) -> int | None:
    if not selected:
        return None

    if not path.is_file():
        return None

    return path.stat().st_size


def finalize_artifacts(
    *,
    paths: BenchmarkPaths,
    document_id: str,
    source_file: str,
    parser_name: str,
    profile_name: str,
    artifact_input: ParserArtifactInput,
    tokenizer_name: str,
    normalization_config: dict[
        str,
        Any,
    ],
    artifact_policy: ArtifactPolicy,
) -> dict[str, Any]:
    page_count = len(
        artifact_input.parser_page_elements
    )

    if len(artifact_input.parser_native_pages) != page_count:
        raise ValueError(
            "parser_native_pages length mismatch"
        )

    source_pages = artifact_input.source_page_markdown or []

    paths.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Normalization (source pages → document.md)
    # --------------------------------------------------------

    started = perf_counter()

    normalized = normalize_pages(
        source_pages,
        normalization_config,
    )

    normalization_seconds = (
        perf_counter()
        - started
    )

    # --------------------------------------------------------
    # Common metrics
    # --------------------------------------------------------

    started = perf_counter()

    short_line_threshold = int(
        normalization_config[
            "short_line_character_threshold"
        ]
    )
    min_rep_fraction = float(
        normalization_config[
            "minimum_repeated_page_fraction"
        ]
    )
    min_rep_count = int(
        normalization_config[
            "minimum_repeated_page_count"
        ]
    )

    raw_noise = analyze_noise(
        normalized.raw_markdown,
        page_texts=source_pages,
        short_line_threshold=short_line_threshold,
        minimum_repeated_page_fraction=min_rep_fraction,
        minimum_repeated_page_count=min_rep_count,
    )

    clean_noise = analyze_noise(
        normalized.clean_markdown,
        page_texts=(
            normalized.clean_page_texts
        ),
        short_line_threshold=short_line_threshold,
        minimum_repeated_page_fraction=min_rep_fraction,
        minimum_repeated_page_count=min_rep_count,
    )

    raw_content = (
        analyze_markdown_content(
            normalized.raw_markdown
        )
    )

    clean_content = (
        analyze_markdown_content(
            normalized.clean_markdown
        )
    )

    native_content = artifact_input.native_markdown or ""

    token_metrics = build_token_metrics(
        raw_text=native_content,
        clean_text=(
            normalized.clean_markdown
        ),
        page_count=page_count,
        tokenizer_name=tokenizer_name,
        removed_records=(
            normalized.removed_records
        ),
    )

    metrics_seconds = (
        perf_counter()
        - started
    )

    # --------------------------------------------------------
    # Canonical per-page records
    # --------------------------------------------------------

    records: list[
        dict[str, Any]
    ] = []

    if artifact_policy.includes(
        "document.jsonl"
    ):
        for index in range(page_count):
            page_source = (
                source_pages[index]
                if index < len(source_pages)
                else ""
            )
            records.append(
                {
                    "document_id": (
                        document_id
                    ),

                    "source_file": (
                        source_file
                    ),

                    "parser": (
                        parser_name
                    ),

                    "profile": (
                        profile_name
                    ),

                    "page_number": (
                        index + 1
                    ),

                    "raw_markdown": (
                        page_source
                    ),

                    "clean_markdown": (
                        normalized
                        .clean_page_texts[
                            index
                        ]
                        if index < len(normalized.clean_page_texts)
                        else ""
                    ),

                    "parser_elements": (
                        artifact_input
                        .parser_page_elements[
                            index
                        ]
                    ),

                    "parser_native": (
                        artifact_input
                        .parser_native_pages[
                            index
                        ]
                    ),
                }
            )

    # --------------------------------------------------------
    # Selected artifact writing
    # --------------------------------------------------------

    started = perf_counter()

    if artifact_policy.includes(
        "raw.md"
    ):
        paths.raw_markdown.write_text(
            native_content,
            encoding="utf-8",
        )

    if artifact_policy.includes(
        "document.md"
    ):
        paths.clean_markdown.write_text(
            normalized.clean_markdown,
            encoding="utf-8",
        )

    enriched_selected = artifact_policy.includes(
        "document.enriched.md"
    )

    if enriched_selected:
        enriched_text = join_page_texts(
            artifact_input.enriched_page_markdown or []
        )
        paths.enriched_markdown.write_text(
            enriched_text,
            encoding="utf-8",
        )

    if artifact_policy.includes(
        "document.jsonl"
    ):
        write_jsonl(
            paths.document_jsonl,
            records,
        )

    if artifact_policy.includes(
        "removed_content.jsonl"
    ):
        write_jsonl(
            paths.removed_content_jsonl,
            normalized.removed_records,
        )

    write_seconds = (
        perf_counter()
        - started
    )

    raw_selected = (
        artifact_policy.includes(
            "raw.md"
        )
    )

    clean_selected = (
        artifact_policy.includes(
            "document.md"
        )
    )

    jsonl_selected = (
        artifact_policy.includes(
            "document.jsonl"
        )
    )

    removed_selected = (
        artifact_policy.includes(
            "removed_content.jsonl"
        )
    )

    raw_bytes = _written_size(
        selected=raw_selected,
        path=paths.raw_markdown,
    )

    clean_bytes = _written_size(
        selected=clean_selected,
        path=paths.clean_markdown,
    )

    enriched_bytes = _written_size(
        selected=enriched_selected,
        path=paths.enriched_markdown,
    )

    jsonl_bytes = _written_size(
        selected=jsonl_selected,
        path=paths.document_jsonl,
    )

    removed_bytes = _written_size(
        selected=removed_selected,
        path=paths.removed_content_jsonl,
    )

    empty_output_pages = sum(
        not any(
            character.isalnum()
            for character
            in page
        )
        for page
        in normalized.clean_page_texts
    )

    page_mapping_complete = (
        artifact_input.page_mapping_status
        == "complete"
    )

    return {
        "timing": {
            "normalization_seconds": round(
                normalization_seconds,
                6,
            ),

            "common_metrics_seconds": round(
                metrics_seconds,
                6,
            ),

            "artifact_write_seconds": round(
                write_seconds,
                6,
            ),
        },

        "content_elements": {
            "raw_markdown": (
                raw_content
            ),

            "clean_markdown": (
                clean_content
            ),
        },

        "heuristics": {
            "raw": raw_noise,
            "cleaned": clean_noise,
        },

        "tokens": token_metrics,

        "normalization": {
            "config": (
                normalization_config
            ),

            "removed_records": len(
                normalized.removed_records
            ),

            "header_records_removed": sum(
                record.get("type")
                == "header"
                for record
                in normalized.removed_records
            ),

            "footer_records_removed": sum(
                record.get("type")
                == "footer"
                for record
                in normalized.removed_records
            ),
        },

        "empty_output_pages": (
            empty_output_pages
        ),

        "artifacts": {
            "raw": {
                "origin_kind": (
                    artifact_input.raw_origin_kind
                ),
                "origin_details": (
                    artifact_input.raw_origin_details
                ),
                "bytes": raw_bytes,
            },
            "clean": {
                "bytes": clean_bytes,
            },
            "enriched": {
                "present": enriched_selected,
                "bytes": enriched_bytes,
            },
        },

        "quality_eligibility": {
            "source_text": bool(native_content),
            "page_mapping_complete": page_mapping_complete,
            "formal_quality_eligible": (
                bool(native_content)
                and page_mapping_complete
            ),
        },

        "output": {
            "selected_artifacts": (
                artifact_policy
                .as_list()
            ),

            "raw_markdown": (
                str(
                    paths.raw_markdown
                )
                if raw_selected
                else None
            ),

            "clean_markdown": (
                str(
                    paths.clean_markdown
                )
                if clean_selected
                else None
            ),

            "document_jsonl": (
                str(
                    paths.document_jsonl
                )
                if jsonl_selected
                else None
            ),

            "removed_content_jsonl": (
                str(
                    paths
                    .removed_content_jsonl
                )
                if removed_selected
                else None
            ),

            "raw_markdown_bytes": (
                raw_bytes
            ),

            "clean_markdown_bytes": (
                clean_bytes
            ),

            "enriched_markdown": (
                str(paths.enriched_markdown)
                if enriched_selected
                else None
            ),

            "enriched_markdown_bytes": (
                enriched_bytes
            ),

            "document_jsonl_bytes": (
                jsonl_bytes
            ),

            "removed_content_jsonl_bytes": (
                removed_bytes
            ),

            "raw_markdown_mb": (
                _mb(raw_bytes)
            ),

            "clean_markdown_mb": (
                _mb(clean_bytes)
            ),

            "document_jsonl_mb": (
                _mb(jsonl_bytes)
            ),
        },
    }
