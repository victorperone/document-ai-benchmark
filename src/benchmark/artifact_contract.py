from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParserArtifactInput:
    native_markdown: str | None
    source_page_markdown: list[str] | None
    enriched_page_markdown: list[str] | None
    page_mapping_status: str  # "complete" | "partial" | "unavailable"
    parser_page_elements: list[dict[str, Any]]
    parser_native_pages: list[dict[str, Any]]
    derived_content_by_page: list[list[dict[str, Any]]]
    raw_origin_kind: str
    raw_origin_details: str


def join_page_texts(page_texts: list[str]) -> str:
    if not page_texts:
        return ""
    return (
        "\n\n".join(p.rstrip() for p in page_texts).rstrip() + "\n"
    )
