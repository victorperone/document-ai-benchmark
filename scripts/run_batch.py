from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.benchmark.preflight import validate_result  # noqa: E402
from src.benchmark.artifact_policy import ArtifactPolicy, ArtifactSelectionError  # noqa: E402
from src.benchmark.paths import build_output_paths  # noqa: E402
from src.benchmark.post_validation import validate_post_execution, validate_resume_candidate  # noqa: E402
from src.benchmark.process_tree import run_process_tree  # noqa: E402
from src.benchmark.execution_paths import (  # noqa: E402
    RUNTIME_DOCKER,
    RUNTIME_HOST,
    resolve_model_root,
    resolve_venv_bin_dir,
    resolve_venv_python,
)
from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS  # noqa: E402

CONFIG_PATH = (
    ROOT
    / "config"
    / "benchmark_profiles.json"
)

LOGS_DIR = ROOT / "logs"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class JobRecord:
    doc: Path
    parser: str
    profile: str
    sha256: str = ""
    output_dir: str = ""
    status: str = "pending"  # pending | skip | done | fail | aborted
    exit_code: int = 0
    elapsed: float = 0.0
    error: str | None = None
    validation: dict | None = None

    @property
    def label(self) -> str:
        return f"{self.parser}/{self.doc.stem}/{self.profile}"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {value!r}"
        )
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Batch orchestrator: discovers PDFs, validates the run plan, "
            "builds source inventories, then executes each document through "
            "every requested parser sequentially."
        )
    )

    p.add_argument(
        "--input-dir",
        metavar="DIR",
        help="Directory with PDFs. Default: config benchmark.input_directory.",
    )

    p.add_argument(
        "--limit",
        metavar="N",
        type=parse_positive_int,
        default=None,
        help="Limit execution to the first N PDFs after deterministic discovery.",
    )

    target = p.add_mutually_exclusive_group(required=False)
    target.add_argument(
        "--suite",
        metavar="SUITE",
        help=(
            "Named suite from benchmark_profiles.json (runs multiple parser+profile pairs). "
            "Defaults to 'default' when neither --suite nor --parser is given."
        ),
    )
    target.add_argument(
        "--parser",
        metavar="PARSER",
        help="Single parser name (e.g. pymupdf). Requires --profile.",
    )

    p.add_argument(
        "--profile",
        metavar="PROFILE",
        help="Profile name (e.g. ocr_auto_rapidtess). Required with --parser.",
    )
    p.add_argument(
        "--output-root",
        metavar="DIR",
        help=(
            "Base output root. "
            "For runtime=host, a 'host' namespace is "
            "appended automatically. "
            "Default: config benchmark.output_directory."
        ),
    )
    p.add_argument(
        "--artifacts",
        default="all",
        metavar="SPEC",
        help="Artifacts selector passed to the parser (default: all).",
    )

    resume = p.add_mutually_exclusive_group()
    resume.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=True,
        help="Skip jobs that already have metrics.json (default).",
    )
    resume.add_argument(
        "--force",
        dest="resume",
        action="store_false",
        help="Re-run jobs even when metrics.json already exists.",
    )

    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue to the next job instead of aborting on first failure.",
    )
    execution_mode = p.add_mutually_exclusive_group()

    execution_mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the full job plan "
            "without executing."
        ),
    )

    execution_mode.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Validate the batch environment "
            "without running document inference."
        ),
    )

    execution_mode.add_argument(
        "--resume-check",
        action="store_true",
        help=(
            "Read-only check: verify that every job in the plan is "
            "reusable (would be SKIP in a resume run). "
            "Exit 0 if all reusable, exit 1 if any job is pending. "
            "Never starts containers or modifies outputs."
        ),
    )

    p.add_argument(
        "--runtime",
        choices=[RUNTIME_DOCKER, RUNTIME_HOST],
        default=os.environ.get("BENCHMARK_RUNTIME", RUNTIME_DOCKER),
        help="Execution runtime: docker (default) or host.",
    )
    p.add_argument(
        "--compose-override",
        metavar="FILE",
        help="Additional compose file to overlay.",
    )
    p.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip post-run summary scripts.",
    )
    p.add_argument(
        "--job-timeout-seconds",
        type=parse_positive_int,
        default=3600,
        help="Maximum host job duration before its process tree is terminated (default: 3600).",
    )
    p.add_argument(
        "--verbose-output",
        action="store_true",
        help="Stream verbose diagnostics from parser adapters.",
    )

    args = p.parse_args()

    if args.parser and not args.profile:
        p.error("--profile is required when --parser is used.")
    if args.profile and not args.parser:
        p.error("--parser is required when --profile is used.")
    if args.resume_check and not args.resume:
        p.error("--force and --resume-check are semantically incompatible: "
                "resume-check must evaluate actual on-disk state without forcing re-execution.")

    return args


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def validate_runtime_support(
    jobs_spec: list[tuple[str, str]],
    runtime: str,
) -> None:
    """Raise SystemExit if any parser does not support the requested runtime.

    Called before any Docker or host dispatch so the error surfaces early,
    before containers are queried or compose files are read.
    """
    errors: list[str] = []
    for parser_name, _ in jobs_spec:
        spec = PARSER_RUNTIME_SPECS.get(parser_name)
        if spec is not None and runtime not in spec.supported_runtimes:
            errors.append(
                f"Parser '{parser_name}' does not support runtime '{runtime}'. "
                f"Supported: {sorted(spec.supported_runtimes)}"
            )
    if errors:
        raise SystemExit("\n".join(errors))


