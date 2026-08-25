from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

RUNTIME_DOCKER = "docker"
RUNTIME_HOST = "host"

_DOCKER_OUTPUT_ROOT = Path("/outputs")
_DOCKER_DATA_ROOT = Path("/data")

_DOCKER_MODEL_ROOTS: dict[str, Path] = {
    "liteparse": Path("/models/liteparse/smolvlm"),
    "docling": Path("/home/appuser/.cache/docling/models"),
    "paddleocr": Path("/home/appuser/.paddlex/official_models"),
    "mineru": Path("/models/mineru"),
    "pymupdf": Path("/models/pymupdf"),
}


def project_root() -> Path:
    return _PROJECT_ROOT


def resolve_output_root(runtime: str) -> Path:
    if runtime == RUNTIME_DOCKER:
        return _DOCKER_OUTPUT_ROOT
    if runtime == RUNTIME_HOST:
        return _PROJECT_ROOT / "outputs"
    raise ValueError(f"Invalid runtime: {runtime!r}")


def resolve_data_root(runtime: str) -> Path:
    if runtime == RUNTIME_DOCKER:
        return _DOCKER_DATA_ROOT
    if runtime == RUNTIME_HOST:
        return _PROJECT_ROOT / "data"
    raise ValueError(f"Invalid runtime: {runtime!r}")


def resolve_model_root(runtime: str, parser_name: str) -> Path:
    if runtime == RUNTIME_DOCKER:
        try:
            return _DOCKER_MODEL_ROOTS[parser_name]
        except KeyError as exc:
            raise ValueError(f"Unknown parser: {parser_name!r}") from exc
    if runtime == RUNTIME_HOST:
        return _PROJECT_ROOT / "models" / parser_name
    raise ValueError(f"Invalid runtime: {runtime!r}")


def resolve_venv_python(parser_name: str) -> Path:
    if sys.platform == "win32":
        return _PROJECT_ROOT / ".venvs" / parser_name / "Scripts" / "python.exe"
    return _PROJECT_ROOT / ".venvs" / parser_name / "bin" / "python"


def resolve_venv_bin_dir(parser_name: str) -> Path:
    if sys.platform == "win32":
        return _PROJECT_ROOT / ".venvs" / parser_name / "Scripts"
    return _PROJECT_ROOT / ".venvs" / parser_name / "bin"
