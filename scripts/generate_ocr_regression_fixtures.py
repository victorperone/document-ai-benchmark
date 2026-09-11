"""Generate deterministic, image-only OCR regression fixtures as synthetic PDFs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import pymupdf


DEFAULT_OUTPUT = Path(
    "/outputs/_fixtures/ocr_regression"
)

DEFAULT_SOURCE_DPI = 300

HEADER = (
    "BENCHMARK OCR - RELATÓRIO CORPORATIVO 2026"
)

FOOTER = (
    "CONFIDENCIAL - USO INTERNO"
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the OCR regression fixture generator."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate deterministic semantic OCR regression "
            "fixtures as image-only PDFs."
        )
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Destination directory. "
            "Default: "
            f"{DEFAULT_OUTPUT}"
        ),
    )

    parser.add_argument(
        "--source-dpi",
        type=int,
        default=DEFAULT_SOURCE_DPI,
        help=(
            "Raster resolution used to create the synthetic "
            "scanned pages. Default: 300."
        ),
    )

    return parser.parse_args()


def sha256_file(
    path: Path,
) -> str:
    """Return the SHA-256 hex digest of a file, reading it in 1 MB chunks.

    Args:
        path: Path to the file to hash.

    Returns:
        Lowercase hex-encoded SHA-256 digest string.
    """
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:
        while True:
            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def page_size(
    *,
    landscape: bool,
) -> tuple[float, float]:
    """Return the A4 page dimensions in points, swapping width and height for landscape.

    Args:
        landscape: When ``True``, return landscape (wider than tall) dimensions.

    Returns:
        ``(width, height)`` in PDF points.
    """
    a4 = pymupdf.paper_rect(
        "a4"
    )

    if landscape:
        return (
            a4.height,
            a4.width,
        )

    return (
        a4.width,
        a4.height,
    )


def common_body_lines(
    page_number: int,
) -> list[str]:
    """Return the standard body-text lines for a synthetic OCR fixture page.

    Lines contain Portuguese accented characters, unique numeric identifiers,
    and financial values that exercise OCR accuracy under each profile.

    Args:
        page_number: 1-based page number used to vary numeric values per page.

    Returns:
        List of body-text strings.
    """
    return [
        (
            "Este documento sintético valida extração OCR "
            "em português do Brasil."
        ),
        (
            "A informação deve permanecer legível após "
            "rasterização e reconhecimento."
        ),
        (
            "Caracteres de teste: ação, informação, "
            "configuração, produção, operação e coração."
        ),
        (
            "Acentuação adicional: café, mês, possível, "
            "saúde, órgão, útil e também."
        ),
        (
            f"Identificador único da página: "
            f"REGRESSAO-{page_number:02d}-2026."
        ),
        (
            f"Receita operacional: "
            f"R$ {page_number * 1234:,.2f}."
        ),
        (
            f"Quantidade processada: "
            f"{page_number * 137} unidades."
        ),
        (
            f"Taxa de aprovação: "
            f"{90 + page_number / 10:.1f}%."
        ),
        (
            "Situação operacional: APROVADO PARA TESTE."
        ),
        (
            "Responsável técnico: Equipe Document AI."
        ),
        (
            "O objetivo desta página é medir OCR, "
            "acentuação, números e preservação textual."
        ),
        (
            "Nenhum texto desta página deve existir como "
            "camada textual no PDF final."
        ),
    ]


def draw_standard_page(
    document: pymupdf.Document,
    *,
    page_number: int,
    total_pages: int,
    landscape: bool = False,
    quality_page: bool = False,
    compact_orientation: bool = False,
) -> tuple[
    pymupdf.Page,
    dict[str, Any],
]:
    """Draw a synthetic source page with header, body text, a small table, and footer.

    The page is added to ``document`` and native text is verified before rasterization.

    Args:
        document: Open ``pymupdf.Document`` to which the new page is appended.
        page_number: 1-based page number rendered in the title and footer.
        total_pages: Total page count shown in the title (e.g. ``"3/8"``).
        landscape: When ``True``, the page uses landscape A4 dimensions.
        quality_page: When ``True``, appends extra small-text lines to the body.
        compact_orientation: When ``True``, uses a shorter body suitable for
            single-page orientation fixtures.

    Returns:
        Tuple of ``(page, truth_dict)`` where ``truth_dict`` contains the expected
        ``page_number``, ``expected_lines``, ``expected_header``, ``expected_footer``,
        and ``expected_page_number`` fields for ground-truth comparison.

    Raises:
        RuntimeError: If the body text does not fit on the page, or if required
            source-text terms are missing from the native PDF layer.
    """
    width, height = page_size(
        landscape=landscape
    )

    page = document.new_page(
        width=width,
        height=height,
    )

    margin = 42

    # --------------------------------------------------------
    # Repeated header
    # --------------------------------------------------------

    page.insert_text(
        pymupdf.Point(
            margin,
            35,
        ),
        HEADER,
        fontsize=10,
        fontname="helv",
    )

    page.draw_line(
        pymupdf.Point(
            margin,
            45,
        ),
        pymupdf.Point(
            width - margin,
            45,
        ),
        width=0.5,
    )

    title = (
        f"Página sintética de regressão OCR "
        f"{page_number}/{total_pages}"
    )

    page.insert_text(
        pymupdf.Point(
            margin,
            75,
        ),
        title,
        fontsize=16,
        fontname="helv",
    )

    expected_lines = [
        HEADER,
        title,
    ]

    # --------------------------------------------------------
    # Main body
    # --------------------------------------------------------

    body_lines = common_body_lines(
        page_number
    )

    if compact_orientation:
        body_lines = [
            (
                "Este documento sintético valida OCR "
                "e orientação de páginas."
            ),
            (
                "Caracteres de teste: ação, informação, "
                "configuração, produção e operação."
            ),
            (
                f"Identificador único da página: "
                f"REGRESSAO-{page_number:02d}-2026."
            ),
            (
                f"Receita operacional: "
                f"R$ {page_number * 1234:,.2f}."
            ),
            (
                "Situação operacional: "
                "APROVADO PARA TESTE."
            ),
            (
                "O texto deve continuar legível após "
                "detecção e correção de orientação."
            ),
        ]

    if quality_page:
        body_lines.extend(
            [
                (
                    "Linha pequena 08pt: "
                    "ação configuração precisão "
                    "0123456789."
                ),
                (
                    "Linha média 10pt: "
                    "informação produção relatório "
                    "R$ 9.876,54."
                ),
                (
                    "Linha normal 12pt: "
                    "extração estruturada e OCR."
                ),
            ]
        )

    body_rect = pymupdf.Rect(
        margin,
        100,
        width - margin,
        height - 170,
    )

    body_text = "\n\n".join(
        body_lines
    )

    body_font_size = (
        10.0
        if compact_orientation
        else 11.0
    )

    spare = page.insert_textbox(
        body_rect,
        body_text,
        fontsize=body_font_size,
        fontname="helv",
        align=pymupdf.TEXT_ALIGN_LEFT,
    )

    if spare < 0:
        raise RuntimeError(
            "Synthetic body text did not fit "
            f"on page {page_number}."
        )

    expected_lines.extend(
        body_lines
    )

    # --------------------------------------------------------
    # Small controlled table
    # --------------------------------------------------------

    table_top = height - 150
    table_left = margin
    table_right = min(
        width - margin,
        table_left + 420,
    )

    table_bottom = table_top + 55

    table_rect = pymupdf.Rect(
        table_left,
        table_top,
        table_right,
        table_bottom,
    )

    page.draw_rect(
        table_rect,
        width=0.7,
    )

    column_1 = table_left + 140
    column_2 = table_left + 280
    row_middle = table_top + 27.5

    page.draw_line(
        pymupdf.Point(
            column_1,
            table_top,
        ),
        pymupdf.Point(
            column_1,
            table_bottom,
        ),
        width=0.5,
    )

    page.draw_line(
        pymupdf.Point(
            column_2,
            table_top,
        ),
        pymupdf.Point(
            column_2,
            table_bottom,
        ),
        width=0.5,
    )

    page.draw_line(
        pymupdf.Point(
            table_left,
            row_middle,
        ),
        pymupdf.Point(
            table_right,
            row_middle,
        ),
        width=0.5,
    )

    table_values = [
        (
            "Indicador",
            "Valor",
            "Status",
        ),
        (
            "Receita",
            f"R$ {page_number * 1000}",
            "OK",
        ),
    ]

    x_positions = [
        table_left + 6,
        column_1 + 6,
        column_2 + 6,
    ]

    y_positions = [
        table_top + 18,
        row_middle + 18,
    ]

    for row_index, row in enumerate(
        table_values
    ):
        for col_index, value in enumerate(
            row
        ):
            page.insert_text(
                pymupdf.Point(
                    x_positions[
                        col_index
                    ],
                    y_positions[
                        row_index
                    ],
                ),
                value,
                fontsize=8.5,
                fontname="helv",
            )

    expected_lines.extend(
        [
            "Indicador Valor Status",
            (
                f"Receita R$ "
                f"{page_number * 1000} OK"
            ),
        ]
    )

    # --------------------------------------------------------
    # Repeated footer + page number
    # --------------------------------------------------------

    footer_y = height - 50

    page.draw_line(
        pymupdf.Point(
            margin,
            footer_y - 12,
        ),
        pymupdf.Point(
            width - margin,
            footer_y - 12,
        ),
        width=0.5,
    )

    page.insert_text(
        pymupdf.Point(
            margin,
            footer_y,
        ),
        FOOTER,
        fontsize=9,
        fontname="helv",
    )

    page.insert_text(
        pymupdf.Point(
            width - margin - 20,
            footer_y,
        ),
        str(
            page_number
        ),
        fontsize=9,
        fontname="helv",
    )

    expected_lines.extend(
        [
            FOOTER,
            str(page_number),
        ]
    )

    # --------------------------------------------------------
    # Verify source text before rasterization.
    # --------------------------------------------------------

    native_source_text = (
        page.get_text(
            "text"
        )
    )

    required_terms = [
        "BENCHMARK OCR",
        "informação",
        "configuração",
        "CONFIDENCIAL",
    ]

    for term in required_terms:
        if term not in native_source_text:
            raise RuntimeError(
                "Source-page text validation failed. "
                f"Missing term: {term!r}"
            )

    truth = {
        "page_number": (
            page_number
        ),
        "expected_lines": (
            expected_lines
        ),
        "expected_header": (
            HEADER
        ),
        "expected_footer": (
            FOOTER
        ),
        "expected_page_number": str(
            page_number
        ),
    }

    return (
        page,
        truth,
    )


def rasterize_document(
    source: pymupdf.Document,
    destination: Path,
    *,
    source_dpi: int,
    pixel_rotation: int = 0,
    page_rotation_metadata: int = 0,
) -> None:
    """Rasterize every page in ``source`` and save an image-only PDF to ``destination``.

    Each page is rendered to a grayscale pixmap at ``source_dpi``, inserted as
    the sole image on a new PDF page whose physical size matches the render
    resolution.  An optional pixel rotation is applied during rendering, and an
    optional PDF page-rotation metadata field can be set independently.

    Args:
        source: Source ``pymupdf.Document`` with native text content.
        destination: Output path for the image-only PDF.
        source_dpi: Raster resolution in DPI (e.g. ``300``).
        pixel_rotation: Clockwise rotation in degrees applied to the pixmap
            before insertion (``0``, ``90``, ``180``, or ``270``).
        page_rotation_metadata: Value written to the PDF ``/Rotate`` key
            (``0``, ``90``, ``180``, or ``270``).
    """
    if destination.exists():
        destination.unlink()

    output = pymupdf.open()

    try:
        scale = (
            source_dpi / 72.0
        )

        for source_page in source:
            matrix = pymupdf.Matrix(
                scale,
                scale,
            )

            if pixel_rotation:
                matrix = (
                    matrix.prerotate(
                        pixel_rotation
                    )
                )

            pixmap = (
                source_page
                .get_pixmap(
                    matrix=matrix,
                    colorspace=(
                        pymupdf.csGRAY
                    ),
                    alpha=False,
                    annots=True,
                )
            )

            image_bytes = (
                pixmap.tobytes(
                    "png"
                )
            )

            # Preserve the physical size implied by the
            # requested source DPI, including 90/270-degree
            # dimension swaps caused by pixel rotation.
            page_width = (
                pixmap.width
                * 72.0
                / source_dpi
            )

            page_height = (
                pixmap.height
                * 72.0
                / source_dpi
            )

            destination_page = (
                output.new_page(
                    width=page_width,
                    height=page_height,
                )
            )

            destination_page.insert_image(
                destination_page.rect,
                stream=image_bytes,
                keep_proportion=False,
            )

            if page_rotation_metadata:
                destination_page.set_rotation(
                    page_rotation_metadata
                )

        output.set_metadata(
            {
                "title": (
                    destination.stem
                ),
                "author": (
                    "document-ai-benchmark"
                ),
                "subject": (
                    "Synthetic OCR regression fixture"
                ),
                "keywords": (
                    "OCR regression synthetic fixture"
                ),
                "creator": (
                    "generate_ocr_regression_fixtures.py"
                ),
                "producer": (
                    "PyMuPDF"
                ),
                "creationDate": (
                    "D:20260814000000Z"
                ),
                "modDate": (
                    "D:20260814000000Z"
                ),
            }
        )

        output.save(
            destination,
            garbage=4,
            deflate=True,
            clean=True,
        )

    finally:
        output.close()


def create_multi_page_fixture(
    destination: Path,
    *,
    pages: int,
    source_dpi: int,
    quality: bool = False,
    landscape: bool = False,
) -> list[dict[str, Any]]:
    """Create a multi-page image-only fixture PDF and return its ground-truth records.

    Args:
        destination: Output path for the rasterized PDF.
        pages: Number of pages to generate.
        source_dpi: Render resolution in DPI.
        quality: When ``True``, enables extra small-text lines on each page.
        landscape: When ``True``, each source page uses landscape A4 dimensions.

    Returns:
        List of truth dicts, one per page, each produced by ``draw_standard_page``.
    """
    source = pymupdf.open()

    truth: list[
        dict[str, Any]
    ] = []

    try:
        for page_number in range(
            1,
            pages + 1,
        ):
            _, page_truth = (
                draw_standard_page(
                    source,
                    page_number=(
                        page_number
                    ),
                    total_pages=pages,
                    landscape=landscape,
                    quality_page=quality,
                )
            )

            truth.append(
                page_truth
            )

        rasterize_document(
            source,
            destination,
            source_dpi=source_dpi,
        )

    finally:
        source.close()

    return truth


def create_orientation_fixture(
    destination: Path,
    *,
    source_dpi: int,
    pixel_rotation: int = 0,
    page_rotation_metadata: int = 0,
    landscape: bool = False,
) -> list[dict[str, Any]]:
    """Create a single-page orientation-variant fixture and return its ground-truth record.

    Generates one compact page, rasterizes it with an optional pixel rotation
    and optional PDF rotation metadata, and augments the truth dict with the
    rotation parameters used.

    Args:
        destination: Output path for the rasterized PDF.
        source_dpi: Render resolution in DPI.
        pixel_rotation: Clockwise rotation applied to the rendered pixels
            (``0``, ``90``, ``180``, or ``270``).
        page_rotation_metadata: Value written to the PDF ``/Rotate`` key.
        landscape: When ``True``, the source page uses landscape A4 dimensions.

    Returns:
        Single-element list containing the truth dict for the generated page.
    """
    source = pymupdf.open()

    try:
        _, page_truth = (
            draw_standard_page(
                source,
                page_number=1,
                total_pages=1,
                landscape=landscape,
                quality_page=False,
                compact_orientation=True,
            )
        )

        rasterize_document(
            source,
            destination,
            source_dpi=source_dpi,
            pixel_rotation=(
                pixel_rotation
            ),
            page_rotation_metadata=(
                page_rotation_metadata
            ),
        )

    finally:
        source.close()

    page_truth[
        "pixel_rotation_degrees"
    ] = pixel_rotation

    page_truth[
        "page_rotation_metadata"
    ] = page_rotation_metadata

    page_truth[
        "landscape_source"
    ] = landscape

    return [
        page_truth
    ]


def validate_image_only_pdf(
    path: Path,
    *,
    expected_pages: int,
) -> dict[str, Any]:
    """Verify that a PDF is a valid image-only fixture and return structural metadata.

    Checks that the page count matches, that no page contains native text,
    and that every page has at least one embedded image.

    Args:
        path: Path to the PDF to validate.
        expected_pages: Expected number of pages.

    Returns:
        Dict with keys ``pages``, ``pages_with_native_text``, ``pages_with_images``,
        ``image_occurrences``, ``page_rotations``, and ``page_sizes``.

    Raises:
        RuntimeError: If the page count, native-text presence, or image coverage
            does not meet expectations.
    """
    document = pymupdf.open(
        path
    )

    try:
        if len(document) != expected_pages:
            raise RuntimeError(
                f"{path.name}: expected "
                f"{expected_pages} pages, "
                f"found {len(document)}."
            )

        pages_with_native_text = 0
        pages_with_images = 0
        image_occurrences = 0
        rotations: list[int] = []
        page_sizes: list[
            dict[str, float]
        ] = []

        for page in document:
            text = page.get_text(
                "text"
            ).strip()

            if text:
                pages_with_native_text += 1

            images = page.get_images(
                full=True
            )

            if images:
                pages_with_images += 1

            image_occurrences += len(
                images
            )

            rotations.append(
                int(
                    page.rotation
                )
            )

            page_sizes.append(
                {
                    "width": round(
                        page.rect.width,
                        3,
                    ),
                    "height": round(
                        page.rect.height,
                        3,
                    ),
                }
            )

        if pages_with_native_text != 0:
            raise RuntimeError(
                f"{path.name}: expected image-only PDF, "
                f"but {pages_with_native_text} page(s) "
                "contain native text."
            )

        if pages_with_images != expected_pages:
            raise RuntimeError(
                f"{path.name}: expected image content "
                "on every page."
            )

        return {
            "pages": len(
                document
            ),
            "pages_with_native_text": (
                pages_with_native_text
            ),
            "pages_with_images": (
                pages_with_images
            ),
            "image_occurrences": (
                image_occurrences
            ),
            "page_rotations": (
                rotations
            ),
            "page_sizes": (
                page_sizes
            ),
        }

    finally:
        document.close()


def main() -> None:
    """Generate all OCR regression fixture PDFs and write a ground-truth JSON manifest."""
    args = parse_args()

    if args.source_dpi <= 0:
        raise SystemExit(
            "--source-dpi must be greater than zero."
        )

    output_dir: Path = (
        args.output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    specifications = [
        {
            "filename": (
                "scan_header_footer_8.pdf"
            ),
            "purpose": (
                "Image-only multi-page OCR fixture with "
                "repeated header, repeated footer, and "
                "page numbers."
            ),
            "kind": (
                "header_footer"
            ),
        },
        {
            "filename": (
                "scan_quality_3.pdf"
            ),
            "purpose": (
                "Image-only OCR quality fixture containing "
                "Portuguese accents, numbers, financial "
                "values, and small text."
            ),
            "kind": (
                "quality"
            ),
        },
        {
            "filename": (
                "scan_landscape_upright.pdf"
            ),
            "purpose": (
                "Image-only landscape page whose text is "
                "already upright."
            ),
            "kind": (
                "landscape"
            ),
        },
        {
            "filename": (
                "scan_pixels_90.pdf"
            ),
            "purpose": (
                "Image-only page with pixels physically "
                "rotated by 90 degrees and no PDF rotation "
                "metadata."
            ),
            "kind": (
                "pixels_90"
            ),
        },
        {
            "filename": (
                "scan_pixels_180.pdf"
            ),
            "purpose": (
                "Image-only page with pixels physically "
                "rotated by 180 degrees and no PDF rotation "
                "metadata."
            ),
            "kind": (
                "pixels_180"
            ),
        },
        {
            "filename": (
                "scan_pixels_270.pdf"
            ),
            "purpose": (
                "Image-only page with pixels physically "
                "rotated by 270 degrees and no PDF rotation "
                "metadata."
            ),
            "kind": (
                "pixels_270"
            ),
        },
        {
            "filename": (
                "scan_metadata_rotation_90.pdf"
            ),
            "purpose": (
                "Image-only page carrying PDF page rotation "
                "metadata of 90 degrees."
            ),
            "kind": (
                "metadata_90"
            ),
        },
    ]

    ground_truth: dict[
        str,
        Any,
    ] = {
        "schema_version": 1,

        "generator": {
            "script": (
                "generate_ocr_regression_fixtures.py"
            ),
            "source_dpi": (
                args.source_dpi
            ),
            "pymupdf_version": (
                importlib.metadata.version(
                    "pymupdf"
                )
            ),
            "description": (
                "Synthetic image-only fixtures generated "
                "locally for OCR regression testing."
            ),
        },

        "fixtures": {},
    }

    for spec in specifications:
        filename = str(
            spec["filename"]
        )

        path = (
            output_dir
            / filename
        )

        kind = str(
            spec["kind"]
        )

        if kind == "header_footer":
            truth = (
                create_multi_page_fixture(
                    path,
                    pages=8,
                    source_dpi=(
                        args.source_dpi
                    ),
                )
            )

        elif kind == "quality":
            truth = (
                create_multi_page_fixture(
                    path,
                    pages=3,
                    source_dpi=(
                        args.source_dpi
                    ),
                    quality=True,
                )
            )

        elif kind == "landscape":
            truth = (
                create_orientation_fixture(
                    path,
                    source_dpi=(
                        args.source_dpi
                    ),
                    landscape=True,
                )
            )

        elif kind == "pixels_90":
            truth = (
                create_orientation_fixture(
                    path,
                    source_dpi=(
                        args.source_dpi
                    ),
                    pixel_rotation=90,
                )
            )

        elif kind == "pixels_180":
            truth = (
                create_orientation_fixture(
                    path,
                    source_dpi=(
                        args.source_dpi
                    ),
                    pixel_rotation=180,
                )
            )

        elif kind == "pixels_270":
            truth = (
                create_orientation_fixture(
                    path,
                    source_dpi=(
                        args.source_dpi
                    ),
                    pixel_rotation=270,
                )
            )

        elif kind == "metadata_90":
            truth = (
                create_orientation_fixture(
                    path,
                    source_dpi=(
                        args.source_dpi
                    ),
                    page_rotation_metadata=90,
                )
            )

        else:
            raise RuntimeError(
                f"Unknown fixture kind: {kind}"
            )

        validation = (
            validate_image_only_pdf(
                path,
                expected_pages=len(
                    truth
                ),
            )
        )

        ground_truth[
            "fixtures"
        ][filename] = {
            "purpose": (
                spec["purpose"]
            ),
            "sha256": (
                sha256_file(
                    path
                )
            ),
            "pages": (
                truth
            ),
            "validation": (
                validation
            ),
        }

    ground_truth_path = (
        output_dir
        / "ground_truth.json"
    )

    ground_truth_path.write_text(
        json.dumps(
            ground_truth,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 78)
    print("OCR REGRESSION FIXTURES")
    print("=" * 78)

    print(
        "Output:",
        output_dir,
    )

    print(
        "Source DPI:",
        args.source_dpi,
    )

    print()

    for filename, record in (
        ground_truth[
            "fixtures"
        ].items()
    ):
        validation = (
            record["validation"]
        )

        print(
            f"{filename}"
        )

        print(
            "  Pages:",
            validation["pages"],
        )

        print(
            "  Native text pages:",
            validation[
                "pages_with_native_text"
            ],
        )

        print(
            "  Image pages:",
            validation[
                "pages_with_images"
            ],
        )

        print(
            "  PDF rotations:",
            validation[
                "page_rotations"
            ],
        )

    print()
    print(
        "Ground truth:",
        ground_truth_path,
    )

    print("=" * 78)
    print(
        "OCR regression fixture generation: OK"
    )
    print("=" * 78)


if __name__ == "__main__":
    main()
