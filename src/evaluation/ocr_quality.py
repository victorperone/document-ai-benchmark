from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Sequence


# ---------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------

_MARKDOWN_TRANSLATION = str.maketrans(
    {
        "|": " ",
        "*": " ",
        "_": " ",
        "#": " ",
        "`": " ",
        ">": " ",
        "[": " ",
        "]": " ",
        "\u2022": " ",
    }
)


def normalize_ocr_text(
    text: str,
) -> str:
    """
    Normalize parser Markdown and ground-truth text into a
    comparable textual representation.

    Important:
    accents are deliberately preserved.

    This normalization removes Markdown presentation noise but
    does not strip diacritics, numbers, currency punctuation,
    decimal separators, or hyphens.
    """

    value = unicodedata.normalize(
        "NFKC",
        text,
    )

    value = value.translate(
        _MARKDOWN_TRANSLATION
    )

    # Remove Markdown table separator rows such as:
    #
    # --- --- ---
    # :--- ---:
    #
    # without removing meaningful hyphens from identifiers.
    value = re.sub(
        r"(?m)^\s*(?:"
        r":?-{3,}:?\s*){2,}$",
        " ",
        value,
    )

    # Case differences are not considered meaningful OCR
    # errors for this normalized benchmark metric.
    value = value.casefold()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


# ---------------------------------------------------------------------
# Word tokenization
# ---------------------------------------------------------------------

_WORD_RE = re.compile(
    r"[^\W_]+(?:[-'][^\W_]+)*",
    flags=re.UNICODE,
)


def tokenize_words(
    text: str,
) -> list[str]:
    return _WORD_RE.findall(
        normalize_ocr_text(
            text
        )
    )


# ---------------------------------------------------------------------
# Levenshtein distance
# ---------------------------------------------------------------------

def levenshtein_distance(
    reference: Sequence[Any],
    hypothesis: Sequence[Any],
) -> int:
    """
    Memory-efficient Levenshtein edit distance.

    Works both for strings (characters) and lists (words).
    """

    if len(reference) < len(hypothesis):
        reference, hypothesis = (
            hypothesis,
            reference,
        )

    previous = list(
        range(
            len(hypothesis) + 1
        )
    )

    for row_index, ref_item in enumerate(
        reference,
        start=1,
    ):
        current = [
            row_index
        ]

        for column_index, hyp_item in enumerate(
            hypothesis,
            start=1,
        ):
            insertion = (
                current[
                    column_index - 1
                ]
                + 1
            )

            deletion = (
                previous[
                    column_index
                ]
                + 1
            )

            substitution = (
                previous[
                    column_index - 1
                ]
                + (
                    0
                    if ref_item
                    == hyp_item
                    else 1
                )
            )

            current.append(
                min(
                    insertion,
                    deletion,
                    substitution,
                )
            )

        previous = current

    return previous[-1]


def error_rate(
    distance: int,
    reference_length: int,
) -> float:
    if reference_length == 0:
        return (
            0.0
            if distance == 0
            else 1.0
        )

    return (
        distance
        / reference_length
    )


# ---------------------------------------------------------------------
# CER / WER
# ---------------------------------------------------------------------

def calculate_cer(
    reference: str,
    hypothesis: str,
) -> dict[str, Any]:
    reference_text = (
        normalize_ocr_text(
            reference
        )
    )

    hypothesis_text = (
        normalize_ocr_text(
            hypothesis
        )
    )

    distance = levenshtein_distance(
        reference_text,
        hypothesis_text,
    )

    return {
        "distance": distance,
        "reference_characters": len(
            reference_text
        ),
        "hypothesis_characters": len(
            hypothesis_text
        ),
        "rate": error_rate(
            distance,
            len(reference_text),
        ),
    }


def calculate_wer(
    reference: str,
    hypothesis: str,
) -> dict[str, Any]:
    reference_words = (
        tokenize_words(
            reference
        )
    )

    hypothesis_words = (
        tokenize_words(
            hypothesis
        )
    )

    distance = levenshtein_distance(
        reference_words,
        hypothesis_words,
    )

    return {
        "distance": distance,
        "reference_words": len(
            reference_words
        ),
        "hypothesis_words": len(
            hypothesis_words
        ),
        "rate": error_rate(
            distance,
            len(reference_words),
        ),
    }


# ---------------------------------------------------------------------
# Occurrence recall
# ---------------------------------------------------------------------

def occurrence_recall(
    reference_values: list[str],
    hypothesis_values: list[str],
) -> dict[str, Any]:
    reference_counter = Counter(
        reference_values
    )

    hypothesis_counter = Counter(
        hypothesis_values
    )

    expected = sum(
        reference_counter.values()
    )

    matched = sum(
        min(
            count,
            hypothesis_counter.get(
                value,
                0,
            ),
        )
        for value, count
        in reference_counter.items()
    )

    recall = (
        matched / expected
        if expected
        else None
    )

    missing: list[str] = []

    for value, count in (
        reference_counter.items()
    ):
        missing_count = max(
            0,
            count
            - hypothesis_counter.get(
                value,
                0,
            ),
        )

        missing.extend(
            [value]
            * missing_count
        )

    return {
        "expected": expected,
        "matched": matched,
        "missing": missing,
        "recall": recall,
    }


