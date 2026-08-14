from __future__ import annotations

import os
import statistics
import threading
from dataclasses import dataclass
from time import perf_counter

import psutil


MONITOR_VERSION = "process_tree_v2"
DEFAULT_INTERVAL_SECONDS = 0.1

MB = 1024 * 1024


def bytes_to_mb(value: int | float) -> float:
    return value / MB


@dataclass
class _ProcessState:
    process: psutil.Process
    baseline_cpu_seconds: float
    last_cpu_seconds: float
    baseline_read_bytes: int
    last_read_bytes: int
    baseline_write_bytes: int
    last_write_bytes: int
    primed: bool = False


class ResourceMonitor:
    """
    Monitor the current process and all descendant processes.

    Important:
    psutil.Process.cpu_percent(interval=None) is stateful. The same
    Process objects are therefore cached between samples.
    """

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self.interval = interval

        self.root_process = psutil.Process(
            os.getpid()
        )

        self.logical_cpus = (
            psutil.cpu_count(logical=True) or 1
        )

        self.processes: dict[
            tuple[int, float],
            _ProcessState,
        ] = {}

        self.cpu_samples: list[float] = []
        self.rss_samples: list[int] = []

        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

        self.started = False
        self.start_time: float | None = None
        self.stop_time: float | None = None

        self.seen_process_keys: set[
            tuple[int, float]
        ] = set()

    @staticmethod
    def _cpu_seconds(
        process: psutil.Process,
    ) -> float:
        times = process.cpu_times()

        return float(
            times.user + times.system
        )

    @staticmethod
    def _io_bytes(
        process: psutil.Process,
    ) -> tuple[int, int]:
        try:
            counters = process.io_counters()

            return (
                int(counters.read_bytes),
                int(counters.write_bytes),
            )

        except (
            AttributeError,
            NotImplementedError,
            psutil.AccessDenied,
            psutil.NoSuchProcess,
        ):
            return 0, 0

    @staticmethod
    def _process_key(
        process: psutil.Process,
    ) -> tuple[int, float]:
        return (
            process.pid,
            process.create_time(),
        )

    def _register_process(
        self,
        process: psutil.Process,
        *,
        existed_at_start: bool,
    ) -> None:
        try:
            key = self._process_key(
                process
            )

            if key in self.processes:
                return

            cpu_seconds = self._cpu_seconds(
                process
            )

            read_bytes, write_bytes = (
                self._io_bytes(process)
            )

            # If a process already existed when monitoring
            # started, only activity after monitor start counts.
            #
            # A process discovered later is a child created
            # during the monitored operation, so its whole
            # lifetime belongs to this benchmark.
            if existed_at_start:
                baseline_cpu = cpu_seconds
                baseline_read = read_bytes
                baseline_write = write_bytes
            else:
                baseline_cpu = 0.0
                baseline_read = 0
                baseline_write = 0

            self.processes[key] = _ProcessState(
                process=process,
                baseline_cpu_seconds=baseline_cpu,
                last_cpu_seconds=cpu_seconds,
                baseline_read_bytes=baseline_read,
                last_read_bytes=read_bytes,
                baseline_write_bytes=baseline_write,
                last_write_bytes=write_bytes,
            )

            self.seen_process_keys.add(key)

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            return

    def _discover_processes(
        self,
        *,
        initial: bool = False,
    ) -> None:
        discovered = [
            self.root_process
        ]

        try:
            discovered.extend(
                self.root_process.children(
                    recursive=True
                )
            )
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            pass

        for process in discovered:
            try:
                key = self._process_key(
                    process
                )
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                continue

            if key not in self.processes:
                self._register_process(
                    process,
                    existed_at_start=initial,
                )

    def _sample(self) -> None:
        self._discover_processes(
            initial=False
        )

        cpu_percent = 0.0
        rss_bytes = 0

        for key, state in list(
            self.processes.items()
        ):
            process = state.process

            try:
                state.last_cpu_seconds = (
                    self._cpu_seconds(
                        process
                    )
                )

                (
                    state.last_read_bytes,
                    state.last_write_bytes,
                ) = self._io_bytes(
                    process
                )

                rss_bytes += (
                    process.memory_info().rss
                )

                if not state.primed:
                    process.cpu_percent(
                        interval=None
                    )

                    state.primed = True

                    continue

                cpu_percent += (
                    process.cpu_percent(
                        interval=None
                    )
                )

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                # Keep the final state already collected.
                continue

        self.cpu_samples.append(
            cpu_percent
        )

        self.rss_samples.append(
            rss_bytes
        )

    def _run(self) -> None:
        while not self.stop_event.wait(
            self.interval
        ):
            self._sample()

    def start(self) -> None:
        if self.started:
            raise RuntimeError(
                "ResourceMonitor already started."
            )

        self.started = True
        self.start_time = perf_counter()

        self._discover_processes(
            initial=True
        )

        # Prime CPU counters for processes that already
        # exist before the monitored operation begins.
        for state in self.processes.values():
            try:
                state.process.cpu_percent(
                    interval=None
                )

                state.primed = True

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                pass

        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

        self.thread.start()

    def stop(self) -> dict[str, object]:
        if not self.started:
            raise RuntimeError(
                "ResourceMonitor was not started."
            )

        self.stop_event.set()

        if self.thread is not None:
            self.thread.join()

        self._sample()

        self.stop_time = perf_counter()

        average_cpu = (
            statistics.mean(
                self.cpu_samples
            )
            if self.cpu_samples
            else 0.0
        )

        peak_cpu = max(
            self.cpu_samples,
            default=0.0,
        )

        average_rss = (
            statistics.mean(
                self.rss_samples
            )
            if self.rss_samples
            else 0.0
        )

        peak_rss = max(
            self.rss_samples,
            default=0,
        )

        process_cpu_seconds = 0.0
        disk_read_bytes = 0
        disk_write_bytes = 0

        for state in self.processes.values():
            process_cpu_seconds += max(
                state.last_cpu_seconds
                - state.baseline_cpu_seconds,
                0.0,
            )

            disk_read_bytes += max(
                state.last_read_bytes
                - state.baseline_read_bytes,
                0,
            )

            disk_write_bytes += max(
                state.last_write_bytes
                - state.baseline_write_bytes,
                0,
            )

        wall_time_seconds = (
            self.stop_time - self.start_time
            if (
                self.start_time is not None
                and self.stop_time is not None
            )
            else 0.0
        )

        return {
            "monitor_version": MONITOR_VERSION,

            "sampling_interval_seconds": (
                self.interval
            ),

            "logical_cpus": (
                self.logical_cpus
            ),

            "processes_observed": len(
                self.seen_process_keys
            ),

            "wall_time_seconds": round(
                wall_time_seconds,
                3,
            ),

            "process_cpu_time_seconds": round(
                process_cpu_seconds,
                3,
            ),

            "average_cpu_percent": round(
                average_cpu,
                2,
            ),

            "peak_cpu_percent": round(
                peak_cpu,
                2,
            ),

            "average_cpu_system_capacity_percent": round(
                min(
                    average_cpu
                    / self.logical_cpus,
                    100.0,
                ),
                2,
            ),

            "peak_cpu_system_capacity_percent": round(
                min(
                    peak_cpu
                    / self.logical_cpus,
                    100.0,
                ),
                2,
            ),

            "average_rss_mb": round(
                bytes_to_mb(
                    average_rss
                ),
                3,
            ),

            "peak_rss_mb": round(
                bytes_to_mb(
                    peak_rss
                ),
                3,
            ),

            "disk_read_mb": round(
                bytes_to_mb(
                    disk_read_bytes
                ),
                3,
            ),

            "disk_write_mb": round(
                bytes_to_mb(
                    disk_write_bytes
                ),
                3,
            ),
        }
