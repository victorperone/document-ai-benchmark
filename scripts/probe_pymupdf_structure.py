from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pymupdf
import pymupdf4llm


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect PyMuPDF4LLM page_chunks "
            "with Layout enabled."
        )
    )

    parser.add_argument(
        "--input",
        required=True,
        type=Path,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.is_file():
        raise SystemExit(
            f"Input not found: {args.input}"
        )

    pymupdf4llm.use_layout(True)

    document = pymupdf.open(
        args.input
    )

    try:
        chunks = pymupdf4llm.to_markdown(
            document,
            page_chunks=True,
            use_ocr=False,
            header=True,
            footer=True,
            write_images=False,
            embed_images=False,
            show_progress=False,
        )

    finally:
        document.close()

    if not isinstance(chunks, list):
        raise RuntimeError(
            "Expected list from page_chunks=True"
        )

    if not chunks:
        raise RuntimeError(
            "No page chunks returned."
        )

    print("=" * 72)
    print("PYMUPDF STRUCTURAL PROBE")
    print("=" * 72)

    print(
        f"Document:       {args.input.name}"
    )

    print(
        f"Chunks:         {len(chunks)}"
    )

    first_chunk = chunks[0]

    print(
        "Chunk keys:     "
        + ", ".join(
            sorted(first_chunk.keys())
        )
    )

    page_boxes_pages = sum(
        isinstance(
            chunk.get("page_boxes"),
            list,
        )
        for chunk in chunks
    )

    print(
        f"page_boxes:     "
        f"{page_boxes_pages}/{len(chunks)} pages"
    )

    for legacy_key in (
        "tables",
        "images",
        "graphics",
    ):
        key_count = sum(
            legacy_key in chunk
            for chunk in chunks
        )

        print(
            f"'{legacy_key}' key: "
            f"{key_count}/{len(chunks)}"
        )

    class_counts = Counter()

    total_boxes = 0
    first_box = None

    per_page_box_counts = []

    for page_number, chunk in enumerate(
        chunks,
        start=1,
    ):
        boxes = chunk.get(
            "page_boxes",
            [],
        )

        if not isinstance(boxes, list):
            boxes = []

        per_page_box_counts.append(
            len(boxes)
        )

        for box in boxes:
            if not isinstance(box, dict):
                continue

            total_boxes += 1

            if first_box is None:
                first_box = box

            box_class = str(
                box.get(
                    "class",
                    "<missing>",
                )
            )

            class_counts[
                box_class
            ] += 1

    print(
        f"Total boxes:    {total_boxes}"
    )

    if first_box is not None:
        print(
            "Box keys:       "
            + ", ".join(
                sorted(first_box.keys())
            )
        )

    print()
    print("BOX CLASS COUNTS")
    print("-" * 72)

    if class_counts:
        for name, count in sorted(
            class_counts.items()
        ):
            print(
                f"{name:<24} {count}"
            )
    else:
        print("<none>")

    metadata_pages = []

    for chunk in chunks:
        metadata = chunk.get(
            "metadata",
            {}
        )

        if isinstance(metadata, dict):
            metadata_pages.append(
                metadata.get(
                    "page_number"
                )
            )

    print()
    print(
        "Metadata first page:",
        (
            metadata_pages[0]
            if metadata_pages
            else None
        ),
    )

    print(
        "Metadata last page:",
        (
            metadata_pages[-1]
            if metadata_pages
            else None
        ),
    )

    print(
        "Min boxes/page:",
        min(per_page_box_counts)
        if per_page_box_counts
        else 0,
    )

    print(
        "Max boxes/page:",
        max(per_page_box_counts)
        if per_page_box_counts
        else 0,
    )

    print()
    print("=" * 72)
    print("STRUCTURAL PROBE: OK")
    print("=" * 72)


if __name__ == "__main__":
    main()