def resolve_jobs_spec(args: argparse.Namespace, config: dict) -> list[tuple[str, str]]:
    suite_name = args.suite if args.suite else (None if args.parser else "default")
    if suite_name is not None:
        suites = config["suites"]
        if suite_name not in suites:
            available = ", ".join(sorted(suites))
            raise SystemExit(f"Unknown suite '{suite_name}'. Available: {available}")
        return [tuple(job) for job in suites[suite_name]]
    return [(args.parser, args.profile)]


# ── Phase 1: Discover PDFs ────────────────────────────────────────────────────

def discover_pdfs(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {input_dir}")
    docs = sorted(p for p in input_dir.glob("*.pdf") if p.is_file())
    if not docs:
        raise SystemExit(f"No PDF files found in {input_dir}")
    return docs


def apply_document_limit(docs: list[Path], limit: int | None) -> list[Path]:
    if limit is None or limit >= len(docs):
        return docs
    return docs[:limit]


# ── Phase 2: Validate batch ───────────────────────────────────────────────────

def validate_batch(jobs_spec: list[tuple[str, str]], config: dict) -> None:
    parsers_cfg = config.get("parsers", {})
    errors: list[str] = []

    for parser_name, profile_name in jobs_spec:
        if parser_name not in parsers_cfg:
            errors.append(f"Unknown parser: '{parser_name}'")
            continue
        profiles = parsers_cfg[parser_name].get("profiles", {})
        if profile_name not in profiles:
            errors.append(f"Unknown profile '{profile_name}' for parser '{parser_name}'")

    if errors:
        raise SystemExit("Validation errors:\n" + "\n".join(f"  - {e}" for e in errors))



# ── Phase 3: Build source inventories ────────────────────────────────────────

def _json_sha_matches(path: Path, expected_sha: str) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("sha256") == expected_sha


def build_source_inventories(
    docs: list[Path],
    doc_sha256: dict[Path, str],
    input_dir: Path,
    output_root: Path,
    compose_base: list[str],
    resume: bool,
    log,
    *,
    runtime: str = RUNTIME_DOCKER,
) -> None:
    inventory_dir = output_root / "_source_inventory"

    for doc in docs:
        inv_file = inventory_dir / f"{doc.stem}.json"
        if resume and _json_sha_matches(inv_file, doc_sha256[doc]):
            log(f"  [SKIP ] source inventory: {doc.name}")
            continue

        log(f"  [BUILD] source inventory: {doc.name}")

        if runtime == RUNTIME_HOST:
            cmd = [
                str(resolve_venv_python("pymupdf")),
                "-m",
                "scripts.build_source_inventory",
                "--input-dir", str(input_dir),
                "--output-dir", str(inventory_dir),
                "--only", doc.name,
            ]
            env = _build_host_environment("pymupdf")
            result = run_process_tree(
                cmd, cwd=ROOT, env=env, timeout=3600, capture_output=False
            )
            code = result.returncode
        else:
            container_input_dir = _to_container_input_dir(input_dir)
            container_inventory_dir = to_container_output_root(output_root) + "/_source_inventory"
            cmd = compose_base + [
                "run", "--rm",
                "-e", "PYTHONPATH=/app",
                "--entrypoint", "python",
                "pymupdf",
                "/app/scripts/build_source_inventory.py",
                "--input-dir", container_input_dir,
                "--output-dir", container_inventory_dir,
                "--only", doc.name,
            ]
            code = subprocess.run(cmd, cwd=str(ROOT)).returncode

        if code != 0:
            raise SystemExit(
                f"Source inventory failed for {doc.name} (exit={code}). "
                "Cannot proceed without it."
            )


# ── Phase 4: Build run plan ───────────────────────────────────────────────────

def build_run_plan(
    docs: list[Path],
    jobs_spec: list[tuple[str, str]],
    output_root: Path,
    resume: bool,
    artifact_policy: ArtifactPolicy | None = None,
) -> tuple[list[JobRecord], dict[Path, str]]:
    plan: list[JobRecord] = []
    sha_cache: dict[Path, str] = {}
    _policy = artifact_policy or ArtifactPolicy.from_cli(["all"])
    for doc in docs:
        if doc not in sha_cache:
            sha_cache[doc] = _sha256(doc)
        for parser_name, profile_name in jobs_spec:
            out_dir = str(output_root / parser_name / doc.stem / profile_name)
            rec = JobRecord(
                doc=doc,
                parser=parser_name,
                profile=profile_name,
                sha256=sha_cache[doc],
                output_dir=out_dir,
            )
            if resume:
                resume_result = validate_resume_candidate(
                    output_root=output_root,
                    parser=parser_name,
                    profile=profile_name,
                    document_path=doc,
                    expected_sha256=sha_cache[doc],
                    requested_artifacts=_policy,
                )
                if resume_result["ok"]:
                    rec.status = "skip"
                    rec.validation = resume_result
            plan.append(rec)
    return plan, sha_cache


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=ROOT, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _is_git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=ROOT, timeout=5,
        )
        return bool(result.stdout.strip()) if result.returncode == 0 else False
    except Exception:
        return False


