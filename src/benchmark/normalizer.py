from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


PAGE_NUMBER_ONLY_RE = re.compile(
    r"^\s*\d+\s*$"
)

PAGE_OF_RE = re.compile(
    r"""
    ^\s*
    (?:page\s*)?
    \d+
    \s*
    (?:
        of
        |
        /
    )
    \s*
    \d+
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class NormalizationResult:
    raw_markdown: str
    clean_markdown: str
    clean_page_texts: list[str]
    removed_records: list[
        dict[str, Any]
    ]


def _normalize_text(
    value: str,
) -> str:
    value = unicodedata.normalize(
        "NFKC",
        value,
    )

    return " ".join(
        value.strip().split()
    ).casefold()


def _candidate_key(
    line: str,
    *,
    normalize_page_numbers: bool,
) -> str:
    normalized = _normalize_text(
        line
    )

    if not normalized:
        return ""

    if normalize_page_numbers:
        if PAGE_NUMBER_ONLY_RE.match(
            normalized
        ):
            return "<page-number>"

        if PAGE_OF_RE.match(
            normalized
        ):
            return "<page-number>"

    return normalized


def _non_empty_line_indexes(
    lines: list[str],
) -> list[int]:
    return [
        index
        for index, line in enumerate(
            lines
        )
        if line.strip()
    ]


def _join_pages(
    pages: list[str],
) -> str:
    """
    Join page Markdown without inserting benchmark-owned
    page markers.

    Page provenance is stored in document.jsonl instead.
    This prevents artificial inflation of token metrics.
    """
    if not pages:
        return ""

    return (
        "\n\n".join(
            page.rstrip()
            for page in pages
        ).rstrip()
        + "\n"
    )


def normalize_pages(
    page_texts: list[str],
    config: dict[str, Any],
) -> NormalizationResult:
    cleanup_enabled = bool(
        config.get(
            "header_footer_cleanup",
            True,
        )
    )

    header_lines = int(
        config.get(
            "header_candidate_lines",
            3,
        )
    )

    footer_lines = int(
        config.get(
            "footer_candidate_lines",
            3,
        )
    )

    minimum_fraction = float(
        config.get(
            "minimum_repeated_page_fraction",
            0.30,
        )
    )

    minimum_count = int(
        config.get(
            "minimum_repeated_page_count",
            3,
        )
    )

    normalize_page_numbers = bool(
        config.get(
            "normalize_page_numbers",
            True,
        )
    )

    trim_outer_whitespace = bool(
        config.get(
            "trim_page_outer_whitespace",
            True,
        )
    )

    page_count = len(
        page_texts
    )

    required_pages = max(
        minimum_count,
        math.ceil(
            page_count
            * minimum_fraction
        ),
    )

    parsed_pages = [
        page.splitlines()
        for page in page_texts
    ]

    header_occurrences: dict[
        str,
        set[int],
    ] = {}

    footer_occurrences: dict[
        str,
        set[int],
    ] = {}

    header_positions: list[
        set[int]
    ] = []

    footer_positions: list[
        set[int]
    ] = []

    for page_index, lines in enumerate(
        parsed_pages
    ):
        non_empty = (
            _non_empty_line_indexes(
                lines
            )
        )

        header_indexes = set(
            non_empty[:header_lines]
        )

        footer_indexes = set(
            non_empty[-footer_lines:]
        )

        header_positions.append(
            header_indexes
        )

        footer_positions.append(
            footer_indexes
        )

        for line_index in header_indexes:
            key = _candidate_key(
                lines[line_index],
                normalize_page_numbers=(
                    normalize_page_numbers
                ),
            )

            if key:
                header_occurrences.setdefault(
                    key,
                    set(),
                ).add(page_index)

        for line_index in footer_indexes:
            key = _candidate_key(
                lines[line_index],
                normalize_page_numbers=(
                    normalize_page_numbers
                ),
            )

            if key:
                footer_occurrences.setdefault(
                    key,
                    set(),
                ).add(page_index)

    repeated_headers = {
        key: pages
        for key, pages
        in header_occurrences.items()
        if len(pages) >= required_pages
    }

    repeated_footers = {
        key: pages
        for key, pages
        in footer_occurrences.items()
        if len(pages) >= required_pages
    }

    removed_records: list[
        dict[str, Any]
    ] = []

    clean_pages: list[str] = []

    for page_index, lines in enumerate(
        parsed_pages
    ):
        remove_indexes: dict[
            int,
            tuple[str, str, set[int]],
        ] = {}

        if cleanup_enabled:
            for line_index in (
                header_positions[
                    page_index
                ]
            ):
                key = _candidate_key(
                    lines[line_index],
                    normalize_page_numbers=(
                        normalize_page_numbers
                    ),
                )

                if key in repeated_headers:
                    remove_indexes[
                        line_index
                    ] = (
                        "header",
                        key,
                        repeated_headers[key],
                    )

            for line_index in (
                footer_positions[
                    page_index
                ]
            ):
                key = _candidate_key(
                    lines[line_index],
                    normalize_page_numbers=(
                        normalize_page_numbers
                    ),
                )

                if key in repeated_footers:
                    remove_indexes.setdefault(
                        line_index,
                        (
                            "footer",
                            key,
                            repeated_footers[key],
                        ),
                    )

        clean_lines: list[str] = []

        for line_index, line in enumerate(
            lines
        ):
            removal = remove_indexes.get(
                line_index
            )

            if removal is None:
                clean_lines.append(
                    line
                )
                continue

            (
                record_type,
                key,
                observed_pages,
            ) = removal

            removed_records.append(
                {
                    "page_number": (
                        page_index + 1
                    ),

                    "line_index": (
                        line_index
                    ),

                    "type": (
                        record_type
                    ),

                    "text": line,

                    "normalized_key": (
                        key
                    ),

                    "reason": (
                        "repeated_page_margin_text"
                    ),

                    "pages_observed": len(
                        observed_pages
                    ),

                    "page_fraction": round(
                        len(observed_pages)
                        / page_count,
                        6,
                    )
                    if page_count
                    else 0.0,
                }
            )

        clean_page = "\n".join(
            clean_lines
        )

        if trim_outer_whitespace:
            clean_page = (
                clean_page.strip()
            )

        clean_pages.append(
            clean_page
        )

    return NormalizationResult(
        raw_markdown=_join_pages(
            page_texts
        ),

        clean_markdown=_join_pages(
            clean_pages
        ),

        clean_page_texts=(
            clean_pages
        ),

        removed_records=(
            removed_records
        ),
    )


def normalize_global_markdown(
    markdown: str,
    config: dict[str, Any],
) -> NormalizationResult:
    """Normalize one global Markdown stream without page-repetition logic.

    A parser that cannot prove page boundaries must not manufacture them just
    so header/footer heuristics can run. The ordinary whitespace policy still
    applies, but repeated page-margin detection is explicitly disabled.
    """
    global_config = dict(config)
    global_config["header_footer_cleanup"] = False
    return normalize_pages([markdown], global_config)
