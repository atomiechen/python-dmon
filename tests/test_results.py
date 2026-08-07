from __future__ import annotations

from contextlib import redirect_stderr
from dataclasses import FrozenInstanceError
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dmon.control import print_task_status, task_snapshot
from dmon.supervisor import stack_snapshot
from dmon.types import DmonMeta, DmonStackMeta, DmonStackTask


class ResultModelTest(unittest.TestCase):
    def test_task_snapshot_is_immutable_data_and_preserves_cli_command_shape(
        self,
    ) -> None:
        meta = DmonMeta(
            task="api",
            pid=42,
            cmd=["python", "-c", "pass"],
            cwd="/project",
            create_time=10.0,
            create_time_human="2026-08-07 12:00:00",
            meta_path="/project/.dmon/api.meta.json",
            log_path="/project/logs/api.log",
        )
        with patch("dmon.control.check_running", return_value=True):
            snapshot = task_snapshot(meta)

        self.assertEqual(snapshot.status, "running")
        self.assertEqual(snapshot.command, ("python", "-c", "pass"))
        meta.cmd.append("changed")
        self.assertEqual(snapshot.command, ("python", "-c", "pass"))
        with self.assertRaises(FrozenInstanceError):
            snapshot.pid = 7  # type: ignore[misc]

        output = StringIO()
        with patch(
            "dmon.control.colored", side_effect=lambda text, *_args, **_style: text
        ), redirect_stderr(output):
            print_task_status(snapshot)
        self.assertEqual(
            output.getvalue(),
            "TASK       : api\n"
            "PID        : 42\n"
            "STATUS     : Running\n"
            "CMD        : ['python', '-c', 'pass']\n"
            "WORKING DIR: /project\n"
            "CREATE TIME: 2026-08-07 12:00:00\n"
            "META PATH  : /project/.dmon/api.meta.json\n"
            "LOG ROTATE : False\n"
            "LOG PATH   : /project/logs/api.log\n",
        )

    def test_stack_snapshot_contains_stable_task_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_meta_path = root / "api.meta.json"
            DmonMeta(
                task="api",
                pid=43,
                create_time=11.0,
                meta_path=str(task_meta_path),
            ).dump(task_meta_path)
            meta = DmonStackMeta(
                stack="dev",
                mode="foreground",
                state="running",
                pid=42,
                create_time=10.0,
                tasks=[DmonStackTask("api", 43, 11.0, str(task_meta_path))],
            )
            with patch("dmon.supervisor.stack_process", return_value=object()), patch(
                "dmon.control.check_running", return_value=True
            ):
                snapshot = stack_snapshot(meta)

        self.assertEqual(snapshot.status, "running")
        self.assertTrue(snapshot.running)
        self.assertEqual(snapshot.mode, "foreground")
        self.assertEqual(snapshot.running_tasks, 1)
        self.assertEqual(snapshot.total_tasks, 1)
        self.assertEqual(snapshot.tasks[0].task, "api")
        self.assertEqual(snapshot.exit_policy, "keep-running")


if __name__ == "__main__":
    unittest.main()