def _metrics_match(
    output_root: Path,
    parser: str,
    doc_stem: str,
    profile: str,
    expected_sha: str,
) -> bool:
    metrics_path = output_root / parser / doc_stem / profile / "metrics.json"
    if not metrics_path.is_file():
        return False
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        metrics.get("document", {}).get("sha256") == expected_sha
        and metrics.get("run", {}).get("parser") == parser
        and metrics.get("run", {}).get("profile") == profile
    )


# ── Phase 5: Execute ──────────────────────────────────────────────────────────

def execute_plan(
    plan: list[JobRecord],
    compose_base: list[str],
    container_output_root: str,
    artifacts: str,
    continue_on_error: bool,
    results_path: Path,
    log,
    *,
    output_root: Path,
    artifact_policy: ArtifactPolicy,
    runtime: str = RUNTIME_DOCKER,
    job_timeout_seconds: int = 3600,
    verbose_output: bool = False,
) -> None:
    total = len(plan)
    current_doc: Path | None = None

    for n, rec in enumerate(plan, 1):
        if rec.doc != current_doc:
            current_doc = rec.doc
            log(f"\n--- {rec.doc.name} ({n}/{total}) ---")

        if rec.status == "skip":
            log(f"  [SKIP ]  {rec.parser}/{rec.profile}")
            _append_result(results_path, rec)
            continue

        clean_job_output(output_root, rec)
        log(f"  [START]  {rec.parser}/{rec.profile}")
        t0 = time.monotonic()
        rec.exit_code = _run_subprocess(
            compose_base, rec.parser, rec.doc, rec.profile, container_output_root, artifacts,
            runtime=runtime, output_root=output_root,
            timeout_seconds=job_timeout_seconds,
            verbose_output=verbose_output,
        )
        rec.elapsed = time.monotonic() - t0

        if rec.exit_code == 0:
            inv_path = output_root / "_source_inventory" / f"{rec.doc.stem}.json"
            validation = validate_post_execution(
                output_root=output_root,
                parser=rec.parser,
                profile=rec.profile,
                document_path=rec.doc,
                expected_sha256=rec.sha256,
                artifact_policy=artifact_policy,
                source_inventory_path=inv_path if inv_path.is_file() else None,
            )
            rec.validation = validation
            if validation["ok"]:
                rec.status = "done"
                warns = [c.get("detail", c["name"]) for c in validation["checks"] if c["status"] == "warn"]
                if warns:
                    log(f"  [WARN ]  {rec.parser}/{rec.profile}  post-validation: {'; '.join(warns)}")
                log(f"  [DONE ]  {rec.parser}/{rec.profile}  ({rec.elapsed:.0f}s)")
            else:
                rec.status = "fail"
                fails = [c.get("detail", c["name"]) for c in validation["checks"] if c["status"] == "fail"]
                rec.error = "post_validation: " + "; ".join(fails)
                log(f"  [FAIL ]  {rec.parser}/{rec.profile}  {rec.error}  ({rec.elapsed:.0f}s)")
        else:
            rec.status = "fail"
            rec.error = f"exit_code={rec.exit_code}"
            log(f"  [FAIL ]  {rec.parser}/{rec.profile}  exit={rec.exit_code}  ({rec.elapsed:.0f}s)")

        _append_result(results_path, rec)

        if rec.status == "fail" and not continue_on_error:
            log("\nAborted on first failure. Use --continue-on-error to keep going.")
            for remaining in plan[n:]:
                remaining.status = "aborted"
                _append_result(results_path, remaining)
            return


def clean_job_output(output_root: Path, rec: JobRecord) -> None:
    """Remove exactly one pending job leaf so stale assets cannot survive."""
    root = output_root.resolve()
    leaf = (output_root / rec.parser / rec.doc.stem / rec.profile).resolve()
    try:
        leaf.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"job output escapes output root: {leaf}") from exc
    if leaf == root or len(leaf.parts) <= len(root.parts) + 2:
        raise ValueError(f"refusing to clean non-leaf output path: {leaf}")
    if leaf.exists():
        if not leaf.is_dir():
            raise ValueError(f"job output leaf is not a directory: {leaf}")
        shutil.rmtree(leaf)


