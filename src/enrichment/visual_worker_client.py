"""Client for the visual enrichment worker process.

Launches visual_worker.py as a child process, waits for it to signal
readiness, then sends VisualRequest objects via stdin and reads
VisualResponse objects from stdout.

The worker is registered with ResourceMonitor so its RSS is tracked
alongside the parent parser process.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

from src.benchmark.process_tree import (
    _assign_windows_job,
    _windows_job_object,
    close_windows_job,
    terminate_process_tree,
)
from src.enrichment.visual_contract import VisualRequest, VisualResponse

_WORKER_SCRIPT = Path(__file__).parent / "visual_worker.py"
_READY_TIMEOUT = 300.0
_REQUEST_TIMEOUT = 180.0
_SHUTDOWN_TIMEOUT = 10.0


class VisualWorkerError(RuntimeError):
    pass


class VisualWorkerClient:
    """Single-use client: create, use, then call shutdown()."""

    def __init__(
        self,
        *,
        language: str,
        smolvlm_model_path: str,
        python_executable: str | None = None,
        resource_monitor: Any | None = None,
        det_model_dir: str | None = None,
        rec_model_dir: str | None = None,
    ) -> None:
        self._language = language
        self._smolvlm_model_path = smolvlm_model_path
        self._resource_monitor = resource_monitor
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=100)
        self._windows_job: object | None = _windows_job_object()

        exe = python_executable or sys.executable
        popen_options: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
        self._proc = subprocess.Popen(
            [exe, str(_WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_options,
        )
        if self._windows_job is not None and not _assign_windows_job(
            self._windows_job, self._proc
        ):
            close_windows_job(self._windows_job)
            self._windows_job = None

        self._stdout_thread = threading.Thread(
            target=self._drain_stdout, name="visual-worker-stdout", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name="visual-worker-stderr", daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        if resource_monitor is not None:
            try:
                resource_monitor.register_child(self._proc.pid)
            except Exception:
                pass

        # Send config as first line
        config: dict[str, Any] = {
            "language": language,
            "smolvlm_model_path": smolvlm_model_path,
        }
        if det_model_dir:
            config["det_model_dir"] = det_model_dir
        if rec_model_dir:
            config["rec_model_dir"] = rec_model_dir
        try:
            self._send_line(json.dumps(config))
            self._wait_for_ready()
        except Exception:
            self.shutdown()
            raise

    def _drain_stdout(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                self._stdout_queue.put(line.rstrip("\r\n"))
        finally:
            self._stdout_queue.put(None)

    def _drain_stderr(self) -> None:
        assert self._proc is not None
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            self._stderr_tail.append(line.rstrip("\r\n"))

    def _error_tail(self) -> str:
        return "\n".join(self._stderr_tail)

    def _send_line(self, line: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise VisualWorkerError("worker process not running")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def _read_line(self, timeout: float, operation: str) -> str:
        if self._proc is None:
            raise VisualWorkerError("worker process not running")
        try:
            line = self._stdout_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise VisualWorkerError(
                f"worker timed out during {operation} after {timeout:.0f}s. "
                f"stderr tail: {self._error_tail()!r}"
            ) from exc
        if line is None:
            raise VisualWorkerError(
                f"worker stdout closed during {operation} "
                f"(exit={self._proc.poll()}). stderr tail: {self._error_tail()!r}"
            )
        return line.strip()

    def _wait_for_ready(self) -> None:
        import time
        deadline = time.monotonic() + _READY_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VisualWorkerError(
                    f"timed out waiting for worker to become ready. "
                    f"stderr tail: {self._error_tail()!r}"
                )
            try:
                raw = self._read_line(remaining, "startup")
            except VisualWorkerError as exc:
                raise VisualWorkerError(f"worker failed during init: {exc}") from exc
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            status = msg.get("status", "")
            if status == "ready":
                return
            if status == "init_error":
                raise VisualWorkerError(
                    f"worker init failed: {msg.get('error', raw)}. "
                    f"stderr tail: {self._error_tail()!r}"
                )

    def process(self, request: VisualRequest) -> VisualResponse:
        with self._lock:
            payload = {
                "request_id": request.request_id,
                "operation": request.operation,
                "image_base64": request.image_base64,
                "language": request.language,
                "prompt": request.prompt,
                "page_number": request.page_number,
                "region_id": request.region_id,
            }
            self._send_line(json.dumps(payload))
            # Clear image bytes from memory after sending
            request = VisualRequest(
                request_id=request.request_id,
                operation=request.operation,
                image_base64="",
                language=request.language,
                prompt=request.prompt,
                page_number=request.page_number,
                region_id=request.region_id,
            )

            raw = self._read_line(_REQUEST_TIMEOUT, f"request {payload['request_id']}")
            try:
                resp_dict = json.loads(raw)
            except json.JSONDecodeError as exc:
                return VisualResponse(
                    request_id=payload["request_id"],
                    status="error",
                    ocr_text="",
                    description="",
                    ocr_engine="paddleocr",
                    ocr_model="",
                    description_engine="smolvlm",
                    description_model=self._smolvlm_model_path,
                    error_detail=f"malformed response: {exc}",
                )

            return VisualResponse(
                request_id=resp_dict.get("request_id", payload["request_id"]),
                status=resp_dict.get("status", "error"),
                ocr_text=resp_dict.get("ocr_text", ""),
                description=resp_dict.get("description", ""),
                ocr_engine=resp_dict.get("ocr_engine", "paddleocr"),
                ocr_model=resp_dict.get("ocr_model", ""),
                description_engine=resp_dict.get("description_engine", "smolvlm"),
                description_model=resp_dict.get("description_model", self._smolvlm_model_path),
                error_detail=resp_dict.get("error_detail", ""),
            )

    def shutdown(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            terminate_process_tree(
                self._proc,
                windows_job=self._windows_job,
                grace_seconds=_SHUTDOWN_TIMEOUT,
            )
        finally:
            close_windows_job(self._windows_job)
            self._windows_job = None
            self._proc = None

    def __enter__(self) -> "VisualWorkerClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()
