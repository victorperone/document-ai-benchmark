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

# Host model roots mirror the physical directories mounted by compose.yaml.
# docling:  ./models/docling:/home/appuser/.cache  → cache/docling/models is the artifacts path
# paddleocr: ./models/paddleocr:/home/appuser/.paddlex → official_models is the model root
# liteparse: ./models/liteparse:/models/liteparse → smolvlm subdir
# mineru:    ./models/mineru:/models/mineru        → flat, same on both sides
_HOST_MODEL_ROOTS: dict[str, Path] = {
    "liteparse": _PROJECT_ROOT / "models" / "liteparse" / "smolvlm",
    "docling": _PROJECT_ROOT / "models" / "docling" / "docling" / "models",
    "paddleocr": _PROJECT_ROOT / "models" / "paddleocr" / "official_models",
    "mineru": _PROJECT_ROOT / "models" / "mineru",
    "pymupdf": _PROJECT_ROOT / "models" / "pymupdf",
}

# Windows requires per-parser Python version because liteparse 2.13.0 only
# ships a cp311 Windows wheel; all other parsers use Python 3.12.
_WINDOWS_PYTHON_VERSION: dict[str, str] = {
    "liteparse": "3.11",
}
_WINDOWS_PYTHON_VERSION_DEFAULT = "3.12"


def project_root() -> Path:
    return _PROJECT_ROOT


def resolve_output_root(runtime: str) -> Path:
    if runtime == RUNTIME_DOCKER:
        return _DOCKER_OUTPUT_ROOT
    if runtime == RUNTIME_HOST:
        # Host outputs are namespaced under outputs/host/ to avoid collisions
        # with Docker outputs that use the same base outputs/ directory.
        return _PROJECT_ROOT / "outputs" / "host"
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
        try:
            return _HOST_MODEL_ROOTS[parser_name]
        except KeyError as exc:
            raise ValueError(f"Unknown parser: {parser_name!r}") from exc
    raise ValueError(f"Invalid runtime: {runtime!r}")


def _windows_python_version(parser_name: str) -> str:
    return _WINDOWS_PYTHON_VERSION.get(parser_name, _WINDOWS_PYTHON_VERSION_DEFAULT)


def resolve_venv_python(parser_name: str) -> Path:
    if sys.platform == "win32":
        return (
            _PROJECT_ROOT
            / ".venvs"
            / parser_name
            / "Scripts"
            / "python.exe"
        )

    return (
        _PROJECT_ROOT
        / ".venvs"
        / parser_name
        / "bin"
        / "python"
    )


def resolve_venv_bin_dir(parser_name: str) -> Path:
    if sys.platform == "win32":
        return _PROJECT_ROOT / ".venvs" / parser_name / "Scripts"
    return _PROJECT_ROOT / ".venvs" / parser_name / "bin"
