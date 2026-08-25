from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParserRuntimeSpec:
    module: str
    model_args: tuple[str, ...] = ()
    model_env: dict[str, str] = field(default_factory=dict)
    preflight_kwargs: dict[str, str] = field(default_factory=dict)


PARSER_RUNTIME_SPECS: dict[str, ParserRuntimeSpec] = {
    "pymupdf": ParserRuntimeSpec(
        module="src.parsers.pymupdf_v2",
    ),
    "docling": ParserRuntimeSpec(
        module="src.parsers.docling_v2",
        model_args=("--model-artifacts-path", "{model_root}"),
        preflight_kwargs={"model_artifacts_override": "{model_root}"},
    ),
    "paddleocr": ParserRuntimeSpec(
        module="src.parsers.paddleocr_v2",
        model_args=("--model-root", "{model_root}"),
        preflight_kwargs={"model_root_override": "{model_root}"},
    ),
    "liteparse": ParserRuntimeSpec(
        module="src.parsers.liteparse_v2",
        model_args=("--model-artifacts-path", "{model_root}"),
        preflight_kwargs={"model_artifacts_override": "{model_root}"},
    ),
    "mineru": ParserRuntimeSpec(
        module="src.parsers.mineru_v2",
        model_env={
            "MINERU_MODEL_SOURCE": "local",
            "HF_HOME": "{model_root}/hf",
        },
    ),
}
