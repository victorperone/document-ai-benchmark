"""Client for the visual enrichment worker process.

Launches visual_worker.py as a child process, waits for it to signal
readiness, then sends VisualRequest objects via stdin and reads
VisualResponse objects from stdout.

The worker is registered with ResourceMonitor so its RSS is tracked
alongside the parent parser process.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from src.enrichment.visual_contract import VisualRequest, VisualResponse

_WORKER_SCRIPT = Path(__file__).parent / "visual_worker.py"
_READY_TIMEOUT = 120.0   # seconds; model loading can be slow on first run


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
    ) -> None:
        self._language = language
        self._smolvlm_model_path = smolvlm_model_path
        self._resource_monitor = resource_monitor
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

        exe = python_executable or sys.executable
        self._proc = subprocess.Popen(
            [exe, str(_WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        if resource_monitor is not None:
            try:
                resource_monitor.register_child(self._proc.pid)
            except Exception:
                pass

        # Send config as first line
        config = {
            "language": language,
            "smolvlm_model_path": smolvlm_model_path,
        }
        self._send_line(json.dumps(config))

        # Wait for "ready" signal
        self._wait_for_ready()

    def _send_line(self, line: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise VisualWorkerError("worker process not running")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def _read_line(self) -> str:
        if self._proc is None or self._proc.stdout is None:
            raise VisualWorkerError("worker process not running")
        line = self._proc.stdout.readline()
        if not line:
            stderr_tail = ""
            if self._proc.stderr:
                try:
                    stderr_tail = self._proc.stderr.read(2000)
                except Exception:
                    pass
            raise VisualWorkerError(
                f"worker stdout closed unexpectedly. stderr: {stderr_tail!r}"
            )
        return line.strip()

    def _wait_for_ready(self) -> None:
        import time
        deadline = time.monotonic() + _READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                raw = self._read_line()
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
                    f"worker init failed: {msg.get('error', raw)}"
                )
        raise VisualWorkerError("timed out waiting for worker to become ready")

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

            raw = self._read_line()
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
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None

    def __enter__(self) -> "VisualWorkerClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()
