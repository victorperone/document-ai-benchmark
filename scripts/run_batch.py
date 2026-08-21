from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import os
import shutil
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

    @property
    def label(self) -> str:
        return f"{self.parser}/{self.doc.stem}/{self.profile}"


# ── CLI ───────────────────────────────────────────────────────────────────────

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

    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--suite",
        metavar="SUITE",
        help="Named suite from benchmark_profiles.json (runs multiple parser+profile pairs).",
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
            "Output root, must be inside ROOT/outputs/. "
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

    args = p.parse_args()

    if args.parser and not args.profile:
        p.error("--profile is required when --parser is used.")
    if args.profile and not args.parser:
        p.error("--parser is required when --profile is used.")

    return args


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_jobs_spec(args: argparse.Namespace, config: dict) -> list[tuple[str, str]]:
    if args.suite:
        suites = config["suites"]
        if args.suite not in suites:
            available = ", ".join(sorted(suites))
            raise SystemExit(f"Unknown suite '{args.suite}'. Available: {available}")
        return [tuple(job) for job in suites[args.suite]]
    return [(args.parser, args.profile)]


# ── Phase 1: Discover PDFs ────────────────────────────────────────────────────

def discover_pdfs(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {input_dir}")
    docs = sorted(p for p in input_dir.glob("*.pdf") if p.is_file())
    if not docs:
        raise SystemExit(f"No PDF files found in {input_dir}")
    return docs


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
) -> None:
    inventory_dir = output_root / "_source_inventory"
    container_input_dir = _to_container_input_dir(input_dir)
    container_inventory_dir = to_container_output_root(output_root) + "/_source_inventory"

    for doc in docs:
        inv_file = inventory_dir / f"{doc.stem}.json"
        if resume and _json_sha_matches(inv_file, doc_sha256[doc]):
            log(f"  [SKIP ] source inventory: {doc.name}")
            continue

        log(f"  [BUILD] source inventory: {doc.name}")
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
) -> tuple[list[JobRecord], dict[Path, str]]:
    plan: list[JobRecord] = []
    sha_cache: dict[Path, str] = {}
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
            if resume and _metrics_match(
                output_root, parser_name, doc.stem, profile_name, sha_cache[doc]
            ):
                rec.status = "skip"
            plan.append(rec)
    return plan, sha_cache


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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

        log(f"  [START]  {rec.parser}/{rec.profile}")
        t0 = time.monotonic()
        rec.exit_code = _run_subprocess(
            compose_base, rec.parser, rec.doc, rec.profile, container_output_root, artifacts
        )
        rec.elapsed = time.monotonic() - t0

        if rec.exit_code == 0:
            rec.status = "done"
            log(f"  [DONE ]  {rec.parser}/{rec.profile}  ({rec.elapsed:.0f}s)")
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


