from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from src.enrichment.visual_worker import _process_request


class VisualWorkerPromptTests(unittest.TestCase):
    def test_description_prompt_excludes_ocr_already_extracted(self) -> None:
        request = {
            "request_id": "r1",
            "image_base64": base64.b64encode(b"image").decode("ascii"),
            "prompt": "Describe visual facts.",
        }
        with (
            patch(
                "src.enrichment.visual_worker._run_ocr",
                return_value="IMAGEM OCR: Orcamento local 2026",
            ),
            patch(
                "src.enrichment.visual_worker._run_description",
                return_value="A bordered label.",
            ) as describe,
        ):
            response = _process_request(
                request, object(), object(), object(), "model", "pt"
            )

        prompt = describe.call_args.args[3]
        self.assertIn("Do not transcribe or repeat", prompt)
        self.assertIn("IMAGEM OCR: Orcamento local 2026", prompt)
        self.assertEqual(response["status"], "success")
