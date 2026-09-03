from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_PAGE_MAPPING_STATUS: frozenset[str] = frozenset({"complete", "unavailable"})
# "partial" não é suportado — requer PageMarkdown(page_number, markdown) para mapeamento inequívoco.

VALID_RAW_ORIGIN_KIND: frozenset[str] = frozenset({
    "parser_native_exact",
    "parser_native_links_relocated",
    "parser_native_per_page_join",
    "adapter_assembled_declared",
    "unavailable",
})


@dataclass(frozen=True)
class ParserArtifactInput:
    native_markdown: str | None
    source_page_markdown: list[str] | None
    enriched_page_markdown: list[str] | None
    page_mapping_status: str  # "complete" | "unavailable" — see VALID_PAGE_MAPPING_STATUS
    parser_page_elements: list[dict[str, Any]]
    parser_native_pages: list[dict[str, Any]]
    derived_content_by_page: list[list[dict[str, Any]]]
    raw_origin_kind: str
    raw_origin_details: str
    # Global enriched Markdown is used when the parser cannot provide a
    # trustworthy page mapping. It intentionally has precedence over the
    # per-page representation in finalize_artifacts().
    enriched_document_markdown: str | None = None
    # Adapters set this from the objective source inventory. None keeps the
    # contract backwards compatible and lets finalize_artifacts infer it from
    # the supplied text.
    content_expected: bool | None = None
    content_expectation_reason: str = ""


def join_page_texts(page_texts: list[str]) -> str:
    if not page_texts:
        return ""
    return (
        "\n\n".join(p.rstrip() for p in page_texts).rstrip() + "\n"
    )
