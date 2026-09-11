"""Text noise and quality heuristics for Markdown content.

Computes character-level ratios (whitespace, non-alphanumeric, replacement
characters, control characters), duplicate line statistics, short-line ratios,
and—when per-page texts are provided—repeated cross-page margin line
detection.  Results are stored in ``metrics.json`` under ``heuristics``.
"""

from __future__ import annotations

import math
import re
from collections import Counter


LINE_END_HYPHEN_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ]-$"
)


def _normalize_line(
    line: str,
) -> str:
    """Collapse internal whitespace and casefold a single line for comparison.

    Args:
        line: A single text line (may have leading/trailing whitespace).

    Returns:
        Lowercased string with all whitespace runs collapsed to a single space.
    """
    return " ".join(
        line.strip().split()
    ).casefold()


def _contains_meaningful_text(
    text: str,
) -> bool:
    """Return ``True`` if *text* contains at least one alphanumeric character.

    Args:
        text: Any string.

    Returns:
        ``True`` when the text has content beyond whitespace and punctuation.
    """
    return any(
        character.isalnum()
        for character in text
    )


def analyze_noise(
    text: str,
    *,
    page_texts: list[str] | None = None,
    short_line_threshold: int = 20,
    minimum_repeated_page_fraction: float = 0.30,
    minimum_repeated_page_count: int = 3,
) -> dict[str, object]:
    """Compute noise and quality heuristics for a Markdown text string.

    When *page_texts* is supplied, cross-page repeated-line detection is also
    performed: lines that appear on at least *minimum_repeated_page_count*
    pages (or the fraction threshold, whichever is larger) are counted as
    repeated margin text.

    Args:
        text: Full document text to analyse.
        page_texts: Per-page text strings used for the repeated-line
            analysis.  ``None`` disables that analysis.
        short_line_threshold: A non-empty line shorter than this many
            characters counts as a "short line".
        minimum_repeated_page_fraction: Minimum fraction of pages a line
            must appear on to qualify as a repeated margin line.
        minimum_repeated_page_count: Absolute minimum page count for the
            repeated-line threshold (takes precedence over the fraction when
            it is larger).

    Returns:
        Dict with keys ``total_characters``, ``total_lines``,
        ``non_empty_lines``, ``whitespace_ratio``,
        ``non_alphanumeric_ratio``, ``empty_lines``, ``empty_pages``,
        ``replacement_character_ratio``, ``control_character_ratio``,
        ``duplicate_line_ratio``, ``repeated_line_ratio``,
        ``repeated_unique_lines``, ``short_line_ratio``,
        ``short_line_character_threshold``, and
        ``line_end_hyphenation_count``.
    """
    total_characters = len(text)

    if total_characters == 0:
        whitespace_ratio = 0.0
        non_alphanumeric_ratio = 0.0
        replacement_ratio = 0.0
        control_ratio = 0.0
    else:
        whitespace_count = sum(
            character.isspace()
            for character in text
        )

        non_alphanumeric_count = sum(
            (
                not character.isalnum()
                and not character.isspace()
            )
            for character in text
        )

        replacement_count = text.count(
            "\ufffd"
        )

        control_count = sum(
            (
                ord(character) < 32
                and character
                not in {
                    "\n",
                    "\r",
                    "\t",
                }
            )
            for character in text
        )

        whitespace_ratio = (
            whitespace_count
            / total_characters
        )

        non_alphanumeric_ratio = (
            non_alphanumeric_count
            / total_characters
        )

        replacement_ratio = (
            replacement_count
            / total_characters
        )

        control_ratio = (
            control_count
            / total_characters
        )

    lines = text.splitlines()

    empty_lines = sum(
        not line.strip()
        for line in lines
    )

    non_empty_lines = [
        line
        for line in lines
        if line.strip()
    ]

    normalized_lines = [
        _normalize_line(line)
        for line in non_empty_lines
    ]

    line_counts = Counter(
        normalized_lines
    )

    duplicate_occurrences = sum(
        max(count - 1, 0)
        for count in line_counts.values()
    )

    duplicate_line_ratio = (
        duplicate_occurrences
        / len(normalized_lines)
        if normalized_lines
        else 0.0
    )

    short_lines = sum(
        len(line.strip())
        < short_line_threshold
        for line in non_empty_lines
    )

    short_line_ratio = (
        short_lines
        / len(non_empty_lines)
        if non_empty_lines
        else 0.0
    )

    line_end_hyphenation_count = sum(
        bool(
            LINE_END_HYPHEN_RE.search(
                line.rstrip()
            )
        )
        for line in non_empty_lines
    )

    empty_pages: int | None = None
    repeated_line_ratio: float | None = None
    repeated_unique_lines: int | None = None

    if page_texts is not None:
        empty_pages = sum(
            not _contains_meaningful_text(
                page
            )
            for page in page_texts
        )

        page_count = len(
            page_texts
        )

        required_pages = max(
            minimum_repeated_page_count,
            math.ceil(
                page_count
                * minimum_repeated_page_fraction
            ),
        )

        line_to_pages: dict[
            str,
            set[int],
        ] = {}

        total_page_line_occurrences = 0

        for page_index, page in enumerate(
            page_texts
        ):
            page_lines = [
                _normalize_line(line)
                for line in page.splitlines()
                if line.strip()
            ]

            total_page_line_occurrences += (
                len(page_lines)
            )

            for normalized_line in set(
                page_lines
            ):
                line_to_pages.setdefault(
                    normalized_line,
                    set(),
                ).add(page_index)

        repeated_lines = {
            line
            for line, pages in (
                line_to_pages.items()
            )
            if len(pages) >= required_pages
        }

        repeated_unique_lines = len(
            repeated_lines
        )

        repeated_occurrences = 0

        for page in page_texts:
            for line in page.splitlines():
                if (
                    line.strip()
                    and _normalize_line(
                        line
                    )
                    in repeated_lines
                ):
                    repeated_occurrences += 1

        repeated_line_ratio = (
            repeated_occurrences
            / total_page_line_occurrences
            if total_page_line_occurrences
            else 0.0
        )

    return {
        "total_characters": (
            total_characters
        ),

        "total_lines": len(
            lines
        ),

        "non_empty_lines": len(
            non_empty_lines
        ),

        "whitespace_ratio": round(
            whitespace_ratio,
            6,
        ),

        "non_alphanumeric_ratio": round(
            non_alphanumeric_ratio,
            6,
        ),

        "empty_lines": int(
            empty_lines
        ),

        "empty_pages": (
            empty_pages
        ),

        "replacement_character_ratio": round(
            replacement_ratio,
            8,
        ),

        "control_character_ratio": round(
            control_ratio,
            8,
        ),

        "duplicate_line_ratio": round(
            duplicate_line_ratio,
            6,
        ),

        "repeated_line_ratio": (
            round(
                repeated_line_ratio,
                6,
            )
            if repeated_line_ratio
            is not None
            else None
        ),

        "repeated_unique_lines": (
            repeated_unique_lines
        ),

        "short_line_ratio": round(
            short_line_ratio,
            6,
        ),

        "short_line_character_threshold": (
            short_line_threshold
        ),

        "line_end_hyphenation_count": int(
            line_end_hyphenation_count
        ),
    }
