from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.benchmark.native_bundle import copy_native_bundle
from src.benchmark.post_validation import _validate_native_dir


class NativeBundleTests(unittest.TestCase):
    def test_recreates_bundle_and_relocates_local_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "images").mkdir(parents=True)
            (source / "images" / "chart.png").write_bytes(b"png")
            markdown = source / "document.md"
            markdown.write_text("before ![chart](images/chart.png) after", encoding="utf-8")
            destination = root / "native"
            destination.mkdir()
            (destination / "stale.bin").write_bytes(b"stale")

            result = copy_native_bundle(
                source_root=source, source_markdown_path=markdown,
                destination=destination, parser="mineru", profile="full",
            )

            self.assertFalse((destination / "stale.bin").exists())
            self.assertIn("assets/", result.markdown)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertTrue(all("sha256" in item for item in manifest["files"]))

    def test_rejects_traversal_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            markdown = source / "document.md"
            markdown.write_text("![bad](../secret.png)", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe relative path"):
                copy_native_bundle(
                    source_root=source, source_markdown_path=markdown,
                    destination=root / "native", parser="x", profile="y",
                )

    def test_post_validation_rejects_unlisted_native_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            native = Path(temporary) / "native"
            native.mkdir()
            (native / "manifest.json").write_text(
                '{"schema_version":1,"parser":"x","profile":"p",'
                '"bundle_status":"unavailable","files":[]}',
                encoding="utf-8",
            )
            (native / "stale.bin").write_bytes(b"stale")
            checks = _validate_native_dir(
                native, "native", parser="x", profile="p"
            )
            self.assertTrue(any(item["status"] == "fail" for item in checks))


if __name__ == "__main__":
    unittest.main()
