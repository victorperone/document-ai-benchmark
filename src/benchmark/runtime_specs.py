from __future__ import annotations

from dataclasses import dataclass, field


_ALL_RUNTIMES: frozenset[str] = frozenset({"docker", "host"})
_HOST_ONLY: frozenset[str] = frozenset({"host"})


@dataclass(frozen=True)
class ParserRuntimeSpec:
    module: str
    model_args: tuple[str, ...] = ()
    model_env: dict[str, str] = field(default_factory=dict)
    preflight_kwargs: dict[str, str] = field(default_factory=dict)
    supported_runtimes: frozenset[str] = field(
        default_factory=lambda: frozenset({"docker", "host"})
    )

_COMMON_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "SCARF_NO_ANALYTICS": "1",
}

PARSER_RUNTIME_SPECS: dict[str, ParserRuntimeSpec] = {
    "pymupdf": ParserRuntimeSpec(
        module="src.parsers.pymupdf_v2",
        model_env={**_COMMON_OFFLINE_ENV,},
    ),
    "docling": ParserRuntimeSpec(
        module="src.parsers.docling_v2",
        model_args=("--model-artifacts-path", "{model_root}"),
        model_env={**_COMMON_OFFLINE_ENV,},
        preflight_kwargs={"model_artifacts_override": "{model_root}"},
    ),
    "paddleocr": ParserRuntimeSpec(
        module="src.parsers.paddleocr_v2",
        model_args=("--model-root", "{model_root}"),
        model_env={
            **_COMMON_OFFLINE_ENV,
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        },
        preflight_kwargs={"model_root_override": "{model_root}"},
    ),
    "liteparse": ParserRuntimeSpec(
        module="src.parsers.liteparse_v2",
        model_args=("--model-artifacts-path", "{model_root}"),
        model_env={**_COMMON_OFFLINE_ENV,},
        preflight_kwargs={"model_artifacts_override": "{model_root}"},
    ),
    "mineru": ParserRuntimeSpec(
        module="src.parsers.mineru_v2",
        model_env={
            **_COMMON_OFFLINE_ENV,
            "MINERU_MODEL_SOURCE": "local",
            "MINERU_TOOLS_CONFIG_JSON": "{model_root}/mineru.json",
            "HF_HOME": "{model_root}/huggingface",
        },
    ),
    "unstructured": ParserRuntimeSpec(
        module="src.parsers.unstructured_v2",
        model_args=("--model-root", "{model_root}"),
        model_env={
            **_COMMON_OFFLINE_ENV,
            "HF_HOME": "{model_root}/huggingface",
            "HF_HUB_CACHE": "{model_root}/huggingface/hub",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "DO_NOT_TRACK": "1",
            "SCARF_NO_ANALYTICS": "1",
            "UNSTRUCTURED_DEFAULT_MODEL_NAME": "yolox",
            "UNSTRUCTURED_HI_RES_MODEL_NAME": "yolox",
            "OMP_THREAD_LIMIT": "1",
        },
        preflight_kwargs={"model_root_override": "{model_root}"},
        supported_runtimes=_HOST_ONLY,
    ),
    "xberg": ParserRuntimeSpec(
        module="src.parsers.xberg_v2",
        model_args=("--model-root", "{model_root}"),
        model_env={
            **_COMMON_OFFLINE_ENV,
            "HF_HOME": "{model_root}/huggingface",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        preflight_kwargs={"model_root_override": "{model_root}"},
        supported_runtimes=_HOST_ONLY,
    ),
}
