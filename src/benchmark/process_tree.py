"""Cross-platform subprocess runner with full process-tree supervision.

``run_process_tree`` launches a command and guarantees that the entire
descendant process tree is terminated if a timeout occurs—using Windows Job
Objects on Windows and POSIX process groups on Linux/macOS.  An optional
*tee_log* file receives stdout/stderr in real time while the output is
simultaneously captured and returned.
"""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Mapping, Sequence


_NTSTATUS_NAMES: dict[int, str] = {
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC0000034: "STATUS_OBJECT_NAME_NOT_FOUND",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION",
    0xC0000096: "STATUS_PRIVILEGED_INSTRUCTION",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
    0xC0000135: "STATUS_DLL_NOT_FOUND",
    0xC0000138: "STATUS_ORDINAL_NOT_FOUND",
    0xC0000139: "STATUS_ENTRYPOINT_NOT_FOUND",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
    0xC0000374: "STATUS_HEAP_CORRUPTION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN",
}


def _decode_ntstatus(returncode: int) -> tuple[str, str] | None:
    """Return (hex_string, name) for Windows NTSTATUS error codes, else None."""
    if sys.platform != "win32":
        return None
    unsigned = returncode & 0xFFFFFFFF
    if unsigned < 0x80000000:
        return None
    hex_str = f"0x{unsigned:08X}"
    name = _NTSTATUS_NAMES.get(unsigned, "STATUS_UNKNOWN")
    return hex_str, name


@dataclass(frozen=True)
class ProcessResult:
    """Result of a process whose complete descendant tree is supervised."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    pid: int
    duration_seconds: float
    exit_code_hex: str | None = None
    windows_status: str | None = None


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
    """Assign *process* to the Windows Job Object in *job*.

    Args:
        job: Opaque ``(kernel32, handle)`` pair from ``_windows_job_object``,
            or ``None``.
        process: The freshly launched subprocess.

    Returns:
        ``True`` when assignment succeeded, ``False`` otherwise.
    """
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
    """Release the Windows Job Object handle if one was created.

    Args:
        windows_job: Opaque ``(kernel32, handle)`` pair from
            ``_windows_job_object``, or ``None``.
    """
    if windows_job is None:
        return
    try:
        kernel32, handle = windows_job  # type: ignore[misc]
        kernel32.CloseHandle(handle)
    except Exception:
        pass


def _tee_reader(pipe: IO[str], buf: io.StringIO, log_file: IO[str]) -> None:
    """Read *pipe* line by line, write each line to both *buf* and *log_file*."""
    try:
        for line in pipe:
            buf.write(line)
            log_file.write(line)
            try:
                log_file.flush()
            except Exception:
                pass
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
    tee_log: IO[str] | None = None,
) -> ProcessResult:
    """Run a command while owning and reliably timing out its whole tree.

    When *tee_log* is provided the subprocess stdout and stderr are streamed
    line-by-line to *tee_log* in real time (incremental persistence) while
    also being captured and returned in :attr:`ProcessResult.stdout` /
    :attr:`ProcessResult.stderr`.  *capture_output* is implied when *tee_log*
    is set.
    """
    command = tuple(os.fspath(value) for value in args)

    use_pipe = capture_output or (tee_log is not None)

    popen_kwargs: dict[str, object] = {
        "cwd": os.fspath(cwd) if cwd is not None else None,
        "env": dict(env) if env is not None else None,
        "text": True,
        "encoding": encoding,
        "errors": errors,
    }
    if use_pipe:
        popen_kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    windows_job = _windows_job_object()
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    start_time = time.monotonic()
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
        if tee_log is not None and process.stdout is not None and process.stderr is not None:
            # Streaming tee: two reader threads drain stdout/stderr concurrently,
            # writing each line to the log file as it arrives.
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            t_out = threading.Thread(
                target=_tee_reader,
                args=(process.stdout, out_buf, tee_log),
                daemon=True,
            )
            t_err = threading.Thread(
                target=_tee_reader,
                args=(process.stderr, err_buf, tee_log),
                daemon=True,
            )
            t_out.start()
            t_err.start()
            try:
                if timeout is not None:
                    deadline = start_time + timeout
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    process.wait(timeout=remaining)
                else:
                    process.wait()
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_process_tree(process, windows_job=windows_job)
                process.wait()
            finally:
                t_out.join(timeout=10)
                t_err.join(timeout=10)
            stdout = out_buf.getvalue()
            stderr = err_buf.getvalue()
        else:
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

    duration_seconds = time.monotonic() - start_time
    final_returncode = process.returncode if process.returncode is not None else 1
    ntstatus = _decode_ntstatus(final_returncode)
    return ProcessResult(
        args=command,
        returncode=final_returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        pid=process.pid,
        duration_seconds=duration_seconds,
        exit_code_hex=ntstatus[0] if ntstatus else None,
        windows_status=ntstatus[1] if ntstatus else None,
    )
