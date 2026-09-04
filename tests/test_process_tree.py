from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.benchmark import process_tree
from src.benchmark.process_tree import run_process_tree


def _alive_non_zombie(pid: int) -> bool:
    status = Path(f"/proc/{pid}/status")
    if status.is_file():
        text = status.read_text(encoding="utf-8", errors="replace")
        if "State:\tZ" in text:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@unittest.skipIf(sys.platform == "win32", "POSIX process-group fallback test")
class ProcessTreeTests(unittest.TestCase):
    def test_timeout_terminates_parent_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            child_pid_path = Path(temporary) / "child.pid"
            source = (
                "import pathlib,subprocess,sys,time;"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));"
                "time.sleep(60)"
            )
            result = run_process_tree(
                [sys.executable, "-c", source, str(child_pid_path)], timeout=0.5
            )
            self.assertTrue(result.timed_out)
            self.assertGreater(result.duration_seconds, 0)
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and _alive_non_zombie(child_pid):
                time.sleep(0.02)
            self.assertFalse(_alive_non_zombie(result.pid))
            self.assertFalse(_alive_non_zombie(child_pid))

    def test_normal_execution_returns_positive_duration(self) -> None:
        result = run_process_tree([sys.executable, "-c", "pass"])
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        self.assertGreater(result.duration_seconds, 0)


class WindowsProcessTreeContractTests(unittest.TestCase):
    def test_windows_uses_new_process_group_and_job_object(self) -> None:
        fake_process = MagicMock()
        fake_process.pid = 123
        fake_process.returncode = 0
        fake_process.communicate.return_value = ("out", "err")
        fake_job = object()
        with (
            patch.object(process_tree.sys, "platform", "win32"),
            patch.object(process_tree.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
            patch.object(process_tree, "_windows_job_object", return_value=fake_job),
            patch.object(process_tree, "_assign_windows_job", return_value=True) as assign,
            patch.object(process_tree, "close_windows_job") as close,
            patch.object(process_tree.subprocess, "Popen", return_value=fake_process) as popen,
        ):
            result = process_tree.run_process_tree(["python.exe", "worker.py"], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertGreater(result.duration_seconds, 0)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 512)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)
        assign.assert_called_once_with(fake_job, fake_process)
        close.assert_called_once_with(fake_job)

    def test_failed_job_assignment_discards_empty_job(self) -> None:
        fake_process = MagicMock(pid=321, returncode=0)
        fake_process.communicate.return_value = (None, None)
        fake_job = object()
        with (
            patch.object(process_tree.sys, "platform", "win32"),
            patch.object(process_tree.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
            patch.object(process_tree, "_windows_job_object", return_value=fake_job),
            patch.object(process_tree, "_assign_windows_job", return_value=False),
            patch.object(process_tree, "close_windows_job") as close,
            patch.object(process_tree.subprocess, "Popen", return_value=fake_process),
        ):
            process_tree.run_process_tree(["python.exe", "worker.py"])
        close.assert_any_call(fake_job)
        close.assert_called_with(None)


if __name__ == "__main__":
    unittest.main()
