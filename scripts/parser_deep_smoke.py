#!/usr/bin/env python3
"""Offline, sequential deep smoke for the seven native Windows parsers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.model_manifest import verify_manifest  # noqa: E402
from src.benchmark.process_tree import run_process_tree  # noqa: E402


PARSER_PROFILES: tuple[tuple[str, str], ...] = (
    ("pymupdf", "full_cpu_local_visual"),
    ("docling", "full_cpu_local"),
    ("mineru", "full_cpu_local"),
    ("paddleocr", "full_cpu_local"),
    ("liteparse", "full_cpu_local"),
    ("unstructured", "full_cpu_local"),
    ("xberg", "full_cpu_layout"),
)
MODEL_ROOTS = {
    "pymupdf": ROOT / "models" / "visual-enrichment",
    "docling": ROOT / "models" / "docling" / "docling" / "models",
    "mineru": ROOT / "models" / "mineru",
    "paddleocr": ROOT / "models" / "paddleocr" / "official_models",
    "liteparse": ROOT / "models" / "liteparse" / "smolvlm",
    "unstructured": ROOT / "models" / "unstructured",
    "xberg": ROOT / "models" / "xberg",
}
MODEL_COMPONENTS = {
    "pymupdf": "visual_enrichment",
    "docling": "docling",
    "mineru": "mineru",
    "paddleocr": "paddleocr",
    "liteparse": "liteparse",
    "unstructured": "unstructured",
    "xberg": "xberg",
}
MODEL_VERSIONS = {
    "pymupdf": "PP-OCRv6_medium_det+PP-OCRv6_medium_rec+SmolVLM-256M-Instruct",
    "docling": "full_cpu_local",
    "mineru": "pipeline-3.4.4",
    "paddleocr": "PPStructureV3-PP-OCRv5",
    "liteparse": "SmolVLM-256M-Instruct",
    "unstructured": "full_cpu_local",
    "xberg": "layout-1.0.14",
}
FIXTURE_ROOT = ROOT / "fixtures" / "deep_smoke"
FIXTURE_PDF = FIXTURE_ROOT / "deep_smoke.pdf"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest.json"
QR_PAYLOAD = "DOC-AI-BENCHMARK-QR-2026"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_fixture() -> dict:
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("pages") != 2:
        raise RuntimeError("deep-smoke manifest must declare schema v1 and two pages")
    if manifest.get("qr_payload") != QR_PAYLOAD:
        raise RuntimeError("deep-smoke QR payload does not match the fixed contract")
    required = {
        "title", "portuguese_digital_text", "markdown_table", "formula", "code",
        "chart_diagram", "text_image", "qr", "stamp", "rotated_raster_region",
    }
    if not required.issubset(set(manifest.get("features") or [])):
        raise RuntimeError("deep-smoke fixture is missing required feature declarations")
    for record in manifest.get("files") or []:
        relative = Path(str(record.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise RuntimeError(f"unsafe fixture path: {relative}")
        path = (FIXTURE_ROOT / relative).resolve()
        if FIXTURE_ROOT.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(f"fixture file missing or outside fixture root: {relative}")
        if path.stat().st_size != record.get("size_bytes"):
            raise RuntimeError(f"fixture size mismatch: {relative}")
        if _sha256(path) != record.get("sha256"):
            raise RuntimeError(f"fixture hash mismatch: {relative}")
    pdf_bytes = FIXTURE_PDF.read_bytes()
    if b"/Count 2" not in pdf_bytes or b"/Rotate 90" not in pdf_bytes:
        raise RuntimeError("deep-smoke PDF structure is not the expected two-page fixture")
    return manifest


def verify_model(parser: str) -> dict:
    root = MODEL_ROOTS[parser].resolve()
    return verify_manifest(
        MODEL_COMPONENTS[parser],
        MODEL_VERSIONS[parser],
        root,
        root / "manifest.json",
    )


def _artifact_text(job_root: Path) -> str:
    contents: list[str] = []
    for name in ("raw.md", "document.md", "document.enriched.md"):
        path = job_root / name
        if path.is_file():
            contents.append(path.read_text(encoding="utf-8"))
    return "\n".join(contents)


def validate_job(parser: str, profile: str, output_base: Path) -> None:
    job_root = output_base.resolve() / "host" / parser / FIXTURE_PDF.stem / profile
    metrics_path = job_root / "metrics.json"
    if not metrics_path.is_file():
        raise RuntimeError(f"{parser}: metrics.json was not produced")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if metrics.get("run", {}).get("parser") != parser:
        raise RuntimeError(f"{parser}: metrics parser provenance mismatch")
    for artifact in ("raw.md", "document.md", "document.enriched.md", "removed_content.jsonl"):
        if not (job_root / artifact).is_file():
            raise RuntimeError(f"{parser}: selected artifact missing: {artifact}")
    native_manifest = job_root / "native" / "manifest.json"
    if not native_manifest.is_file():
        raise RuntimeError(f"{parser}: native manifest missing")
    for name, validation in (metrics.get("content_validation") or {}).items():
        if validation.get("selected") and validation.get("valid") is not True:
            raise RuntimeError(f"{parser}: invalid selected artifact content: {name}")

    text = _artifact_text(job_root)
    normalized = re.sub(r"\s+", " ", text).casefold()
    enriched = re.sub(
        r"\s+", " ",
        (job_root / "document.enriched.md").read_text(encoding="utf-8"),
    ).casefold()
    if parser == "xberg" and QR_PAYLOAD.casefold() not in enriched:
        raise RuntimeError(f"{parser}: exact QR payload not found")
    if parser in {"pymupdf", "liteparse", "unstructured"}:
        occurrences = enriched.count("imagem ocr")
        if occurrences != 1:
            raise RuntimeError(
                f"{parser}: image OCR marker must occur exactly once, got {occurrences}"
            )
    if parser in {"pymupdf", "docling", "mineru", "paddleocr", "xberg"}:
        if "quantidade" not in normalized:
            raise RuntimeError(f"{parser}: table content marker not found")
        if not any(marker in normalized for marker in ("e = mc", "e=mc", "formula")):
            raise RuntimeError(f"{parser}: formula marker not found")

    forbidden = ("visual_crops", "visual-crops", "document-ai-visual-")
    leaked = [
        path for path in job_root.rglob("*")
        if path.is_file() and any(part in path.as_posix().casefold() for part in forbidden)
    ]
    if leaked:
        raise RuntimeError(f"{parser}: transient visual crops persisted: {leaked}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs" / "deep_smoke")
    parser.add_argument("--job-timeout-seconds", type=int, default=3600)
    parser.add_argument("--verbose-output", action="store_true")
    parser.add_argument("--validate-fixture-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verify_fixture()
    print("DEEP_SMOKE_FIXTURE=PASS")
    if args.validate_fixture_only:
        return 0
    if os.name != "nt":
        raise RuntimeError("full deep smoke must run on native Windows Server")
    if args.job_timeout_seconds <= 0:
        raise ValueError("--job-timeout-seconds must be positive")

    env = os.environ.copy()
    env.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        "DO_NOT_TRACK": "1",
    })
    failures: list[str] = []
    for parser, profile in PARSER_PROFILES:
        try:
            verify_model(parser)
            command = [
                sys.executable, str(ROOT / "scripts" / "run_batch.py"),
                "--parser", parser, "--profile", profile,
                "--runtime", "host", "--input-dir", str(FIXTURE_ROOT),
                "--output-root", str(args.output_root.resolve()),
                "--artifacts", "all", "--force", "--no-summary",
                "--job-timeout-seconds", str(args.job_timeout_seconds),
            ]
            if args.verbose_output:
                command.append("--verbose-output")
            result = run_process_tree(
                command, cwd=ROOT, env=env, timeout=args.job_timeout_seconds + 360,
                capture_output=True,
            )
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "no subprocess output")[-4000:]
                raise RuntimeError(f"runner failed with {result.returncode}: {detail}")
            validate_job(parser, profile, args.output_root)
            verify_model(parser)
            print(f"DEEP_SMOKE_PARSER=PASS parser={parser} profile={profile}")
        except Exception as exc:
            failures.append(parser)
            print(f"DEEP_SMOKE_PARSER=FAIL parser={parser} error={exc}", file=sys.stderr)
    print("DEEP_SMOKE_READY=" + ",".join(p for p, _ in PARSER_PROFILES if p not in failures))
    print("DEEP_SMOKE_FAILED=" + ",".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
