"""
Runtime campaign contract tests.

Covers: manifest schema, phase naming, output roots, suite references,
limit values, phase order, plan-mode safety, and execute-mode subprocess
behavior (preflight → execution → resume chain).

No Docker. No real inference. All subprocess calls are mocked.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CAMPAIGN_CONFIG_PATH = ROOT / "config" / "runtime_campaign.json"
BENCHMARK_CONFIG_PATH = ROOT / "config" / "benchmark_profiles.json"
RUNNER_PATH = ROOT / "scripts" / "run_runtime_campaign.py"


def _load_campaign() -> dict:
    return json.loads(CAMPAIGN_CONFIG_PATH.read_text(encoding="utf-8"))


def _load_benchmark_config() -> dict:
    return json.loads(BENCHMARK_CONFIG_PATH.read_text(encoding="utf-8"))


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_runtime_campaign", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER_PATH), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


class TestCampaignManifestSchema(unittest.TestCase):

    def test_schema_version_is_1(self):
        self.assertEqual(_load_campaign()["schema_version"], 1)

    def test_phases_key_exists(self):
        self.assertIn("phases", _load_campaign())

    def test_phases_is_list(self):
        self.assertIsInstance(_load_campaign()["phases"], list)

    def test_phases_not_empty(self):
        self.assertGreater(len(_load_campaign()["phases"]), 0)

    def test_each_phase_has_required_fields(self):
        for phase in _load_campaign()["phases"]:
            for field in ("name", "suite", "output_root"):
                self.assertIn(field, phase, f"phase {phase.get('name')!r} missing field {field!r}")

    def test_limit_when_present_is_positive(self):
        for phase in _load_campaign()["phases"]:
            limit = phase.get("limit")
            if limit is not None:
                self.assertGreater(limit, 0, f"phase {phase['name']!r} has non-positive limit")


class TestPhaseNames(unittest.TestCase):

    def test_phase_names_unique(self):
        names = [p["name"] for p in _load_campaign()["phases"]]
        self.assertEqual(len(names), len(set(names)), "Duplicate phase names found")

    def test_exactly_ten_phases(self):
        self.assertEqual(len(_load_campaign()["phases"]), 10)

    def test_expected_phase_names_present(self):
        expected = [
            "smoke_limit1", "smoke_full",
            "default_limit1", "default_full",
            "full_corpus_limit1", "full_corpus_full",
            "diagnostic_ocr_limit1", "diagnostic_ocr_full",
            "visual_ablation_limit1", "visual_ablation_full",
        ]
        names = [p["name"] for p in _load_campaign()["phases"]]
        self.assertEqual(names, expected)


class TestOutputRoots(unittest.TestCase):

    def test_output_roots_unique(self):
        roots = [p["output_root"] for p in _load_campaign()["phases"]]
        self.assertEqual(len(roots), len(set(roots)), "Duplicate output roots found")

    def test_output_roots_under_runtime_prefix(self):
        for phase in _load_campaign()["phases"]:
            self.assertTrue(
                phase["output_root"].startswith("outputs/_runtime/"),
                f"phase {phase['name']!r} output_root not under outputs/_runtime/",
            )


class TestSuiteReferences(unittest.TestCase):

    def test_all_suites_exist_in_benchmark_config(self):
        known_suites = set(_load_benchmark_config()["suites"].keys())
        for phase in _load_campaign()["phases"]:
            self.assertIn(
                phase["suite"],
                known_suites,
                f"phase {phase['name']!r} references unknown suite {phase['suite']!r}",
            )


class TestLimitConventions(unittest.TestCase):

    def test_limit1_phases_have_limit_1(self):
        for phase in _load_campaign()["phases"]:
            if phase["name"].endswith("_limit1"):
                self.assertEqual(
                    phase.get("limit"),
                    1,
                    f"phase {phase['name']!r} should have limit=1",
                )

    def test_full_phases_have_no_limit(self):
        for phase in _load_campaign()["phases"]:
            if phase["name"].endswith("_full"):
                self.assertIsNone(
                    phase.get("limit"),
                    f"phase {phase['name']!r} should have limit=null",
                )


class TestPlanMode(unittest.TestCase):

    def test_no_args_exits_zero(self):
        result = _run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_flag_exits_zero(self):
        result = _run_cli("--plan")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_mode_prints_all_phases(self):
        result = _run_cli("--plan")
        for phase in _load_campaign()["phases"]:
            self.assertIn(phase["name"], result.stdout + result.stderr)

    def test_plan_mode_does_not_call_subprocess(self):
        runner = _load_runner()
        with patch.object(runner.subprocess, "run") as mock_run:
            runner.print_plan(runner.load_campaign()["phases"])
        mock_run.assert_not_called()

    def test_plan_mode_shows_phase_count(self):
        result = _run_cli("--plan")
        combined = result.stdout + result.stderr
        self.assertIn("10", combined)


class TestExecuteMode(unittest.TestCase):

    def _make_completed(self, returncode: int) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=returncode)

    def test_execute_calls_run_batch_for_preflight(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        calls_made: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls_made.append(list(cmd))
            return self._make_completed(0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            with patch.object(runner, "write_report"):
                runner.run_phase(phase, None)

        preflight_call = calls_made[0]
        self.assertIn("--preflight", preflight_call)
        self.assertIn("--suite", preflight_call)
        self.assertIn("smoke", preflight_call)

    def test_execute_preflight_before_execution(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        step_order: list[str] = []

        def fake_run(cmd, **kwargs):
            flat = " ".join(str(c) for c in cmd)
            if "--preflight" in flat:
                step_order.append("preflight")
            else:
                step_order.append("execute_or_resume")
            return self._make_completed(0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            runner.run_phase(phase, None)

        self.assertEqual(step_order[0], "preflight")

    def test_execution_only_if_preflight_passes(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return self._make_completed(1)  # preflight fails

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.run_phase(phase, None)

        self.assertEqual(call_count, 1, "Should stop after failed preflight")
        self.assertEqual(result["preflight_exit_code"], 1)
        self.assertIsNone(result["execution_exit_code"])

    def test_resume_only_if_execution_passes(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._make_completed(0)  # preflight passes
            return self._make_completed(1)  # execution fails

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.run_phase(phase, None)

        self.assertEqual(call_count, 2)
        self.assertEqual(result["execution_exit_code"], 1)
        self.assertIsNone(result["resume_exit_code"])

    def test_all_three_steps_called_on_success(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return self._make_completed(0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.run_phase(phase, None)

        self.assertEqual(call_count, 3)
        self.assertEqual(result["status"], "PASS")

    def test_failure_stops_campaign(self):
        runner = _load_runner()

        call_order: list[str] = []
        phases = [
            {"name": "smoke_limit1", "suite": "smoke", "limit": 1, "output_root": "outputs/_runtime/smoke_limit1"},
            {"name": "smoke_full", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/smoke_full"},
        ]

        def fake_run_phase(phase, input_dir):
            call_order.append(phase["name"])
            if phase["name"] == "smoke_limit1":
                return {
                    "phase": phase["name"], "suite": phase["suite"], "limit": phase.get("limit"),
                    "preflight_exit_code": 1, "execution_exit_code": None, "resume_exit_code": None,
                    "status": "FAIL", "output_root": phase["output_root"],
                    "started_at": "2026-01-01T00:00:00", "elapsed_seconds": 1.0,
                }
            return {
                "phase": phase["name"], "suite": phase["suite"], "limit": phase.get("limit"),
                "preflight_exit_code": 0, "execution_exit_code": 0, "resume_exit_code": 0,
                "status": "PASS", "output_root": phase["output_root"],
                "started_at": "2026-01-01T00:00:00", "elapsed_seconds": 1.0,
            }

        with patch.object(runner, "run_phase", side_effect=fake_run_phase):
            with patch.object(runner, "write_report"):
                with patch.object(runner, "load_campaign", return_value={"phases": phases}):
                    with patch.object(runner, "load_benchmark_config",
                                      return_value={"suites": {"smoke": []}}):
                        args = type("Args", (), {
                            "execute": True, "plan": False, "phase": None, "input_dir": None
                        })()
                        try:
                            with patch("sys.argv", ["run_runtime_campaign.py", "--execute"]):
                                runner.main()
                        except SystemExit:
                            pass

        self.assertEqual(call_order, ["smoke_limit1"])


class TestCommandConstruction(unittest.TestCase):

    def test_limit1_phase_includes_limit_flag(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        cmd = runner.build_run_batch_cmd(phase, "preflight")
        self.assertIn("--limit", cmd)
        limit_idx = cmd.index("--limit")
        self.assertEqual(cmd[limit_idx + 1], "1")

    def test_full_phase_excludes_limit_flag(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_full",
            "suite": "smoke",
            "limit": None,
            "output_root": "outputs/_runtime/smoke_full",
        }
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertNotIn("--limit", cmd)

    def test_command_includes_no_summary(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertIn("--no-summary", cmd)

    def test_command_includes_correct_output_root(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertIn("--output-root", cmd)
        idx = cmd.index("--output-root")
        self.assertEqual(cmd[idx + 1], "outputs/_runtime/smoke_limit1")

    def test_preflight_step_includes_preflight_flag(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "preflight")
        self.assertIn("--preflight", cmd)

    def test_execute_step_does_not_include_preflight_flag(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertNotIn("--preflight", cmd)

    def test_execute_step_includes_force_flag(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertIn("--force", cmd)

    def test_execute_step_does_not_include_resume_check(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertNotIn("--resume-check", cmd)

    def test_resume_step_includes_resume_check_flag(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "resume")
        self.assertIn("--resume-check", cmd)

    def test_resume_step_does_not_include_force(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "resume")
        self.assertNotIn("--force", cmd)

    def test_resume_step_does_not_include_preflight(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "resume")
        self.assertNotIn("--preflight", cmd)

    def test_preflight_step_does_not_include_force(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "preflight")
        self.assertNotIn("--force", cmd)

    def test_preflight_step_does_not_include_resume_check(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "preflight")
        self.assertNotIn("--resume-check", cmd)

    def test_command_calls_run_batch_not_other_scripts(self):
        runner = _load_runner()
        phase = {"name": "x", "suite": "smoke", "limit": None, "output_root": "outputs/_runtime/x"}
        cmd = runner.build_run_batch_cmd(phase, "execute")
        self.assertTrue(any("run_batch.py" in str(c) for c in cmd))


class TestResumeCheckChain(unittest.TestCase):
    """Verify the preflight → execute (--force) → resume-check chain semantics."""

    def _make_completed(self, returncode: int) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=returncode)

    def _steps_from_calls(self, calls_made: list[list[str]]) -> list[str]:
        steps = []
        for cmd in calls_made:
            flat = " ".join(str(c) for c in cmd)
            if "--preflight" in flat:
                steps.append("preflight")
            elif "--force" in flat:
                steps.append("execute")
            elif "--resume-check" in flat:
                steps.append("resume")
            else:
                steps.append("unknown")
        return steps

    def test_success_chain_is_preflight_execute_resume(self):
        """All steps pass → PASS with exactly 3 calls in correct order."""
        runner = _load_runner()
        phase = {"name": "smoke_limit1", "suite": "smoke", "limit": 1,
                 "output_root": "outputs/_runtime/smoke_limit1"}
        calls_made = []

        def fake_run(cmd, **kwargs):
            calls_made.append(list(cmd))
            return self._make_completed(0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.run_phase(phase, None)

        self.assertEqual(len(calls_made), 3)
        steps = self._steps_from_calls(calls_made)
        self.assertEqual(steps, ["preflight", "execute", "resume"])
        self.assertEqual(result["status"], "PASS")

    def test_resume_check_fail_means_phase_fail(self):
        """preflight=0, execute=0, resume-check=1 → FAIL."""
        runner = _load_runner()
        phase = {"name": "smoke_limit1", "suite": "smoke", "limit": 1,
                 "output_root": "outputs/_runtime/smoke_limit1"}
        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return self._make_completed(0)
            return self._make_completed(1)  # resume-check fails

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.run_phase(phase, None)

        self.assertEqual(call_count[0], 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["resume_exit_code"], 1)

    def test_resume_step_is_read_only_not_a_fourth_call(self):
        """After preflight+execute succeed and resume-check fails, no 4th call is made."""
        runner = _load_runner()
        phase = {"name": "smoke_limit1", "suite": "smoke", "limit": 1,
                 "output_root": "outputs/_runtime/smoke_limit1"}
        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return self._make_completed(0)
            return self._make_completed(1)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            runner.run_phase(phase, None)

        self.assertEqual(call_count[0], 3, "Exactly 3 calls — no 4th attempt after resume-check failure")

    def test_execute_uses_force_flag(self):
        """The execute step command must contain --force."""
        runner = _load_runner()
        phase = {"name": "smoke_limit1", "suite": "smoke", "limit": 1,
                 "output_root": "outputs/_runtime/smoke_limit1"}
        execute_cmds: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            flat = " ".join(str(c) for c in cmd)
            if "--force" in flat:
                execute_cmds.append(list(cmd))
            return self._make_completed(0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            runner.run_phase(phase, None)

        self.assertEqual(len(execute_cmds), 1, "Exactly one --force call (the execute step)")

    def test_resume_uses_resume_check_flag(self):
        """The resume step command must contain --resume-check."""
        runner = _load_runner()
        phase = {"name": "smoke_limit1", "suite": "smoke", "limit": 1,
                 "output_root": "outputs/_runtime/smoke_limit1"}
        resume_cmds: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            flat = " ".join(str(c) for c in cmd)
            if "--resume-check" in flat:
                resume_cmds.append(list(cmd))
            return self._make_completed(0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            runner.run_phase(phase, None)

        self.assertEqual(len(resume_cmds), 1, "Exactly one --resume-check call (the resume step)")


class TestPhaseResultSchema(unittest.TestCase):

    def test_pass_result_has_required_fields(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        with patch.object(runner.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0)):
            result = runner.run_phase(phase, None)

        for field in ("phase", "suite", "limit", "preflight_exit_code",
                      "execution_exit_code", "resume_exit_code", "status",
                      "output_root", "started_at", "elapsed_seconds"):
            self.assertIn(field, result, f"result missing field {field!r}")

    def test_fail_result_status_is_fail(self):
        runner = _load_runner()
        phase = {
            "name": "smoke_limit1",
            "suite": "smoke",
            "limit": 1,
            "output_root": "outputs/_runtime/smoke_limit1",
        }
        with patch.object(runner.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 1)):
            result = runner.run_phase(phase, None)

        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
