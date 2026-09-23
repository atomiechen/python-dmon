from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import psutil
import yaml

from dmon.control import (
    check_running,
    start_single,
    stop_owned_processes,
    stop_single,
    task_owns_listener,
)
from dmon.supervisor import cleanup_stack_tasks, start_foreground_stack
from dmon.types import (
    DmonMeta,
    DmonStackMeta,
    DmonStackTask,
    DmonTaskConfig,
    ProcessIdentity,
)


FIXTURE = Path(__file__).parent / "fixtures" / "exiting_parent.py"


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("condition not met before timeout")


class OwnershipTest(unittest.TestCase):
    def run_dmon(self, root, *args):
        return subprocess.run(
            [sys.executable, "-m", "dmon", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_stack_remembers_child_after_parent_and_supervisor_exit(self):
        for crash in (False, True):
            with self.subTest(crash=crash), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child_path, gate = root / "child.pid", root / "exit-parent"
                (root / "dmon.yaml").write_text(
                    yaml.safe_dump(
                        {
                            "tasks": {
                                "api": [
                                    sys.executable,
                                    str(FIXTURE),
                                    str(child_path),
                                    str(gate),
                                ]
                            },
                            "stacks": {"dev": ["api"]},
                        }
                    ),
                    encoding="utf-8",
                )
                meta_path = root / ".dmon/dev.stack.json"
                child = None
                try:
                    started = self.run_dmon(root, "stack", "up", "-d", "dev")
                    self.assertEqual(started.returncode, 0, started.stderr)
                    wait_until(child_path.exists)
                    child = psutil.Process(int(child_path.read_text()))
                    birth = child.create_time()

                    def recorded():
                        meta = DmonStackMeta.load(meta_path)
                        return meta and any(
                            item.pid == child.pid and item.create_time == birth
                            for task in meta.tasks
                            for item in task.descendants
                        )

                    wait_until(recorded)
                    meta = DmonStackMeta.load(meta_path)
                    parent = meta.tasks[0]
                    if crash:
                        supervisor = psutil.Process(meta.pid)
                        supervisor.kill()
                        wait_until(
                            lambda: not check_running(meta.pid, meta.create_time)
                        )
                    gate.touch()
                    wait_until(
                        lambda: not check_running(parent.pid, parent.create_time)
                    )
                    if crash:
                        status = self.run_dmon(
                            root, "stack", "status", "dev", "--format", "json"
                        )
                        snapshot = json.loads(status.stdout)["stacks"][0]["snapshot"]
                        self.assertEqual(snapshot["status"], "orphaned")
                        self.assertIn(
                            child.pid, snapshot["tasks"][0]["live_descendant_pids"]
                        )
                    else:
                        wait_until(lambda: not check_running(child.pid, birth))
                    stopped = self.run_dmon(root, "stack", "down", "dev")
                    self.assertEqual(stopped.returncode, 0, stopped.stderr)
                    wait_until(lambda: not check_running(child.pid, birth))
                    self.assertFalse(meta_path.exists())
                finally:
                    if meta_path.exists():
                        self.run_dmon(root, "stack", "down", "dev")
                    if child is not None and child.is_running():
                        child.kill()

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_unobserved_orphan_is_not_killed_or_reported_as_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_path, gate = root / "child.pid", root / "exit-parent"
            parent = subprocess.Popen(
                [sys.executable, str(FIXTURE), str(child_path), str(gate)],
                start_new_session=True,
            )
            meta = DmonMeta(
                task="unobserved",
                pid=parent.pid,
                create_time=psutil.Process(parent.pid).create_time(),
                popen_kwargs={"start_new_session": True},
            )
            path = root / "task.meta.json"
            meta.dump(path)
            child = None
            try:
                wait_until(child_path.exists)
                child = psutil.Process(int(child_path.read_text()))
                gate.touch()
                parent.wait(timeout=5)
                output = StringIO()
                with redirect_stderr(output):
                    self.assertEqual(stop_single(path, timeout=0.2), 1)
                    meta.meta_path = str(path)
                    meta.log_path = str(root / "task.log")
                    meta.cwd = str(root)
                    meta.cmd = [sys.executable, "-c", "raise SystemExit(0)"]
                    self.assertEqual(start_single(meta), 1)
                self.assertTrue(path.exists())
                self.assertTrue(child.is_running())
                self.assertIn("unverified members", output.getvalue())
                self.assertIn("residual processes", output.getvalue())
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=5)
                if child is not None and child.is_running():
                    child.kill()

    def test_recycled_descendant_identity_is_never_signalled(self):
        meta = DmonMeta(task="stale", descendants=[ProcessIdentity(os.getpid(), 0.0)])
        with patch("dmon.control.terminate_process") as terminate:
            self.assertEqual(stop_owned_processes(meta, 0.2), 0)
        terminate.assert_not_called()

    def test_unreadable_socket_table_is_not_positive_ownership_evidence(self):
        process = psutil.Process()
        meta = DmonMeta(pid=process.pid, create_time=process.create_time())
        with patch.object(
            psutil.Process, "net_connections", side_effect=psutil.AccessDenied()
        ), patch.object(psutil.Process, "children", return_value=[]):
            self.assertFalse(task_owns_listener(meta, "127.0.0.1", 80))

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_foreground_incomplete_cleanup_retains_stack_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_path, gate = root / "child.pid", root / "exit-parent"
            stack_path = root / ".dmon/dev.stack.json"
            probe = (
                "from pathlib import Path; "
                f"child=Path({str(child_path)!r}); gate=Path({str(gate)!r}); "
                "gate.touch() if child.exists() else None; raise SystemExit(1)"
            )
            config = DmonTaskConfig(
                task="api",
                cmd=[sys.executable, str(FIXTURE), str(child_path), str(gate)],
                cwd=str(root),
                log_path=str(root / "api.log"),
                meta_path=str(root / ".dmon/api.meta.json"),
                ready={
                    "command": [sys.executable, "-c", probe],
                    "timeout": 2,
                    "interval": 0.05,
                },
            )
            try:
                # Model a child missed by the polling observer. Do not fabricate
                # permission to kill it from the remaining process group alone.
                with patch(
                    "dmon.supervisor.refresh_descendants", return_value=False
                ), redirect_stderr(StringIO()):
                    result = start_foreground_stack(
                        "dev",
                        [config],
                        root / "dmon.yaml",
                        stack_path,
                        root / "stack.log",
                    )
                self.assertEqual(result, 1)
                self.assertTrue(stack_path.exists())
                self.assertEqual(DmonStackMeta.load(stack_path).state, "cleanup-failed")
                self.assertTrue((root / ".dmon/api.meta.json").exists())
            finally:
                if child_path.exists():
                    child = psutil.Process(int(child_path.read_text()))
                    birth = child.create_time()
                    child.kill()
                    wait_until(lambda: not check_running(child.pid, birth))
                if stack_path.exists():
                    with redirect_stderr(StringIO()):
                        cleanup_stack_tasks(DmonStackMeta.load(stack_path).tasks)
                    stack_path.unlink()

    def test_descendant_identity_survives_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stack.json"
            expected = DmonStackMeta(
                stack="dev",
                tasks=[
                    DmonStackTask(
                        "api",
                        123,
                        100.0,
                        "api.meta.json",
                        descendants=[ProcessIdentity(124, 101.0)],
                        new_session=True,
                    )
                ],
            )
            expected.dump(path)
            self.assertEqual(DmonStackMeta.load(path), expected)


if __name__ == "__main__":
    unittest.main()
