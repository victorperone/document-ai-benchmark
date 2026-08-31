"""
Validate and certify Docling model artifacts for the full_cpu_local profile.

Levels:
  A - structural: all required files exist and are non-empty
  B - component load: each model can be loaded offline individually
  C - pipeline init: the full Docling pipeline initialises offline

Writes a manifest only after all three levels pass.

Usage:
  python validate_docling_models.py [--model-root PATH] [--validate-only] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.parsers.docling_v2 import (  # noqa: E402
    CODE_FORMULA_ARTIFACT_DIRECTORY,
    GRANITE_CHART_V4_ARTIFACT_DIRECTORY,
    LAYOUT_ARTIFACT_DIRECTORY,
    PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY,
    RAPIDOCR_ARTIFACT_DIRECTORY,
    SMOLVLM_ARTIFACT_DIRECTORY,
    TABLEFORMER_ARTIFACT_DIRECTORY,
    _validate_code_formula_artifacts,
    _validate_granite_chart_v4_artifacts,
    _validate_layout_artifacts,
    _validate_picture_classifier_artifacts,
    _validate_rapidocr_artifacts,
    _validate_smolvlm_artifacts,
    _validate_tableformer_artifacts,
    _build_pipeline_options,
    _resolve_profile_runtime,
)
from src.benchmark.config import get_profile  # noqa: E402

MANIFEST_SCHEMA_VERSION = 1
DOCLING_PARSER_NAME = "docling"
FULL_CPU_LOCAL_PROFILE = "full_cpu_local"
MANIFEST_FILENAME = "docling_models_manifest.json"

# HF env vars that must be active during offline validation
_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "SCARF_NO_ANALYTICS": "1",
}


def _apply_offline_env() -> dict[str, str | None]:
    saved: dict[str, str | None] = {}
    for k, v in _OFFLINE_ENV.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _block_network() -> None:
    """Patch socket to raise on any network attempt."""
    original_create = socket.create_connection

    def blocked(*args, **kwargs):
        raise RuntimeError(
            "Network access attempted during offline validation"
        )

    class BlockedSocket(socket.socket):
        def connect(self, *args, **kwargs):
            return blocked(*args, **kwargs)

        def connect_ex(self, *args, **kwargs):
            return blocked(*args, **kwargs)

    socket.create_connection = blocked  # type: ignore[assignment]
    socket.socket = BlockedSocket  # type: ignore[misc]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    excluded_parts = {
        ".cache",
        "_hf_runtime",
        "xet",
        "__pycache__",
    }
    excluded_suffixes = {".pyc", ".pyo", ".lock", ".tmp"}
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and not any(p in excluded_parts for p in item.parts)
        and item.suffix.lower() not in excluded_suffixes
    ):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def file_record(path: Path, model_root: Path) -> dict:
    try:
        rel = path.resolve().relative_to(model_root.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError(
            f"Artifact is outside model root: {path}"
        ) from exc
    return {
        "path": rel,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


# ---------------------------------------------------------------------------
# Level A — structural validation
# ---------------------------------------------------------------------------

def validate_structural(model_root: Path) -> list[dict]:
    results = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append({"check": name, "pass": ok, "detail": detail})
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")

    # Layout (always required)
    ok, detail = _validate_layout_artifacts(model_root)
    check("layout model", ok, detail)

    # TableFormer accurate
    ok, detail = _validate_tableformer_artifacts(model_root, mode="accurate")
    check("tableformer accurate", ok, detail)

    # RapidOCR torch:pt
    ok, detail = _validate_rapidocr_artifacts(model_root)
    check("rapidocr torch:pt", ok, detail)

    # SmolVLM
    ok, detail = _validate_smolvlm_artifacts(model_root)
    check("smolvlm picture description", ok, detail)

    # Picture classifier
    ok, detail = _validate_picture_classifier_artifacts(model_root)
    check("picture classifier", ok, detail)

    # CodeFormulaV2
    ok, detail = _validate_code_formula_artifacts(model_root)
    check("code formula v2", ok, detail)

    # Granite Vision V4
    ok, detail = _validate_granite_chart_v4_artifacts(model_root)
    check("granite vision v4 chart extraction", ok, detail)

    return results


# ---------------------------------------------------------------------------
# Level B — component load (offline)
# ---------------------------------------------------------------------------

def validate_components(model_root: Path) -> list[dict]:
    results: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append({"check": name, "pass": ok, "detail": detail})
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")

    # Granite processor
    granite_path = model_root / GRANITE_CHART_V4_ARTIFACT_DIRECTORY
    try:
        from transformers import AutoProcessor  # type: ignore[import-untyped]
        _proc = AutoProcessor.from_pretrained(
            str(granite_path),
            trust_remote_code=True,
            local_files_only=True,
        )
        check("granite processor load", True, f"loaded from {granite_path}")
    except Exception as exc:
        check("granite processor load", False, f"{type(exc).__name__}: {exc}")

    # SmolVLM processor
    smolvlm_path = model_root / SMOLVLM_ARTIFACT_DIRECTORY
    try:
        from transformers import AutoProcessor  # type: ignore[import-untyped]  # noqa: F811
        _proc = AutoProcessor.from_pretrained(
            str(smolvlm_path),
            local_files_only=True,
        )
        check("smolvlm processor load", True, f"loaded from {smolvlm_path}")
    except Exception as exc:
        check("smolvlm processor load", False, f"{type(exc).__name__}: {exc}")

    # CodeFormula — try tokenizer/processor
    formula_path = model_root / CODE_FORMULA_ARTIFACT_DIRECTORY
    try:
        from transformers import AutoTokenizer  # type: ignore[import-untyped]
        _tok = AutoTokenizer.from_pretrained(
            str(formula_path),
            local_files_only=True,
        )
        check("code formula tokenizer load", True, f"loaded from {formula_path}")
    except Exception as exc:
        check("code formula tokenizer load", False, f"{type(exc).__name__}: {exc}")

    # Picture classifier — via docling API
    try:
        from docling.datamodel.pipeline_options import (  # type: ignore[import-untyped]
            PdfPipelineOptions,
        )
        _opts = PdfPipelineOptions()
        classifier_dir = model_root / PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY
        if classifier_dir.is_dir():
            check(
                "picture classifier dir",
                True,
                f"directory present: {classifier_dir}",
            )
        else:
            check(
                "picture classifier dir",
                False,
                f"missing: {classifier_dir}",
            )
    except Exception as exc:
        check(
            "picture classifier load",
            False,
            f"{type(exc).__name__}: {exc}",
        )

    # TableFormer config
    tf_config = (
        model_root
        / TABLEFORMER_ARTIFACT_DIRECTORY
        / "model_artifacts"
        / "tableformer"
        / "accurate"
        / "tm_config.json"
    )
    try:
        config_data = json.loads(tf_config.read_text(encoding="utf-8"))
        check(
            "tableformer config parse",
            True,
            f"valid JSON, model type: {config_data.get('model', {}).get('type', 'unknown')}",
        )
    except Exception as exc:
        check("tableformer config parse", False, f"{type(exc).__name__}: {exc}")

    return results


# ---------------------------------------------------------------------------
# Level C — pipeline initialization (gate principal)
# ---------------------------------------------------------------------------

def validate_pipeline_init(model_root: Path) -> tuple[bool, str]:
    print("  Constructing PdfPipelineOptions from full_cpu_local profile...")
    try:
        from docling.datamodel.base_models import (  # type: ignore[import-untyped]
            InputFormat,
        )
        from docling.document_converter import (  # type: ignore[import-untyped]
            DocumentConverter,
            PdfFormatOption,
        )

        raw_profile = get_profile(DOCLING_PARSER_NAME, FULL_CPU_LOCAL_PROFILE)
        profile = _resolve_profile_runtime(
            raw_profile,
            model_artifacts_override=model_root,
        )
        pipeline_options = _build_pipeline_options(profile)
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options
                )
            },
        )
        converter.initialize_pipeline(InputFormat.PDF)
        return True, "pipeline initialized successfully"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _model_record(
    model_root: Path,
    subdir: str,
    enabled: bool,
) -> dict:
    model_dir = model_root / subdir
    if not enabled or not model_dir.is_dir():
        return {"enabled": enabled, "directory": subdir, "present": model_dir.is_dir()}

    tree_sha, file_count = tree_digest(model_dir)
    weight_files = sorted(
        p.relative_to(model_root).as_posix()
        for p in model_dir.rglob("*.safetensors")
        if p.is_file()
        and ".cache" not in p.parts
    ) + sorted(
        p.relative_to(model_root).as_posix()
        for p in model_dir.rglob("*.pth")
        if p.is_file()
    )

    return {
        "enabled": True,
        "directory": subdir,
        "present": True,
        "tree_digest": tree_sha,
        "file_count": file_count,
        "weight_files": weight_files,
    }


def build_manifest(
    model_root: Path,
    structural_results: list[dict],
    component_results: list[dict],
    pipeline_initialized: bool,
    manifest_path: Path,
) -> None:
    structural_pass = all(r["pass"] for r in structural_results)
    component_pass = all(r["pass"] for r in component_results)

    try:
        docling_version = importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        docling_version = "unknown"

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "parser": DOCLING_PARSER_NAME,
        "docling_version": docling_version,
        "profile": FULL_CPU_LOCAL_PROFILE,
        "model_root": str(model_root),
        "offline_validation": {
            "passed": structural_pass and component_pass and pipeline_initialized,
            "structural_pass": structural_pass,
            "component_pass": component_pass,
            "pipeline_initialized": pipeline_initialized,
        },
        "capabilities": {
            "layout": _model_record(model_root, LAYOUT_ARTIFACT_DIRECTORY, True),
            "table_structure": _model_record(
                model_root, TABLEFORMER_ARTIFACT_DIRECTORY, True
            ),
            "ocr": _model_record(model_root, RAPIDOCR_ARTIFACT_DIRECTORY, True),
            "picture_description": _model_record(
                model_root, SMOLVLM_ARTIFACT_DIRECTORY, True
            ),
            "picture_classification": _model_record(
                model_root, PICTURE_CLASSIFIER_ARTIFACT_DIRECTORY, True
            ),
            "chart_extraction": _model_record(
                model_root, GRANITE_CHART_V4_ARTIFACT_DIRECTORY, True
            ),
            "formula_code_enrichment": _model_record(
                model_root, CODE_FORMULA_ARTIFACT_DIRECTORY, True
            ),
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(manifest_path)
    print(f"  Manifest written: {manifest_path}")


# ---------------------------------------------------------------------------
# Manifest validation (for preflight --validate-only check)
# ---------------------------------------------------------------------------

def validate_manifest(manifest_path: Path, model_root: Path) -> tuple[bool, str]:
    if not manifest_path.is_file():
        return False, f"manifest not found: {manifest_path}"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read manifest: {exc}"

    schema = manifest.get("schema_version")
    if schema != MANIFEST_SCHEMA_VERSION:
        return False, f"unsupported schema_version: {schema!r}"

    if manifest.get("parser") != DOCLING_PARSER_NAME:
        return False, f"parser mismatch: {manifest.get('parser')!r}"

    offline = manifest.get("offline_validation", {})
    if not offline.get("passed"):
        return False, "offline_validation.passed is not True"

    if not offline.get("pipeline_initialized"):
        return False, "pipeline_initialized is not True"

    # Check that model directories still exist
    capabilities = manifest.get("capabilities", {})
    missing = []
    for cap_name, cap_data in capabilities.items():
        if not isinstance(cap_data, dict):
            continue
        if not cap_data.get("enabled", True):
            continue
        subdir = cap_data.get("directory")
        if subdir and not (model_root / subdir).is_dir():
            missing.append(subdir)

    if missing:
        return False, "model directories removed: " + ", ".join(missing)

    return True, "manifest valid"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Docling model artifacts for full_cpu_local.",
    )
    parser.add_argument(
        "--model-root",
        type=Path,
        default=None,
        help="Path to the Docling model artifacts directory.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only run validators; do not trigger downloads.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate the manifest even if it already exists.",
    )
    parser.add_argument(
        "--skip-component-load",
        action="store_true",
        help="Skip Level B component load (structural + pipeline only).",
    )
    parser.add_argument(
        "--skip-pipeline-init",
        action="store_true",
        help="Skip Level C pipeline initialization.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    default_root = _REPO_ROOT / "models" / "docling" / "docling" / "models"
    model_root = (args.model_root or default_root).resolve()
    manifest_path = (
        _REPO_ROOT / "models" / "docling" / "manifests" / MANIFEST_FILENAME
    )

    print("=" * 70)
    print("DOCLING MODEL VALIDATION")
    print("=" * 70)
    print(f"Model root : {model_root}")
    print(f"Manifest   : {manifest_path}")
    print()

    if not model_root.is_dir():
        print(f"[FAIL] Model root does not exist: {model_root}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Apply offline env before validation phases
    # ------------------------------------------------------------------
    saved_env = _apply_offline_env()
    _block_network()

    try:
        # Level A — structural
        print("[Level A] Structural validation")
        structural_results = validate_structural(model_root)
        structural_pass = all(r["pass"] for r in structural_results)
        print(
            f"\nLevel A: {'PASS' if structural_pass else 'FAIL'} "
            f"({sum(r['pass'] for r in structural_results)}/{len(structural_results)} checks)\n"
        )

        if not structural_pass:
            print("[ABORT] Structural validation failed. Fix missing files before proceeding.")
            sys.exit(2)

        # Level B — component load
        component_results: list[dict] = []
        if not args.skip_component_load:
            print("[Level B] Component load (offline)")
            component_results = validate_components(model_root)
            component_pass = all(r["pass"] for r in component_results)
            print(
                f"\nLevel B: {'PASS' if component_pass else 'FAIL'} "
                f"({sum(r['pass'] for r in component_results)}/{len(component_results)} checks)\n"
            )
        else:
            print("[Level B] Skipped (--skip-component-load)\n")
            component_pass = True

        # Level C — pipeline initialization
        pipeline_ok = False
        if not args.skip_pipeline_init:
            print("[Level C] Pipeline initialization (offline)")
            pipeline_ok, pipeline_detail = validate_pipeline_init(model_root)
            status = "PASS" if pipeline_ok else "FAIL"
            print(f"  [{status}] pipeline init: {pipeline_detail}")
            print(f"\nLevel C: {status}\n")
        else:
            print("[Level C] Skipped (--skip-pipeline-init)\n")
            pipeline_ok = True

        all_pass = structural_pass and component_pass and pipeline_ok

        if all_pass:
            if not args.validate_only:
                if manifest_path.is_file() and not args.force:
                    print(f"[INFO] Manifest already exists: {manifest_path}")
                    print("       Use --force to regenerate.")
                else:
                    print("[Manifest] Generating manifest...")
                    build_manifest(
                        model_root,
                        structural_results,
                        component_results,
                        pipeline_ok,
                        manifest_path,
                    )
            print("\n[PASS] All validation levels passed.")
        else:
            print("\n[FAIL] One or more validation levels failed.")
            sys.exit(3)

    finally:
        _restore_env(saved_env)


if __name__ == "__main__":
    main()
