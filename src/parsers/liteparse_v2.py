from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from src.benchmark.artifact_policy import (
    ArtifactPolicy,
    ArtifactSelectionError,
)
from src.benchmark.config import (
    BenchmarkConfigurationError,
    get_profile,
)
from src.benchmark.cpu_resources import resolve_parallelism
from src.benchmark.preflight import make_check, make_result
from src.benchmark.runtime_io import add_runtime_arguments

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARSER_NAME = "liteparse"
PARSER_DISPLAY_NAME = "LiteParse"
LITEPARSE_REQUIRED_VERSION = "2.13.0"
TRANSFORMERS_REQUIRED_VERSION = "5.16.1"

SMOLVLM_ARTIFACT_DIRECTORY = "HuggingFaceTB--SmolVLM-256M-Instruct"
DEFAULT_MODEL_ARTIFACTS = Path("/models/liteparse/smolvlm")

FULL_PAGE_OCR_REASONS: frozenset[str] = frozenset(
    {
        "scanned",
        "no-text",
        "sparse-text",
        "garbled",
    }
)

_TESSDATA_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    "/usr/local/share/tessdata",
)

# Module-level SmolVLM model cache (avoids reloading between images)
_smolvlm_cache: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Markdown block parsing
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_TABLE_ROW_RE = re.compile(r"^\|")
_LIST_ITEM_RE = re.compile(r"^(\s*[-*]|\s*\d+\.)\s+")
_CODE_FENCE_RE = re.compile(r"^```")
_RULE_RE = re.compile(r"^(---+|\*\*\*+|___+)$")


def _parse_markdown_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not text:
        return blocks

    in_code = False
    code_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        if _CODE_FENCE_RE.match(stripped):
            if in_code:
                in_code = False
                blocks.append(
                    {"kind": "code", "text": "\n".join(code_lines)}
                )
                code_lines = []
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            continue

        m = _HEADING_RE.match(stripped)
        if m:
            blocks.append(
                {
                    "kind": "heading",
                    "level": len(m.group(1)),
                    "text": m.group(2).strip(),
                }
            )
            continue

        if _TABLE_ROW_RE.match(stripped):
            blocks.append({"kind": "table", "text": stripped})
            continue

        if _LIST_ITEM_RE.match(stripped):
            blocks.append({"kind": "list_item", "text": stripped})
            continue

        if _RULE_RE.match(stripped):
            blocks.append({"kind": "rule", "text": stripped})
            continue

        blocks.append({"kind": "paragraph", "text": stripped})

    return blocks


# ---------------------------------------------------------------------------
# Usable-text heuristic
# ---------------------------------------------------------------------------

_MIN_ALNUM_CHARS = 10
_MIN_ALNUM_RATIO = 0.30


def _is_usable_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    alnum_chars = [ch for ch in stripped if ch.isalnum()]
    if len(alnum_chars) < _MIN_ALNUM_CHARS:
        return False

    if len(alnum_chars) / len(stripped) < _MIN_ALNUM_RATIO:
        return False

    # Reject highly-repeated single-char sequences (noise from OCR)
    if stripped and len(set(stripped)) <= 2 and len(stripped) > 4:
        return False

    return True


# ---------------------------------------------------------------------------
# Orientation detection & rotation
# ---------------------------------------------------------------------------


def _detect_and_correct_orientation(
    image_bytes: bytes,
) -> tuple[bytes, int]:
    """Detect orientation via Tesseract OSD and rotate if needed.

    Returns ``(corrected_bytes, rotation_degrees_applied)``.
    Falls back to (original_bytes, 0) on OSD failure.
    """
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        osd = pytesseract.image_to_osd(
            img,
            output_type=pytesseract.Output.DICT,
        )
        rotation = int(osd.get("rotate", 0))

        if rotation == 0:
            return image_bytes, 0

        rotated = img.rotate(rotation, expand=True)
        buf = io.BytesIO()
        rotated.save(buf, format="PNG")
        return buf.getvalue(), rotation

    except Exception:
        return image_bytes, 0


# ---------------------------------------------------------------------------
# Image OCR
# ---------------------------------------------------------------------------


def _ocr_image_bytes(
    image_bytes: bytes,
    lang: str = "por+eng",
) -> str:
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    try:
        text = pytesseract.image_to_string(
            img,
            lang=lang,
            config="--psm 3",
        )
        return text.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# SmolVLM visual description
# ---------------------------------------------------------------------------


