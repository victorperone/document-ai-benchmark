from __future__ import annotations

import csv
import json
from pathlib import Path


OUTPUT_ROOT = Path("/outputs")
METRICS_ROOT = Path("/metrics")

CSV_PATH = METRICS_ROOT / "parser_comparison.csv"
MARKDOWN_PATH = METRICS_ROOT / "parser_comparison.md"


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


def main() -> None:
    pymupdf = load_metrics("pymupdf")
    docling = load_metrics("docling")

    documents = sorted(
        set(pymupdf) & set(docling),
        key=lambda name: pymupdf[name]["document"]["pages"],
    )

    if not documents:
        raise SystemExit(
            "No matching benchmark documents found."
        )

    rows = []

    for document in documents:
        py = pymupdf[document]
        dc = docling[document]

        py_time = py["processing"]["pipeline_seconds"]
        dc_time = dc["processing"]["pipeline_seconds"]

        py_tokens = py["tokens"]["full_markdown_tokens"]
        dc_tokens = dc["tokens"]["full_markdown_tokens"]

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
                "docling_tables": dc["content"]["tables_detected"],
                "docling_pictures": dc["content"]["pictures_detected"],
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
        "# Parser Comparison",
        "",
        "Native PDF baseline with OCR disabled.",
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

    MARKDOWN_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(f"Documents compared: {len(rows)}")
    print(f"CSV:      {CSV_PATH}")
    print(f"Markdown: {MARKDOWN_PATH}")


if __name__ == "__main__":
    main()
