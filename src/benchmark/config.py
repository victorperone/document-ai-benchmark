"""Benchmark configuration loader.

Reads ``config/benchmark_profiles.json`` (schema version 3) and exposes
typed helpers for the three sub-sections that adapters and the orchestrator
need: parser profiles, the reference tokenizer name, and normalisation
settings.
"""

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
    """Raised when the benchmark configuration is missing, invalid, or
    references an unknown parser/profile combination."""


def load_config(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load and return the raw benchmark configuration dict.

    Args:
        path: Path to the JSON configuration file.  Defaults to
            ``config/benchmark_profiles.json`` relative to the project root.

    Returns:
        Parsed configuration dict (schema version 3).

    Raises:
        BenchmarkConfigurationError: If the file does not exist or does not
            declare ``schema_version: 3``.
    """
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

    if config.get("schema_version") != 3:
        raise BenchmarkConfigurationError(
            "Benchmark schema version 3 is required."
        )

    return config


def get_profile(
    parser_name: str,
    profile_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deep copy of the named parser profile.

    The copy ensures that adapters cannot accidentally mutate the shared
    configuration object.

    Args:
        parser_name: Parser identifier, e.g. ``"pymupdf"``.
        profile_name: Profile identifier, e.g. ``"default"``.
        config: Pre-loaded configuration dict.  When ``None`` the default
            configuration file is loaded.

    Returns:
        Deep copy of the profile dict.

    Raises:
        BenchmarkConfigurationError: If the parser/profile combination does
            not exist in the configuration.
    """
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
    """Return the tiktoken encoding name used as the reference tokenizer.

    Args:
        config: Pre-loaded configuration dict.  When ``None`` the default
            configuration file is loaded.

    Returns:
        Encoding name string, e.g. ``"cl100k_base"``.
    """
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
    """Return a deep copy of the ``normalization`` configuration block.

    Args:
        config: Pre-loaded configuration dict.  When ``None`` the default
            configuration file is loaded.

    Returns:
        Deep copy of the normalisation settings dict.
    """
    resolved_config = (
        config
        if config is not None
        else load_config()
    )

    return copy.deepcopy(
        resolved_config["normalization"]
    )
