"""Preflight contract tests for LiteParse."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.benchmark.config import get_profile
from src.parsers import liteparse_v2


class LiteParsePreflightTests(unittest.TestCase):

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _run_preflight(
        self,
        profile_name: str,
        profile_override: dict | None = None,
        *,
        liteparse_version: str | None = liteparse_v2.LITEPARSE_REQUIRED_VERSION,
        tesseract_present: bool = True,
        tessdata_present: bool = True,
    ) -> dict:
        """Run preflight with mocked external dependencies.

        *liteparse_version* is the value returned by the version check.
        Pass ``None`` to simulate liteparse not being installed.
        """
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Fake tessdata directory with traineddata stubs.
            tessdata_dir = tmp_path / "tessdata"
            tessdata_dir.mkdir()
            if tessdata_present:
                for lang in ("eng", "por", "osd"):
                    (tessdata_dir / f"{lang}.traineddata").touch()

            # Fake SmolVLM model artifact directory under DEFAULT_MODEL_ARTIFACTS.
            fake_model_root = tmp_path / "smolvlm_root"
            fake_model_root.mkdir()
            smolvlm_dir = fake_model_root / liteparse_v2.SMOLVLM_ARTIFACT_DIRECTORY
            smolvlm_dir.mkdir()

            def _fake_get_profile(parser: str, name: str) -> dict:
                base = get_profile(parser, name)
                if profile_override:
                    base.update(profile_override)
                return base

            def _fake_pkg_version(pkg_name: str) -> str | None:
                if pkg_name == "liteparse":
                    return liteparse_version
                return None

            def _fake_which(cmd: str) -> str | None:
                if cmd == "tesseract":
                    return "/usr/bin/tesseract" if tesseract_present else None
                return None

            def _fake_tessdata_prefix() -> str | None:
                return str(tessdata_dir) if tessdata_present else None

            def _fake_tess_version() -> str | None:
                return "5.3.0" if tesseract_present else None

            with (
                patch.object(liteparse_v2, "get_profile", side_effect=_fake_get_profile),
                patch.object(liteparse_v2, "_package_version", side_effect=_fake_pkg_version),
                patch.object(liteparse_v2, "_find_tessdata_prefix", side_effect=_fake_tessdata_prefix),
                patch.object(liteparse_v2, "_get_tesseract_version", side_effect=_fake_tess_version),
                patch.object(liteparse_v2, "DEFAULT_MODEL_ARTIFACTS", fake_model_root),
                patch("shutil.which", side_effect=_fake_which),
            ):
                return liteparse_v2.preflight_profile(profile_name)

    def _find_check(self, result: dict, name: str) -> dict:
        """Return the single check whose name equals *name*."""
        checks = result.get("checks", [])
        matches = [c for c in checks if c.get("name") == name]
        self.assertEqual(
            len(matches),
            1,
            f"Expected exactly one check named {name!r}, "
            f"got {len(matches)}: {[c.get('name') for c in checks]}",
        )
        return matches[0]

    # ── Profile configuration ─────────────────────────────────────────────

    def test_preflight_passes_for_native_profile(self) -> None:
        result = self._run_preflight("native")
        self.assertTrue(result["ok"], result)

    def test_preflight_passes_for_ocr_tesseract_profile(self) -> None:
        result = self._run_preflight("ocr_auto_tesseract")
        self.assertTrue(result["ok"], result)

    def test_preflight_rejects_unknown_profile(self) -> None:
        result = self._run_preflight("no_such_profile")
        check = self._find_check(result, "profile configuration")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    # ── Version check ─────────────────────────────────────────────────────

    def test_preflight_fails_when_liteparse_version_wrong(self) -> None:
        result = self._run_preflight("native", liteparse_version="0.0.1")
        check = self._find_check(result, "liteparse version")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    def test_preflight_passes_with_correct_version(self) -> None:
        result = self._run_preflight(
            "native",
            liteparse_version=liteparse_v2.LITEPARSE_REQUIRED_VERSION,
        )
        check = self._find_check(result, "liteparse version")
        self.assertEqual(check["status"], "pass")

    # ── Remote services ───────────────────────────────────────────────────

    def test_preflight_fails_when_remote_services_enabled(self) -> None:
        result = self._run_preflight(
            "native",
            {"remote_services_enabled": True},
        )
        check = self._find_check(result, "remote services disabled")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    def test_preflight_fails_when_ocr_server_url_set(self) -> None:
        result = self._run_preflight(
            "native",
            {"ocr_server_url": "http://ocr-server:8080"},
        )
        check = self._find_check(result, "ocr server url")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    # ── Image extraction ──────────────────────────────────────────────────

    def test_preflight_fails_when_extract_images_false(self) -> None:
        result = self._run_preflight(
            "native",
            {"extract_images": False},
        )
        check = self._find_check(result, "image extraction enabled")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    def test_preflight_fails_when_image_mode_not_off(self) -> None:
        result = self._run_preflight(
            "native",
            {"image_mode": "embed"},
        )
        check = self._find_check(result, "image mode")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    # ── Tesseract (only for OCR profiles) ─────────────────────────────────

    def test_preflight_fails_when_tesseract_absent(self) -> None:
        result = self._run_preflight(
            "ocr_auto_tesseract",
            tesseract_present=False,
        )
        check = self._find_check(result, "tesseract executable")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    def test_preflight_fails_when_eng_tessdata_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            tessdata = Path(tmp) / "tessdata"
            tessdata.mkdir()
            # eng is absent; por and osd present.
            (tessdata / "por.traineddata").touch()
            (tessdata / "osd.traineddata").touch()

            fake_model_root = Path(tmp) / "smolvlm_root"
            fake_model_root.mkdir()
            (fake_model_root / liteparse_v2.SMOLVLM_ARTIFACT_DIRECTORY).mkdir()

            with (
                patch.object(liteparse_v2, "get_profile",
                             side_effect=lambda p, n: get_profile(p, n)),
                patch.object(liteparse_v2, "_package_version",
                             return_value=liteparse_v2.LITEPARSE_REQUIRED_VERSION),
                patch.object(liteparse_v2, "_find_tessdata_prefix",
                             return_value=str(tessdata)),
                patch.object(liteparse_v2, "_get_tesseract_version",
                             return_value="5.3.0"),
                patch.object(liteparse_v2, "DEFAULT_MODEL_ARTIFACTS", fake_model_root),
                patch("shutil.which", return_value="/usr/bin/tesseract"),
            ):
                result = liteparse_v2.preflight_profile("ocr_auto_tesseract")

        check = self._find_check(result, "tessdata eng")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    def test_preflight_fails_when_por_tessdata_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            tessdata = Path(tmp) / "tessdata"
            tessdata.mkdir()
            (tessdata / "eng.traineddata").touch()
            (tessdata / "osd.traineddata").touch()

            fake_model_root = Path(tmp) / "smolvlm_root"
            fake_model_root.mkdir()
            (fake_model_root / liteparse_v2.SMOLVLM_ARTIFACT_DIRECTORY).mkdir()

            with (
                patch.object(liteparse_v2, "get_profile",
                             side_effect=lambda p, n: get_profile(p, n)),
                patch.object(liteparse_v2, "_package_version",
                             return_value=liteparse_v2.LITEPARSE_REQUIRED_VERSION),
                patch.object(liteparse_v2, "_find_tessdata_prefix",
                             return_value=str(tessdata)),
                patch.object(liteparse_v2, "_get_tesseract_version",
                             return_value="5.3.0"),
                patch.object(liteparse_v2, "DEFAULT_MODEL_ARTIFACTS", fake_model_root),
                patch("shutil.which", return_value="/usr/bin/tesseract"),
            ):
                result = liteparse_v2.preflight_profile("ocr_auto_tesseract")

        check = self._find_check(result, "tessdata por")
        self.assertEqual(check["status"], "fail")

    def test_preflight_fails_when_osd_tessdata_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            tessdata = Path(tmp) / "tessdata"
            tessdata.mkdir()
            (tessdata / "eng.traineddata").touch()
            (tessdata / "por.traineddata").touch()

            fake_model_root = Path(tmp) / "smolvlm_root"
            fake_model_root.mkdir()
            (fake_model_root / liteparse_v2.SMOLVLM_ARTIFACT_DIRECTORY).mkdir()

            with (
                patch.object(liteparse_v2, "get_profile",
                             side_effect=lambda p, n: get_profile(p, n)),
                patch.object(liteparse_v2, "_package_version",
                             return_value=liteparse_v2.LITEPARSE_REQUIRED_VERSION),
                patch.object(liteparse_v2, "_find_tessdata_prefix",
                             return_value=str(tessdata)),
                patch.object(liteparse_v2, "_get_tesseract_version",
                             return_value="5.3.0"),
                patch.object(liteparse_v2, "DEFAULT_MODEL_ARTIFACTS", fake_model_root),
                patch("shutil.which", return_value="/usr/bin/tesseract"),
            ):
                result = liteparse_v2.preflight_profile("ocr_auto_tesseract")

        check = self._find_check(result, "tessdata osd")
        self.assertEqual(check["status"], "fail")

    def test_preflight_native_skips_tesseract_check(self) -> None:
        result = self._run_preflight("native", tesseract_present=False)
        check_names = [c["name"] for c in result["checks"]]
        self.assertNotIn(
            "tesseract executable",
            check_names,
            "Native profile must not perform a tesseract executable check",
        )

    # ── Visual profile ────────────────────────────────────────────────────

    def test_preflight_visual_fails_when_smolvlm_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            tessdata = Path(tmp) / "tessdata"
            tessdata.mkdir()
            for lang in ("eng", "por", "osd"):
                (tessdata / f"{lang}.traineddata").touch()

            # SmolVLM model dir does NOT exist here.
            absent_root = Path(tmp) / "absent_root"
            absent_root.mkdir()
            # We do NOT create SMOLVLM_ARTIFACT_DIRECTORY inside it.

            with (
                patch.object(liteparse_v2, "get_profile",
                             side_effect=lambda p, n: get_profile(p, n)),
                patch.object(liteparse_v2, "_package_version",
                             return_value=liteparse_v2.LITEPARSE_REQUIRED_VERSION),
                patch.object(liteparse_v2, "_find_tessdata_prefix",
                             return_value=str(tessdata)),
                patch.object(liteparse_v2, "_get_tesseract_version",
                             return_value="5.3.0"),
                patch.object(liteparse_v2, "DEFAULT_MODEL_ARTIFACTS", absent_root),
                patch("shutil.which", return_value="/usr/bin/tesseract"),
            ):
                result = liteparse_v2.preflight_profile("ocr_auto_visual")

        check = self._find_check(result, "smolvlm model")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    def test_preflight_visual_passes_with_model_present(self) -> None:
        result = self._run_preflight("ocr_auto_visual")
        check = self._find_check(result, "smolvlm model")
        self.assertEqual(check["status"], "pass")
        self.assertTrue(result["ok"], result)

    def test_preflight_visual_fails_when_prompt_empty(self) -> None:
        result = self._run_preflight(
            "ocr_auto_visual",
            {"image_description_prompt": "   "},
        )
        check = self._find_check(result, "image description prompt")
        self.assertEqual(check["status"], "fail")
        self.assertFalse(result["ok"])

    # ── Output schema ─────────────────────────────────────────────────────

    def test_preflight_result_has_required_fields(self) -> None:
        result = self._run_preflight("native")
        for field in ("schema_version", "parser", "profile", "ok", "checks"):
            self.assertIn(field, result, f"Result missing field {field!r}")

    def test_preflight_ok_is_consistent_with_checks(self) -> None:
        result = self._run_preflight("native")
        has_failure = any(c["status"] == "fail" for c in result["checks"])
        self.assertEqual(result["ok"], not has_failure)

    def test_preflight_parser_name_is_liteparse(self) -> None:
        result = self._run_preflight("native")
        self.assertEqual(result["parser"], "liteparse")


if __name__ == "__main__":
    unittest.main()
