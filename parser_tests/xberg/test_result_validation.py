"""Tests for xberg_v2._unwrap_extraction_result."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.parsers.xberg_v2 import (
    XbergConfigurationError,
    _unwrap_extraction_result,
)


def _summary(*, inputs: int = 1, results: int = 1, errors: int = 0):
    return SimpleNamespace(inputs=inputs, results=results, errors=errors)


class TestXbergResultEnvelope(unittest.TestCase):
    def test_valid_envelope(self) -> None:
        document = SimpleNamespace(content="text", pages=[])
        envelope = SimpleNamespace(
            results=[document],
            errors=[],
            summary=_summary(),
        )

        actual, summary = _unwrap_extraction_result(envelope)

        self.assertIs(actual, document)
        self.assertEqual(summary.results, 1)

    def test_error_item_fails(self) -> None:
        envelope = SimpleNamespace(
            results=[],
            errors=["failure"],
            summary=_summary(results=0, errors=1),
        )

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)

    def test_zero_results_fails(self) -> None:
        envelope = SimpleNamespace(
            results=[],
            errors=[],
            summary=_summary(results=0),
        )

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)

    def test_multiple_results_fail(self) -> None:
        document = SimpleNamespace(content="text", pages=[])
        envelope = SimpleNamespace(
            results=[document, document],
            errors=[],
            summary=_summary(results=2),
        )

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)

    def test_summary_error_fails(self) -> None:
        document = SimpleNamespace(content="text", pages=[])
        envelope = SimpleNamespace(
            results=[document],
            errors=[],
            summary=_summary(errors=1),
        )

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)

    def test_missing_summary_fails(self) -> None:
        document = SimpleNamespace(content="text", pages=[])
        envelope = SimpleNamespace(results=[document], errors=[], summary=None)

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)

    def test_document_without_content_fails(self) -> None:
        document = SimpleNamespace(pages=[])  # no .content attribute
        envelope = SimpleNamespace(
            results=[document],
            errors=[],
            summary=_summary(),
        )

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)

    def test_summary_inputs_not_one_fails(self) -> None:
        document = SimpleNamespace(content="text", pages=[])
        envelope = SimpleNamespace(
            results=[document],
            errors=[],
            summary=_summary(inputs=0),
        )

        with self.assertRaises(XbergConfigurationError):
            _unwrap_extraction_result(envelope)


if __name__ == "__main__":
    unittest.main()