def _append_result(results_path: Path, rec: JobRecord) -> None:
    row = {
        "document": rec.doc.name,
        "sha256": rec.sha256,
        "parser": rec.parser,
        "profile": rec.profile,
        "status": rec.status,
        "exit_code": rec.exit_code,
        "elapsed_seconds": round(rec.elapsed, 2),
        "output_dir": rec.output_dir,
        "error": rec.error,
        "validation": rec.validation,
    }
    with results_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _to_container_input_dir(dir_path: Path) -> str:
    data_dir = (ROOT / "data").resolve()
    try:
        return "/data/" + str(dir_path.resolve().relative_to(data_dir))
    except ValueError:
        raise SystemExit(f"--input-dir must be inside {data_dir}")


def to_container_output_root(output_root: Path) -> str:
    outputs_dir = (ROOT / "outputs").resolve()
    try:
        relative = output_root.resolve().relative_to(outputs_dir)
    except ValueError:
        raise SystemExit(f"--output-root must be inside {outputs_dir}")
    if relative == Path("."):
        return "/outputs"
    return "/outputs/" + relative.as_posix()


def _to_container_doc_path(doc_path: Path) -> str:
    data_dir = (ROOT / "data").resolve()
    try:
        relative = doc_path.resolve().relative_to(data_dir)
    except ValueError:
        raise SystemExit(f"Input document must be inside {data_dir}: {doc_path}")
    return "/data/" + relative.as_posix()


def _build_docker_command(
    compose_base: list[str],
    parser_name: str,
    doc_path: Path,
    profile_name: str,
    container_output_root: str,
    artifacts: str,
) -> list[str]:
    return compose_base + [
        "run", "--rm",
        "-e", "PYTHONPATH=/app",
        "--entrypoint", "python",
        parser_name,
        f"/app/src/parsers/{parser_name}_v2.py",
        "--input", _to_container_doc_path(doc_path),
        "--output-root", container_output_root,
        "--profile", profile_name,
        "--artifacts", artifacts,
    ]


def _build_host_command(
    parser_name: str,
    doc_path: Path,
    output_root: Path,
    profile_name: str,
    artifacts: str,
) -> tuple[list[str], dict[str, str]]:
    spec = PARSER_RUNTIME_SPECS[parser_name]
    model_root = resolve_model_root(RUNTIME_HOST, parser_name)

    model_args = [
        v.replace("{model_root}", str(model_root))
        for v in spec.model_args
    ]
    model_env = {
        k: v.replace("{model_root}", str(model_root))
        for k, v in spec.model_env.items()
    }

    cmd = [
        str(resolve_venv_python(parser_name)),
        "-m",
        spec.module,
        "--input", str(doc_path),
        "--output-root", str(output_root),
        "--profile", profile_name,
        "--artifacts", artifacts,
        *model_args,
    ]

    return cmd, model_env


def _build_host_environment(
    parser_name: str,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    venv_bin = str(resolve_venv_bin_dir(parser_name))
    current_path = env.get("PATH", "")
    env["PATH"] = venv_bin if not current_path else venv_bin + os.pathsep + current_path
    return env


def _run_host_subprocess(
    parser_name: str,
    cmd: list[str],
    extra_env: dict[str, str],
    timeout_seconds: int = 3600,
) -> int:
    env = _build_host_environment(parser_name, extra_env)
    result = run_process_tree(
        cmd,
        cwd=str(ROOT),
        env=env,
        timeout=timeout_seconds,
    )
    if result.timed_out:
        print(f"Host job timed out after {timeout_seconds}s: {parser_name}", file=sys.stderr)
    return result.returncode


def _run_subprocess(
    compose_base: list[str],
    parser_name: str,
    doc_path: Path,
    profile_name: str,
    container_output_root: str,
    artifacts: str,
    *,
    runtime: str = RUNTIME_DOCKER,
    output_root: Path | None = None,
    timeout_seconds: int = 3600,
    verbose_output: bool = False,
) -> int:
    if runtime == RUNTIME_HOST:
        if output_root is None:
            raise ValueError("output_root is required for host runtime")
        cmd, extra_env = _build_host_command(
            parser_name, doc_path, output_root, profile_name, artifacts
        )
        if verbose_output:
            cmd.append("--verbose")
        return _run_host_subprocess(
            parser_name, cmd, extra_env, timeout_seconds=timeout_seconds
        )

    cmd = _build_docker_command(
        compose_base, parser_name, doc_path, profile_name, container_output_root, artifacts
    )
    if verbose_output:
        cmd.append("--verbose")
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


# ── Phase 6: Batch summary ────────────────────────────────────────────────────

def batch_summary(plan: list[JobRecord], elapsed: float, log) -> dict[str, int]:
    counts: dict[str, int] = {"done": 0, "skip": 0, "fail": 0, "aborted": 0}
    for rec in plan:
        if rec.status in counts:
            counts[rec.status] += 1

    log(
        f"\nbatch_end"
        f"  done={counts['done']}"
        f"  skip={counts['skip']}"
        f"  fail={counts['fail']}"
        f"  aborted={counts['aborted']}"
        f"  elapsed={elapsed:.0f}s"
    )
    return counts


# ── Post-run ──────────────────────────────────────────────────────────────────

_COMPARISON_REQUIREMENTS: dict[str, frozenset[tuple[str, str]]] = {
    "build_parser_comparison.py": frozenset(
        {
            ("pymupdf", "native"),
            ("docling", "native"),
        }
    ),
    "build_native_parser_comparison.py": frozenset(
        {
            ("pymupdf", "native"),
            ("docling", "native"),
            ("mineru", "txt"),
        }
    ),
}


def run_summary_scripts(
    jobs_spec: list[tuple[str, str]],
    output_root: Path,
) -> bool:
    planned = set(jobs_spec)
    metrics_root = ROOT / "metrics"
    all_ok = True

    for script_name, required_pairs in _COMPARISON_REQUIREMENTS.items():
        script_path = ROOT / "scripts" / script_name

        if not script_path.is_file():
            print(
                f"[SUMMARY] not found, skipping: {script_name}"
            )
            continue

        if not required_pairs.issubset(planned):
            missing = required_pairs - planned
            missing_str = ", ".join(
                f"{p}/{pr}" for p, pr in sorted(missing)
            )
            print(
                f"[SUMMARY] skipped {script_name}: "
                f"required profiles not in current run "
                f"({missing_str})"
            )
            continue

        print(f"\n[SUMMARY] {script_name}")
        completed = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--output-root",
                str(output_root),
                "--metrics-root",
                str(metrics_root),
            ],
            cwd=str(ROOT),
        )

        if completed.returncode != 0:
            print(
                f"[SUMMARY FAIL] {script_name} "
                f"exit={completed.returncode}"
            )
            all_ok = False

    return all_ok


