from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VisualRequest:
    request_id: str       # e.g. "p4-picture-2"
    operation: str        # "ocr_and_describe"
    image_base64: str     # PNG bytes encoded as base64; cleared after send
    language: str         # e.g. "por"
    prompt: str
    page_number: int
    region_id: str


@dataclass
class VisualResponse:
    request_id: str
    status: str           # "success" | "error"
    ocr_text: str
    description: str
    ocr_engine: str
    ocr_model: str
    description_engine: str
    description_model: str
    error_detail: str = ""
