from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

import psutil
import yaml

from dmon import Dmon, DmonConfigError
from dmon import control
from dmon.control import diagnostic_output
from dmon.types import DmonStackMeta, DmonStackTask


class ApiTest(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        config = root / "dmon.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "tasks": {
                        "service": [
                            sys.executable,
                            "-c",
                            "import time; time.sleep(60)",
                        ]
                    },
                    "default_task": "service",
                }
            ),
            encoding="utf-8",
        )
        return config

    def test_public_api_lifecycle_is_structured_silent_and_restores_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_project(root)
            client = Dmon(config=config)
            previous = Path.cwd()
            output = StringIO()
            try:
                with redirect_stdout(output), redirect_stderr(output):
                    started = client.start()
                    status = client.status()
                    listed = client.list_tasks()
                    restarted = client.restart("SERVICE")
                    stopped = client.stop("service")
                    missing = client.status("service")

                self.assertTrue(started.ok)
                self.assertEqual(started.results[0].snapshot.task, "service")
                self.assertTrue(status.ok)
                self.assertEqual(len(listed), 1)
                self.assertTrue(listed[0].ok)
                self.assertTrue(restarted.ok)
                self.assertNotEqual(
                    started.results[0].snapshot.pid,
                    restarted.results[0].snapshot.pid,
                )
                self.assertTrue(stopped.ok)
                self.assertFalse(missing.ok)
                self.assertEqual(missing.error, "task metadata not found")
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(Path.cwd(), previous)
            finally:
                client.stop("service")

    def test_invalid_config_raises_and_corrupt_runtime_state_is_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_project(root)
            client = Dmon(config=config)
            meta_path = root / ".dmon" / "service.meta.json"
            meta_path.parent.mkdir()
            meta_path.write_text("{broken", encoding="utf-8")

            result = client.status("service")

            self.assertFalse(result.ok)
            self.assertTrue(result.error)
            self.assertTrue(meta_path.exists())
            with self.assertRaises(DmonConfigError):
                Dmon(config=root / "missing.yaml").status("service")

    def test_environment_file_is_config_relative_and_never_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "service.env").write_text(
                "DMON_API_SECRET=from-file\n", encoding="utf-8"
            )
            config = root / "dmon.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "tasks": {
                            "service": {
                                "cmd": [
                                    sys.executable,
                                    "-c",
                                    "import time; time.sleep(60)",
                                ],
                                "env_file": "service.env",
                                "ready": {
                                    "command": [
                                        sys.executable,
                                        "-c",
                                        "import os; raise SystemExit("
                                        "os.environ.get('DMON_API_SECRET') != 'from-file')",
                                    ]
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            client = Dmon(config=config)
            previous = Path.cwd()
            try:
                self.assertTrue(client.start("service").ok)
                self.assertTrue(client.wait("service", timeout=1)[0].ready)
                metadata = (root / ".dmon" / "service.meta.json").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("DMON_API_SECRET", metadata)
                self.assertNotIn("from-file", metadata)
                self.assertEqual(Path.cwd(), previous)
            finally:
                client.stop("service")

            (root / "service.env").unlink()
            with self.assertRaisesRegex(DmonConfigError, "environment file not found"):
                client.start("service")

    def test_stack_inspection_reuses_public_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_project(root)
            client = Dmon(config=config)
            try:
                started = client.start("service")
                task = started.results[0].snapshot
                self.assertIsNotNone(task)
                assert task is not None
                stack_path = root / ".dmon" / "dev.stack.json"
                process = psutil.Process(os.getpid())
                DmonStackMeta(
                    stack="dev",
                    mode="foreground",
                    state="running",
                    pid=process.pid,
                    create_time=process.create_time(),
                    tasks=[
                        DmonStackTask(
                            task.task,
                            task.pid,
                            task.create_time,
                            task.meta_path,
                        )
                    ],
                ).dump(stack_path)

                status = client.stack_status("DEV")
                listed = client.list_stacks()

                self.assertTrue(status.ok)
                self.assertEqual(status.snapshot.status, "running")
                self.assertEqual(status.snapshot.tasks[0], task)
                self.assertEqual(listed, (status,))
            finally:
                client.stop("service")

    def test_concurrent_api_start_keeps_one_metadata_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_project(root)
            results = []

            def start() -> None:
                results.append(Dmon(config=config).start("service"))

            threads = [threading.Thread(target=start) for _ in range(2)]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(sorted(result.ok for result in results), [False, True])
                data = json.loads(
                    (root / ".dmon" / "service.meta.json").read_text(encoding="utf-8")
                )
                self.assertGreater(data["pid"], 0)
            finally:
                Dmon(config=config).stop("service")

    def test_api_diagnostics_do_not_capture_another_thread(self) -> None:
        api_output = StringIO()
        host_output = StringIO()
        barrier = threading.Barrier(2)

        def api_call() -> None:
            with diagnostic_output(api_output):
                barrier.wait()
                control.print("api diagnostic", file=sys.stderr)

        thread = threading.Thread(target=api_call)
        with redirect_stderr(host_output):
            thread.start()
            barrier.wait()
            control.print("host diagnostic", file=sys.stderr)
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(api_output.getvalue(), "api diagnostic\n")
        self.assertEqual(host_output.getvalue(), "host diagnostic\n")


if __name__ == "__main__":
    unittest.main()
