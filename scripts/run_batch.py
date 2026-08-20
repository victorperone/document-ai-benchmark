from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "benchmark_profiles.json"
LOGS_DIR = ROOT / "logs"

# (parser, profile) pairs present in config but not yet supported by v2 adapters.
_KNOWN_UNSUPPORTED: set[tuple[str, str]] = {
    ("docling", "ocr_auto_visual"),         # picture_description rejected by v2
    ("paddleocr", "ocr_structured_visual"), # does not satisfy v2 contract
}


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
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the full job plan without executing.",
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

    unsupported = [(p, pr) for p, pr in jobs_spec if (p, pr) in _KNOWN_UNSUPPORTED]
    if unsupported:
        print("WARNING: the following jobs are not yet supported by the v2 adapters:")
        for parser_name, profile_name in unsupported:
            print(f"  - {parser_name}/{profile_name}")
        print("  They will likely fail with the current v2 adapters. Use individual validated parser/profile pairs instead.\n")


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

    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"batch_{ts}.log"
    results_path = LOGS_DIR / f"batch_{ts}_results.jsonl"
    print(f"Master log: {log_path.relative_to(ROOT)}")
    print(f"Results:    {results_path.relative_to(ROOT)}\n")

    compose_base: list[str] = ["docker", "compose"]
    if args.compose_override:
        compose_base += ["-f", "compose.yaml", "-f", args.compose_override]

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
