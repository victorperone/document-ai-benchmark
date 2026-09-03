"""Unit tests for scripts/model_manifest.py — strict verify_manifest."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.model_manifest import build_manifest, verify_manifest


def _make_root(tmp: str, *, files: dict[str, bytes] | None = None) -> tuple[Path, Path]:
    root = Path(tmp)
    content = files or {"weights.bin": b"model-weights"}
    for name, data in content.items():
        (root / name).write_bytes(data)
    manifest_path = root / "manifest.json"
    return root, manifest_path


class TestVerifyManifestVersionStrict(unittest.TestCase):

    def test_correct_version_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp)
            mp.write_text(json.dumps(build_manifest("comp", "1.2.3", root, mp)), encoding="utf-8")
            result = verify_manifest("comp", "1.2.3", root, mp)
            self.assertEqual(result["version"], "1.2.3")

    def test_wrong_version_fails_even_with_valid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp)
            mp.write_text(json.dumps(build_manifest("comp", "1.2.3", root, mp)), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "version mismatch"):
                verify_manifest("comp", "9.9.9", root, mp)

    def test_empty_expected_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp)
            mp.write_text(json.dumps(build_manifest("comp", "1.0", root, mp)), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                verify_manifest("comp", "", root, mp)


class TestVerifyManifestTampering(unittest.TestCase):

    def test_unlisted_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp)
            mp.write_text(json.dumps(build_manifest("comp", "v1", root, mp)), encoding="utf-8")
            (root / "extra.bin").write_bytes(b"surprise")
            with self.assertRaisesRegex(RuntimeError, "unlisted model files"):
                verify_manifest("comp", "v1", root, mp)

    def test_missing_declared_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp)
            mp.write_text(json.dumps(build_manifest("comp", "v1", root, mp)), encoding="utf-8")
            (root / "weights.bin").unlink()
            with self.assertRaisesRegex(RuntimeError, "model file missing"):
                verify_manifest("comp", "v1", root, mp)

    def test_corrupted_file_hash_fails(self) -> None:
        original = b"model-weights"
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp, files={"weights.bin": original})
            mp.write_text(json.dumps(build_manifest("comp", "v1", root, mp)), encoding="utf-8")
            # Replace with same-length content to isolate the hash check
            tampered = b"x" * len(original)
            (root / "weights.bin").write_bytes(tampered)
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                verify_manifest("comp", "v1", root, mp)

    def test_absent_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "weights.bin").write_bytes(b"data")
            mp = root / "manifest.json"
            with self.assertRaises(Exception):
                verify_manifest("comp", "v1", root, mp)


class TestVerifyManifestReadOnly(unittest.TestCase):

    def test_verify_does_not_create_or_modify_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, mp = _make_root(tmp)
            mp.write_text(json.dumps(build_manifest("comp", "v1", root, mp)), encoding="utf-8")
            before = {p: p.read_bytes() for p in root.iterdir()}
            verify_manifest("comp", "v1", root, mp)
            after = {p: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()