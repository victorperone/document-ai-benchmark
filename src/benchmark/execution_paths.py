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
    "visual_enrichment": Path("/models/visual-enrichment"),
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
    "unstructured": _PROJECT_ROOT / "models" / "unstructured",
    "xberg": _PROJECT_ROOT / "models" / "xberg",
    "visual_enrichment": _PROJECT_ROOT / "models" / "visual-enrichment",
}

_PARSER_MODEL_COMPONENT: dict[str, str] = {
    parser_name: parser_name
    for parser_name in _HOST_MODEL_ROOTS
    if parser_name != "visual_enrichment"
}


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


def resolve_component_model_root(runtime: str, component_name: str) -> Path:
    """Resolve an offline model root for a parser or auxiliary component."""
    if runtime == RUNTIME_DOCKER:
        try:
            return _DOCKER_MODEL_ROOTS[component_name]
        except KeyError as exc:
            raise ValueError(f"Unknown model component: {component_name!r}") from exc
    if runtime == RUNTIME_HOST:
        try:
            path = _HOST_MODEL_ROOTS[component_name].resolve()
        except KeyError as exc:
            raise ValueError(f"Unknown model component: {component_name!r}") from exc
        models_root = (_PROJECT_ROOT / "models").resolve()
        if path == models_root or models_root not in path.parents:
            raise ValueError(f"Host model root escapes models/: {path}")
        return path
    raise ValueError(f"Invalid runtime: {runtime!r}")


def resolve_model_root(runtime: str, parser_name: str) -> Path:
    """Backwards-compatible parser model root resolver."""
    try:
        component = _PARSER_MODEL_COMPONENT[parser_name]
    except KeyError as exc:
        raise ValueError(f"Unknown parser: {parser_name!r}") from exc
    return resolve_component_model_root(runtime, component)


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
