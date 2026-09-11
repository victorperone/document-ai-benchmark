"""Parser runtime specification registry.

``PARSER_RUNTIME_SPECS`` maps each parser name to a ``ParserRuntimeSpec``
describing which Python module to invoke, which CLI arguments pass model
paths, which environment variables should be set, and which runtimes
(``"docker"``, ``"host"``) the parser supports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


_ALL_RUNTIMES: frozenset[str] = frozenset({"docker", "host"})
_HOST_ONLY: frozenset[str] = frozenset({"host"})


@dataclass(frozen=True)
class ParserRuntimeSpec:
    """Runtime specification for a single parser.

    Attributes:
        module: Dotted Python module path passed to ``python -m`` when
            launching the parser subprocess.
        model_args: Extra CLI arguments appended to the subprocess command
            for passing model paths.  The placeholder ``{model_root}`` is
            expanded to the resolved model root at launch time.
        model_env: Environment variable overrides for the subprocess.  The
            placeholder ``{model_root}`` is expanded in values.
        preflight_kwargs: Key/value pairs forwarded to the adapter's
            ``preflight()`` function.  The placeholder ``{model_root}`` is
            expanded in values.
        supported_runtimes: Set of runtime identifiers on which this parser
            can run.  Defaults to both ``"docker"`` and ``"host"``.
    """

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
        model_args=(
            "--model-artifacts-path",
            "{model_root}",
        ),
        model_env={
            **_COMMON_OFFLINE_ENV,
            "HF_HOME": "{model_root}/_hf_runtime",
            "HF_HUB_CACHE": (
                "{model_root}/_hf_runtime/hub"
            ),
            "HF_XET_CACHE": (
                "{model_root}/_hf_runtime/xet"
            ),
        },
        preflight_kwargs={
            "model_artifacts_override": "{model_root}"
        },
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
            "UNSTRUCTURED_DEFAULT_MODEL_NAME": "yolox",
            "UNSTRUCTURED_HI_RES_MODEL_NAME": "yolox",
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
        },
        preflight_kwargs={"model_root_override": "{model_root}"},
        supported_runtimes=_HOST_ONLY,
    ),
    "inventory": ParserRuntimeSpec(
        module="scripts.build_source_inventory",
        model_args=(),
        model_env={},
        preflight_kwargs={},
        supported_runtimes=_HOST_ONLY,
    ),
}
