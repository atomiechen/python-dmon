from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import psutil
import yaml

from dmon.types import DmonMeta, DmonStackMeta, DmonStackTask


class JsonCliTest(unittest.TestCase):
    def run_dmon(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "dmon", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    def make_project(self, root: Path) -> None:
        (root / "dmon.yaml").write_text(
            yaml.safe_dump(
                {
                    "tasks": {
                        "running": [sys.executable, "-c", "pass"],
                        "exited": [sys.executable, "-c", "pass"],
                    },
                    "stacks": {"dev": ["running"]},
                }
            ),
            encoding="utf-8",
        )
        meta_dir = root / ".dmon"
        meta_dir.mkdir()
        process = psutil.Process(os.getpid())
        running = DmonMeta(
            task="running",
            pid=process.pid,
            create_time=process.create_time(),
            meta_path=str(meta_dir / "running.meta.json"),
        )
        running.dump(running.meta_path)
        DmonMeta(
            task="exited",
            pid=-1,
            create_time=-1,
            meta_path=str(meta_dir / "exited.meta.json"),
        ).dump(meta_dir / "exited.meta.json")
        DmonStackMeta(
            stack="dev",
            mode="foreground",
            state="running",
            pid=process.pid,
            create_time=process.create_time(),
            tasks=[
                DmonStackTask(
                    running.task,
                    running.pid,
                    running.create_time,
                    running.meta_path,
                )
            ],
        ).dump(meta_dir / "dev.stack.json")

    def test_task_json_status_and_list_preserve_exit_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)

            running = self.run_dmon(root, "status", "running", "--format", "json")
            self.assertEqual(running.returncode, 0, running.stderr)
            data = json.loads(running.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["tasks"][0]["snapshot"]["status"], "running")
            self.assertNotIn("env", data["tasks"][0]["snapshot"])
            self.assertNotIn("\x1b", running.stdout)

            exited = self.run_dmon(root, "status", "--format", "json", "exited")
            self.assertNotEqual(exited.returncode, 0)
            data = json.loads(exited.stdout)
            self.assertFalse(data["ok"])
            self.assertEqual(data["tasks"][0]["snapshot"]["status"], "exited")
            self.assertEqual(data["tasks"][0]["error"], "task has exited")
            self.assertIn("exited: task has exited", exited.stderr)

            listed = self.run_dmon(root, "list", "--format", "json")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            data = json.loads(listed.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(
                [item["name"] for item in data["tasks"]], ["exited", "running"]
            )
            self.assertTrue(all(item["ok"] for item in data["tasks"]))

            (root / ".dmon" / "running.meta.json").unlink()
            missing = self.run_dmon(root, "status", "running", "--format", "json")
            self.assertNotEqual(missing.returncode, 0)
            data = json.loads(missing.stdout)
            self.assertEqual(data["tasks"][0]["error"], "task metadata not found")

    def test_empty_json_lists_are_successful(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dmon.yaml").write_text("tasks: {}\n", encoding="utf-8")
            tasks = self.run_dmon(root, "list", "--format", "json")
            stacks = self.run_dmon(root, "stack", "list", "--format", "json")
            self.assertEqual(tasks.returncode, 0, tasks.stderr)
            self.assertEqual(stacks.returncode, 0, stacks.stderr)
            self.assertEqual(json.loads(tasks.stdout), {"ok": True, "tasks": []})
            self.assertEqual(json.loads(stacks.stdout), {"ok": True, "stacks": []})

    def test_json_reports_corrupt_metadata_without_polluting_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            corrupt = root / ".dmon" / "broken.meta.json"
            corrupt.write_text("{broken", encoding="utf-8")

            result = self.run_dmon(root, "list", "--format", "json")

            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertFalse(data["ok"])
            broken = next(item for item in data["tasks"] if item["name"] == "broken")
            self.assertFalse(broken["ok"])
            self.assertIsNone(broken["snapshot"])
            self.assertIn("broken:", result.stderr)
            self.assertNotIn(result.stderr, result.stdout)

    def test_stack_json_status_and_list_use_the_same_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)

            status = self.run_dmon(root, "stack", "status", "dev", "--format", "json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_data = json.loads(status.stdout)
            self.assertTrue(status_data["ok"])
            stack = status_data["stacks"][0]
            self.assertEqual(stack["snapshot"]["status"], "running")
            self.assertEqual(stack["snapshot"]["mode"], "foreground")

            listed = self.run_dmon(root, "stack", "list", "--format", "json")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            list_data = json.loads(listed.stdout)
            self.assertEqual(list_data["stacks"], status_data["stacks"])

            meta_path = root / ".dmon" / "dev.stack.json"
            meta = DmonStackMeta.load(meta_path)
            self.assertIsNotNone(meta)
            assert meta is not None
            meta.tasks[0].create_time = -1
            meta.dump(meta_path)
            degraded = self.run_dmon(root, "stack", "status", "dev", "--format", "json")
            self.assertNotEqual(degraded.returncode, 0)
            self.assertEqual(
                json.loads(degraded.stdout)["stacks"][0]["snapshot"]["status"],
                "degraded",
            )

            process = psutil.Process(os.getpid())
            meta.pid = -1
            meta.create_time = -1
            meta.tasks[0].pid = process.pid
            meta.tasks[0].create_time = process.create_time()
            meta.dump(meta_path)
            orphaned = self.run_dmon(root, "stack", "status", "dev", "--format", "json")
            self.assertNotEqual(orphaned.returncode, 0)
            self.assertEqual(
                json.loads(orphaned.stdout)["stacks"][0]["snapshot"]["status"],
                "orphaned",
            )


if __name__ == "__main__":
    unittest.main()
