from __future__ import annotations

import re


HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s+\S"
)

LIST_RE = re.compile(
    r"^\s*(?:[-+*]|\d+[.)])\s+\S"
)

IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\([^)]+\)"
)

TABLE_SEPARATOR_RE = re.compile(
    r"""
    ^\s*
    \|?
    \s*:?-{3,}:?\s*
    (?:\|
        \s*:?-{3,}:?\s*
    )+
    \|?
    \s*$
    """,
    re.VERBOSE,
)

FENCED_CODE_RE = re.compile(
    r"^\s*```"
)

HTML_IMAGE_PLACEHOLDER_RE = re.compile(
    r"<!--\s*(?:image|picture)[^>]*-->",
    re.IGNORECASE,
)


def analyze_markdown_content(
    markdown: str,
) -> dict[str, int]:
    lines = markdown.splitlines()

    headings = 0
    list_items = 0
    tables = 0
    fenced_code_markers = 0

    for line in lines:
        if HEADING_RE.match(line):
            headings += 1

        if LIST_RE.match(line):
            list_items += 1

        if TABLE_SEPARATOR_RE.match(line):
            tables += 1

        if FENCED_CODE_RE.match(line):
            fenced_code_markers += 1

    markdown_images = len(
        IMAGE_RE.findall(markdown)
    )

    image_placeholders = len(
        HTML_IMAGE_PLACEHOLDER_RE.findall(
            markdown
        )
    )

    return {
        "tables": tables,
        "image_references": (
            markdown_images
        ),
        "image_placeholders": (
            image_placeholders
        ),
        "headings": headings,
        "list_items": list_items,
        "code_blocks": (
            fenced_code_markers // 2
        ),
    }
