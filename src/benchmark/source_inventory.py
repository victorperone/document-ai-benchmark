from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Any

import pymupdf

from src.benchmark.content_validation import inventory_requires_content


MB = 1024 * 1024


def calculate_sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def _meaningful_text(
    text: str,
) -> bool:
    return any(
        character.isalnum()
        for character in text
    )


def analyze_pdf_source(
    pdf_path: Path,
) -> dict[str, Any]:
    """
    Measure objective PDF properties.

    Semantic concepts such as tables, headings, lists,
    charts, diagrams, etc. are intentionally excluded.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.is_file():
        raise FileNotFoundError(
            pdf_path
        )

    started = perf_counter()

    document = pymupdf.open(
        pdf_path
    )

    pages: list[dict[str, Any]] = []

    total_native_characters = 0
    total_text_blocks = 0
    total_image_blocks = 0

    total_embedded_image_occurrences = 0
    unique_image_xrefs: set[int] = set()
    image_measurement_complete = True

    total_drawing_groups = 0
    drawing_measurement_complete = True

    pages_with_native_text = 0
    pages_without_native_text = 0
    pages_with_embedded_images = 0

    warnings: list[dict[str, Any]] = []

    try:
        for page_index in range(
            document.page_count
        ):
            page = document.load_page(
                page_index
            )

            text = page.get_text(
                "text"
            )

            native_characters = len(
                text
            )

            has_native_text = (
                _meaningful_text(text)
            )

            if has_native_text:
                pages_with_native_text += 1
            else:
                pages_without_native_text += 1

            total_native_characters += (
                native_characters
            )

            text_dict = page.get_text(
                "dict"
            )

            text_blocks = 0
            image_blocks = 0

            for block in text_dict.get(
                "blocks",
                [],
            ):
                block_type = block.get(
                    "type"
                )

                if block_type == 0:
                    text_blocks += 1

                elif block_type == 1:
                    image_blocks += 1

            total_text_blocks += (
                text_blocks
            )

            total_image_blocks += (
                image_blocks
            )

            try:
                images = page.get_images(
                    full=True
                )
            except Exception as exc:
                images = []
                image_measurement_complete = False

                warnings.append(
                    {
                        "page_number": (
                            page_index + 1
                        ),
                        "metric": (
                            "embedded_images"
                        ),
                        "error": (
                            type(exc).__name__
                        ),
                    }
                )

            image_occurrences = len(
                images
            )

            if image_occurrences > 0:
                pages_with_embedded_images += 1

            total_embedded_image_occurrences += (
                image_occurrences
            )

            for image in images:
                if not image:
                    continue

                xref = image[0]

                if (
                    isinstance(xref, int)
                    and xref > 0
                ):
                    unique_image_xrefs.add(
                        xref
                    )

            try:
                drawing_groups = len(
                    page.get_drawings()
                )

                total_drawing_groups += (
                    drawing_groups
                )

            except Exception as exc:
                drawing_groups = None

                drawing_measurement_complete = (
                    False
                )

                warnings.append(
                    {
                        "page_number": (
                            page_index + 1
                        ),
                        "metric": (
                            "drawing_groups"
                        ),
                        "error": (
                            type(exc).__name__
                        ),
                    }
                )

            pages.append(
                {
                    "page_number": (
                        page_index + 1
                    ),

                    "native_text_characters": (
                        native_characters
                    ),

                    "has_meaningful_native_text": (
                        has_native_text
                    ),

                    "native_text_blocks": (
                        text_blocks
                    ),

                    "image_blocks": (
                        image_blocks
                    ),

                    "embedded_image_occurrences": (
                        image_occurrences
                    ),

                    "drawing_groups": (
                        drawing_groups
                    ),
                }
            )

    finally:
        document.close()

    elapsed = (
        perf_counter() - started
    )

    page_count = len(
        pages
    )

    native_text_coverage_ratio = (
        pages_with_native_text
        / page_count
        if page_count
        else 0.0
    )

    return {
        "inventory_version": (
            "source_inventory_v1"
        ),

        "file": pdf_path.name,

        "sha256": calculate_sha256(
            pdf_path
        ),

        "file_size_mb": round(
            pdf_path.stat().st_size
            / MB,
            3,
        ),

        "pages": page_count,

        "measurement_complete": (
            image_measurement_complete
            and drawing_measurement_complete
        ),

        "native_text": {
            "characters": (
                total_native_characters
            ),

            "text_blocks": (
                total_text_blocks
            ),

            "pages_with_native_text": (
                pages_with_native_text
            ),

            "pages_without_native_text": (
                pages_without_native_text
            ),

            "page_coverage_ratio": round(
                native_text_coverage_ratio,
                6,
            ),
        },

        "images": {
            "image_blocks": (
                total_image_blocks
            ),

            "embedded_image_occurrences": (
                total_embedded_image_occurrences
            ),

            "unique_embedded_image_xrefs": (
                len(unique_image_xrefs)
            ),

            "pages_with_embedded_images": (
                pages_with_embedded_images
            ),

            "measurement_complete": (
                image_measurement_complete
            ),
        },

        "vector_content": {
            "drawing_groups": (
                total_drawing_groups
                if drawing_measurement_complete
                else None
            ),

            "measurement_complete": (
                drawing_measurement_complete
            ),
        },

        "inventory_processing_seconds": round(
            elapsed,
            3,
        ),

        "warnings": warnings,

        "per_page": pages,
    }
