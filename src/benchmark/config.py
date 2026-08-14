from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "benchmark_profiles.json"
)


class BenchmarkConfigurationError(RuntimeError):
    pass


def load_config(
    path: Path | None = None,
) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.is_file():
        raise BenchmarkConfigurationError(
            f"Benchmark configuration not found: "
            f"{config_path}"
        )

    config = json.loads(
        config_path.read_text(
            encoding="utf-8"
        )
    )

    if config.get("schema_version") != 2:
        raise BenchmarkConfigurationError(
            "Benchmark schema version 2 is required."
        )

    return config


def get_profile(
    parser_name: str,
    profile_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_config = (
        config
        if config is not None
        else load_config()
    )

    try:
        profile = (
            resolved_config["parsers"]
            [parser_name]
            ["profiles"]
            [profile_name]
        )
    except KeyError as exc:
        raise BenchmarkConfigurationError(
            f"Unknown parser/profile: "
            f"{parser_name}/{profile_name}"
        ) from exc

    # Return an isolated copy so adapters cannot
    # accidentally modify the shared configuration.
    return copy.deepcopy(profile)


def get_reference_tokenizer(
    config: dict[str, Any] | None = None,
) -> str:
    resolved_config = (
        config
        if config is not None
        else load_config()
    )

    return str(
        resolved_config["benchmark"]
        ["reference_tokenizer"]
    )


def get_normalization_config(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_config = (
        config
        if config is not None
        else load_config()
    )

    return copy.deepcopy(
        resolved_config["normalization"]
    )