def _run_subprocess(
    compose_base: list[str],
    parser_name: str,
    doc_path: Path,
    profile_name: str,
    container_output_root: str,
    artifacts: str,
) -> int:
    cmd = compose_base + [
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

def run_summary_scripts() -> None:
    for script in (
        "scripts/build_parser_comparison.py",
        "scripts/build_native_parser_comparison.py",
    ):
        script_path = ROOT / script
        if not script_path.is_file():
            print(f"[SUMMARY] not found, skipping: {script}")
            continue
        print(f"\n[SUMMARY] {script}")
        subprocess.run([sys.executable, str(script_path)], cwd=str(ROOT))


def run_parser_preflight(
    compose_base: list[str],
    parser_name: str,
    profile_name: str,
) -> dict:
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
        "PREFLIGHT — infrastructure"
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

    # --------------------------------------------------
    # Compose override
    # --------------------------------------------------

    if compose_override:
        override_path = Path(
            compose_override
        )

        if not override_path.is_absolute():
            override_path = (
                ROOT
                / override_path
            )

        report(
            override_path.is_file(),
            "compose override",
            str(override_path),
        )

    # --------------------------------------------------
    # Docker CLI
    # --------------------------------------------------

    docker_path = shutil.which(
        "docker"
    )

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

    # --------------------------------------------------
    # Docker daemon
    # --------------------------------------------------

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

    # --------------------------------------------------
    # Docker Compose configuration
    # --------------------------------------------------

    missing_required_services = True

    compose_result = subprocess.run(
        compose_base
        + [
            "config",
            "--services",
        ],
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
        report(
            True,
            "Docker Compose configuration",
        )

        services = {
            line.strip()
            for line
            in compose_result.stdout.splitlines()
            if line.strip()
        }

        required_services = (
            set(parsers)
            | {
                "pymupdf",
            }
        )

        missing_required_services = False
        for service in sorted(
            required_services
        ):
            present = service in services
            if not present:
                missing_required_services = True
            report(
                present,
                f"Compose service: {service}",
            )

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
    print("PREFLIGHT — parser/profile")
    print("-" * 72)

    if not parser_preflight_ready:
        print(
            "  [SKIP] parser/profile checks "
            "because Docker/Compose infrastructure failed"
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


# ── Orchestrator ──────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    config = load_config()
    benchmark = config["benchmark"]

    jobs_spec = resolve_jobs_spec(args, config)
    input_dir = Path(args.input_dir) if args.input_dir else ROOT / benchmark["input_directory"]
    output_root = (
        (ROOT / args.output_root).resolve()
        if args.output_root
        else (ROOT / benchmark["output_directory"]).resolve()
    )
    container_output_root = to_container_output_root(output_root)

    # ── 1. Discover PDFs ──────────────────────────────────────────────────────
    docs = discover_pdfs(input_dir)

    # ── 2. Validate batch ─────────────────────────────────────────────────────
    validate_batch(jobs_spec, config)

    # ── 3. Build run plan ─────────────────────────────────────────────────────
    plan, doc_sha256 = build_run_plan(docs, jobs_spec, output_root, resume=args.resume)

    total = len(plan)
    pending = sum(1 for r in plan if r.status == "pending")
    skipped = total - pending

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK — BATCH RUN")
    print("=" * 72)
    if args.suite:
        print(f"Suite:      {args.suite}  ({len(jobs_spec)} parser/profile pairs)")
    else:
        print(f"Parser:     {args.parser}  /  {args.profile}")
    print(f"Input dir:  {input_dir}")
    print(f"Output:     {output_root}  →  {container_output_root}")
    print(f"Documents:  {len(docs)}")
    print(f"Total jobs: {total}  (pending={pending}, already-done={skipped})")
    print(f"On error:   {'continue' if args.continue_on_error else 'abort'}")
    if args.compose_override:
        print(f"Overlay:    {args.compose_override}")
    print("=" * 72)

    compose_base = build_compose_base(args.compose_override)

    if args.dry_run:
        print("\nDRY RUN — run plan:\n")
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

    if args.preflight:
        ok = run_preflight(
            jobs_spec,
            docs,
            input_dir,
            output_root,
            compose_base,
            args.compose_override,
        )
        sys.exit(0 if ok else 1)

    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"batch_{ts}.log"
    results_path = LOGS_DIR / f"batch_{ts}_results.jsonl"
    print(f"Master log: {log_path.relative_to(ROOT)}")
    print(f"Results:    {results_path.relative_to(ROOT)}\n")

    with log_path.open("w", encoding="utf-8") as lf:

        def log(msg: str) -> None:
            print(msg)
            lf.write(msg + "\n")
            lf.flush()

        log(f"batch_start={ts}  total={total}  input={input_dir}  output={output_root}")

        # ── 4. Build source inventories ───────────────────────────────────────
        log("\n[SOURCE INVENTORIES]")
        build_source_inventories(docs, doc_sha256, input_dir, output_root, compose_base, args.resume, log)

        # ── 5. Execute ────────────────────────────────────────────────────────
        batch_start = time.monotonic()
        execute_plan(
            plan, compose_base, container_output_root,
            args.artifacts, args.continue_on_error, results_path, log,
        )
        elapsed = time.monotonic() - batch_start

        # ── 6. Batch summary ──────────────────────────────────────────────────
        counts = batch_summary(plan, elapsed, log)

    if counts["fail"]:
        print(f"\nWARNING: {counts['fail']} job(s) failed. See {log_path.name} for details.")

    if not args.no_summary and counts["done"] > 0:
        run_summary_scripts()

    print("\nBatch complete.")


if __name__ == "__main__":
    main()
