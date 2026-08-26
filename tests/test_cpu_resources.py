from __future__ import annotations

import unittest
from unittest.mock import patch

from src.benchmark.cpu_resources import (
    _quota_to_cpu_count,
    available_logical_cpus,
    resolve_parallelism,
)


class CpuResourcesTests(unittest.TestCase):
    @patch(
        "src.benchmark.cpu_resources.available_logical_cpus",
        return_value=(8, "test"),
    )
    def test_uses_all_available_cpus(
        self,
        _mock_available,
    ) -> None:
        result = resolve_parallelism(2)

        self.assertEqual(
            result["configured_fallback"],
            2,
        )
        self.assertEqual(
            result["available_logical_cpus"],
            8,
        )
        self.assertEqual(
            result["effective"],
            8,
        )

    @patch(
        "src.benchmark.cpu_resources.available_logical_cpus",
        return_value=(1, "test"),
    )
    def test_does_not_oversubscribe_single_cpu(
        self,
        _mock_available,
    ) -> None:
        result = resolve_parallelism(2)

        self.assertEqual(
            result["effective"],
            1,
        )

    def test_fractional_cgroup_quota_rounds_up(
        self,
    ) -> None:
        self.assertEqual(
            _quota_to_cpu_count(
                150000,
                100000,
            ),
            2,
        )
        self.assertEqual(
            _quota_to_cpu_count(
                50000,
                100000,
            ),
            1,
        )

    @patch(
        "src.benchmark.cpu_resources.os.process_cpu_count",
        create=True,
        new=None,
    )
    @patch(
        "src.benchmark.cpu_resources.os.sched_getaffinity",
        create=True,
        return_value=set(range(20)),
    )
    @patch(
        "src.benchmark.cpu_resources._cgroup_cpu_limit",
        return_value=(2, "cgroup_v2"),
    )
    @patch(
        "src.benchmark.cpu_resources.os.cpu_count",
        return_value=20,
    )
    def test_cgroup_quota_caps_host_cpu_count(
        self,
        _mock_cpu_count,
        _mock_cgroup,
        _mock_affinity,
    ) -> None:
        count, source = (
            available_logical_cpus(2)
        )

        self.assertEqual(count, 2)
        self.assertEqual(
            source,
            "cgroup_v2",
        )

    @patch(
        "src.benchmark.cpu_resources.os.process_cpu_count",
        create=True,
        new=None,
    )
    @patch(
        "src.benchmark.cpu_resources.os.sched_getaffinity",
        create=True,
        new=None,
    )
    @patch(
        "src.benchmark.cpu_resources._cgroup_cpu_limit",
        return_value=None,
    )
    @patch(
        "src.benchmark.cpu_resources.os.cpu_count",
        return_value=None,
    )
    def test_fallback_when_detection_unavailable(
        self,
        _mock_cpu_count,
        _mock_cgroup,
    ) -> None:
        count, source = (
            available_logical_cpus(2)
        )

        self.assertEqual(count, 2)
        self.assertEqual(
            source,
            "configured_fallback",
        )

    def test_rejects_invalid_fallback(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            resolve_parallelism(0)


if __name__ == "__main__":
    unittest.main()
