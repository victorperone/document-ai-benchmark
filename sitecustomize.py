"""
Offline network guard — activated only when DOCUMENT_AI_ENFORCE_OFFLINE=1.

Inject via PYTHONPATH so Python loads this before any user code:
    $env:PYTHONPATH = "$RepoRoot;" + $env:PYTHONPATH

Behaviour when active:
- Loopback addresses (127.x, ::1, localhost) are allowed.
- All other outbound socket.connect() calls are blocked and logged.
- Each attempt is written as a JSON line to DOCUMENT_AI_OFFLINE_LOG
  (defaults to logs/offline_guard.jsonl relative to this file's parent).
- Any logged attempt causes the readiness gate to fail — the gate reads
  the log file and checks for non-empty content.

Network isolation at the OS/firewall level is a separate prerequisite
(documented in RUNTIME_VALIDATION_RUNBOOK.md). This guard catches
Python-level calls only; native-extension sockets may bypass it.
"""
from __future__ import annotations

import json
import os
import socket
import time
import traceback
from pathlib import Path

_GUARD_ACTIVE = os.environ.get("DOCUMENT_AI_ENFORCE_OFFLINE", "0") == "1"

if _GUARD_ACTIVE:
    _LOG_PATH: Path = Path(
        os.environ.get(
            "DOCUMENT_AI_OFFLINE_LOG",
            str(Path(__file__).resolve().parent / "logs" / "offline_guard.jsonl"),
        )
    )

    _LOOPBACK_PREFIXES = ("127.", "::1", "0:0:0:0:0:0:0:1")

    def _is_loopback(host: str) -> bool:
        """Return True if ``host`` resolves to a loopback address.

        Accepts ``localhost``, ``::1``, and any address whose string
        representation starts with a prefix in ``_LOOPBACK_PREFIXES``
        (``127.``, ``::1``, ``0:0:0:0:0:0:0:1``).

        Args:
            host: Hostname or IP address string as passed to
                ``socket.socket.connect``.

        Returns:
            ``True`` if the host is loopback; ``False`` otherwise.
        """
        h = host.strip().lower().rstrip(".")
        if h in ("localhost", "::1"):
            return True
        return any(h.startswith(p) for p in _LOOPBACK_PREFIXES)

    def _log_attempt(host: str, port: int | None, stack: str) -> None:
        """Append a blocked connection attempt to the offline guard log.

        Creates the log directory if it does not exist. Silently ignores
        ``OSError`` so that a write failure never prevents the guard from
        blocking the connection.

        Args:
            host: Target hostname or IP of the blocked connection.
            port: Target port number, or ``None`` if not available.
            stack: Formatted traceback string at the point of the call.
        """
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "host": host,
            "port": port,
            "stack": stack,
        }
        try:
            with _LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    _original_connect = socket.socket.connect

    def _guarded_connect(self: socket.socket, address: object) -> None:  # type: ignore[override]
        """Replacement for ``socket.socket.connect`` that blocks non-loopback connections.

        Extracts the host and port from ``address``, checks whether the host
        is a loopback address, and raises ``OSError`` if it is not. Every
        blocked attempt is logged via ``_log_attempt`` before raising.

        Args:
            self: The ``socket.socket`` instance (passed implicitly as the
                monkey-patched method receiver).
            address: The connection target. For TCP/UDP sockets this is a
                ``(host, port)`` tuple; for Unix-domain sockets a path string.

        Raises:
            OSError: Always raised for non-loopback destinations, with a
                message that names the blocked host/port and advises how to
                disable the guard.
        """
        host: str = ""
        port: int | None = None
        if isinstance(address, (tuple, list)) and len(address) >= 2:
            host = str(address[0])
            port = int(address[1])
        elif isinstance(address, str):
            host = address

        if not host or not _is_loopback(host):
            stack = "".join(traceback.format_stack()[:-1])
            _log_attempt(host, port, stack)
            raise OSError(
                f"[offline-guard] Outbound connection blocked: {host}:{port}. "
                "Set DOCUMENT_AI_ENFORCE_OFFLINE=0 to disable."
            )
        return _original_connect(self, address)

    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]