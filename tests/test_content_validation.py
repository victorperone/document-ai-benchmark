from __future__ import annotations

import unittest

from src.benchmark.content_validation import inventory_requires_content


class ContentExpectationTests(unittest.TestCase):
    def test_completely_measured_empty_pdf_does_not_require_text(self) -> None:
        expected, reason = inventory_requires_content({
            "native_text": {"characters": 0},
            "images": {"embedded_image_occurrences": 0, "measurement_complete": True},
            "vector_content": {"drawing_groups": 0, "measurement_complete": True},
        })
        self.assertFalse(expected)
        self.assertIn("proves", reason)

    def test_incomplete_measurement_cannot_exempt_empty_output(self) -> None:
        expected, reason = inventory_requires_content({
            "native_text": {"characters": 0},
            "images": {"embedded_image_occurrences": 0, "measurement_complete": False},
            "vector_content": {"drawing_groups": 0, "measurement_complete": True},
        })
        self.assertTrue(expected)
        self.assertIn("could not prove", reason)

    def test_any_objective_content_requires_text(self) -> None:
        expected, _ = inventory_requires_content({
            "native_text": {"characters": 1},
            "images": {"embedded_image_occurrences": 0},
            "vector_content": {"drawing_groups": 0},
        })
        self.assertTrue(expected)


if __name__ == "__main__":
    unittest.main()
