from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProcessResult:
    """Result of a process whose complete descendant tree is supervised."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    pid: int


def _windows_job_object() -> object | None:
    """Create a kill-on-close Job Object, or return None as a safe fallback."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            kernel32.CloseHandle(handle)
            return None
        return (kernel32, handle)
    except Exception:
        return None


def _assign_windows_job(job: object | None, process: subprocess.Popen[str]) -> bool:
    if job is None:
        return False
    try:
        kernel32, handle = job  # type: ignore[misc]
        return bool(kernel32.AssignProcessToJobObject(handle, int(process._handle)))
    except Exception:
        return False


def terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    windows_job: object | None = None,
    grace_seconds: float = 5.0,
) -> None:
    """Terminate *process* and its descendants, then wait for the parent."""
    if process.poll() is not None:
        return

    if sys.platform == "win32":
        terminated = False
        if windows_job is not None:
            try:
                kernel32, handle = windows_job  # type: ignore[misc]
                terminated = bool(kernel32.TerminateJobObject(handle, 1))
            except Exception:
                terminated = False
        if not terminated:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(grace_seconds, 1.0),
                    check=False,
                )
            except Exception:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    if sys.platform == "win32":
        try:
            process.kill()
        except ProcessLookupError:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass
    process.wait()


def close_windows_job(windows_job: object | None) -> None:
    if windows_job is None:
        return
    try:
        kernel32, handle = windows_job  # type: ignore[misc]
        kernel32.CloseHandle(handle)
    except Exception:
        pass


def run_process_tree(
    args: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    capture_output: bool = False,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> ProcessResult:
    """Run a command while owning and reliably timing out its whole tree."""
    command = tuple(os.fspath(value) for value in args)
    popen_kwargs: dict[str, object] = {
        "cwd": os.fspath(cwd) if cwd is not None else None,
        "env": dict(env) if env is not None else None,
        "text": True,
        "encoding": encoding,
        "errors": errors,
    }
    if capture_output:
        popen_kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    windows_job = _windows_job_object()
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)  # type: ignore[arg-type]
    if windows_job is not None and not _assign_windows_job(windows_job, process):
        # Never retain an empty Job Object: TerminateJobObject could report
        # success while leaving the unassigned process tree alive.
        close_windows_job(windows_job)
        windows_job = None
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        try:
            out, err = process.communicate(timeout=timeout)
            stdout = out or ""
            stderr = err or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            partial_stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            partial_stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            terminate_process_tree(process, windows_job=windows_job)
            out, err = process.communicate()
            stdout = out if isinstance(out, str) else partial_stdout
            stderr = err if isinstance(err, str) else partial_stderr
    finally:
        close_windows_job(windows_job)

    return ProcessResult(
        args=command,
        returncode=process.returncode if process.returncode is not None else 1,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        pid=process.pid,
    )
