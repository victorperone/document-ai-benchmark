"""Profile contract tests for LiteParse profiles."""
from __future__ import annotations

import unittest

from src.benchmark.config import get_profile

_ALL_PROFILES = ("native", "ocr_auto_tesseract", "ocr_auto_visual")


class LiteParseProfileContractTests(unittest.TestCase):

    # ── native ────────────────────────────────────────────────────────────

    def test_native_profile_disables_ocr(self) -> None:
        profile = get_profile("liteparse", "native")
        self.assertFalse(profile["ocr_enabled"])

    def test_native_profile_has_extract_images(self) -> None:
        profile = get_profile("liteparse", "native")
        self.assertTrue(profile["extract_images"])

    def test_native_profile_has_image_mode_off(self) -> None:
        profile = get_profile("liteparse", "native")
        self.assertEqual(profile["image_mode"], "off")

    def test_native_profile_blocks_remote_services(self) -> None:
        profile = get_profile("liteparse", "native")
        self.assertFalse(profile["remote_services_enabled"])

    def test_native_profile_has_no_image_description(self) -> None:
        profile = get_profile("liteparse", "native")
        self.assertFalse(profile.get("image_description", False))

    def test_native_profile_is_cpu_only(self) -> None:
        profile = get_profile("liteparse", "native")
        self.assertEqual(profile["accelerator_device"], "cpu")

    # ── ocr_auto_tesseract ────────────────────────────────────────────────

    def test_ocr_tesseract_enables_ocr(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertTrue(profile["ocr_enabled"])

    def test_ocr_tesseract_uses_tesseract_engine(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertEqual(profile["ocr_engine"], "tesseract")

    def test_ocr_tesseract_has_no_image_description(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertFalse(profile.get("image_description", False))

    def test_ocr_tesseract_has_high_dpi(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertGreaterEqual(profile["dpi"], 300)

    def test_ocr_tesseract_has_orientation_detection(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertTrue(profile["orientation_detection"])

    def test_ocr_tesseract_blocks_remote_services(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertFalse(profile["remote_services_enabled"])

    def test_ocr_tesseract_is_cpu_only(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_tesseract")
        self.assertEqual(profile["accelerator_device"], "cpu")

    # ── ocr_auto_visual ───────────────────────────────────────────────────

    def test_ocr_visual_enables_image_description(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_visual")
        self.assertTrue(profile["image_description"])

    def test_ocr_visual_uses_fallback_only_strategy(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_visual")
        self.assertTrue(profile["image_description_fallback_only"])

    def test_ocr_visual_has_description_prompt(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_visual")
        prompt = profile.get("image_description_prompt", "")
        self.assertTrue(
            isinstance(prompt, str) and prompt.strip(),
            "image_description_prompt must be a non-empty string",
        )

    def test_ocr_visual_blocks_remote_services(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_visual")
        self.assertFalse(profile["remote_services_enabled"])

    def test_ocr_visual_is_cpu_only(self) -> None:
        profile = get_profile("liteparse", "ocr_auto_visual")
        self.assertEqual(profile["accelerator_device"], "cpu")

    # ── invariants across all profiles ───────────────────────────────────

    def test_all_profiles_have_extract_images(self) -> None:
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                profile = get_profile("liteparse", name)
                self.assertTrue(
                    profile.get("extract_images", False),
                    f"Profile {name!r}: extract_images must be True",
                )

    def test_all_profiles_have_image_mode_off(self) -> None:
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                profile = get_profile("liteparse", name)
                self.assertEqual(
                    profile.get("image_mode"),
                    "off",
                    f"Profile {name!r}: image_mode must be 'off'",
                )

    def test_all_profiles_block_remote_services(self) -> None:
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                profile = get_profile("liteparse", name)
                self.assertFalse(
                    profile.get("remote_services_enabled", True),
                    f"Profile {name!r}: remote_services_enabled must be False",
                )

    def test_all_profiles_have_num_workers(self) -> None:
        for name in _ALL_PROFILES:
            with self.subTest(profile=name):
                profile = get_profile("liteparse", name)
                num_workers = profile.get("num_workers")
                self.assertIsNotNone(
                    num_workers,
                    f"Profile {name!r}: num_workers must be set",
                )
                self.assertIsInstance(num_workers, int)
                self.assertGreater(num_workers, 0)


if __name__ == "__main__":
    unittest.main()
