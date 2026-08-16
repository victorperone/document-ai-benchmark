from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate repeated header/footer cleanup "
            "for a canonical Benchmark v2 output."
        )
    )

    parser.add_argument(
        "--ground-truth",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--fixture",
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help=(
            "Parser/profile directory containing "
            "document.jsonl and removed_content.jsonl."
        ),
    )

    return parser.parse_args()


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(
            f"Required file not found: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def load_jsonl(
    path: Path,
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(
            f"Required file not found: {path}"
        )

    return [
        json.loads(line)
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def require(
    mapping: dict[str, Any],
    key: str,
    context: str,
) -> Any:
    if key not in mapping:
        raise RuntimeError(
            f"Missing {context}.{key}. "
            f"Available keys: "
            f"{sorted(mapping.keys())}"
        )

    return mapping[key]


def normalize_line(
    text: str,
) -> str:
    value = unicodedata.normalize(
        "NFKC",
        text,
    )

    value = value.casefold()

    value = re.sub(
        r"[*_#>`|]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def levenshtein(
    left: str,
    right: str,
) -> int:
    if len(left) < len(right):
        left, right = (
            right,
            left,
        )

    previous = list(
        range(
            len(right) + 1
        )
    )

    for row_index, left_char in enumerate(
        left,
        start=1,
    ):
        current = [
            row_index
        ]

        for column_index, right_char in enumerate(
            right,
            start=1,
        ):
            current.append(
                min(
                    current[
                        column_index - 1
                    ]
                    + 1,
                    previous[
                        column_index
                    ]
                    + 1,
                    previous[
                        column_index - 1
                    ]
                    + (
                        left_char
                        != right_char
                    ),
                )
            )

        previous = current

    return previous[-1]


def similarity(
    left: str,
    right: str,
) -> float:
    left = normalize_line(
        left
    )

    right = normalize_line(
        right
    )

    maximum = max(
        len(left),
        len(right),
    )

    if maximum == 0:
        return 1.0

    return (
        1.0
        - levenshtein(
            left,
            right,
        )
        / maximum
    )


def nonempty_lines(
    text: str,
) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]


def best_edge_match(
    text: str,
    expected: str,
    *,
    from_start: bool,
    candidate_lines: int = 6,
) -> tuple[
    float,
    str | None,
]:
    lines = nonempty_lines(
        text
    )

    candidates = (
        lines[
            :candidate_lines
        ]
        if from_start
        else lines[
            -candidate_lines:
        ]
    )

    if not candidates:
        return (
            0.0,
            None,
        )

    scored = [
        (
            similarity(
                candidate,
                expected,
            ),
            candidate,
        )
        for candidate in candidates
    ]

    return max(
        scored,
        key=lambda item: item[0],
    )


def main() -> None:
    args = parse_args()

    ground_truth = load_json(
        args.ground_truth
    )

    fixtures = require(
        ground_truth,
        "fixtures",
        "ground_truth",
    )

    if args.fixture not in fixtures:
        raise RuntimeError(
            f"Fixture {args.fixture!r} "
            "not present in ground truth. "
            f"Available fixtures: "
            f"{sorted(fixtures.keys())}"
        )

    fixture = fixtures[
        args.fixture
    ]

    ground_pages = require(
        fixture,
        "pages",
        f"fixtures.{args.fixture}",
    )

    records = load_jsonl(
        args.output_dir
        / "document.jsonl"
    )

    removed_path = (
        args.output_dir
        / "removed_content.jsonl"
    )

    removed_records = (
        load_jsonl(
            removed_path
        )
        if removed_path.is_file()
        else []
    )

    if len(records) != len(
        ground_pages
    ):
        raise RuntimeError(
            "Page-count mismatch. "
            f"Ground truth: "
            f"{len(ground_pages)}; "
            f"output: {len(records)}."
        )

    ground_by_page = {
        int(
            require(
                page,
                "page_number",
                "ground_truth.page",
            )
        ): page
        for page in ground_pages
    }

    records_by_page = {
        int(
            require(
                record,
                "page_number",
                "document.jsonl",
            )
        ): record
        for record in records
    }

    if (
        set(ground_by_page)
        != set(records_by_page)
    ):
        raise RuntimeError(
            "Page-number mismatch between "
            "ground truth and document.jsonl."
        )

    print("=" * 96)
    print(
        "HEADER / FOOTER OCR REGRESSION"
    )
    print("=" * 96)

    raw_header_scores: list[
        float
    ] = []

    clean_header_scores: list[
        float
    ] = []

    raw_footer_scores: list[
        float
    ] = []

    clean_footer_scores: list[
        float
    ] = []

    missing_identifiers: list[
        str
    ] = []

    for page_number in sorted(
        ground_by_page
    ):
        truth = ground_by_page[
            page_number
        ]

        record = records_by_page[
            page_number
        ]

        raw = str(
            require(
                record,
                "raw_markdown",
                "document.jsonl",
            )
        )

        clean = str(
            require(
                record,
                "clean_markdown",
                "document.jsonl",
            )
        )

        expected_header = str(
            require(
                truth,
                "expected_header",
                "ground_truth.page",
            )
        )

        expected_footer = str(
            require(
                truth,
                "expected_footer",
                "ground_truth.page",
            )
        )

        identifier = (
            f"REGRESSAO-"
            f"{page_number:02d}-2026"
        )

        raw_header = (
            best_edge_match(
                raw,
                expected_header,
                from_start=True,
            )
        )

        clean_header = (
            best_edge_match(
                clean,
                expected_header,
                from_start=True,
            )
        )

        raw_footer = (
            best_edge_match(
                raw,
                expected_footer,
                from_start=False,
            )
        )

        clean_footer = (
            best_edge_match(
                clean,
                expected_footer,
                from_start=False,
            )
        )

        raw_header_scores.append(
            raw_header[0]
        )

        clean_header_scores.append(
            clean_header[0]
        )

        raw_footer_scores.append(
            raw_footer[0]
        )

        clean_footer_scores.append(
            clean_footer[0]
        )

        identifier_present = (
            normalize_line(
                identifier
            )
            in normalize_line(
                clean
            )
        )

        if not identifier_present:
            missing_identifiers.append(
                identifier
            )

        print()
        print(
            f"PAGE {page_number}"
        )

        print(
            "  raw header similarity:   "
            f"{raw_header[0]:.3f}"
        )

        print(
            "  clean header similarity: "
            f"{clean_header[0]:.3f}"
        )

        print(
            "  raw footer similarity:   "
            f"{raw_footer[0]:.3f}"
        )

        print(
            "  clean footer similarity: "
            f"{clean_footer[0]:.3f}"
        )

        print(
            "  body ID preserved:       "
            f"{identifier_present}"
        )

        print(
            "  raw header candidate:    "
            f"{raw_header[1]!r}"
        )

        print(
            "  raw footer candidate:    "
            f"{raw_footer[1]!r}"
        )

    average = (
        lambda values:
        sum(values)
        / len(values)
        if values
        else 0.0
    )

    print()
    print("=" * 96)
    print("SUMMARY")
    print("=" * 96)

    print(
        "Average raw header similarity:   "
        f"{average(raw_header_scores):.3f}"
    )

    print(
        "Average clean header similarity: "
        f"{average(clean_header_scores):.3f}"
    )

    print(
        "Average raw footer similarity:   "
        f"{average(raw_footer_scores):.3f}"
    )

    print(
        "Average clean footer similarity: "
        f"{average(clean_footer_scores):.3f}"
    )

    print(
        "Missing unique body identifiers:",
        missing_identifiers,
    )

    print(
        "Removed-content records:",
        len(
            removed_records
        ),
    )

    if removed_records:
        print(
            "Removed-content keys:",
            sorted(
                removed_records[
                    0
                ].keys()
            ),
        )

        type_counts: dict[
            str,
            int,
        ] = {}

        for record in removed_records:
            record_type = str(
                record.get(
                    "type",
                    "<unknown>",
                )
            )

            type_counts[
                record_type
            ] = (
                type_counts.get(
                    record_type,
                    0,
                )
                + 1
            )

        print(
            "Removed-content types:",
            type_counts,
        )

    print("=" * 96)

    if missing_identifiers:
        print(
            "RESULT: BODY CONTENT "
            "REQUIRES INSPECTION"
        )

        sys.exit(
            2
        )

    print(
        "RESULT: UNIQUE BODY CONTENT "
        "PRESERVED"
    )


if __name__ == "__main__":
    main()
