from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

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
    value: int,
) -> float:
    return round(
        value / MB,
        6,
    )


def finalize_artifacts(
    *,
    paths: BenchmarkPaths,
    document_id: str,
    source_file: str,
    parser_name: str,
    profile_name: str,
    page_texts: list[str],
    parser_page_elements: list[
        dict[str, Any]
    ],
    parser_native_pages: list[
        dict[str, Any]
    ],
    tokenizer_name: str,
    normalization_config: dict[
        str,
        Any,
    ],
) -> dict[str, Any]:
    page_count = len(
        page_texts
    )

    if len(parser_page_elements) != page_count:
        raise ValueError(
            "parser_page_elements length mismatch"
        )

    if len(parser_native_pages) != page_count:
        raise ValueError(
            "parser_native_pages length mismatch"
        )

    # --------------------------------------------------------
    # Normalization
    # --------------------------------------------------------

    started = perf_counter()

    normalized = normalize_pages(
        page_texts,
        normalization_config,
    )

    normalization_seconds = (
        perf_counter() - started
    )

    # --------------------------------------------------------
    # Common metrics
    # --------------------------------------------------------

    started = perf_counter()

    raw_noise = analyze_noise(
        normalized.raw_markdown,
        page_texts=page_texts,
        short_line_threshold=int(
            normalization_config[
                "short_line_character_threshold"
            ]
        ),
        minimum_repeated_page_fraction=float(
            normalization_config[
                "minimum_repeated_page_fraction"
            ]
        ),
        minimum_repeated_page_count=int(
            normalization_config[
                "minimum_repeated_page_count"
            ]
        ),
    )

    clean_noise = analyze_noise(
        normalized.clean_markdown,
        page_texts=(
            normalized.clean_page_texts
        ),
        short_line_threshold=int(
            normalization_config[
                "short_line_character_threshold"
            ]
        ),
        minimum_repeated_page_fraction=float(
            normalization_config[
                "minimum_repeated_page_fraction"
            ]
        ),
        minimum_repeated_page_count=int(
            normalization_config[
                "minimum_repeated_page_count"
            ]
        ),
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

    token_metrics = build_token_metrics(
        raw_text=(
            normalized.raw_markdown
        ),
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
        perf_counter() - started
    )

    # --------------------------------------------------------
    # Artifacts
    # --------------------------------------------------------

    started = perf_counter()

    paths.raw_markdown.write_text(
        normalized.raw_markdown,
        encoding="utf-8",
    )

    paths.clean_markdown.write_text(
        normalized.clean_markdown,
        encoding="utf-8",
    )

    write_jsonl(
        paths.removed_content_jsonl,
        normalized.removed_records,
    )

    records = []

    for index in range(
        page_count
    ):
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
                    page_texts[index]
                ),

                "clean_markdown": (
                    normalized.clean_page_texts[
                        index
                    ]
                ),

                "parser_elements": (
                    parser_page_elements[
                        index
                    ]
                ),

                "parser_native": (
                    parser_native_pages[
                        index
                    ]
                ),
            }
        )

    write_jsonl(
        paths.document_jsonl,
        records,
    )

    write_seconds = (
        perf_counter() - started
    )

    raw_bytes = (
        paths.raw_markdown
        .stat()
        .st_size
    )

    clean_bytes = (
        paths.clean_markdown
        .stat()
        .st_size
    )

    jsonl_bytes = (
        paths.document_jsonl
        .stat()
        .st_size
    )

    removed_bytes = (
        paths.removed_content_jsonl
        .stat()
        .st_size
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

        "output": {
            "raw_markdown": str(
                paths.raw_markdown
            ),

            "clean_markdown": str(
                paths.clean_markdown
            ),

            "document_jsonl": str(
                paths.document_jsonl
            ),

            "removed_content_jsonl": str(
                paths.removed_content_jsonl
            ),

            "raw_markdown_bytes": (
                raw_bytes
            ),

            "clean_markdown_bytes": (
                clean_bytes
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
