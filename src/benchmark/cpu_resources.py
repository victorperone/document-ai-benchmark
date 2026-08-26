from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


def _quota_to_cpu_count(
    quota: int,
    period: int,
) -> int | None:
    if quota <= 0 or period <= 0:
        return None

    return max(
        1,
        math.ceil(quota / period),
    )


def _cgroup_cpu_limit() -> tuple[int, str] | None:
    """
    Detect Linux cgroup CPU quotas.

    Supports:
    - cgroup v2: /sys/fs/cgroup/cpu.max
    - cgroup v1: cpu.cfs_quota_us / cpu.cfs_period_us
    """

    # cgroup v2
    cpu_max = Path("/sys/fs/cgroup/cpu.max")

    try:
        if cpu_max.is_file():
            raw = cpu_max.read_text(
                encoding="utf-8"
            ).strip()

            parts = raw.split()

            if (
                len(parts) >= 2
                and parts[0] != "max"
            ):
                quota = int(parts[0])
                period = int(parts[1])

                count = _quota_to_cpu_count(
                    quota,
                    period,
                )

                if count is not None:
                    return count, "cgroup_v2"
    except (
        OSError,
        ValueError,
    ):
        pass

    # cgroup v1
    quota_path = Path(
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"
    )
    period_path = Path(
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us"
    )

    try:
        if (
            quota_path.is_file()
            and period_path.is_file()
        ):
            quota = int(
                quota_path.read_text(
                    encoding="utf-8"
                ).strip()
            )
            period = int(
                period_path.read_text(
                    encoding="utf-8"
                ).strip()
            )

            count = _quota_to_cpu_count(
                quota,
                period,
            )

            if count is not None:
                return count, "cgroup_v1"
    except (
        OSError,
        ValueError,
    ):
        pass

    return None


def available_logical_cpus(
    configured_fallback: int = 2,
) -> tuple[int, str]:
    """
    Return the CPU concurrency available to the process.

    All detectable limits are considered and the smallest
    positive value wins. This prevents oversubscription when
    affinity or a container CPU quota is more restrictive than
    the host CPU count.

    The configured fallback is used only when CPU detection
    is unavailable. It is not a minimum or maximum.
    """

    configured_fallback = int(
        configured_fallback
    )

    if configured_fallback <= 0:
        raise ValueError(
            "configured_fallback must be greater than zero"
        )

    candidates: list[
        tuple[int, str]
    ] = []

    process_cpu_count = getattr(
        os,
        "process_cpu_count",
        None,
    )

    if callable(process_cpu_count):
        try:
            count = process_cpu_count()
        except (
            OSError,
            ValueError,
        ):
            count = None

        if (
            count is not None
            and int(count) > 0
        ):
            candidates.append(
                (
                    int(count),
                    "os.process_cpu_count",
                )
            )

    sched_getaffinity = getattr(
        os,
        "sched_getaffinity",
        None,
    )

    if callable(sched_getaffinity):
        try:
            affinity = sched_getaffinity(0)
        except (
            OSError,
            ValueError,
        ):
            affinity = None

        if affinity:
            candidates.append(
                (
                    len(affinity),
                    "os.sched_getaffinity",
                )
            )

    cgroup_limit = _cgroup_cpu_limit()

    if cgroup_limit is not None:
        candidates.append(
            cgroup_limit
        )

    count = os.cpu_count()

    if (
        count is not None
        and int(count) > 0
    ):
        candidates.append(
            (
                int(count),
                "os.cpu_count",
            )
        )

    if not candidates:
        return (
            configured_fallback,
            "configured_fallback",
        )

    return min(
        candidates,
        key=lambda item: item[0],
    )


def resolve_parallelism(
    configured_fallback: int,
) -> dict[str, Any]:
    """
    Resolve automatic CPU parallelism.

    The configured value is only a fallback when runtime CPU
    detection fails. There is deliberately no fixed maximum.
    """

    configured_fallback = int(
        configured_fallback
    )

    if configured_fallback <= 0:
        raise ValueError(
            "configured_fallback must be greater than zero"
        )

    available, source = (
        available_logical_cpus(
            configured_fallback
        )
    )

    return {
        "configured_fallback": (
            configured_fallback
        ),
        "available_logical_cpus": available,
        "effective": available,
        "source": source,
    }
