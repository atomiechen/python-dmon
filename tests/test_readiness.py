from __future__ import annotations

import unittest
from unittest.mock import patch

from dmon.readiness import ReadySpec, wait_for_readiness


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ReadinessTest(unittest.TestCase):
    def test_probe_retries_use_one_monotonic_deadline(self) -> None:
        clock = Clock()
        spec = ReadySpec("command", timeout=1.0, interval=0.1, command=("check",))
        with patch("dmon.readiness.time.monotonic", side_effect=clock.monotonic), patch(
            "dmon.readiness.time.sleep", side_effect=clock.sleep
        ), patch("dmon.readiness.probe", side_effect=[False, False, True]) as probe:
            result = wait_for_readiness("service", spec, cwd=".", env=None)

        self.assertTrue(result.ready)
        self.assertEqual(result.reason, "ready")
        self.assertEqual(result.attempts, 3)
        self.assertAlmostEqual(result.elapsed, 0.2)
        self.assertEqual(probe.call_count, 3)

    def test_timeout_is_bounded_and_reports_attempt_count(self) -> None:
        clock = Clock()
        spec = ReadySpec("command", timeout=0.25, interval=0.1, command=("check",))
        with patch("dmon.readiness.time.monotonic", side_effect=clock.monotonic), patch(
            "dmon.readiness.time.sleep", side_effect=clock.sleep
        ), patch("dmon.readiness.probe", return_value=False):
            result = wait_for_readiness("service", spec, cwd=".", env=None)

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "timeout")
        self.assertEqual(result.attempts, 3)
        self.assertAlmostEqual(result.elapsed, 0.25)

    def test_process_exit_and_stop_request_preempt_probes(self) -> None:
        spec = ReadySpec("command", timeout=30, interval=1, command=("check",))
        with patch("dmon.readiness.probe") as probe:
            exited = wait_for_readiness(
                "service", spec, cwd=".", env=None, process_running=lambda: False
            )
            stopped = wait_for_readiness(
                "service", spec, cwd=".", env=None, stop_requested=lambda: True
            )

        self.assertEqual((exited.reason, exited.attempts), ("process-exited", 0))
        self.assertEqual((stopped.reason, stopped.attempts), ("stopped", 0))
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