def _describe_image_with_smolvlm(
    image_bytes: bytes,
    model_root: Path,
    prompt: str,
) -> str:
    model_dir = (
        model_root
        / SMOLVLM_ARTIFACT_DIRECTORY
    )

    if not model_dir.is_dir():
        raise RuntimeError(
            "SmolVLM model directory is missing: "
            f"{model_dir}"
        )

    model_key = str(model_dir)

    try:
        import torch
        from PIL import Image
        from transformers import (
            AutoModelForImageTextToText,
            AutoProcessor,
        )

        if model_key not in _smolvlm_cache:
            processor = AutoProcessor.from_pretrained(
                str(model_dir),
                local_files_only=True,
            )

            model = (
                AutoModelForImageTextToText
                .from_pretrained(
                    str(model_dir),
                    local_files_only=True,
                    dtype=torch.float32,
                )
                .to("cpu")
            )
            model.eval()

            _smolvlm_cache[model_key] = (
                processor,
                model,
            )

        processor, model = (
            _smolvlm_cache[model_key]
        )

        image = (
            Image.open(
                io.BytesIO(image_bytes)
            )
            .convert("RGB")
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ]

        # Build the textual chat template separately and
        # explicitly provide the in-memory PIL image. This
        # guarantees that the visual tensor is actually passed
        # to SmolVLM instead of leaving a bare image placeholder.
        prompt_text = (
            processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
        )

        inputs = processor(
            text=prompt_text,
            images=[image],
            return_tensors="pt",
        ).to("cpu")

        input_length = int(
            inputs["input_ids"].shape[1]
        )

        with torch.no_grad():
            generated = model.generate(
                **inputs,
                max_new_tokens=128,
                do_sample=False,
            )

        generated_only = generated[
            :,
            input_length:,
        ]

        descriptions = (
            processor.batch_decode(
                generated_only,
                skip_special_tokens=True,
            )
        )

        description = (
            descriptions[0].strip()
            if descriptions
            else ""
        )

        if not description:
            raise RuntimeError(
                "SmolVLM returned an empty description."
            )

        return description

    except Exception as exc:
        raise RuntimeError(
            "SmolVLM image description failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Image processing pipeline
# ---------------------------------------------------------------------------


def _image_file_hash(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_document_images(
    all_images: list[Any],
    profile: dict[str, Any],
    image_output_dir: Path,
    model_root: Path,
    ocr_language: str = "por+eng",
) -> dict[str, dict[str, Any]]:
    """Process extracted images with OCR and optional SmolVLM."""

    image_description_enabled = bool(
        profile.get(
            "image_description",
            False,
        )
    )

    fallback_only = bool(
        profile.get(
            "image_description_fallback_only",
            False,
        )
    )

    description_prompt = str(
        profile.get(
            "image_description_prompt",
            (
                "Describe the image concisely "
                "and factually."
            ),
        )
    )

    enrichments: dict[
        str,
        dict[str, Any],
    ] = {}

    hash_to_enrichment: dict[
        str,
        dict[str, Any],
    ] = {}

    for img_obj in all_images:
        img_path_attr = getattr(
            img_obj,
            "path",
            None,
        )
        img_name = (
            getattr(
                img_obj,
                "name",
                None,
            )
            or ""
        )

        if img_path_attr:
            img_file = Path(
                img_path_attr
            )
        elif (
            img_name
            and image_output_dir.exists()
        ):
            img_file = (
                image_output_dir
                / img_name
            )
        else:
            continue

        if not img_file.is_file():
            continue

        key = str(img_file)
        file_hash = _image_file_hash(
            img_file
        )

        if (
            file_hash
            in hash_to_enrichment
        ):
            enrichment = dict(
                hash_to_enrichment[
                    file_hash
                ]
            )
            enrichment[
                "duplicate"
            ] = True
            enrichments[key] = enrichment
            continue

        image_bytes = (
            img_file.read_bytes()
        )

        corrected_bytes, rotation = (
            _detect_and_correct_orientation(
                image_bytes
            )
        )

        ocr_text = _ocr_image_bytes(
            corrected_bytes,
            lang=ocr_language,
        )

        has_usable_text = (
            _is_usable_text(
                ocr_text
            )
        )

        enrichment: dict[
            str,
            Any,
        ] = {
            "file": key,
            "hash": file_hash,
            "rotation_applied": rotation,
            "ocr_attempted": True,
            "ocr_text": (
                ocr_text
                if has_usable_text
                else None
            ),
            "has_usable_text": (
                has_usable_text
            ),
            "image_description": None,
            "model": None,
            "duplicate": False,
        }

        should_describe = (
            image_description_enabled
            and (
                not fallback_only
                or not has_usable_text
            )
        )

        description: str | None = None

        if should_describe:
            description = (
                _describe_image_with_smolvlm(
                    corrected_bytes,
                    model_root,
                    description_prompt,
                )
            )
            enrichment[
                "image_description"
            ] = description
            enrichment[
                "model"
            ] = (
                SMOLVLM_ARTIFACT_DIRECTORY
            )

        if (
            has_usable_text
            and description
        ):
            enrichment["kind"] = (
                "image_text_and_description"
            )
            enrichment["engine"] = (
                "tesseract"
            )

        elif has_usable_text:
            enrichment["kind"] = (
                "image_text"
            )
            enrichment["engine"] = (
                "tesseract"
            )

        elif description:
            enrichment["kind"] = (
                "image_description"
            )

        else:
            enrichment["kind"] = "none"

        hash_to_enrichment[
            file_hash
        ] = enrichment

        enrichments[key] = enrichment

    return enrichments


# ---------------------------------------------------------------------------
# Page text reconstruction from text_items
# ---------------------------------------------------------------------------


def _text_items_to_text(text_items: list[Any]) -> str:
    """Reconstruct page text from LiteParse text items in reading order."""
    if not text_items:
        return ""

    # Sort by vertical position (y) then horizontal (x)
    items = sorted(
        text_items,
        key=lambda ti: (
            round(getattr(ti, "y", 0), 0),
            getattr(ti, "x", 0),
        ),
    )

    lines: list[str] = []
    current_y: float | None = None
    current_line: list[str] = []
    y_threshold = 5.0  # px tolerance for same line

    for item in items:
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue

        y = float(getattr(item, "y", 0))

        if current_y is None or abs(y - current_y) > y_threshold:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [text]
            current_y = y
        else:
            current_line.append(text)

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


def _extract_page_texts(
    result: Any,
    page_count: int,
) -> list[str]:
    """Extract per-page text strings from a LiteParse result."""
    pages = getattr(result, "pages", None) or []
    page_map: dict[int, str] = {}

    for page in pages:
        page_num = int(getattr(page, "page_num", 0) or 0)
        if page_num < 1:
            continue

        text_items = getattr(page, "text_items", None) or []
        page_text = _text_items_to_text(text_items)
        if not page_text:
            # Fallback: use any text attribute on the page object
            page_text = str(getattr(page, "text", "") or "")
        page_map[page_num] = page_text

    # If no per-page data, fall back to splitting result.text
    if not page_map:
        full_text = str(getattr(result, "text", "") or "")
        if full_text and page_count > 0:
            chunk = len(full_text) // page_count
            for i in range(page_count):
                start = i * chunk
                end = start + chunk if i < page_count - 1 else len(full_text)
                page_map[i + 1] = full_text[start:end]

    return [page_map.get(i + 1, "") for i in range(page_count)]


def _merge_page_texts(
    native_texts: list[str],
    ocr_texts_by_page: dict[int, str],
    page_count: int,
) -> list[str]:
    """Merge native and OCR texts, preferring OCR for pages that needed it."""
    merged: list[str] = []
    for i in range(page_count):
        page_num = i + 1
        if page_num in ocr_texts_by_page:
            merged.append(ocr_texts_by_page[page_num])
        else:
            merged.append(native_texts[i] if i < len(native_texts) else "")
    return merged


# ---------------------------------------------------------------------------
# Page text with image enrichments
# ---------------------------------------------------------------------------


def _compact_markdown_tables(text: str) -> str:
    """Compact table whitespace while preserving valid Markdown."""
    lines: list[str] = []
    for line in text.splitlines():
        rline = line.rstrip()
        if rline.startswith("|") and rline.endswith("|"):
            cells = rline.split("|")
            rline = "|".join(c.strip() for c in cells)
        lines.append(rline)
    return "\n".join(lines)


def _build_page_text_with_enrichments(
    raw_text: str,
    page_images: list[Any],
    enrichments: dict[str, dict[str, Any]],
) -> str:
    parts: list[str] = [raw_text.rstrip() if raw_text else ""]

    for img_obj in page_images:
        img_path_attr = getattr(img_obj, "path", None)
        img_name = getattr(img_obj, "name", None) or ""

        if img_path_attr:
            key = str(img_path_attr)
        else:
            continue

        enrichment = enrichments.get(key)
        if not enrichment:
            continue

        kind = enrichment.get("kind", "none")

        if kind in {
            "image_text",
            "image_text_and_description",
        }:
            text = enrichment.get("ocr_text", "")
            if text:
                # OCR text is part of the document content — no synthetic label.
                parts.append(f"\n{text}")
        # VLM descriptions are stored in parser_native only; never injected
        # into the compared markdown (adendo §2, §9).

    combined = "\n\n".join(p for p in parts if p)
    combined = _compact_markdown_tables(combined)

    # Normalize whitespace
    output_lines: list[str] = []
    prev_blank = False
    for line in combined.splitlines():
        rline = line.rstrip()
        is_blank = rline == ""
        if is_blank and prev_blank:
            continue
        output_lines.append(rline)
        prev_blank = is_blank

    return "\n".join(output_lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Structured output builders
# ---------------------------------------------------------------------------


def _count_blocks(blocks: list[dict[str, Any]]) -> Counter[str]:
    return Counter(b.get("kind", "unknown") for b in blocks)


def _build_structured_output(
    page_texts: list[str],
    ocr_decisions: dict[int, dict[str, Any]],
    image_enrichments: dict[str, dict[str, Any]],
    all_images: list[Any],
    page_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parser_page_elements: list[dict[str, Any]] = []
    parser_native_pages: list[dict[str, Any]] = []

    for i in range(page_count):
        page_num = i + 1
        text = page_texts[i] if i < len(page_texts) else ""
        blocks = _parse_markdown_blocks(text)
        counts = _count_blocks(blocks)
        decision_info = ocr_decisions.get(page_num, {})

        page_images = [
            img for img in all_images
            if getattr(img, "page_num", None) == page_num
        ]
        img_enrichment_records = []
        for img_obj in page_images:
            img_path_attr = getattr(img_obj, "path", None)
            if img_path_attr and str(img_path_attr) in image_enrichments:
                img_enrichment_records.append(
                    image_enrichments[str(img_path_attr)]
                )

        elements: dict[str, Any] = {
            "page_number": page_num,
            "layout_boxes": sum(counts.values()),
            "tables_detected": counts.get("table", 0),
            "images_detected": len(page_images),
            "headings_detected": counts.get("heading", 0),
            "lists_detected": counts.get("list_item", 0),
            "text_blocks_detected": counts.get("paragraph", 0),
            "code_blocks_detected": counts.get("code", 0),
            "ocr_applied": decision_info.get("decision") == "full_page_ocr",
            "orientation_applied": decision_info.get("rotation_applied", 0),
            "box_class_counts": dict(sorted(counts.items())),
        }
        parser_page_elements.append(elements)

        native_page: dict[str, Any] = {
            "page_number": page_num,
            "blocks": blocks,
            "ocr_decision": decision_info.get("decision", "native"),
            "ocr_reasons": decision_info.get("reasons", []),
            "orientation_applied": decision_info.get("rotation_applied", 0),
            "images": img_enrichment_records,
            "label_counts": dict(sorted(counts.items())),
        }
        parser_native_pages.append(native_page)

    return parser_page_elements, parser_native_pages


# ---------------------------------------------------------------------------
# Source inventory
# ---------------------------------------------------------------------------


def _load_cached_inventory(
    input_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    destination = (
        output_root
        / "_source_inventory"
        / f"{input_path.stem}.json"
    )

    if not destination.is_file():
        raise BenchmarkConfigurationError(
            "Source Inventory not found for LiteParse run: "
            f"{destination}. Build the common Source Inventory "
            "before running the parser benchmark."
        )

    inventory = json.loads(
        destination.read_text(encoding="utf-8")
    )

    current_sha = _sha256(input_path)
    inventory_sha = inventory.get("sha256")

    if inventory_sha != current_sha:
        raise BenchmarkConfigurationError(
            "Source Inventory SHA-256 does not match the input PDF. "
            f"Inventory: {destination}. "
            "Rebuild the common Source Inventory before benchmarking."
        )

    return inventory


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _get_tesseract_version() -> str | None:
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = (result.stdout or result.stderr).splitlines()
        return first_line[0].strip() if first_line else None
    except Exception:
        return None


def _build_metrics(
    *,
    input_path: Path,
    profile: dict[str, Any],
    profile_name: str,
    inventory: dict[str, Any],
    artifact_result: dict[str, Any],
    ocr_decisions: dict[int, dict[str, Any]],
    image_enrichments: dict[str, dict[str, Any]],
    all_images: list[Any],
    liteparse_version: str | None,
    pipeline_seconds: float,
    page_count: int,
    resources: dict[str, Any],
    tokenizer_name: str,
    artifact_selected_list: list[str],
    run_log_path: Path | None,
    metrics_json_path: Path | None,
) -> dict[str, Any]:
    pages_needing_ocr = [
        pn for pn, info in ocr_decisions.items()
        if info.get("decision") == "full_page_ocr"
    ]
    pages_rotated = [
        pn for pn, info in ocr_decisions.items()
        if info.get("rotation_applied", 0) != 0
    ]

    reason_counter: Counter[str] = Counter()
    for info in ocr_decisions.values():
        for r in info.get("reasons", []):
            reason_counter[r] += 1

    all_enrichments = list(image_enrichments.values())
    images_detected = len(all_images)
    images_extracted = sum(
        1 for e in all_enrichments if not e.get("duplicate", False)
    )
    images_ocr_attempted = sum(
        1 for e in all_enrichments if e.get("ocr_attempted", False)
    )
    images_with_usable_text = sum(
        1 for e in all_enrichments if e.get("has_usable_text", False)
    )
    images_described = sum(
        1
        for e in all_enrichments
        if e.get("image_description")
    )

    source_summary = {
        k: v for k, v in inventory.items() if k != "per_page"
    }

    input_bytes = input_path.stat().st_size
    clean_bytes = artifact_result.get("output", {}).get("clean_markdown_bytes")
    size_ratio = round(input_bytes / clean_bytes, 6) if clean_bytes else None

    ocr_enabled = bool(profile.get("ocr_enabled", False))

    return {
        "benchmark": {
            "schema_version": 3,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "reference_tokenizer": tokenizer_name,
        },
        "run": {
            "parser": PARSER_NAME,
            "parser_display_name": PARSER_DISPLAY_NAME,
            "profile": profile_name,
            "verbose": False,
            "artifact_selection": artifact_selected_list,
            "resolved_config": profile,
            "versions": {
                "liteparse": liteparse_version,
                "transformers": _package_version(
                    "transformers"
                ),
                "torch": _package_version(
                    "torch"
                ),
                "tesseract": _get_tesseract_version(),
            },
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "document": {
            "id": input_path.stem,
            "file": input_path.name,
            "sha256": inventory.get("sha256"),
            "pages": page_count,
            "input_size_mb": inventory.get("file_size_mb"),
        },
        "source_pdf": source_summary,
        "processing": {
            **artifact_result["timing"],
            "pipeline_seconds": round(pipeline_seconds, 6),
            "pages_total": page_count,
            "pages_processed": page_count,
            "failed_pages": 0,
            "partial_pages": None,
            "empty_output_pages": artifact_result["empty_output_pages"],
            "pipeline_pages_per_second": (
                round(page_count / pipeline_seconds, 6)
                if pipeline_seconds > 0 else None
            ),
            "ocr": {
                "enabled": ocr_enabled,
                "engine": "tesseract" if ocr_enabled else None,
                "language": profile.get("ocr_language") if ocr_enabled else None,
                "dpi": profile.get("dpi") if ocr_enabled else None,
                "pages_needing_ocr": len(pages_needing_ocr),
                "pages_rotated": len(pages_rotated),
                "ocr_reason_counts": dict(reason_counter),
                "images_detected": images_detected,
                "images_extracted": images_extracted,
                "images_ocr_attempted": images_ocr_attempted,
                "images_with_usable_text": images_with_usable_text,
                "images_described": images_described,
            },
            "warnings_count": 0,
            "errors_count": 0,
        },
        "resources": resources,
        "content_elements": {
            **artifact_result["content_elements"],
        },
        "heuristics": artifact_result["heuristics"],
        "tokens": artifact_result["tokens"],
        "normalization": artifact_result["normalization"],
        "artifacts": artifact_result["artifacts"],
        "quality_eligibility": artifact_result["quality_eligibility"],
        "output": {
            **artifact_result["output"],
            "run_log": str(run_log_path) if run_log_path else None,
            "metrics_json": str(metrics_json_path) if metrics_json_path else None,
            "input_to_clean_markdown_size_ratio": size_ratio,
        },
    }


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------


def _resolve_profile_runtime(
    profile: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict(profile)

    configured_workers = int(
        resolved.get(
            "num_workers",
            2,
        )
    )

    if configured_workers <= 0:
        raise BenchmarkConfigurationError(
            "LiteParse num_workers must be greater than zero."
        )

    try:
        parallelism = resolve_parallelism(
            configured_workers
        )
    except ValueError as exc:
        raise BenchmarkConfigurationError(
            str(exc)
        ) from exc

    resolved["num_workers_configured"] = (
        configured_workers
    )
    resolved["available_logical_cpus"] = int(
        parallelism["available_logical_cpus"]
    )
    resolved["num_workers"] = int(
        parallelism["effective"]
    )
    resolved["parallelism_source"] = str(
        parallelism["source"]
    )

    return resolved


def _build_parser_config(profile: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs dict for liteparse.LiteParse() from a resolved profile."""
    ocr_enabled = bool(profile.get("ocr_enabled", False))

    config: dict[str, Any] = {
        "ocr_enabled": ocr_enabled,
        "output_format": "markdown",
        "image_mode": "off",
        "extract_images": True,
        "extract_links": bool(profile.get("extract_links", False)),
        "keep_headers_footers": bool(profile.get("keep_headers_footers", True)),
        "preserve_very_small_text": bool(profile.get("preserve_very_small_text", False)),
        "extract_annotations": bool(profile.get("extract_annotations", False)),
        "extract_form_fields": bool(profile.get("extract_form_fields", False)),
        "extract_structure_tree": bool(profile.get("extract_structure_tree", False)),
        "extract_document_metadata": bool(profile.get("extract_document_metadata", True)),
        "extract_vector_graphics": bool(profile.get("extract_vector_graphics", False)),
        "extract_text_metadata": bool(profile.get("extract_text_metadata", False)),
        "extract_screenshots": bool(profile.get("extract_screenshots", False)),
        "quiet": True,
        "continue_on_page_error": False,
        "ocr_server_url": None,
        "num_workers": int(profile.get("num_workers", 2)),
        "dpi": int(profile.get("dpi", 150)),
        "max_pages": 2000,
    }

    if ocr_enabled:
        config["ocr_language"] = str(
            profile.get("ocr_language", "por+eng")
        )

    tessdata = _find_tessdata_prefix()
    if tessdata:
        config["tessdata_path"] = tessdata

    return config


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _find_tessdata_prefix() -> str | None:
    import os

    prefix_env = os.environ.get("TESSDATA_PREFIX")
    if prefix_env and Path(prefix_env).is_dir():
        return prefix_env

    for candidate in _TESSDATA_CANDIDATES:
        if Path(candidate).is_dir():
            return candidate

    return None


def preflight_profile(
    profile_name: str,
    *,
    model_artifacts_override: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # Profile configuration
    try:
        profile = _resolve_profile_runtime(
            get_profile(
                PARSER_NAME,
                profile_name,
            )
        )
    except Exception as exc:
        checks.append(
            make_check(
                "profile configuration",
                "fail",
                f"{type(exc).__name__}: {exc}",
            )
        )
        return make_result(PARSER_NAME, profile_name, checks)

    checks.append(
        make_check("profile configuration", "pass", profile_name)
    )

    # Package version
    installed_version = _package_version("liteparse")
    if installed_version is None:
        checks.append(
            make_check(
                "liteparse version",
                "fail",
                "liteparse is not installed",
            )
        )
    elif installed_version != LITEPARSE_REQUIRED_VERSION:
        checks.append(
            make_check(
                "liteparse version",
                "fail",
                (
                    f"expected {LITEPARSE_REQUIRED_VERSION!r}, "
                    f"got {installed_version!r}"
                ),
            )
        )
    else:
        checks.append(
            make_check("liteparse version", "pass", installed_version)
        )

    # Transformers runtime required by local SmolVLM
    transformers_version = _package_version(
        "transformers"
    )

    if (
        transformers_version
        != TRANSFORMERS_REQUIRED_VERSION
    ):
        checks.append(
            make_check(
                "transformers version",
                "fail",
                (
                    "expected "
                    f"{TRANSFORMERS_REQUIRED_VERSION!r}, "
                    f"got {transformers_version!r}"
                ),
            )
        )
    else:
        checks.append(
            make_check(
                "transformers version",
                "pass",
                transformers_version,
            )
        )

    try:
        from transformers import (
            AutoModelForImageTextToText,
            AutoProcessor,
        )

        _ = (
            AutoModelForImageTextToText,
            AutoProcessor,
        )

    except Exception as exc:
        checks.append(
            make_check(
                "smolvlm transformers API",
                "fail",
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )
        )
    else:
        checks.append(
            make_check(
                "smolvlm transformers API",
                "pass",
                "AutoModelForImageTextToText",
            )
        )

    # CPU only
    device = str(profile.get("accelerator_device", "cpu"))
    checks.append(
        make_check(
            "cpu only",
            "pass" if device == "cpu" else "fail",
            device,
        )
    )

    # Remote services
    remote_enabled = bool(profile.get("remote_services_enabled", False))
    checks.append(
        make_check(
            "remote services disabled",
            "pass" if not remote_enabled else "fail",
            "local" if not remote_enabled else "remote services enabled",
        )
    )

    ocr_server = profile.get("ocr_server_url")
    checks.append(
        make_check(
            "ocr server url",
            "pass" if ocr_server is None else "fail",
            "none" if ocr_server is None else str(ocr_server),
        )
    )

    # Image extraction contract
    extract_images = bool(profile.get("extract_images", False))
    checks.append(
        make_check(
            "image extraction enabled",
            "pass" if extract_images else "fail",
            "enabled" if extract_images else "extract_images must be True",
        )
    )

    image_mode = str(profile.get("image_mode", ""))
    checks.append(
        make_check(
            "image mode",
            "pass" if image_mode == "off" else "fail",
            image_mode or "not set",
        )
    )

    # Workers
    configured_workers = int(
        profile["num_workers_configured"]
    )
    available_cpus = int(
        profile["available_logical_cpus"]
    )
    effective_workers = int(
        profile["num_workers"]
    )

    checks.append(
        make_check(
            "workers configured fallback",
            "pass",
            str(configured_workers),
        )
    )
    checks.append(
        make_check(
            "logical CPUs available",
            "pass" if available_cpus > 0 else "fail",
            str(available_cpus),
        )
    )
    checks.append(
        make_check(
            "workers effective",
            "pass" if effective_workers > 0 else "fail",
            str(effective_workers),
        )
    )

    # Tesseract (OCR profiles only)
    ocr_enabled = bool(profile.get("ocr_enabled", False))

    if ocr_enabled:
        from src.benchmark.external_tools import resolve_tesseract_executable
        tess_bin = resolve_tesseract_executable()
        checks.append(
            make_check(
                "tesseract executable",
                "pass" if tess_bin else "fail",
                tess_bin or "not found",
            )
        )

        tess_version = _get_tesseract_version()
        checks.append(
            make_check(
                "tesseract version",
                "pass" if tess_version else "warn",
                tess_version or "unavailable",
            )
        )

        tessdata_prefix = _find_tessdata_prefix()
        required_langs: list[str] = list(
            profile.get("tessdata_required", ["eng", "por", "osd"])
        )

        for lang in required_langs:
            if tessdata_prefix:
                traineddata = Path(tessdata_prefix) / f"{lang}.traineddata"
                exists = traineddata.is_file()
                detail = str(traineddata)
            else:
                exists = False
                detail = "tessdata directory not found"

            checks.append(
                make_check(
                    f"tessdata {lang}",
                    "pass" if exists else "fail",
                    detail,
                )
            )

        ocr_language = str(profile.get("ocr_language", ""))
        checks.append(
            make_check(
                "ocr language",
                "pass" if ocr_language else "fail",
                ocr_language or "not set",
            )
        )

        dpi = int(profile.get("dpi", 0))
        checks.append(
            make_check(
                "dpi",
                "pass" if dpi >= 150 else "fail",
                str(dpi),
            )
        )

    # Visual profile (SmolVLM)
    if bool(profile.get("image_description", False)):
        prompt = str(
            profile.get("image_description_prompt", "")
        ).strip()
        checks.append(
            make_check(
                "image description prompt",
                "pass" if prompt else "fail",
                "configured" if prompt else "empty",
            )
        )

        fallback_only = bool(
            profile.get("image_description_fallback_only", False)
        )
        checks.append(
            make_check(
                "image description locality",
                "pass" if not remote_enabled else "fail",
                "local" if not remote_enabled else "remote enabled",
            )
        )

        effective_artifacts = (
            model_artifacts_override
            if model_artifacts_override is not None
            else DEFAULT_MODEL_ARTIFACTS
        )
        smolvlm_path = effective_artifacts / SMOLVLM_ARTIFACT_DIRECTORY
        checks.append(
            make_check(
                "smolvlm model",
                "pass" if smolvlm_path.is_dir() else "fail",
                str(smolvlm_path),
            )
        )

    return make_result(PARSER_NAME, profile_name, checks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LiteParse benchmark adapter v2.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/outputs"),
    )
    parser.add_argument(
        "--profile",
        default="native",
    )
    parser.add_argument(
        "--model-artifacts-path",
        type=Path,
        default=None,
        help="Override for pre-downloaded model artifacts directory.",
    )

    add_runtime_arguments(parser)
    args = parser.parse_args()

    try:
        args.artifact_policy = ArtifactPolicy.from_cli(args.artifacts)
    except ArtifactSelectionError as exc:
        parser.error(str(exc))

    return args


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main() -> None:
    import liteparse as _liteparse
    from src.benchmark.artifact_contract import ParserArtifactInput, join_page_texts
    from src.benchmark.artifacts import finalize_artifacts
    from src.benchmark.config import (
        get_normalization_config,
        get_reference_tokenizer,
    )
    from src.benchmark.metrics_writer import write_json
    from src.benchmark.paths import build_output_paths
    from src.benchmark.resource_monitor import ResourceMonitor
    from src.benchmark.runtime_io import parser_output_context

    args = parse_args()
    artifact_policy: ArtifactPolicy = args.artifact_policy
    input_path = args.input.resolve()

    if not input_path.is_file():
        raise SystemExit(f"Input not found: {input_path}")

    profile = _resolve_profile_runtime(
        get_profile(
            PARSER_NAME,
            args.profile,
        )
    )
    normalization_config = get_normalization_config()
    tokenizer_name = get_reference_tokenizer()

    paths = build_output_paths(
        args.output_root,
        PARSER_NAME,
        input_path.stem,
        args.profile,
    )

    inventory = _load_cached_inventory(input_path, args.output_root)
    page_count = int(inventory["pages"])

    liteparse_version = _package_version("liteparse")
    ocr_enabled = bool(profile.get("ocr_enabled", False))
    ocr_language = str(profile.get("ocr_language", "por+eng"))
    image_description = bool(profile.get("image_description", False))
    model_root = (
        args.model_artifacts_path
        if args.model_artifacts_path is not None
        else DEFAULT_MODEL_ARTIFACTS
    )

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK V2")
    print("=" * 72)
    print(f"Parser:        {PARSER_DISPLAY_NAME}")
    print(f"Version:       {liteparse_version}")
    print(f"Input:         {input_path}")
    print(f"Profile:       {args.profile}")
    print(f"OCR enabled:   {ocr_enabled}")
    print(f"OCR language:  {ocr_language if ocr_enabled else 'N/A'}")
    print(f"DPI:           {profile.get('dpi', 150)}")
    print(
        "Workers:       "
        f"{profile['num_workers']} "
        f"(configured={profile['num_workers_configured']}, "
        f"available={profile['available_logical_cpus']}, "
        f"source={profile['parallelism_source']})"
    )
    print(f"Visual desc:   {image_description}")
    print(f"Tokenizer:     {tokenizer_name}")
    print(f"Output:        {paths.output_dir}")
    print(
        "Artifacts:     "
        + ", ".join(artifact_policy.as_list())
    )
    print(f"Verbose:       {args.verbose}")
    print("=" * 72)

    monitor = ResourceMonitor()
    pipeline_started = perf_counter()
    monitor.start()

    try:
        with parser_output_context(
            run_log_path=paths.run_log,
            keep_run_log=artifact_policy.includes("run.log"),
            verbose=args.verbose,
        ):
            with TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                image_output_dir = tmp_path / "images"
                image_output_dir.mkdir()

                parser_config = _build_parser_config(profile)
                parser_config["image_output_dir"] = image_output_dir

                # ── OCR routing pre-pass ──────────────────────────────────
                ocr_decisions: dict[int, dict[str, Any]] = {}
                pages_needing_ocr: list[int] = []

                if ocr_enabled:
                    complexity_parser = _liteparse.LiteParse(
                        ocr_enabled=False,
                        quiet=True,
                        max_pages=2000,
                    )
                    complexity_results = complexity_parser.is_complex(
                        input_path
                    )
                    for cr in complexity_results:
                        reasons = list(
                            getattr(cr, "reasons", []) or []
                        )
                        page_num = int(
                            getattr(cr, "page_number", 0)
                        )
                        needs_full_ocr = any(
                            r in FULL_PAGE_OCR_REASONS for r in reasons
                        )
                        decision = (
                            "full_page_ocr"
                            if needs_full_ocr
                            else "native"
                        )
                        if needs_full_ocr:
                            pages_needing_ocr.append(page_num)
                        ocr_decisions[page_num] = {
                            "decision": decision,
                            "reasons": reasons,
                            "rotation_applied": 0,
                        }

                # ── Native parse ──────────────────────────────────────────
                native_config = dict(parser_config)
                native_config["ocr_enabled"] = False
                native_parser = _liteparse.LiteParse(**native_config)
                native_result = native_parser.parse(input_path)

                # Write raw.md from native parse
                raw_text = str(
                    getattr(native_result, "text", "") or ""
                )
                if artifact_policy.includes("raw.md"):
                    paths.raw_markdown.write_text(
                        raw_text, encoding="utf-8"
                    )

                native_page_texts = _extract_page_texts(
                    native_result, page_count
                )

                # ── Selective OCR for pages that need it ──────────────────
                ocr_page_texts: dict[int, str] = {}

                if ocr_enabled and pages_needing_ocr:
                    target_str = ",".join(
                        str(p) for p in sorted(pages_needing_ocr)
                    )
                    ocr_config = dict(parser_config)
                    ocr_config["ocr_enabled"] = True
                    ocr_config["dpi"] = int(profile.get("dpi", 300))
                    ocr_config["target_pages"] = target_str

                    ocr_parser = _liteparse.LiteParse(**ocr_config)
                    ocr_result = ocr_parser.parse(input_path)
                    ocr_page_texts_raw = _extract_page_texts(
                        ocr_result, page_count
                    )
                    for pn in pages_needing_ocr:
                        idx = pn - 1
                        if idx < len(ocr_page_texts_raw):
                            ocr_page_texts[pn] = ocr_page_texts_raw[idx]

                # Merge native + OCR page texts
                merged_page_texts = _merge_page_texts(
                    native_page_texts,
                    ocr_page_texts,
                    page_count,
                )

                # ── Collect all images ────────────────────────────────────
                all_images: list[Any] = list(
                    getattr(native_result, "images", []) or []
                )

                # ── Image enrichment ──────────────────────────────────────
                image_enrichments: dict[str, dict[str, Any]] = {}

                if ocr_enabled and all_images:
                    image_enrichments = _process_document_images(
                        all_images,
                        profile,
                        image_output_dir,
                        model_root,
                        ocr_language=ocr_language,
                    )

                # ── Build page texts with enrichments ─────────────────────
                page_texts: list[str] = []
                for i, text in enumerate(merged_page_texts):
                    page_num = i + 1
                    page_images = [
                        img for img in all_images
                        if getattr(img, "page_num", None) == page_num
                    ]
                    enriched = _build_page_text_with_enrichments(
                        text,
                        page_images,
                        image_enrichments,
                    )
                    page_texts.append(enriched)

                # ── Structured output ─────────────────────────────────────
                parser_page_elements, parser_native_pages = (
                    _build_structured_output(
                        page_texts,
                        ocr_decisions,
                        image_enrichments,
                        all_images,
                        page_count,
                    )
                )

    except Exception:
        monitor.stop()
        raise

    pipeline_seconds = perf_counter() - pipeline_started

    artifact_input = ParserArtifactInput(
        native_markdown=join_page_texts(page_texts),
        source_page_markdown=page_texts,
        enriched_page_markdown=None,
        page_mapping_status="complete",
        parser_page_elements=parser_page_elements,
        parser_native_pages=parser_native_pages,
        derived_content_by_page=[[] for _ in page_texts],
        raw_origin_kind="adapter_assembled_declared",
        raw_origin_details="page_texts join",
    )

    artifact_result = finalize_artifacts(
        paths=paths,
        document_id=input_path.stem,
        source_file=input_path.name,
        parser_name=PARSER_NAME,
        profile_name=args.profile,
        artifact_input=artifact_input,
        tokenizer_name=tokenizer_name,
        normalization_config=normalization_config,
        artifact_policy=artifact_policy,
    )

    resources = monitor.stop()

    metrics = _build_metrics(
        input_path=input_path,
        profile=profile,
        profile_name=args.profile,
        inventory=inventory,
        artifact_result=artifact_result,
        ocr_decisions=ocr_decisions,
        image_enrichments=image_enrichments,
        all_images=all_images,
        liteparse_version=liteparse_version,
        pipeline_seconds=pipeline_seconds,
        page_count=page_count,
        resources=resources,
        tokenizer_name=tokenizer_name,
        artifact_selected_list=artifact_policy.as_list(),
        run_log_path=(
            paths.run_log
            if artifact_policy.includes("run.log")
            else None
        ),
        metrics_json_path=(
            paths.metrics_json
            if artifact_policy.includes("metrics.json")
            else None
        ),
    )

    if artifact_policy.includes("metrics.json"):
        write_json(paths.metrics_json, metrics)


if __name__ == "__main__":
    main()
