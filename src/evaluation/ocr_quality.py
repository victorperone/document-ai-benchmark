"""OCR quality metrics for the document-AI benchmark.

Provides text normalisation, tokenisation, and a suite of metrics used
to compare parser output against ground-truth text:

- Character Error Rate (CER) and Word Error Rate (WER) via Levenshtein
  edit distance.
- Occurrence recall for accented tokens, numeric tokens, BRL currency
  values, and regression identifiers.
- Critical-term recall for a configurable set of Portuguese terms.
- A composite ``evaluate_ocr_text`` function that returns all of the above
  in a single structured result.
"""
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
    """Normalize parser Markdown and ground-truth text for metric comparison.

    Applies NFKC Unicode normalisation, strips Markdown presentation
    characters (``|``, ``*``, ``_``, ``#``, backtick, ``>``, ``[``, ``]``,
    bullet), removes Markdown table-separator rows, case-folds the result,
    and collapses whitespace. Accents are deliberately preserved.

    Args:
        text: Raw text from a parser or from the ground-truth corpus.

    Returns:
        Normalised, case-folded string ready for metric computation.
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
    """Tokenize text into a list of normalised word tokens.

    Normalises ``text`` first via ``normalize_ocr_text``, then extracts
    tokens matching ``_WORD_RE`` (Unicode word characters including
    internal hyphens and apostrophes).

    Args:
        text: Raw text to tokenize.

    Returns:
        List of lowercase word strings. Empty list if no tokens are found.
    """
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
    """Compute the Levenshtein edit distance between two sequences.

    Uses a single-row DP approach (O(min(m, n)) space). Works for both
    strings (character-level CER) and token lists (word-level WER).

    Args:
        reference: The ground-truth sequence.
        hypothesis: The predicted sequence.

    Returns:
        Minimum number of single-element insertions, deletions, or
        substitutions needed to transform ``hypothesis`` into ``reference``.
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
    """Compute the normalised error rate from an edit distance.

    Args:
        distance: Levenshtein edit distance between reference and hypothesis.
        reference_length: Number of elements in the reference sequence.

    Returns:
        ``distance / reference_length``, clamped to ``[0.0, …]``. Returns
        ``0.0`` when both ``distance`` and ``reference_length`` are zero;
        returns ``1.0`` when ``distance > 0`` and ``reference_length == 0``.
    """
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
    """Calculate Character Error Rate between reference and hypothesis.

    Both strings are normalised before comparison.

    Args:
        reference: Ground-truth text.
        hypothesis: Parser output text.

    Returns:
        Dict with keys:
            ``distance``: character-level edit distance (int).
            ``reference_characters``: length of normalised reference (int).
            ``hypothesis_characters``: length of normalised hypothesis (int).
            ``rate``: CER as a float in ``[0.0, …]``.
    """
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
    """Calculate Word Error Rate between reference and hypothesis.

    Both strings are normalised and tokenised before comparison.

    Args:
        reference: Ground-truth text.
        hypothesis: Parser output text.

    Returns:
        Dict with keys:
            ``distance``: word-level edit distance (int).
            ``reference_words``: number of tokens in normalised reference (int).
            ``hypothesis_words``: number of tokens in normalised hypothesis (int).
            ``rate``: WER as a float in ``[0.0, …]``.
    """
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
    """Compute multiset recall: how many expected items appear in the hypothesis.

    Each item in ``reference_values`` must be matched at most once by an
    equal item in ``hypothesis_values``, respecting duplicates via Counter
    arithmetic.

    Args:
        reference_values: Expected values (may contain duplicates).
        hypothesis_values: Values produced by the parser.

    Returns:
        Dict with keys:
            ``expected``: total count of reference values (int).
            ``matched``: count of reference values found in the hypothesis (int).
            ``missing``: list of reference values absent from the hypothesis.
            ``recall``: ``matched / expected`` as a float, or ``None`` when
                ``expected`` is zero.
    """
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
    """Return True if the token contains at least one combining diacritic.

    Decomposes the string to NFD form and checks for Unicode combining
    characters.

    Args:
        token: A single word token.

    Returns:
        ``True`` if any character in the NFD decomposition has a non-zero
        Unicode combining class; ``False`` otherwise.
    """
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
    """Extract all word tokens that contain at least one diacritic.

    Args:
        text: Raw text to scan.

    Returns:
        List of normalised tokens (in the order they appear) that pass
        ``has_diacritic``.
    """
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
    """Extract numeric tokens from normalised text.

    Matches sequences that start with a digit and may continue with digits,
    commas, periods, slashes, percent signs, or hyphens. Trailing punctuation
    (``.,;:``) is stripped from each match.

    Args:
        text: Raw text to scan.

    Returns:
        List of numeric string tokens (e.g. ``"1.234,56"``, ``"2026"``,
        ``"50%"``).
    """
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
    """Extract Brazilian Real (BRL) currency values from normalised text.

    Matches the pattern ``r$<digits>`` (case-insensitive, optional internal
    spaces). Internal spaces are removed and trailing punctuation is stripped
    from each match.

    Args:
        text: Raw text to scan.

    Returns:
        List of currency strings such as ``"r$1.234,56"``.
    """
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
    """Extract benchmark regression identifiers from normalised text.

    Matches tokens of the form ``regressao-NN-2026`` (case-insensitive)
    and returns them in lower-case.

    Args:
        text: Raw text to scan.

    Returns:
        List of lower-cased regression ID strings (e.g.
        ``"regressao-01-2026"``).
    """
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
    """Compute occurrence recall for a set of critical Portuguese terms.

    Each term is normalised and its occurrence count is compared between
    reference and hypothesis. The result delegates to ``occurrence_recall``.

    Args:
        reference: Ground-truth text.
        hypothesis: Parser output text.
        terms: Sequence of terms to check. Defaults to
            ``DEFAULT_CRITICAL_TERMS``.

    Returns:
        ``occurrence_recall`` result dict (keys: ``expected``, ``matched``,
        ``missing``, ``recall``).
    """
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
    """Run the full OCR quality evaluation suite on a reference/hypothesis pair.

    Args:
        reference: Ground-truth text for the document or page.
        hypothesis: Parser output text to evaluate.

    Returns:
        Dict with the following keys, each mapping to its respective
        sub-result dict:
            ``cer``: Character Error Rate (``calculate_cer``).
            ``wer``: Word Error Rate (``calculate_wer``).
            ``accented_token_recall``: Recall of accented word tokens.
            ``numeric_token_recall``: Recall of numeric tokens.
            ``currency_value_recall``: Recall of BRL currency values.
            ``regression_id_recall``: Recall of regression identifiers.
            ``critical_term_recall``: Recall of domain-specific critical terms.
    """
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
