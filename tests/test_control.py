from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import psutil

from dmon.control import (
    check_running,
    list_processes,
    start,
    start_single,
    status,
    stop_single,
    terminate_process_tree,
)
from dmon.types import DmonMeta, DmonTaskConfig


FIXTURE = Path(__file__).parent / "fixtures" / "process_tree.py"


def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not met before timeout")


class ControlTest(unittest.TestCase):
    def make_config(self, root: Path, task: str, command: list[str]) -> DmonTaskConfig:
        return DmonTaskConfig(
            task=task,
            cmd=command,
            cwd=str(root),
            log_path=str(root / "logs" / f"{task}.log"),
            meta_path=str(root / ".dmon" / f"{task}.meta.json"),
        )

    def cleanup_config(self, config: DmonTaskConfig) -> None:
        meta_path = Path(config.meta_path)
        if meta_path.exists():
            with redirect_stderr(StringIO()):
                stop_single(meta_path, timeout=1.0)

    def test_missing_executable_is_reported_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "missing",
                ["dmon-executable-that-does-not-exist"],
            )
            output = StringIO()
            with redirect_stderr(output):
                self.assertEqual(start_single(config), 1)
            self.assertIn("Start failed for task 'missing'", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())
            self.assertFalse(Path(config.meta_path).exists())

    def test_metadata_write_failure_stops_the_started_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "metadata-failure",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            original_dump = DmonMeta.dump
            started_pid = None

            def fail_final_dump(meta, path, *, exclusive=False):
                nonlocal started_pid
                if exclusive:
                    return original_dump(meta, path, exclusive=True)
                started_pid = meta.pid
                raise OSError("simulated metadata write failure")

            with patch.object(DmonMeta, "dump", fail_final_dump), redirect_stderr(
                StringIO()
            ):
                self.assertEqual(start_single(config), 1)

            self.assertIsNotNone(started_pid)
            assert started_pid is not None
            wait_until(
                lambda: not psutil.pid_exists(started_pid)
                or psutil.Process(started_pid).status() == psutil.STATUS_ZOMBIE
            )
            self.assertFalse(Path(config.meta_path).exists())

    def test_start_does_not_remove_an_active_start_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "reserved",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            meta_path = Path(config.meta_path)
            meta_path.parent.mkdir(parents=True)
            DmonMeta(
                task=config.task,
                state="starting",
                meta_path=config.meta_path,
            ).dump(meta_path, exclusive=True)
            output = StringIO()
            with redirect_stderr(output):
                self.assertEqual(start_single(config), 1)
            self.assertTrue(meta_path.exists())
            self.assertIn("already being started", output.getvalue())
            with redirect_stderr(StringIO()):
                self.assertEqual(stop_single(meta_path), 0)

    def test_corrupt_metadata_is_reported_without_being_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            meta_path = root / ".dmon" / "broken.meta.json"
            meta_path.parent.mkdir()
            meta_path.write_text("{broken", encoding="utf-8")
            config = self.make_config(
                root,
                "broken",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            for operation in (
                lambda: start_single(config),
                lambda: stop_single(meta_path),
                lambda: status([meta_path]),
                lambda: list_processes(meta_path.parent, full_width=False),
            ):
                with self.subTest(operation=operation), redirect_stderr(StringIO()):
                    self.assertEqual(operation(), 1)
            self.assertTrue(meta_path.exists())

    def test_multi_start_is_explicitly_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "running",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            missing = self.make_config(
                root,
                "missing",
                ["dmon-executable-that-does-not-exist"],
            )
            try:
                output = StringIO()
                with redirect_stderr(output):
                    self.assertEqual(start([running, missing]), 1)
                meta = DmonMeta.load(running.meta_path)
                self.assertIsNotNone(meta)
                assert meta is not None
                self.assertTrue(psutil.pid_exists(meta.pid))
                self.assertIn("best-effort", output.getvalue())
                self.assertIn("successful tasks were left running", output.getvalue())
            finally:
                self.cleanup_config(running)

    def test_status_fails_for_exited_task_and_stop_cleans_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "short",
                [sys.executable, "-c", "pass"],
            )
            with redirect_stderr(StringIO()):
                self.assertEqual(start_single(config), 0)
            meta = DmonMeta.load(config.meta_path)
            self.assertIsNotNone(meta)
            assert meta is not None
            wait_until(lambda: not check_running(meta.pid, meta.create_time))
            with redirect_stderr(StringIO()):
                self.assertEqual(status([config.meta_path]), 1)
                self.assertEqual(stop_single(config.meta_path), 0)
            self.assertFalse(Path(config.meta_path).exists())

    def test_start_replaces_stale_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "restartable",
                [sys.executable, "-c", "pass"],
            )
            with redirect_stderr(StringIO()):
                self.assertEqual(start_single(config), 0)
            first = DmonMeta.load(config.meta_path)
            self.assertIsNotNone(first)
            assert first is not None
            wait_until(lambda: not check_running(first.pid, first.create_time))

            config.cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
            try:
                with redirect_stderr(StringIO()):
                    self.assertEqual(start_single(config), 0)
                second = DmonMeta.load(config.meta_path)
                self.assertIsNotNone(second)
                assert second is not None
                self.assertNotEqual(first.pid, second.pid)
                self.assertTrue(psutil.pid_exists(second.pid))
            finally:
                self.cleanup_config(config)

    def test_stop_terminates_parent_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_pid_file = root / "child.pid"
            config = self.make_config(
                root,
                "tree",
                [
                    sys.executable,
                    str(FIXTURE),
                    "--child-pid-file",
                    str(child_pid_file),
                ],
            )
            try:
                with redirect_stderr(StringIO()):
                    self.assertEqual(start_single(config), 0)
                meta = DmonMeta.load(config.meta_path)
                self.assertIsNotNone(meta)
                assert meta is not None
                wait_until(child_pid_file.exists)
                child_pid = int(child_pid_file.read_text(encoding="utf-8"))
                self.assertTrue(psutil.pid_exists(meta.pid))
                self.assertTrue(psutil.pid_exists(child_pid))

                with redirect_stderr(StringIO()):
                    self.assertEqual(stop_single(config.meta_path, timeout=2.0), 0)
                wait_until(lambda: not psutil.pid_exists(meta.pid))
                wait_until(
                    lambda: not psutil.pid_exists(child_pid)
                    or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
                )
                self.assertFalse(Path(config.meta_path).exists())
            finally:
                self.cleanup_config(config)

    def test_process_tree_fallback_terminates_parent_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_pid_file = root / "child.pid"
            parent = subprocess.Popen(
                [
                    sys.executable,
                    str(FIXTURE),
                    "--child-pid-file",
                    str(child_pid_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                wait_until(child_pid_file.exists)
                child_pid = int(child_pid_file.read_text(encoding="utf-8"))
                with redirect_stderr(StringIO()):
                    self.assertEqual(
                        terminate_process_tree(psutil.Process(parent.pid), timeout=2.0),
                        0,
                    )
                wait_until(lambda: parent.poll() is not None)
                wait_until(
                    lambda: not psutil.pid_exists(child_pid)
                    or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
                )
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
