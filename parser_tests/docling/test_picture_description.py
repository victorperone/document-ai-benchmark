from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.benchmark.config import (
    BenchmarkConfigurationError,
    get_profile,
)
from src.parsers import docling_v2


class DescriptionStub:
    def __init__(
        self,
        *,
        text: str,
        confidence: float | None = None,
        created_by: str | None = None,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.created_by = created_by

    def model_dump(
        self,
        *,
        mode: str,
        exclude_none: bool,
    ) -> dict[str, object]:
        if mode != "json":
            raise AssertionError(
                f"Unexpected serialization mode: {mode!r}"
            )

        payload: dict[str, object] = {
            "text": self.text,
            "confidence": self.confidence,
            "created_by": self.created_by,
        }

        if exclude_none:
            payload = {
                key: value
                for key, value in payload.items()
                if value is not None
            }

        return payload


class PictureItem:
    def __init__(
        self,
        description: object | None,
    ) -> None:
        self.label = "picture"
        self.content_layer = None
        self.parent = None
        self.self_ref = "#/pictures/0"
        self.text = None
        self.prov = []
        self.meta = SimpleNamespace(
            classification=None,
            description=description,
        )


class DoclingPictureDescriptionTests(
    unittest.TestCase,
):
    def setUp(self) -> None:
        self.profile = copy.deepcopy(
            get_profile(
                "docling",
                "ocr_auto_visual",
            )
        )

    def _new_options(self):
        options = docling_v2.PdfPipelineOptions()
        options.do_picture_description = True
        return options

    def test_visual_profile_contract(self) -> None:
        self.assertTrue(
            self.profile["picture_description"]
        )
        self.assertEqual(
            self.profile[
                "picture_description_preset"
            ],
            "smolvlm",
        )
        self.assertEqual(
            self.profile["picture_area_threshold"],
            0.0,
        )
        self.assertTrue(
            self.profile["generate_picture_images"]
        )
        self.assertEqual(
            self.profile["images_scale"],
            2.0,
        )
        self.assertFalse(
            self.profile[
                "remote_services_enabled"
            ]
        )
        self.assertEqual(
            self.profile["accelerator_device"],
            "cpu",
        )

    def test_non_visual_profiles_remain_disabled(
        self,
    ) -> None:
        for profile_name in (
            "native",
            "ocr_auto",
        ):
            with self.subTest(
                profile=profile_name
            ):
                profile = get_profile(
                    "docling",
                    profile_name,
                )
                self.assertFalse(
                    profile[
                        "picture_description"
                    ]
                )
                self.assertFalse(
                    profile[
                        "generate_picture_images"
                    ]
                )
                self.assertFalse(
                    profile[
                        "remote_services_enabled"
                    ]
                )

    def test_configure_picture_description(
        self,
    ) -> None:
        options = self._new_options()

        docling_v2._configure_picture_description(
            options,
            self.profile,
        )

        configured = (
            options.picture_description_options
        )

        self.assertIsNot(
            configured,
            docling_v2.smolvlm_picture_description,
        )
        self.assertEqual(
            configured.prompt,
            self.profile[
                "picture_description_prompt"
            ],
        )
        self.assertEqual(
            configured.picture_area_threshold,
            0.0,
        )
        self.assertEqual(
            configured.repo_id,
            "HuggingFaceTB/"
            "SmolVLM-256M-Instruct",
        )

    def _run_visual_preflight(
        self,
        profile: dict[str, object],
        *,
        model_present: bool = True,
    ) -> dict[str, object]:
        with TemporaryDirectory() as tmp:
            model_root = Path(tmp)

            if model_present:
                (
                    model_root
                    / docling_v2.SMOLVLM_ARTIFACT_DIRECTORY
                ).mkdir()

            candidate = copy.deepcopy(profile)
            candidate["model_artifacts_path"] = str(
                model_root
            )

            with patch.object(
                docling_v2,
                "get_profile",
                return_value=candidate,
            ):
                return docling_v2.preflight_profile(
                    "ocr_auto_visual"
                )

    def _find_preflight_check(
        self,
        result: dict[str, object],
        name: str,
    ) -> dict[str, object]:
        checks = result["checks"]

        self.assertIsInstance(checks, list)

        matches = [
            check
            for check in checks
            if isinstance(check, dict)
            and check.get("name") == name
        ]

        self.assertEqual(
            len(matches),
            1,
            f"Expected exactly one preflight "
            f"check named {name!r}.",
        )

        return matches[0]

    def test_preflight_accepts_valid_visual_contract(
        self,
    ) -> None:
        result = self._run_visual_preflight(
            self.profile
        )

        self.assertTrue(result["ok"])

        expected_checks = {
            "picture description preset": "pass",
            "picture description prompt": "pass",
            "picture area threshold": "pass",
            "picture description locality": "pass",
            "picture description model": "pass",
        }

        for name, expected_status in (
            expected_checks.items()
        ):
            with self.subTest(check=name):
                check = self._find_preflight_check(
                    result,
                    name,
                )
                self.assertEqual(
                    check["status"],
                    expected_status,
                )

    def test_preflight_rejects_unknown_preset(
        self,
    ) -> None:
        self.profile[
            "picture_description_preset"
        ] = "unknown"

        result = self._run_visual_preflight(
            self.profile
        )

        check = self._find_preflight_check(
            result,
            "picture description preset",
        )

        self.assertEqual(
            check["status"],
            "fail",
        )
        self.assertFalse(result["ok"])

    def test_preflight_rejects_empty_prompt(
        self,
    ) -> None:
        self.profile[
            "picture_description_prompt"
        ] = "   "

        result = self._run_visual_preflight(
            self.profile
        )

        check = self._find_preflight_check(
            result,
            "picture description prompt",
        )

        self.assertEqual(
            check["status"],
            "fail",
        )
        self.assertFalse(result["ok"])

    def test_preflight_rejects_remote_services(
        self,
    ) -> None:
        self.profile[
            "remote_services_enabled"
        ] = True

        result = self._run_visual_preflight(
            self.profile
        )

        check = self._find_preflight_check(
            result,
            "picture description locality",
        )

        self.assertEqual(
            check["status"],
            "fail",
        )
        self.assertFalse(result["ok"])

    def test_preflight_rejects_missing_model(
        self,
    ) -> None:
        result = self._run_visual_preflight(
            self.profile,
            model_present=False,
        )

        check = self._find_preflight_check(
            result,
            "picture description model",
        )

        self.assertEqual(
            check["status"],
            "fail",
        )
        self.assertFalse(result["ok"])

    def test_preflight_rejects_invalid_threshold(
        self,
    ) -> None:
        self.profile[
            "picture_area_threshold"
        ] = -0.01

        result = self._run_visual_preflight(
            self.profile
        )

        check = self._find_preflight_check(
            result,
            "picture area threshold",
        )

        self.assertEqual(
            check["status"],
            "fail",
        )
        self.assertFalse(result["ok"])


    def test_global_preset_is_not_mutated(
        self,
    ) -> None:
        original_prompt = (
            docling_v2
            .smolvlm_picture_description
            .prompt
        )
        original_threshold = (
            docling_v2
            .smolvlm_picture_description
            .picture_area_threshold
        )

        options = self._new_options()

        docling_v2._configure_picture_description(
            options,
            self.profile,
        )

        self.assertEqual(
            docling_v2
            .smolvlm_picture_description
            .prompt,
            original_prompt,
        )
        self.assertEqual(
            docling_v2
            .smolvlm_picture_description
            .picture_area_threshold,
            original_threshold,
        )
        self.assertEqual(
            original_threshold,
            0.05,
        )

    def test_unknown_preset_is_rejected(
        self,
    ) -> None:
        self.profile[
            "picture_description_preset"
        ] = "unknown"

        with self.assertRaisesRegex(
            BenchmarkConfigurationError,
            "Unsupported Docling "
            "picture-description preset",
        ):
            docling_v2._configure_picture_description(
                self._new_options(),
                self.profile,
            )

    def test_empty_prompt_is_rejected(
        self,
    ) -> None:
        self.profile[
            "picture_description_prompt"
        ] = "   "

        with self.assertRaisesRegex(
            BenchmarkConfigurationError,
            "picture_description_prompt "
            "must be non-empty",
        ):
            docling_v2._configure_picture_description(
                self._new_options(),
                self.profile,
            )

    def test_threshold_zero_is_valid(
        self,
    ) -> None:
        self.profile[
            "picture_area_threshold"
        ] = 0.0
        options = self._new_options()

        docling_v2._configure_picture_description(
            options,
            self.profile,
        )

        self.assertEqual(
            options
            .picture_description_options
            .picture_area_threshold,
            0.0,
        )

    def test_threshold_one_is_valid(
        self,
    ) -> None:
        self.profile[
            "picture_area_threshold"
        ] = 1.0
        options = self._new_options()

        docling_v2._configure_picture_description(
            options,
            self.profile,
        )

        self.assertEqual(
            options
            .picture_description_options
            .picture_area_threshold,
            1.0,
        )

    def test_negative_threshold_is_rejected(
        self,
    ) -> None:
        self.profile[
            "picture_area_threshold"
        ] = -0.01

        with self.assertRaisesRegex(
            BenchmarkConfigurationError,
            "picture_area_threshold must be "
            "between 0.0 and 1.0",
        ):
            docling_v2._configure_picture_description(
                self._new_options(),
                self.profile,
            )

    def test_threshold_above_one_is_rejected(
        self,
    ) -> None:
        self.profile[
            "picture_area_threshold"
        ] = 1.01

        with self.assertRaisesRegex(
            BenchmarkConfigurationError,
            "picture_area_threshold must be "
            "between 0.0 and 1.0",
        ):
            docling_v2._configure_picture_description(
                self._new_options(),
                self.profile,
            )

    def test_non_numeric_threshold_is_rejected(
        self,
    ) -> None:
        self.profile[
            "picture_area_threshold"
        ] = "invalid"

        with self.assertRaisesRegex(
            BenchmarkConfigurationError,
            "picture_area_threshold must be "
            "numeric",
        ):
            docling_v2._configure_picture_description(
                self._new_options(),
                self.profile,
            )

    def test_numeric_string_threshold_is_accepted(
        self,
    ) -> None:
        result = docling_v2._resolve_picture_area_threshold(
            {"picture_area_threshold": "0.5"},
            default=0.05,
        )
        self.assertEqual(result, 0.5)

    def test_serializer_preserves_description(
        self,
    ) -> None:
        item = PictureItem(
            DescriptionStub(
                text=(
                    "A chart showing an "
                    "increasing trend."
                ),
                confidence=0.91,
                created_by="smolvlm",
            )
        )

        payload = (
            docling_v2
            ._serialize_item_for_page(
                item,
                level=0,
                page_number=1,
            )
        )

        self.assertEqual(
            payload["picture_description"],
            {
                "text": (
                    "A chart showing an "
                    "increasing trend."
                ),
                "confidence": 0.91,
                "created_by": "smolvlm",
            },
        )

    def test_serializer_omits_missing_description(
        self,
    ) -> None:
        item = PictureItem(None)

        payload = (
            docling_v2
            ._serialize_item_for_page(
                item,
                level=0,
                page_number=1,
            )
        )

        self.assertNotIn(
            "picture_description",
            payload,
        )

    def test_serializer_rejects_unknown_schema(
        self,
    ) -> None:
        item = PictureItem(
            SimpleNamespace(
                text="description"
            )
        )

        with self.assertRaisesRegex(
            TypeError,
            "does not expose model_dump",
        ):
            docling_v2._serialize_item_for_page(
                item,
                level=0,
                page_number=1,
            )


if __name__ == "__main__":
    unittest.main()
