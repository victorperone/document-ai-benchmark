from __future__ import annotations

import csv
import json
from pathlib import Path


OUTPUT_ROOT = Path("/outputs")
METRICS_ROOT = Path("/metrics")

CSV_PATH = METRICS_ROOT / "native_parser_comparison.csv"
MARKDOWN_PATH = METRICS_ROOT / "native_parser_comparison.md"

PARSERS = (
    "pymupdf",
    "docling",
    "mineru",
)


def load_metrics(parser: str) -> dict[str, dict]:
    results = {}

    for path in sorted(
        (OUTPUT_ROOT / parser).glob("*/metrics.json")
    ):
        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        results[data["document"]["file"]] = data

    return results


def safe_ratio(
    numerator: float,
    denominator: float,
) -> float:
    if denominator == 0:
        return 0.0

    return numerator / denominator


def main() -> None:
    all_metrics = {
        parser: load_metrics(parser)
        for parser in PARSERS
    }

    common_documents = set(
        all_metrics[PARSERS[0]]
    )

    for parser in PARSERS[1:]:
        common_documents &= set(
            all_metrics[parser]
        )

    if not common_documents:
        raise SystemExit(
            "No documents shared by all parsers."
        )

    documents = sorted(
        common_documents,
        key=lambda filename: (
            all_metrics["pymupdf"][filename]
            ["document"]["pages"]
        ),
    )

    rows = []

    for document in documents:
        py = all_metrics["pymupdf"][document]
        dc = all_metrics["docling"][document]
        mu = all_metrics["mineru"][document]

        py_time = py["processing"][
            "pipeline_seconds"
        ]
        dc_time = dc["processing"][
            "pipeline_seconds"
        ]
        mu_time = mu["processing"][
            "pipeline_seconds"
        ]

        py_ram = py["resources"]["peak_rss_mb"]
        dc_ram = dc["resources"]["peak_rss_mb"]
        mu_ram = mu["resources"]["peak_rss_mb"]

        py_tokens = py["tokens"][
            "full_markdown_tokens"
        ]
        dc_tokens = dc["tokens"][
            "full_markdown_tokens"
        ]
        mu_tokens = mu["tokens"][
            "full_markdown_tokens"
        ]

        rows.append(
            {
                "document": document,
                "pages": py["document"]["pages"],

                "pymupdf_seconds": round(
                    py_time,
                    3,
                ),
                "docling_seconds": round(
                    dc_time,
                    3,
                ),
                "mineru_seconds": round(
                    mu_time,
                    3,
                ),

                "docling_vs_pymupdf_x": round(
                    safe_ratio(
                        dc_time,
                        py_time,
                    ),
                    2,
                ),
                "mineru_vs_pymupdf_x": round(
                    safe_ratio(
                        mu_time,
                        py_time,
                    ),
                    2,
                ),
                "mineru_vs_docling_x": round(
                    safe_ratio(
                        mu_time,
                        dc_time,
                    ),
                    2,
                ),

                "pymupdf_ram_mb": py_ram,
                "docling_ram_mb": dc_ram,
                "mineru_ram_mb": mu_ram,

                "pymupdf_tokens": py_tokens,
                "docling_tokens": dc_tokens,
                "mineru_tokens": mu_tokens,

                "docling_tables": dc[
                    "content"
                ]["tables_detected"],
                "docling_pictures": dc[
                    "content"
                ]["pictures_detected"],

                "mineru_tables": mu[
                    "content"
                ]["tables_detected"],
                "mineru_pictures": mu[
                    "content"
                ]["pictures_detected"],
                "mineru_charts": mu[
                    "content"
                ]["charts_detected"],
            }
        )

    METRICS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    with CSV_PATH.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )

        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Native Parser Comparison",
        "",
        "CPU benchmark with OCR disabled.",
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
        lines.append(
            "| "
            f"{row['document']} | "
            f"{row['docling_tables']} | "
            f"{row['docling_pictures']} | "
            f"{row['mineru_tables']} | "
            f"{row['mineru_pictures']} | "
            f"{row['mineru_charts']} |"
        )

    total_py = sum(
        row["pymupdf_seconds"]
        for row in rows
    )
    total_dc = sum(
        row["docling_seconds"]
        for row in rows
    )
    total_mu = sum(
        row["mineru_seconds"]
        for row in rows
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

    MARKDOWN_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        f"Documents compared: {len(rows)}"
    )
    print(f"CSV:      {CSV_PATH}")
    print(f"Markdown: {MARKDOWN_PATH}")


if __name__ == "__main__":
    main()
