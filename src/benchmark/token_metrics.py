from __future__ import annotations

from typing import Any

import tiktoken


class TokenCounter:
    def __init__(
        self,
        encoding_name: str,
    ) -> None:
        self.encoding_name = encoding_name

        self.encoding = (
            tiktoken.get_encoding(
                encoding_name
            )
        )

    def count(
        self,
        text: str,
    ) -> int:
        return len(
            self.encoding.encode(
                text,
                disallowed_special=(),
            )
        )


def build_token_metrics(
    *,
    raw_text: str,
    clean_text: str,
    enriched_text: str | None = None,
    page_count: int,
    tokenizer_name: str,
    removed_records: list[
        dict[str, Any]
    ]
    | None = None,
) -> dict[str, object]:
    counter = TokenCounter(
        tokenizer_name
    )

    raw_tokens = counter.count(
        raw_text
    )

    clean_tokens = counter.count(
        clean_text
    )

    enriched_tokens = (
        counter.count(enriched_text)
        if enriched_text is not None
        else None
    )

    tokens_removed = max(
        raw_tokens - clean_tokens,
        0,
    )

    reduction_percent = (
        (
            tokens_removed
            / raw_tokens
        )
        * 100
        if raw_tokens > 0
        else 0.0
    )

    header_footer_tokens = 0
    other_removed_tokens = 0

    for record in (
        removed_records or []
    ):
        text = str(
            record.get("text", "")
        )

        removed_tokens = counter.count(
            text
        )

        record_type = str(
            record.get("type", "")
        ).lower()

        if record_type in {
            "header",
            "footer",
            "repeated_header",
            "repeated_footer",
        }:
            header_footer_tokens += (
                removed_tokens
            )
        else:
            other_removed_tokens += (
                removed_tokens
            )

    return {
        "reference": {
            "tokenizer": tokenizer_name,

            "raw_markdown_tokens": (
                raw_tokens
            ),

            "clean_markdown_tokens": (
                clean_tokens
            ),

            "enriched_markdown_tokens": (
                enriched_tokens
            ),

            "derived_tokens": None,

            "tokens_removed": (
                tokens_removed
            ),

            "token_reduction_percent": round(
                reduction_percent,
                3,
            ),

            "estimated_header_footer_record_tokens": (
                header_footer_tokens
            ),

            "estimated_other_removed_record_tokens": (
                other_removed_tokens
            ),

            "raw_tokens_per_page": round(
                (
                    raw_tokens / page_count
                    if page_count > 0
                    else 0.0
                ),
                3,
            ),

            "clean_tokens_per_page": round(
                (
                    clean_tokens
                    / page_count
                    if page_count > 0
                    else 0.0
                ),
                3,
            ),
        },

        "deployment": {
            "model": None,
            "tokenizer": None,
            "raw_markdown_tokens": None,
            "clean_markdown_tokens": None,
        },
    }
