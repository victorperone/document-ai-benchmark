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
_SHUTDOWN_TIMEOUT = 10.0


class VisualWorkerError(RuntimeError):
    """Raised when the visual enrichment worker process fails or times out."""


class VisualWorkerClient:
    """Single-use client that manages a visual enrichment worker subprocess.

    Spawns ``visual_worker.py`` as a child process, waits for it to signal
    readiness (``{"status": "ready"}``), then serialises ``VisualRequest``
    objects over stdin and deserialises ``VisualResponse`` objects from
    stdout. Stdout/stderr are drained by background daemon threads to
    prevent pipe-buffer deadlocks.

    On Windows the child is assigned to a Job Object so it is terminated
    if the parent exits unexpectedly. On POSIX a new session is created for
    the same reason.

    Usage::

        with VisualWorkerClient(language="pt", smolvlm_model_path="/models/smolvlm") as client:
            response = client.process(request)
    """

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
        """Launch the worker process and block until it is ready.

        Args:
            language: OCR language code forwarded to the worker (e.g. ``"pt"``).
            smolvlm_model_path: Local directory path to the SmolVLM model.
            python_executable: Python interpreter to use for the child process.
                Defaults to ``sys.executable``.
            resource_monitor: Optional monitor object that exposes a
                ``register_child(pid)`` method; used to track the worker's
                RSS alongside the parent parser.
            det_model_dir: Optional PaddleOCR text-detection model directory.
            rec_model_dir: Optional PaddleOCR text-recognition model directory.

        Raises:
            VisualWorkerError: If the worker process fails to start or reports
                an ``init_error`` during model loading.
        """
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
        """Read all lines from the worker's stdout into ``_stdout_queue``.

        Runs in a daemon thread. Puts ``None`` as a sentinel when the pipe
        is exhausted so callers can detect that the worker has exited.
        """
        assert self._proc is not None
        assert self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                self._stdout_queue.put(line.rstrip("\r\n"))
        finally:
            self._stdout_queue.put(None)

    def _drain_stderr(self) -> None:
        """Read all lines from the worker's stderr into ``_stderr_tail``.

        Runs in a daemon thread. The deque is bounded to 100 lines so
        error messages remain available for diagnostics without growing
        unboundedly.
        """
        assert self._proc is not None
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            self._stderr_tail.append(line.rstrip("\r\n"))

    def _error_tail(self) -> str:
        """Return the last captured stderr lines as a single string."""
        return "\n".join(self._stderr_tail)

    def _send_line(self, line: str) -> None:
        """Write a single line to the worker's stdin and flush.

        Args:
            line: A single JSON string without a trailing newline.

        Raises:
            VisualWorkerError: If the worker process or its stdin pipe is
                no longer available.
        """
        if self._proc is None or self._proc.stdin is None:
            raise VisualWorkerError("worker process not running")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def _read_line(
        self,
        timeout: float | None,
        operation: str,
    ) -> str:
        """Read one response line from the worker's stdout queue.

        Args:
            timeout: Seconds to wait before raising ``VisualWorkerError``.
                Pass ``None`` to block indefinitely (used during startup and
                request processing where the worker is expected to reply
                eventually).
            operation: Human-readable label for the current operation,
                included in error messages.

        Returns:
            The stripped response line.

        Raises:
            VisualWorkerError: If the queue times out, the worker process is
                gone, or the stdout pipe has been closed.
        """
        if self._proc is None:
            raise VisualWorkerError("worker process not running")
        try:
            line = self._stdout_queue.get(timeout=timeout)
        except queue.Empty as exc:
            if timeout is None:
                raise VisualWorkerError(
                    f"worker stopped responding during {operation}. "
                    f"stderr tail: {self._error_tail()!r}"
                ) from exc

            raise VisualWorkerError(
                f"worker timed out during {operation} "
                f"after {timeout:.0f}s. "
                f"stderr tail: {self._error_tail()!r}"
            ) from exc
        if line is None:
            raise VisualWorkerError(
                f"worker stdout closed during {operation} "
                f"(exit={self._proc.poll()}). stderr tail: {self._error_tail()!r}"
            )
        return line.strip()

    def _wait_for_ready(self) -> None:
        """Block until the worker signals ``{"status": "ready"}``.

        Intermediate status lines such as ``"loading_ocr"`` and
        ``"loading_vlm"`` are silently consumed. Non-JSON lines are
        skipped. Raises on ``"init_error"`` or if the worker exits
        prematurely.

        Raises:
            VisualWorkerError: If the worker reports an initialisation
                failure or the stdout pipe closes before ``"ready"`` is
                received.
        """
        while True:
            try:
                raw = self._read_line(
                    None,
                    "startup",
                )
            except VisualWorkerError as exc:
                raise VisualWorkerError(
                    f"worker failed during init: {exc}"
                ) from exc

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            status = msg.get("status", "")

            if status == "ready":
                return

            if status == "init_error":
                raise VisualWorkerError(
                    f"worker init failed: "
                    f"{msg.get('error', raw)}. "
                    f"stderr tail: {self._error_tail()!r}"
                )

    def process(self, request: VisualRequest) -> VisualResponse:
        """Send a visual enrichment request and return the response.

        Serialises the request to JSON, writes it to the worker's stdin,
        then reads and deserialises the response from stdout. The
        ``image_base64`` field is cleared from the local ``VisualRequest``
        copy immediately after the payload is written to minimise the
        time sensitive image data stays in memory.

        This method is thread-safe: concurrent callers are serialised by
        an internal lock because the worker processes one request at a time.

        Args:
            request: The enrichment request to send.

        Returns:
            A ``VisualResponse`` populated from the worker's JSON reply.
            On JSON parse failure the response carries ``status="error"``
            and a description of the malformed payload.

        Raises:
            VisualWorkerError: If the worker process has stopped responding
                or its stdout pipe has closed.
        """
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

            raw = self._read_line(
                None,
                f"request {payload['request_id']}",
            )
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
        """Terminate the worker process and release all resources.

        Closes the worker's stdin pipe to signal EOF, waits up to
        ``_SHUTDOWN_TIMEOUT`` seconds for a clean exit, and forcefully
        terminates the process tree if the timeout expires. The Windows
        Job Object (if any) is always closed before returning.

        Safe to call multiple times; subsequent calls are no-ops.
        """
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
        """Return self to support use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Call ``shutdown()`` when exiting the context manager."""
        self.shutdown()
