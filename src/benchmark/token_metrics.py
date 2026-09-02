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
    source_text: str,
    clean_text: str,
    enriched_text: str | None = None,
    page_count: int,
    tokenizer_name: str,
    removed_records: list[
        dict[str, Any]
    ]
    | None = None,
) -> dict[str, object]:
    """Compute token metrics for the three canonical text representations.

    raw_text    — native_markdown (source of raw.md)
    source_text — join(source_page_markdown) (normalization input)
    clean_text  — normalized output (source of document.md)
    """
    counter = TokenCounter(
        tokenizer_name
    )

    raw_tokens = counter.count(raw_text)
    source_tokens = counter.count(source_text)
    clean_tokens = counter.count(clean_text)

    enriched_tokens = (
        counter.count(enriched_text)
        if enriched_text is not None
        else None
    )

    # normalization_tokens_removed: effect of normalizer on source pages
    normalization_tokens_removed = max(source_tokens - clean_tokens, 0)
    # tokens_removed: alias for backward compatibility
    tokens_removed = normalization_tokens_removed
    # raw_to_clean_token_delta: quantitative delta (not normalization alone)
    raw_to_clean_token_delta = raw_tokens - clean_tokens

    normalization_reduction_percent = (
        (normalization_tokens_removed / source_tokens) * 100
        if source_tokens > 0
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

            "raw_markdown_tokens": raw_tokens,
            "source_markdown_tokens": source_tokens,
            "clean_markdown_tokens": clean_tokens,
            "enriched_markdown_tokens": enriched_tokens,
            "derived_tokens": None,

            "normalization_tokens_removed": normalization_tokens_removed,
            "tokens_removed": tokens_removed,
            "raw_to_clean_token_delta": raw_to_clean_token_delta,

            "token_reduction_percent": round(
                normalization_reduction_percent,
                3,
            ),

            "estimated_header_footer_record_tokens": (
                header_footer_tokens
            ),

            "estimated_other_removed_record_tokens": (
                other_removed_tokens
            ),

            "raw_tokens_per_page": round(
                raw_tokens / page_count
                if page_count > 0
                else 0.0,
                3,
            ),

            "source_tokens_per_page": round(
                source_tokens / page_count
                if page_count > 0
                else 0.0,
                3,
            ),

            "clean_tokens_per_page": round(
                clean_tokens / page_count
                if page_count > 0
                else 0.0,
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
