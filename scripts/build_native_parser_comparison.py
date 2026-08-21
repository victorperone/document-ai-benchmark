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

PROFILES: dict[str, str] = {
    "pymupdf": "native",
    "docling": "native",
    "mineru": "txt",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Build three-parser native comparison "
            "(PyMuPDF native, Docling native, MinerU txt)."
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


def safe_ratio(
    numerator: float,
    denominator: float,
) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def main() -> None:
    args = parse_args()

    all_metrics: dict[str, dict[str, dict]] = {}

    try:
        for parser, profile in PROFILES.items():
            all_metrics[parser] = load_metrics_by_document(
                args.output_root,
                parser,
                profile,
            )
    except SummaryInputError as exc:
        raise SystemExit(str(exc))

    for parser, profile in PROFILES.items():
        if not all_metrics[parser]:
            raise SystemExit(
                f"No metrics found for {parser}/{profile} "
                f"under {args.output_root}"
            )

    try:
        documents = require_same_documents(
            {
                f"{parser}/{profile}": all_metrics[parser]
                for parser, profile in PROFILES.items()
            }
        )
    except SummaryInputError as exc:
        raise SystemExit(str(exc))

    documents = sorted(
        documents,
        key=lambda filename: (
            all_metrics["pymupdf"][filename]["document"]["pages"]
        ),
    )

    rows = []

    for document in documents:
        py = all_metrics["pymupdf"][document]
        dc = all_metrics["docling"][document]
        mu = all_metrics["mineru"][document]

        py_time = py["processing"]["pipeline_seconds"]
        dc_time = dc["processing"]["pipeline_seconds"]
        mu_time = mu["processing"]["pipeline_seconds"]

        py_ram = py["resources"]["peak_rss_mb"]
        dc_ram = dc["resources"]["peak_rss_mb"]
        mu_ram = mu["resources"]["peak_rss_mb"]

        py_tokens = py["tokens"]["reference"]["clean_markdown_tokens"]
        dc_tokens = dc["tokens"]["reference"]["clean_markdown_tokens"]
        mu_tokens = mu["tokens"]["reference"]["clean_markdown_tokens"]

        dc_parser_output = dc["content_elements"]["parser_output"]
        mu_parser_output = mu["content_elements"]["parser_output"]

        rows.append(
            {
                "document": document,
                "pages": py["document"]["pages"],

                "pymupdf_seconds": round(py_time, 3),
                "docling_seconds": round(dc_time, 3),
                "mineru_seconds": round(mu_time, 3),

                "docling_vs_pymupdf_x": round(
                    safe_ratio(dc_time, py_time), 2
                ),
                "mineru_vs_pymupdf_x": round(
                    safe_ratio(mu_time, py_time), 2
                ),
                "mineru_vs_docling_x": round(
                    safe_ratio(mu_time, dc_time), 2
                ),

                "pymupdf_ram_mb": py_ram,
                "docling_ram_mb": dc_ram,
                "mineru_ram_mb": mu_ram,

                "pymupdf_tokens": py_tokens,
                "docling_tokens": dc_tokens,
                "mineru_tokens": mu_tokens,

                # tables_detected and images_detected from content_elements.parser_output
                "docling_tables": dc_parser_output["tables_detected"],
                "docling_pictures": dc_parser_output["images_detected"],

                "mineru_tables": mu_parser_output["tables_detected"],
                "mineru_pictures": mu_parser_output["images_detected"],
                # charts_detected is None in MinerU; preserve None (not measured).
                "mineru_charts": mu_parser_output["charts_detected"],
            }
        )

    args.metrics_root.mkdir(parents=True, exist_ok=True)

    csv_path = args.metrics_root / "native_parser_comparison.csv"
    markdown_path = args.metrics_root / "native_parser_comparison.md"

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)

    total_py = sum(row["pymupdf_seconds"] for row in rows)
    total_dc = sum(row["docling_seconds"] for row in rows)
    total_mu = sum(row["mineru_seconds"] for row in rows)

    lines = [
        "# Native Parser Comparison",
        "",
        "CPU benchmark with OCR disabled.",
        "",
        f"PyMuPDF profile: `{PROFILES['pymupdf']}`",
        f"Docling profile: `{PROFILES['docling']}`",
        f"MinerU profile: `{PROFILES['mineru']}`",
        "",
        "> CPU utilization is intentionally omitted from "
        "cross-parser comparison because MinerU uses the "
        "corrected process-tree monitor v2 while the earlier "
        "PyMuPDF4LLM and Docling native runs used monitor v1.",
        "",
        "> Table, picture, image, and chart counts are parser-specific "
        "classifications and must not be interpreted as directly "
        "equivalent quality metrics.",
        "",
        "## Performance",
        "",
        "| Document | Pages | PyMuPDF s | Docling s | MinerU s | "
        "Docling / PyMuPDF | MinerU / PyMuPDF | MinerU / Docling |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        lines.append(
            "| "
            f"{row['document']} | "
            f"{row['pages']} | "
            f"{row['pymupdf_seconds']} | "
            f"{row['docling_seconds']} | "
            f"{row['mineru_seconds']} | "
            f"{row['docling_vs_pymupdf_x']}x | "
            f"{row['mineru_vs_pymupdf_x']}x | "
            f"{row['mineru_vs_docling_x']}x |"
        )

    lines.extend(
        [
            "",
            "## Peak Memory",
            "",
            "| Document | PyMuPDF MB | Docling MB | MinerU MB |",
            "|---|---:|---:|---:|",
        ]
    )

    for row in rows:
        lines.append(
            "| "
            f"{row['document']} | "
            f"{row['pymupdf_ram_mb']} | "
            f"{row['docling_ram_mb']} | "
            f"{row['mineru_ram_mb']} |"
        )

    lines.extend(
        [
            "",
            "## Markdown Tokens",
            "",
            "| Document | PyMuPDF | Docling | MinerU |",
            "|---|---:|---:|---:|",
        ]
    )

    for row in rows:
        lines.append(
            "| "
            f"{row['document']} | "
            f"{row['pymupdf_tokens']} | "
            f"{row['docling_tokens']} | "
            f"{row['mineru_tokens']} |"
        )

    lines.extend(
        [
            "",
            "## Structural Detection",
            "",
            "| Document | Docling Tables | Docling Pictures | "
            "MinerU Tables | MinerU Pictures | MinerU Charts |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )

    for row in rows:
        charts_cell = (
            str(row["mineru_charts"])
            if row["mineru_charts"] is not None
            else "N/A"
        )
        lines.append(
            "| "
            f"{row['document']} | "
            f"{row['docling_tables']} | "
            f"{row['docling_pictures']} | "
            f"{row['mineru_tables']} | "
            f"{row['mineru_pictures']} | "
            f"{charts_cell} |"
        )

    lines.extend(
        [
            "",
            "## Aggregate Runtime",
            "",
            f"- PyMuPDF4LLM: {total_py:.3f} s",
            f"- Docling: {total_dc:.3f} s",
            f"- MinerU: {total_mu:.3f} s",
            f"- Docling / PyMuPDF4LLM: "
            f"{safe_ratio(total_dc, total_py):.2f}x",
            f"- MinerU / PyMuPDF4LLM: "
            f"{safe_ratio(total_mu, total_py):.2f}x",
            f"- MinerU / Docling: "
            f"{safe_ratio(total_mu, total_dc):.2f}x",
        ]
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
