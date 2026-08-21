from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CAMPAIGN_CONFIG_PATH = ROOT / "config" / "runtime_campaign.json"
BENCHMARK_CONFIG_PATH = ROOT / "config" / "benchmark_profiles.json"
LOGS_DIR = ROOT / "logs"
RUN_BATCH = ROOT / "scripts" / "run_batch.py"

VALID_STATUSES = {"PASS", "EXPECTED_BLOCK", "ENVIRONMENT_BLOCK", "IMPLEMENTATION_FAIL", "NOT_RUN", "FAIL"}


def load_campaign() -> dict:
    return json.loads(CAMPAIGN_CONFIG_PATH.read_text(encoding="utf-8"))


def load_benchmark_config() -> dict:
    return json.loads(BENCHMARK_CONFIG_PATH.read_text(encoding="utf-8"))


def build_run_batch_cmd(phase: dict, step: str) -> list[str]:
    """Build the run_batch.py command for a given phase step (preflight/execute/resume)."""
    cmd = [
        sys.executable,
        str(RUN_BATCH),
        "--suite", phase["suite"],
        "--output-root", phase["output_root"],
        "--no-summary",
    ]

    if phase.get("limit") is not None:
        cmd += ["--limit", str(phase["limit"])]

    if step == "preflight":
        cmd.append("--preflight")
    elif step == "execute":
        cmd.append("--force")
    elif step == "resume":
        cmd.append("--resume-check")

    return cmd


def print_plan(phases: list[dict]) -> None:
    print()
    print("RUNTIME VALIDATION CAMPAIGN — PLAN")
    print("=" * 72)
    for i, phase in enumerate(phases, 1):
        limit_str = f"limit={phase['limit']}" if phase.get("limit") is not None else "full"
        print(f"  {i:2d}. {phase['name']:<30}  suite={phase['suite']:<15}  {limit_str}")
        print(f"       output: {phase['output_root']}")
    print()
    print(f"Total phases: {len(phases)}")
    print()


def run_phase(phase: dict, input_dir: str | None) -> dict:
    name = phase["name"]
    started_at = datetime.now().isoformat()
    t0 = time.monotonic()

    base_args: list[str] = []
    if input_dir:
        base_args = ["--input-dir", input_dir]

    def _run(step: str) -> int:
        cmd = build_run_batch_cmd(phase, step) + base_args
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode

    print(f"\n{'=' * 72}")
    print(f"PHASE: {name}")
    print(f"{'=' * 72}")

    print(f"\n[1/3] preflight")
    preflight_exit = _run("preflight")

    if preflight_exit != 0:
        elapsed = time.monotonic() - t0
        print(f"\nPHASE {name}: preflight FAILED (exit={preflight_exit}) — stopping phase")
        return {
            "phase": name,
            "suite": phase["suite"],
            "limit": phase.get("limit"),
            "preflight_exit_code": preflight_exit,
            "execution_exit_code": None,
            "resume_exit_code": None,
            "status": "FAIL",
            "output_root": phase["output_root"],
            "started_at": started_at,
            "elapsed_seconds": round(elapsed, 2),
        }

    print(f"\n[2/3] execution")
    execution_exit = _run("execute")

    if execution_exit != 0:
        elapsed = time.monotonic() - t0
        print(f"\nPHASE {name}: execution FAILED (exit={execution_exit}) — stopping phase")
        return {
            "phase": name,
            "suite": phase["suite"],
            "limit": phase.get("limit"),
            "preflight_exit_code": preflight_exit,
            "execution_exit_code": execution_exit,
            "resume_exit_code": None,
            "status": "FAIL",
            "output_root": phase["output_root"],
            "started_at": started_at,
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }

    print(f"\n[3/3] resume check")
    resume_exit = _run("resume")

    elapsed = time.monotonic() - t0
    status = "PASS" if resume_exit == 0 else "FAIL"
    print(f"\nPHASE {name}: {status}  elapsed={elapsed:.0f}s")

    return {
        "phase": name,
        "suite": phase["suite"],
        "limit": phase.get("limit"),
        "preflight_exit_code": preflight_exit,
        "execution_exit_code": execution_exit,
        "resume_exit_code": resume_exit,
        "status": status,
        "output_root": phase["output_root"],
        "started_at": started_at,
        "elapsed_seconds": round(elapsed, 2),
    }


def write_report(results: list[dict], ts: str) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    json_path = LOGS_DIR / f"runtime_campaign_{ts}.json"
    md_path = LOGS_DIR / f"runtime_campaign_{ts}.md"

    json_path.write_text(
        json.dumps({"schema_version": 1, "results": results}, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Runtime Validation Campaign Report",
        f"Generated: {ts}",
        "",
        "| Phase | Suite | Limit | Preflight | Execution | Resume | Status | Elapsed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        limit = str(r["limit"]) if r["limit"] is not None else "full"
        pf = r["preflight_exit_code"]
        ex = r["execution_exit_code"]
        re = r["resume_exit_code"]
        lines.append(
            f"| {r['phase']} | {r['suite']} | {limit} "
            f"| {pf} | {ex} | {re} | {r['status']} | {r['elapsed_seconds']}s |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written:")
    print(f"  JSON: {json_path.relative_to(ROOT)}")
    print(f"  MD:   {md_path.relative_to(ROOT)}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Runtime validation campaign runner. Safe by default: prints plan only."
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--plan",
        action="store_true",
        help="Print the campaign plan and exit without executing (default behavior).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Execute the campaign phases (starts Docker containers).",
    )
    p.add_argument(
        "--phase",
        metavar="NAME",
        help="Select only the named phase for planning or execution.",
    )
    p.add_argument(
        "--input-dir",
        metavar="DIR",
        help="Override the input directory for run_batch.py.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    campaign = load_campaign()
    benchmark_config = load_benchmark_config()

    phases = campaign["phases"]

    if args.phase:
        names = [p["name"] for p in phases]
        if args.phase not in names:
            available = ", ".join(names)
            raise SystemExit(f"Unknown phase '{args.phase}'. Available: {available}")
        phases = [p for p in phases if p["name"] == args.phase]

    if not args.execute:
        print_plan(phases)
        return

    known_suites = set(benchmark_config.get("suites", {}).keys())
    for phase in phases:
        if phase["suite"] not in known_suites:
            raise SystemExit(
                f"Phase '{phase['name']}' references unknown suite '{phase['suite']}'"
            )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results: list[dict] = []

    for phase in phases:
        result = run_phase(phase, args.input_dir)
        results.append(result)
        if result["status"] == "FAIL":
            print(f"\nCampaign stopped: phase '{phase['name']}' failed.")
            for remaining in phases[len(results):]:
                results.append({
                    "phase": remaining["name"],
                    "suite": remaining["suite"],
                    "limit": remaining.get("limit"),
                    "preflight_exit_code": None,
                    "execution_exit_code": None,
                    "resume_exit_code": None,
                    "status": "NOT_RUN",
                    "output_root": remaining["output_root"],
                    "started_at": None,
                    "elapsed_seconds": 0,
                })
            break

    write_report(results, ts)

    failed = [r for r in results if r["status"] == "FAIL"]
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
