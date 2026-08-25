from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generic preflight runner. "
            "Validates adapter + profile without running inference."
        )
    )
    p.add_argument("--parser", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument(
        "--runtime",
        choices=["docker", "host"],
        default="docker",
        help="Runtime context: docker (default) or host.",
    )
    p.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (required for --runtime host).",
    )
    p.add_argument(
        "--model-artifacts-path",
        type=Path,
        default=None,
        help="Model artifacts override for adapters that accept it.",
    )
    return p.parse_args()


def _emit(result: dict) -> None:
    print(
        "PREFLIGHT_JSON="
        + json.dumps(result, ensure_ascii=False)
    )


def _fail_result(
    parser: str,
    profile: str,
    name: str,
    detail: str,
) -> dict:
    return {
        "schema_version": 1,
        "parser": parser,
        "profile": profile,
        "ok": False,
        "checks": [
            {
                "name": name,
                "status": "fail",
                "detail": detail,
            }
        ],
    }


def _container_checks() -> list[dict]:
    from src.benchmark.preflight import make_check

    checks: list[dict] = []

    checks.append(
        make_check(
            "/app",
            "pass" if Path("/app").is_dir() else "fail",
            "/app",
        )
    )

    checks.append(
        make_check(
            "/data",
            "pass" if Path("/data").is_dir() else "fail",
            "/data",
        )
    )

    try:
        with tempfile.NamedTemporaryFile(
            dir="/outputs",
            delete=True,
        ):
            pass
        outputs_ok = True
        outputs_detail = "/outputs"
    except Exception as exc:
        outputs_ok = False
        outputs_detail = str(exc)

    checks.append(
        make_check(
            "/outputs writable",
            "pass" if outputs_ok else "fail",
            outputs_detail,
        )
    )

    return checks


def _host_checks(project_root: Path) -> list[dict]:
    from src.benchmark.preflight import make_check

    checks: list[dict] = []

    checks.append(
        make_check(
            "project root",
            "pass" if project_root.is_dir() else "fail",
            str(project_root),
        )
    )

    data_dir = project_root / "data"
    checks.append(
        make_check(
            "data directory",
            "pass" if data_dir.is_dir() else "fail",
            str(data_dir),
        )
    )

    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=str(outputs_dir), delete=True):
            pass
        outputs_ok = True
        outputs_detail = str(outputs_dir)
    except Exception as exc:
        outputs_ok = False
        outputs_detail = str(exc)

    checks.append(
        make_check(
            "outputs writable",
            "pass" if outputs_ok else "fail",
            outputs_detail,
        )
    )

    return checks


def _build_override_kwargs(
    runtime: str,
    parser_name: str,
    model_artifacts_path: Path | None,
) -> dict:
    if runtime != "host":
        return {}

    if model_artifacts_path is not None:
        override = model_artifacts_path
    else:
        try:
            from src.benchmark.execution_paths import (
                RUNTIME_HOST,
                resolve_model_root,
            )
            override = resolve_model_root(RUNTIME_HOST, parser_name)
        except Exception:
            return {}

    try:
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS
        spec = PARSER_RUNTIME_SPECS.get(parser_name)
        if not spec or not spec.preflight_kwargs:
            return {}
        return {
            k: Path(v.replace("{model_root}", str(override)))
            for k, v in spec.preflight_kwargs.items()
        }
    except Exception:
        return {}


def main() -> None:
    args = parse_args()
    parser_name = args.parser
    profile_name = args.profile
    runtime = args.runtime

    project_root = args.project_root or ROOT

    # Ensure project root is on sys.path so src.* imports resolve
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # -- Load shared preflight helpers --
    try:
        from src.benchmark.preflight import (
            make_check,
            make_result,
            validate_result,
        )
    except Exception as exc:
        result = _fail_result(
            parser_name,
            profile_name,
            "preflight module import",
            f"{type(exc).__name__}: {exc}",
        )
        _emit(result)
        sys.exit(1)

    # -- Runtime-specific environment checks --
    if runtime == "host":
        generic_checks = _host_checks(project_root)
    else:
        generic_checks = _container_checks()

    # -- Adapter import --
    module_name = f"src.parsers.{parser_name}_v2"
    try:
        adapter = importlib.import_module(module_name)
    except Exception as exc:
        result = make_result(
            parser_name,
            profile_name,
            generic_checks
            + [
                make_check(
                    "adapter import",
                    "fail",
                    f"{type(exc).__name__}: {exc}",
                )
            ],
        )
        _emit(result)
        sys.exit(0 if result["ok"] else 1)

    generic_checks.append(
        make_check("adapter import", "pass", module_name)
    )

    # -- preflight_profile() present --
    preflight_fn = getattr(adapter, "preflight_profile", None)
    if preflight_fn is None or not callable(preflight_fn):
        result = make_result(
            parser_name,
            profile_name,
            generic_checks
            + [
                make_check(
                    "preflight_profile",
                    "fail",
                    f"{module_name} does not expose preflight_profile()",
                )
            ],
        )
        _emit(result)
        sys.exit(0 if result["ok"] else 1)

    generic_checks.append(
        make_check("preflight_profile", "pass")
    )

    # -- Call preflight_profile() --
    override_kwargs = _build_override_kwargs(
        runtime, parser_name, args.model_artifacts_path
    )
    try:
        adapter_result = preflight_fn(profile_name, **override_kwargs)
    except Exception as exc:
        result = make_result(
            parser_name,
            profile_name,
            generic_checks
            + [
                make_check(
                    "preflight_profile() call",
                    "fail",
                    f"{type(exc).__name__}: {exc}",
                )
            ],
        )
        _emit(result)
        sys.exit(0 if result["ok"] else 1)

    # -- Validate schema --
    try:
        validate_result(adapter_result)
    except Exception as exc:
        result = make_result(
            parser_name,
            profile_name,
            generic_checks
            + [
                make_check(
                    "preflight result schema",
                    "fail",
                    f"{type(exc).__name__}: {exc}",
                )
            ],
        )
        _emit(result)
        sys.exit(0 if result["ok"] else 1)

    # -- Aggregate: generic checks prepended to adapter checks --
    final_checks = generic_checks + adapter_result["checks"]
    final_result = make_result(
        adapter_result["parser"],
        adapter_result["profile"],
        final_checks,
    )

    _emit(final_result)
    sys.exit(0 if final_result["ok"] else 1)


if __name__ == "__main__":
    main()
