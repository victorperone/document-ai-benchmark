from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.summary_io import (  # noqa: E402
    SummaryInputError,
    load_metrics_by_document,
    require_same_documents,
)

PYMUPDF_PROFILE = "native"
DOCLING_PROFILE = "native"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Build PyMuPDF vs Docling comparison "
            "(native profile, OCR disabled)."
        )
    )

    p.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "outputs",
        metavar="DIR",
        help="Root of parser outputs. Default: <repo>/outputs.",
    )

    p.add_argument(
        "--metrics-root",
        type=Path,
        default=ROOT / "metrics",
        metavar="DIR",
        help="Root for comparison outputs. Default: <repo>/metrics.",
    )

    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        pymupdf = load_metrics_by_document(
            args.output_root,
            "pymupdf",
            PYMUPDF_PROFILE,
        )
        docling = load_metrics_by_document(
            args.output_root,
            "docling",
            DOCLING_PROFILE,
        )
    except SummaryInputError as exc:
        raise SystemExit(str(exc))

    if not pymupdf:
        raise SystemExit(
            f"No metrics found for pymupdf/{PYMUPDF_PROFILE} "
            f"under {args.output_root}"
        )

    if not docling:
        raise SystemExit(
            f"No metrics found for docling/{DOCLING_PROFILE} "
            f"under {args.output_root}"
        )

    try:
        documents = require_same_documents(
            {
                f"pymupdf/{PYMUPDF_PROFILE}": pymupdf,
                f"docling/{DOCLING_PROFILE}": docling,
            }
        )
    except SummaryInputError as exc:
        raise SystemExit(str(exc))

    documents = sorted(
        documents,
        key=lambda name: pymupdf[name]["document"]["pages"],
    )

    rows = []

    for document in documents:
        py = pymupdf[document]
        dc = docling[document]

        py_time = py["processing"]["pipeline_seconds"]
        dc_time = dc["processing"]["pipeline_seconds"]

        py_tokens = py["tokens"]["reference"]["clean_markdown_tokens"]
        dc_tokens = dc["tokens"]["reference"]["clean_markdown_tokens"]

        slowdown = (
            dc_time / py_time
            if py_time > 0
            else 0
        )

        token_delta = (
            ((dc_tokens - py_tokens) / py_tokens) * 100
            if py_tokens > 0
            else 0
        )

        dc_parser_output = dc["content_elements"]["parser_output"]

        rows.append(
            {
                "document": document,
                "pages": py["document"]["pages"],
                "pymupdf_seconds": round(py_time, 3),
                "docling_seconds": round(dc_time, 3),
                "docling_slowdown_x": round(slowdown, 2),
                "pymupdf_ram_mb": py["resources"]["peak_rss_mb"],
                "docling_ram_mb": dc["resources"]["peak_rss_mb"],
                "pymupdf_tokens": py_tokens,
                "docling_tokens": dc_tokens,
                "token_delta_percent": round(token_delta, 2),
                # tables_detected and images_detected from content_elements.parser_output
                "docling_tables": dc_parser_output["tables_detected"],
                "docling_pictures": dc_parser_output["images_detected"],
            }
        )

    args.metrics_root.mkdir(parents=True, exist_ok=True)

    csv_path = args.metrics_root / "parser_comparison.csv"
    markdown_path = args.metrics_root / "parser_comparison.md"

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Parser Comparison",
        "",
        "Native PDF baseline with OCR disabled.",
        "",
        f"PyMuPDF profile: `{PYMUPDF_PROFILE}`",
        f"Docling profile: `{DOCLING_PROFILE}`",
        "",
        "| Document | Pages | PyMuPDF s | Docling s | Docling Slowdown | PyMuPDF RAM MB | Docling RAM MB | PyMuPDF Tokens | Docling Tokens | Token Delta | Tables | Pictures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        lines.append(
            "| "
            f"{row['document']} | "
            f"{row['pages']} | "
            f"{row['pymupdf_seconds']} | "
            f"{row['docling_seconds']} | "
            f"{row['docling_slowdown_x']}x | "
            f"{row['pymupdf_ram_mb']} | "
            f"{row['docling_ram_mb']} | "
            f"{row['pymupdf_tokens']} | "
            f"{row['docling_tokens']} | "
            f"{row['token_delta_percent']}% | "
            f"{row['docling_tables']} | "
            f"{row['docling_pictures']} |"
        )

    markdown_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(f"Documents compared: {len(rows)}")
    print(f"CSV:      {csv_path}")
    print(f"Markdown: {markdown_path}")


if __name__ == "__main__":
    main()
