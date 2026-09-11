"""Data contract between parser adapters and the artifact pipeline.

Defines the input dataclass that every adapter must populate before calling
``finalize_artifacts()``, together with the closed-enum constants that gate
which combinations are legal.
"""

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
    """All parser-produced data needed to materialise benchmark artifacts.

    Adapters fill this dataclass and pass it to ``finalize_artifacts()``.
    The combination of ``page_mapping_status`` and the list lengths must
    satisfy the cardinality rules enforced there.

    Attributes:
        native_markdown: Raw Markdown exactly as the parser produced it,
            before any normalisation.  ``None`` when the parser produced no
            output at all.
        source_page_markdown: One Markdown string per page, required when
            ``page_mapping_status == "complete"``.  ``None`` otherwise.
        enriched_page_markdown: Optional parser-supplied enriched Markdown,
            one string per page.  When present the lengths must match
            ``parser_page_elements``.
        page_mapping_status: ``"complete"`` when every page is individually
            mapped, ``"unavailable"`` when the parser cannot provide per-page
            boundaries.  See ``VALID_PAGE_MAPPING_STATUS``.
        parser_page_elements: Structured element list for each page, as
            returned by the parser.  Length determines the canonical page
            count.
        parser_native_pages: Native page-level objects from the parser.
            Must have the same length as ``parser_page_elements``.
        derived_content_by_page: Additional items derived per page (e.g.
            injected captions or charts).  Must have the same length as
            ``parser_page_elements`` when the mapping is complete.
        raw_origin_kind: How ``native_markdown`` was produced.  Must be a
            member of ``VALID_RAW_ORIGIN_KIND``.
        raw_origin_details: Free-form human-readable description of the
            raw origin (logged in metrics).
        enriched_document_markdown: Optional single-stream enriched
            Markdown.  When supplied it takes precedence over the per-page
            variant in ``finalize_artifacts()``.
        content_expected: ``True`` when the source document is known to
            contain readable content and the adapter expects non-empty
            output.  ``None`` lets ``finalize_artifacts`` infer from the
            text.
        content_expectation_reason: Human-readable explanation for the
            ``content_expected`` value (logged in metrics).
    """

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
    """Join per-page Markdown strings into one document string.

    Pages are separated by a blank line.  Trailing whitespace on each page
    is stripped before joining, and the result ends with exactly one newline.

    Args:
        page_texts: Ordered list of per-page Markdown strings.

    Returns:
        A single Markdown string, or an empty string when the list is empty.
    """
    if not page_texts:
        return ""
    return (
        "\n\n".join(p.rstrip() for p in page_texts).rstrip() + "\n"
    )