def run_parser_preflight(
    compose_base: list[str],
    parser_name: str,
    profile_name: str,
    *,
    runtime: str = RUNTIME_DOCKER,
) -> dict:
    if runtime == RUNTIME_HOST:
        cmd = [
            str(resolve_venv_python(parser_name)),
            "-m",
            "scripts.parser_preflight",
            "--parser", parser_name,
            "--profile", profile_name,
            "--runtime", "host",
            "--project-root", str(ROOT),
        ]
        spec = PARSER_RUNTIME_SPECS.get(parser_name)
        model_root = resolve_model_root(RUNTIME_HOST, parser_name)
        extra_env = {
            k: v.replace("{model_root}", str(model_root))
            for k, v in (spec.model_env if spec else {}).items()
        }
        result = run_process_tree(
            cmd,
            cwd=str(ROOT),
            timeout=300,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=_build_host_environment(parser_name, extra_env),
        )
    else:
        cmd = compose_base + [
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "-e", "PYTHONPATH=/app",
            "--entrypoint", "python",
            parser_name,
            "/app/scripts/parser_preflight.py",
            "--parser", parser_name,
            "--profile", profile_name,
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    preflight_json: dict | None = None
    for line in reversed((result.stdout or "").splitlines()):
        if line.startswith("PREFLIGHT_JSON="):
            try:
                preflight_json = json.loads(
                    line[len("PREFLIGHT_JSON="):]
                )
            except json.JSONDecodeError:
                pass
            break

    if preflight_json is None:
        tail = "\n".join(
            (result.stdout + "\n" + result.stderr)
            .splitlines()[-20:]
        )
        return {
            "schema_version": 1,
            "parser": parser_name,
            "profile": profile_name,
            "ok": False,
            "checks": [
                {
                    "name": "parser preflight protocol",
                    "status": "fail",
                    "detail": tail.strip() or "No PREFLIGHT_JSON= line found",
                }
            ],
        }


    _protocol_error: str | None = None
    try:
        validate_result(preflight_json)

        if preflight_json["parser"] != parser_name:
            raise ValueError(
                f"Preflight parser mismatch: "
                f"expected {parser_name!r}, "
                f"got {preflight_json['parser']!r}"
            )

        if preflight_json["profile"] != profile_name:
            raise ValueError(
                f"Preflight profile mismatch: "
                f"expected {profile_name!r}, "
                f"got {preflight_json['profile']!r}"
            )

    except Exception as exc:
        _protocol_error = f"{type(exc).__name__}: {exc}"

    if _protocol_error is not None:
        return {
            "schema_version": 1,
            "parser": parser_name,
            "profile": profile_name,
            "ok": False,
            "checks": [
                {
                    "name": "parser preflight protocol",
                    "status": "fail",
                    "detail": _protocol_error,
                }
            ],
        }

    expected_returncode = 0 if preflight_json["ok"] else 1
    if result.returncode != expected_returncode:
        return {
            "schema_version": 1,
            "parser": parser_name,
            "profile": profile_name,
            "ok": False,
            "checks": [
                {
                    "name": "parser preflight protocol",
                    "status": "fail",
                    "detail": (
                        f"Exit code mismatch: "
                        f"JSON ok={preflight_json['ok']} "
                        f"but process exited {result.returncode}"
                    ),
                }
            ],
        }

    return preflight_json


def build_compose_base(
    compose_override: str | None,
) -> list[str]:
    compose_base: list[str] = [
        "docker",
        "compose",
    ]

    if compose_override:
        compose_base += [
            "-f",
            "compose.yaml",
            "-f",
            compose_override,
        ]

    return compose_base


def nearest_existing_parent(
    path: Path,
) -> Path:
    current = path.resolve()

    while (
        not current.exists()
        and current != current.parent
    ):
        current = current.parent

    return current


_PREFLIGHT_STATUS_LABEL: dict[str, str] = {
    "pass": "OK  ",
    "warn": "WARN",
    "fail": "FAIL",
}


def run_preflight(
    jobs_spec: list[
        tuple[str, str]
    ],
    docs: list[Path],
    input_dir: Path,
    output_root: Path,
    compose_base: list[str],
    compose_override: str | None,
    runtime: str = RUNTIME_DOCKER,
) -> bool:
    failures = 0
    warnings_count = 0

    def report(
        ok: bool,
        label: str,
        detail: str | None = None,
    ) -> None:
        nonlocal failures

        if ok:
            status = "OK"
        else:
            status = "FAIL"
            failures += 1

        print(
            f"  [{status:<4}] {label}"
        )

        if detail:
            for line in detail.splitlines():
                print(
                    f"         {line}"
                )

    print()
    print(
        "PREFLIGHT - infrastructure"
    )
    print(
        "-" * 72
    )

    # --------------------------------------------------
    # Benchmark configuration
    # --------------------------------------------------

    report(
        CONFIG_PATH.is_file(),
        "benchmark configuration",
        str(CONFIG_PATH),
    )

    # --------------------------------------------------
    # Input
    # --------------------------------------------------

    report(
        input_dir.is_dir(),
        "input directory",
        str(input_dir),
    )

    report(
        bool(docs),
        "PDF discovery",
        f"{len(docs)} PDF(s)",
    )

    # --------------------------------------------------
    # Output
    # --------------------------------------------------

    writable_parent = (
        nearest_existing_parent(
            output_root
        )
    )

    output_writable = (
        writable_parent.is_dir()
        and os.access(
            writable_parent,
            os.W_OK,
        )
    )

    report(
        output_writable,
        "output path writable",
        str(writable_parent),
    )

    # --------------------------------------------------
    # Required project files
    # --------------------------------------------------

    inventory_script = (
        ROOT
        / "scripts"
        / "build_source_inventory.py"
    )

    report(
        inventory_script.is_file(),
        "source inventory script",
        str(inventory_script),
    )

    parsers = sorted(
        {
            parser_name
            for parser_name, _
            in jobs_spec
        }
    )

    for parser_name in parsers:
        adapter = (
            ROOT
            / "src"
            / "parsers"
            / f"{parser_name}_v2.py"
        )

        report(
            adapter.is_file(),
            (
                f"adapter "
                f"{parser_name}_v2.py"
            ),
            str(adapter),
        )

    if runtime == RUNTIME_HOST:
        # --------------------------------------------------
        # Host: check venv existence for each required parser
        # --------------------------------------------------

        required_venvs = set(parsers) | {"pymupdf"}

        for venv_name in sorted(required_venvs):
            python_exe = resolve_venv_python(venv_name)
            report(
                python_exe.is_file(),
                f"venv {venv_name}",
                str(python_exe),
            )

        parser_preflight_ready = failures == 0

    else:
        # --------------------------------------------------
        # Docker: compose override, CLI, daemon, services
        # --------------------------------------------------

        if compose_override:
            override_path = Path(compose_override)

            if not override_path.is_absolute():
                override_path = ROOT / override_path

            report(
                override_path.is_file(),
                "compose override",
                str(override_path),
            )

        docker_path = shutil.which("docker")

        report(
            docker_path is not None,
            "Docker CLI",
            docker_path,
        )

        if docker_path is None:
            print()
            print(
                f"Preflight result: FAIL "
                f"({failures} failure(s))"
            )
            return False

        docker_info = subprocess.run(
            [
                "docker",
                "info",
                "--format",
                "{{.ServerVersion}}",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )

        docker_detail = (
            docker_info.stdout.strip()
            if docker_info.returncode == 0
            else docker_info.stderr.strip()
        )

        report(
            docker_info.returncode == 0,
            "Docker daemon",
            docker_detail or None,
        )

        missing_required_services = True

        compose_result = subprocess.run(
            compose_base + ["config", "--services"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )

        if compose_result.returncode != 0:
            report(
                False,
                "Docker Compose configuration",
                (
                    compose_result.stderr.strip()
                    or compose_result.stdout.strip()
                ),
            )

        else:
            report(True, "Docker Compose configuration")

            services = {
                line.strip()
                for line in compose_result.stdout.splitlines()
                if line.strip()
            }

            required_services = set(parsers) | {"pymupdf"}

            missing_required_services = False
            for service in sorted(required_services):
                present = service in services
                if not present:
                    missing_required_services = True
                report(present, f"Compose service: {service}")

        parser_preflight_ready = (
            docker_path is not None
            and docker_info.returncode == 0
            and compose_result.returncode == 0
            and not missing_required_services
        )

    # --------------------------------------------------
    # Parser / profile
    # --------------------------------------------------

    print()
    print("PREFLIGHT - parser/profile")
    print("-" * 72)

    if not parser_preflight_ready:
        print(
            "  [SKIP] parser/profile checks "
            "because infrastructure checks failed"
        )
        print()
        parts = [f"{failures} failure(s)"]
        if warnings_count:
            parts.append(f"{warnings_count} warning(s)")
        print(
            "Preflight result: FAIL "
            f"({', '.join(parts)})"
        )
        return False

    seen: set[tuple[str, str]] = set()
    ordered_pairs: list[tuple[str, str]] = []
    for pair in jobs_spec:
        if pair not in seen:
            seen.add(pair)
            ordered_pairs.append(pair)

    for parser_name, profile_name in ordered_pairs:
        print()
        print(f"{parser_name}/{profile_name}")

        result = run_parser_preflight(
            compose_base,
            parser_name,
            profile_name,
            runtime=runtime,
        )

        for check in result.get("checks", []):
            status = check.get("status", "fail")
            label = _PREFLIGHT_STATUS_LABEL.get(
                status,
                status.upper()[:4],
            )
            detail = check.get("detail")
            print(f"  [{label}] {check['name']}")
            if detail:
                for line in str(detail).splitlines():
                    print(f"         {line}")
            if status == "fail":
                failures += 1
            elif status == "warn":
                warnings_count += 1

    print()

    if failures == 0:
        suffix = (
            f" ({warnings_count} warning(s))"
            if warnings_count
            else ""
        )
        print(f"Preflight result: PASS{suffix}")
    else:
        parts = [f"{failures} failure(s)"]
        if warnings_count:
            parts.append(f"{warnings_count} warning(s)")
        print(
            "Preflight result: FAIL "
            f"({', '.join(parts)})"
        )

    return failures == 0


def _resolve_batch_output_root(
    requested_output_root: str | None,
    benchmark_output_directory: str,
    runtime: str,
) -> Path:
    if requested_output_root:
        base_root = (
            ROOT
            / requested_output_root
        ).resolve()
    else:
        base_root = (
            ROOT
            / benchmark_output_directory
        ).resolve()

    if runtime == RUNTIME_HOST:
        return base_root / "host"

    if runtime == RUNTIME_DOCKER:
        return base_root

    raise ValueError(
        f"Invalid runtime: {runtime!r}"
    )

# ── Orchestrator ──────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    config = load_config()
    benchmark = config["benchmark"]

    if getattr(args, "compose_override", None) and args.runtime == RUNTIME_HOST:
        raise SystemExit(
            "Error: --compose-override has no effect with --runtime host. "
            "Remove --compose-override or switch to --runtime docker."
        )

    jobs_spec = resolve_jobs_spec(args, config)
    runtime = args.runtime

    # Guard: reject host-only parsers when running docker (and vice-versa).
    # Must run before any Docker compose or host dispatch.
    validate_runtime_support(jobs_spec, runtime)

    try:
        artifact_policy = ArtifactPolicy.from_cli([args.artifacts])
    except ArtifactSelectionError as exc:
        raise SystemExit(f"Invalid --artifacts value: {exc}")

    input_dir = Path(args.input_dir) if args.input_dir else ROOT / benchmark["input_directory"]

    output_root = _resolve_batch_output_root(
        requested_output_root=args.output_root,
        benchmark_output_directory=(
            benchmark["output_directory"]
        ),
        runtime=runtime,
    )

    # resume-check is read-only: it never calls docker, so no container path needed.
    # host runtime also doesn't use container paths.
    container_output_root = (
        "" if (args.resume_check or runtime == RUNTIME_HOST)
        else to_container_output_root(output_root)
    )

    # ── 1. Discover PDFs ──────────────────────────────────────────────────────
    all_docs = discover_pdfs(input_dir)
    docs = apply_document_limit(all_docs, args.limit)

    # ── 2. Validate batch ─────────────────────────────────────────────────────
    validate_batch(jobs_spec, config)

    # ── 3. Build run plan ─────────────────────────────────────────────────────
    plan, doc_sha256 = build_run_plan(docs, jobs_spec, output_root, resume=args.resume,
                                      artifact_policy=artifact_policy)

    total = len(plan)
    pending = sum(1 for r in plan if r.status == "pending")
    skipped = total - pending

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK - BATCH RUN")
    print("=" * 72)
    effective_suite = args.suite if args.suite else (None if args.parser else "default")
    if effective_suite:
        print(f"Suite:      {effective_suite}  ({len(jobs_spec)} parser/profile pairs)")
    else:
        print(f"Parser:     {args.parser}  /  {args.profile}")
    print(f"Input dir:  {input_dir}")
    if container_output_root:
        print(f"Output:     {output_root}  ->  {container_output_root}")
    else:
        print(f"Output:     {output_root}")
    print(f"Documents:  {len(docs)}")
    if args.limit is not None and len(docs) < len(all_docs):
        print(f"Limit:      {args.limit}  (from {len(all_docs)} discovered PDFs)")
    print(f"Total jobs: {total}  (pending={pending}, already-done={skipped})")
    print(f"Runtime:    {runtime}")
    print(f"On error:   {'continue' if args.continue_on_error else 'abort'}")
    if args.compose_override:
        print(f"Overlay:    {args.compose_override}")
    print("=" * 72)

    compose_base = build_compose_base(args.compose_override)

    if args.dry_run:
        print("\nDRY RUN - run plan:\n")
        for n, rec in enumerate(plan, 1):
            tag = "SKIP" if rec.status == "skip" else "    "
            print(
                f"  {n:3d}/{total}"
                f"  [{tag:4}]"
                f"  {rec.parser:<10}"
                f"  {rec.profile:<30}"
                f"  {rec.doc.name}"
            )
        print()
        return

    if args.resume_check:
        print("\nRESUME CHECK - job reusability:\n")
        for rec in plan:
            tag = "SKIP   " if rec.status == "skip" else "PENDING"
            print(
                f"  [{tag}]  {rec.parser:<10}  {rec.profile:<30}  {rec.doc.name}"
            )
        n_skip = sum(1 for r in plan if r.status == "skip")
        n_pending = sum(1 for r in plan if r.status == "pending")
        print()
        if n_pending == 0:
            print(f"Resume check: PASS - all {n_skip} job(s) reusable")
            return
        print(f"Resume check: FAIL - {n_pending} job(s) pending (not reusable)")
        sys.exit(1)

    if args.preflight:
        ok = run_preflight(
            jobs_spec,
            docs,
            input_dir,
            output_root,
            compose_base,
            args.compose_override,
            runtime,
        )
        sys.exit(0 if ok else 1)

    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"batch_{ts}.log"
    results_path = LOGS_DIR / f"batch_{ts}_results.jsonl"
    manifest_path = LOGS_DIR / f"batch_{ts}_manifest.json"
    manifest = {
        "batch_start": ts,
        "execution_runtime": runtime,
        "host_os": platform.platform(),
        "orchestrator_python": sys.version.split()[0],
        "git_commit": _get_git_sha(),
        "git_dirty": _is_git_dirty(),
        "config_sha256": _sha256(CONFIG_PATH),
        "suite": args.suite if args.suite else None,
        "jobs": [{"parser": p, "profile": pr} for p, pr in jobs_spec],
        "documents": [
            {"name": doc.name, "sha256": doc_sha256[doc]}
            for doc in docs
        ],
        "document_count": len(docs),
        "total_jobs": len(jobs_spec) * len(docs),
        "input_dir": str(input_dir),
        "output_root": str(output_root),
        "artifacts": args.artifacts,
        "flags": {
            "resume": args.resume,
            "force": not args.resume,
            "continue_on_error": args.continue_on_error,
            "no_summary": args.no_summary,
            "limit": args.limit,
            "job_timeout_seconds": args.job_timeout_seconds,
            "verbose_output": args.verbose_output,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Master log: {log_path.relative_to(ROOT)}")
    print(f"Results:    {results_path.relative_to(ROOT)}")
    print(f"Manifest:   {manifest_path.relative_to(ROOT)}\n")

    with log_path.open("w", encoding="utf-8") as lf:

        def log(msg: str) -> None:
            print(msg)
            lf.write(msg + "\n")
            lf.flush()

        log(f"batch_start={ts}  total={total}  input={input_dir}  output={output_root}")

        # ── 4. Build source inventories ───────────────────────────────────────
        log("\n[SOURCE INVENTORIES]")
        build_source_inventories(
            docs, doc_sha256, input_dir, output_root, compose_base, args.resume, log,
            runtime=runtime,
        )

        # ── 5. Execute ────────────────────────────────────────────────────────
        batch_start = time.monotonic()
        execute_plan(
            plan, compose_base, container_output_root,
            args.artifacts, args.continue_on_error, results_path, log,
            output_root=output_root,
            artifact_policy=artifact_policy,
            runtime=runtime,
            job_timeout_seconds=args.job_timeout_seconds,
            verbose_output=args.verbose_output,
        )
        elapsed = time.monotonic() - batch_start

        # ── 6. Batch summary ──────────────────────────────────────────────────
        counts = batch_summary(plan, elapsed, log)

    if counts["fail"]:
        print(f"\nWARNING: {counts['fail']} job(s) failed. See {log_path.name} for details.")

    if not args.no_summary and counts["done"] > 0:
        run_summary_scripts(jobs_spec, output_root)

    print("\nBatch complete.")
    if counts["fail"] or counts["aborted"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
