"""Orientation detection and rotation tests for LiteParse."""
from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, call, patch

from src.parsers import liteparse_v2


def _make_osd_dict(rotation: int = 0) -> dict:
    """Return a pytesseract OSD dict with the given rotation."""
    return {
        "rotate": rotation,
        "orientation_conf": 95.0,
        "script": "Latin",
        "script_conf": 88.0,
    }


def _make_png_bytes(color: str = "white") -> bytes:
    """Return minimal 1×1 PNG bytes via Pillow for use as test input."""
    from PIL import Image

    img = Image.new("RGB", (8, 8), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class LiteParseRotationTests(unittest.TestCase):

    def _run_detect(
        self,
        rotation: int,
        *,
        osd_raises: bool = False,
    ) -> tuple[bytes, int]:
        """Invoke _detect_and_correct_orientation with mocked pytesseract."""
        image_bytes = _make_png_bytes()

        osd_dict = _make_osd_dict(rotation)

        with patch.dict(
            "sys.modules",
            {"pytesseract": MagicMock()},
        ):
            import pytesseract as _pt

            if osd_raises:
                _pt.image_to_osd.side_effect = RuntimeError(
                    "OSD engine failed"
                )
            else:
                _pt.image_to_osd.return_value = osd_dict
            _pt.Output = MagicMock()
            _pt.Output.DICT = "dict"

            # Also patch PIL so we control the rotate call.
            from PIL import Image

            real_open = Image.open

            original_img = real_open(io.BytesIO(image_bytes))

            with patch("PIL.Image.open", return_value=original_img):
                result_bytes, applied = (
                    liteparse_v2._detect_and_correct_orientation(
                        image_bytes
                    )
                )

        return result_bytes, applied

    def test_upright_image_no_rotation_applied(self) -> None:
        original = _make_png_bytes()
        _, applied = self._run_detect(0)
        self.assertEqual(applied, 0)

    def test_90_degree_rotation_detected_and_corrected(self) -> None:
        _, applied = self._run_detect(90)
        self.assertEqual(applied, 90)

    def test_180_degree_rotation_detected_and_corrected(self) -> None:
        _, applied = self._run_detect(180)
        self.assertEqual(applied, 180)

    def test_270_degree_rotation_detected_and_corrected(self) -> None:
        _, applied = self._run_detect(270)
        self.assertEqual(applied, 270)

    def test_returns_applied_rotation_degrees(self) -> None:
        """The second element of the tuple must equal the OSD rotation."""
        for degrees in (0, 90, 180, 270):
            with self.subTest(degrees=degrees):
                _, applied = self._run_detect(degrees)
                self.assertEqual(applied, degrees)

    def test_zero_rotation_returns_original(self) -> None:
        """When rotation=0, the returned bytes must equal the input."""
        original = _make_png_bytes()
        with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
            import pytesseract as _pt

            _pt.image_to_osd.return_value = _make_osd_dict(0)
            _pt.Output = MagicMock()
            _pt.Output.DICT = "dict"

            with patch("PIL.Image.open") as mock_open:
                mock_img = MagicMock()
                mock_open.return_value = mock_img

                result_bytes, applied = (
                    liteparse_v2._detect_and_correct_orientation(original)
                )

        # For zero rotation the original bytes are returned unchanged.
        self.assertEqual(result_bytes, original)
        self.assertEqual(applied, 0)

    def test_osd_failure_falls_back_gracefully(self) -> None:
        """When OSD raises, the function returns (original_bytes, 0)."""
        original = _make_png_bytes()

        with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
            import pytesseract as _pt

            _pt.image_to_osd.side_effect = RuntimeError("OSD engine failed")
            _pt.Output = MagicMock()
            _pt.Output.DICT = "dict"

            result_bytes, applied = (
                liteparse_v2._detect_and_correct_orientation(original)
            )

        self.assertEqual(result_bytes, original)
        self.assertEqual(applied, 0)


if __name__ == "__main__":
    unittest.main()