# ---------------------------------------------------------------------
# Accented-token recall
# ---------------------------------------------------------------------

def has_diacritic(
    token: str,
) -> bool:
    decomposed = (
        unicodedata.normalize(
            "NFD",
            token,
        )
    )

    return any(
        unicodedata.combining(
            character
        )
        for character
        in decomposed
    )


def extract_accented_tokens(
    text: str,
) -> list[str]:
    return [
        token
        for token
        in tokenize_words(
            text
        )
        if has_diacritic(
            token
        )
    ]


# ---------------------------------------------------------------------
# Numeric information
# ---------------------------------------------------------------------

_NUMERIC_RE = re.compile(
    r"(?<![\w])"
    r"\d"
    r"[\d.,/%-]*",
    flags=re.UNICODE,
)


def extract_numeric_tokens(
    text: str,
) -> list[str]:
    normalized = (
        normalize_ocr_text(
            text
        )
    )

    values: list[str] = []

    for match in _NUMERIC_RE.finditer(
        normalized
    ):
        value = (
            match.group(0)
            .rstrip(
                ".,;:"
            )
        )

        if value:
            values.append(
                value
            )

    return values


# ---------------------------------------------------------------------
# Currency values
# ---------------------------------------------------------------------

_CURRENCY_RE = re.compile(
    r"r\$\s*"
    r"\d[\d.,]*",
    flags=re.IGNORECASE,
)


def extract_currency_values(
    text: str,
) -> list[str]:
    normalized = (
        normalize_ocr_text(
            text
        )
    )

    values: list[str] = []

    for match in _CURRENCY_RE.finditer(
        normalized
    ):
        value = (
            match.group(0)
            .replace(
                " ",
                "",
            )
            .rstrip(
                ".,;:"
            )
        )

        values.append(
            value
        )

    return values


# ---------------------------------------------------------------------
# Regression identifiers
# ---------------------------------------------------------------------

_IDENTIFIER_RE = re.compile(
    r"\bregressao-\d{2}-2026\b",
    flags=re.IGNORECASE,
)


def extract_regression_ids(
    text: str,
) -> list[str]:
    normalized = (
        normalize_ocr_text(
            text
        )
    )

    return [
        value.casefold()
        for value
        in _IDENTIFIER_RE.findall(
            normalized
        )
    ]


# ---------------------------------------------------------------------
# Critical terms
# ---------------------------------------------------------------------

DEFAULT_CRITICAL_TERMS = (
    "ação",
    "informação",
    "configuração",
    "produção",
    "operação",
    "aprovação",
    "aprovado para teste",
)


def critical_term_recall(
    reference: str,
    hypothesis: str,
    terms: Sequence[str] = (
        DEFAULT_CRITICAL_TERMS
    ),
) -> dict[str, Any]:
    normalized_reference = (
        normalize_ocr_text(
            reference
        )
    )

    normalized_hypothesis = (
        normalize_ocr_text(
            hypothesis
        )
    )

    reference_values: list[str] = []
    hypothesis_values: list[str] = []

    for term in terms:
        normalized_term = (
            normalize_ocr_text(
                term
            )
        )

        reference_count = (
            normalized_reference.count(
                normalized_term
            )
        )

        hypothesis_count = (
            normalized_hypothesis.count(
                normalized_term
            )
        )

        reference_values.extend(
            [normalized_term]
            * reference_count
        )

        hypothesis_values.extend(
            [normalized_term]
            * hypothesis_count
        )

    return occurrence_recall(
        reference_values,
        hypothesis_values,
    )


# ---------------------------------------------------------------------
# Complete quality evaluation
# ---------------------------------------------------------------------

def evaluate_ocr_text(
    *,
    reference: str,
    hypothesis: str,
) -> dict[str, Any]:
    cer = calculate_cer(
        reference,
        hypothesis,
    )

    wer = calculate_wer(
        reference,
        hypothesis,
    )

    accented = occurrence_recall(
        extract_accented_tokens(
            reference
        ),
        extract_accented_tokens(
            hypothesis
        ),
    )

    numeric = occurrence_recall(
        extract_numeric_tokens(
            reference
        ),
        extract_numeric_tokens(
            hypothesis
        ),
    )

    currency = occurrence_recall(
        extract_currency_values(
            reference
        ),
        extract_currency_values(
            hypothesis
        ),
    )

    identifiers = occurrence_recall(
        extract_regression_ids(
            reference
        ),
        extract_regression_ids(
            hypothesis
        ),
    )

    critical = critical_term_recall(
        reference,
        hypothesis,
    )

    return {
        "cer": cer,
        "wer": wer,
        "accented_token_recall": (
            accented
        ),
        "numeric_token_recall": (
            numeric
        ),
        "currency_value_recall": (
            currency
        ),
        "regression_id_recall": (
            identifiers
        ),
        "critical_term_recall": (
            critical
        ),
    }
