#!/usr/bin/env python3
"""Create or read-only verify the common offline-model manifest v1."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(component: str, version: str, root: Path, manifest_path: Path) -> dict:
    root = root.resolve()
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() == manifest_path.resolve() or path.is_symlink():
            continue
        files.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if not files:
        raise RuntimeError(f"no model files found below {root}")
    return {
        "schema_version": 1,
        "component": component,
        "version": version,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def verify_manifest(
    component: str,
    expected_version: str,
    root: Path,
    manifest_path: Path,
) -> dict:
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise RuntimeError("model manifest schema_version must be 1")
    if manifest.get("component") != component:
        raise RuntimeError(
            f"component mismatch: expected {component!r}, got {manifest.get('component')!r}"
        )
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise RuntimeError("model manifest version is missing")
    if manifest["version"] != expected_version:
        raise RuntimeError(
            f"version mismatch: expected {expected_version!r}, got {manifest['version']!r}"
        )
    if not isinstance(manifest.get("prepared_at_utc"), str):
        raise RuntimeError("model manifest prepared_at_utc is missing")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("model manifest files must be a non-empty list")
    declared_paths: set[str] = set()
    for index, record in enumerate(files):
        relative = Path(str(record.get("path", "")))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe files[{index}].path")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"files[{index}].path escapes model root") from exc
        if not candidate.is_file():
            raise RuntimeError(f"model file missing: {relative}")
        if candidate.stat().st_size != record.get("size_bytes"):
            raise RuntimeError(f"model file size mismatch: {relative}")
        if sha256_file(candidate) != record.get("sha256"):
            raise RuntimeError(f"model file hash mismatch: {relative}")
        normalized = relative.as_posix()
        if normalized in declared_paths:
            raise RuntimeError(f"duplicate model manifest path: {normalized}")
        declared_paths.add(normalized)
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.resolve() != manifest_path
    }
    unexpected = sorted(actual_paths - declared_paths)
    missing = sorted(declared_paths - actual_paths)
    if unexpected:
        raise RuntimeError(f"unlisted model files detected: {unexpected[:10]}")
    if missing:
        raise RuntimeError(f"manifest declares missing model files: {missing[:10]}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "verify"))
    parser.add_argument("--component", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    manifest_path = (args.manifest or root / "manifest.json").resolve()
    if args.mode == "prepare":
        manifest = build_manifest(args.component, args.version, root, manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(manifest_path)
    else:
        verify_manifest(args.component, args.version, root, manifest_path)
    print(f"MODEL_MANIFEST_{args.mode.upper()}=PASS component={args.component}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
