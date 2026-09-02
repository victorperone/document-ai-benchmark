"""Visual enrichment pipeline for PyMuPDF adapter.

Extracts image regions from a pymupdf Document in memory (no disk writes),
sends them to VisualWorkerClient, and returns enriched_page_markdown and
derived_content_by_page for ParserArtifactInput.

Design constraints:
- Images are rendered in memory only (get_pixmap + tobytes("png"))
- No pix.save() calls; no temporary files
- image_base64 cleared from VisualRequest after send (handled by client)
- region_id is stable: p<page>-picture-<index>-<sha256_prefix>
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any

_VISUAL_CLASSES = frozenset({"picture", "chart", "diagram"})
_MIN_AREA_FRACTION = 0.002
_MIN_WIDTH_PX = 80
_MAX_DIMENSION_PX = 2500
_RENDER_DPI = 150


def _box_to_rect(box: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Return (x0, y0, x1, y1) from a page_box dict, or None if invalid."""
    bbox = box.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _region_id(page_number: int, index: int, image_bytes: bytes) -> str:
    sha_prefix = hashlib.sha256(image_bytes).hexdigest()[:8]
    return f"p{page_number}-picture-{index}-{sha_prefix}"


def _render_region(document: Any, page_index: int, rect: tuple, render_dpi: int = _RENDER_DPI) -> bytes | None:
    """Render a page region to PNG bytes in memory. Returns None on failure."""
    try:
        import pymupdf  # type: ignore[import]
        page = document[page_index]
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        if page_area <= 0:
            return None

        clip = pymupdf.Rect(rect[0], rect[1], rect[2], rect[3])
        region_area = clip.width * clip.height
        if region_area / page_area < _MIN_AREA_FRACTION:
            return None

        scale = render_dpi / 72.0
        mat = pymupdf.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        if pix.width < _MIN_WIDTH_PX:
            return None
        if pix.width > _MAX_DIMENSION_PX or pix.height > _MAX_DIMENSION_PX:
            # Clamp: re-render at lower scale
            max_scale = min(
                _MAX_DIMENSION_PX / (pix.width / scale),
                _MAX_DIMENSION_PX / (pix.height / scale),
                scale,
            )
            mat2 = pymupdf.Matrix(max_scale, max_scale)
            pix = page.get_pixmap(matrix=mat2, clip=clip, alpha=False)
        return pix.tobytes("png")
    except Exception:
        return None


def _derived_block(
    *,
    region_id: str,
    page_number: int,
    description: str,
    ocr_text: str,
    description_model: str,
    ocr_engine: str,
) -> str:
    lines = [
        "<!-- derived:start",
        "type=visual_description",
        f"page={page_number}",
        f"region_id={region_id}",
        f"engine=smolvlm",
        f"model={description_model}",
        "-->",
    ]
    if ocr_text.strip():
        lines.append(f"> **Texto OCR:** {ocr_text.strip()}")
    if description.strip():
        lines.append(f"> **Descrição visual:** {description.strip()}")
    lines.append("<!-- derived:end -->")
    return "\n".join(lines)


def enrich_pages(
    *,
    document: Any,
    native_pages: list[dict[str, Any]],
    page_texts: list[str],
    worker_client: Any,
    language: str,
    description_model: str,
    render_dpi: int = _RENDER_DPI,
) -> tuple[list[str] | None, list[list[dict[str, Any]]], dict[str, Any]]:
    """Run visual enrichment for all pages.

    Returns:
        enriched_page_markdown: one string per page (base text + derived blocks)
        derived_content_by_page: one list of dicts per page
        metrics: summary dict for visual_enrichment metrics block
    """
    page_count = len(page_texts)
    enriched_pages: list[str] = list(page_texts)
    derived_by_page: list[list[dict[str, Any]]] = [[] for _ in range(page_count)]

    regions_detected = 0
    regions_processed = 0
    regions_failed = 0
    successful_derived_blocks = 0

    for page_index, native in enumerate(native_pages):
        page_number = page_index + 1
        boxes = native.get("page_boxes", [])
        if not isinstance(boxes, list):
            continue

        visual_boxes = [
            b for b in boxes
            if isinstance(b, dict) and b.get("class") in _VISUAL_CLASSES
        ]
        regions_detected += len(visual_boxes)

        page_extra_blocks: list[str] = []

        for region_index, box in enumerate(visual_boxes):
            rect = _box_to_rect(box)
            if rect is None:
                regions_failed += 1
                continue

            image_bytes = _render_region(document, page_index, rect, render_dpi=render_dpi)
            if image_bytes is None:
                regions_failed += 1
                continue

            rid = _region_id(page_number, region_index, image_bytes)
            image_b64 = base64.b64encode(image_bytes).decode("ascii")

            from src.enrichment.visual_contract import VisualRequest
            req = VisualRequest(
                request_id=rid,
                operation="ocr_and_describe",
                image_base64=image_b64,
                language=language,
                prompt="Descreva o conteúdo desta imagem de forma objetiva e concisa.",
                page_number=page_number,
                region_id=rid,
            )

            try:
                resp = worker_client.process(req)
                regions_processed += 1
            except Exception:
                regions_failed += 1
                continue

            ocr_text_val = resp.ocr_text.strip() if resp.ocr_text else None
            description_val = resp.description.strip() if resp.description else None

            derived_item: dict[str, Any] = {
                "type": "image_description",
                "source": "pymupdf",
                "region_id": rid,
                "page_number": page_number,
                "box_class": box.get("class"),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
                "storage_policy": "transient",
                "deleted_after_processing": True,
                "status": resp.status,
                "ocr_engine": resp.ocr_engine,
                "ocr_model": resp.ocr_model,
                "description_engine": resp.description_engine,
                "description_model": resp.description_model,
                "ocr_text": ocr_text_val or None,
                "text": description_val or ocr_text_val or None,
            }
            if resp.error_detail:
                derived_item["error_detail"] = resp.error_detail

            derived_by_page[page_index].append(derived_item)

            if resp.status == "success" and (description_val or ocr_text_val):
                block = _derived_block(
                    region_id=rid,
                    page_number=page_number,
                    description=resp.description,
                    ocr_text=resp.ocr_text,
                    description_model=resp.description_model,
                    ocr_engine=resp.ocr_engine,
                )
                page_extra_blocks.append(block)
                successful_derived_blocks += 1

            # Explicit cleanup — image_bytes released here
            del image_bytes

        if page_extra_blocks:
            enriched_pages[page_index] = (
                page_texts[page_index].rstrip()
                + "\n\n"
                + "\n\n".join(page_extra_blocks)
            )

    metrics: dict[str, Any] = {
        "enabled": True,
        "regions_detected": regions_detected,
        "regions_processed": regions_processed,
        "regions_failed": regions_failed,
        "images_persisted": 0,
        "temporary_files_created": 0,
    }

    # enriched_page_markdown is None when no useful derived text was produced
    final_enriched = list(enriched_pages) if successful_derived_blocks > 0 else None
    return final_enriched, derived_by_page, metrics
