from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time
import unittest

import psutil
import yaml


class DetachedStackTest(unittest.TestCase):
    def run_dmon(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "dmon", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )

    def assert_dmon_success(
        self, root: Path, result: subprocess.CompletedProcess[str]
    ) -> None:
        diagnostics = result.stderr
        for log_path in sorted((root / "logs").glob("*.stack.log")):
            diagnostics += f"\n--- {log_path.name} ---\n"
            diagnostics += log_path.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, diagnostics)

    def wait_for_stack_state(self, meta_path: Path, state: str) -> dict:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if data.get("state") == state:
                return data
            time.sleep(0.05)
        self.fail(f"stack did not reach {state!r}: {meta_path}")

    def test_stack_list_handles_empty_and_corrupt_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty = self.run_dmon(root, "stack", "list")
            self.assertEqual(empty.returncode, 0, empty.stderr)
            self.assertIn("Found 0 stacks", empty.stderr)

            meta_dir = root / ".dmon"
            meta_dir.mkdir()
            corrupt = meta_dir / "broken.stack.json"
            corrupt.write_text("{broken", encoding="utf-8")
            config = {
                "tasks": {"service": [sys.executable, "-c", "pass"]},
                "stacks": {"broken": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            listed = self.run_dmon(root, "stack", "list")
            self.assertNotEqual(listed.returncode, 0)
            self.assertIn("Cannot read stack metadata", listed.stderr)
            status = self.run_dmon(root, "stack", "status", "broken")
            self.assertNotEqual(status.returncode, 0)
            self.assertIn("metadata cannot be read", status.stderr)
            started = self.run_dmon(root, "stack", "up", "broken")
            self.assertNotEqual(started.returncode, 0)
            self.assertIn("metadata cannot be read", started.stderr)
            self.assertTrue(corrupt.exists())

    def test_foreground_stack_cli_attaches_output_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-u",
                        "-c",
                        "import time; print('service ready'); time.sleep(0.5)",
                    ]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

            result = self.run_dmon(root, "stack", "up", "dev")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("[service] service ready", result.stdout)
            self.assertFalse((root / ".dmon" / "service.meta.json").exists())

    def test_foreground_stack_is_discoverable_and_stoppable_cross_terminal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [sys.executable, "-c", "import time; time.sleep(60)"]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            foreground = subprocess.Popen(
                [sys.executable, "-m", "dmon", "stack", "up", "dev"],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                meta = self.wait_for_stack_state(meta_path, "running")
                self.assertEqual(meta["mode"], "foreground")

                status = self.run_dmon(root, "stack", "status", "dev")
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertIn("MODE       : foreground", status.stderr)
                self.assertNotIn("LOG        :", status.stderr)
                self.assertRegex(status.stderr, r"service\s+\d+\s+\d+\s+Running")

                listed = self.run_dmon(root, "stack", "list")
                self.assertEqual(listed.returncode, 0, listed.stderr)
                self.assertRegex(
                    listed.stderr, r"dev\s+Running\s+\d+\s+1/1\s+foreground"
                )

                duplicate = self.run_dmon(root, "stack", "up", "-d", "dev")
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn("already active", duplicate.stderr)

                restarted = self.run_dmon(root, "stack", "restart", "dev")
                self.assertNotEqual(restarted.returncode, 0)
                self.assertIn(
                    "cannot be restarted from another terminal", restarted.stderr
                )

                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                stdout, stderr = foreground.communicate(timeout=15)
                self.assertEqual(foreground.returncode, 0, stdout + stderr)
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                if foreground.poll() is None:
                    foreground.kill()
                    foreground.wait(timeout=5)
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_concurrent_foreground_and_detached_start_have_one_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [sys.executable, "-c", "import time; time.sleep(60)"]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            processes = [
                subprocess.Popen(
                    [sys.executable, "-m", "dmon", "stack", "up", *options, "dev"],
                    cwd=root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for options in ([], ["-d"])
            ]
            try:
                meta = self.wait_for_stack_state(meta_path, "running")
                self.assertIn(meta["mode"], {"foreground", "detached"})
                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                results = [process.communicate(timeout=15) for process in processes]
                self.assertEqual(
                    sorted(process.returncode for process in processes), [0, 1], results
                )
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    process.communicate()
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    @unittest.skipIf(sys.platform.startswith("win"), "SIGTERM is POSIX-specific")
    def test_foreground_sigterm_cleans_owned_tasks_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [sys.executable, "-c", "import time; time.sleep(60)"]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            foreground = subprocess.Popen(
                [sys.executable, "-m", "dmon", "stack", "up", "dev"],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.wait_for_stack_state(meta_path, "running")
                foreground.terminate()
                stdout, stderr = foreground.communicate(timeout=15)
                self.assertEqual(foreground.returncode, 0, stdout + stderr)
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                if foreground.poll() is None:
                    foreground.kill()
                    foreground.wait(timeout=5)
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_down_recovers_after_foreground_supervisor_is_killed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [sys.executable, "-c", "import time; time.sleep(60)"]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            foreground = subprocess.Popen(
                [sys.executable, "-m", "dmon", "stack", "up", "dev"],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.wait_for_stack_state(meta_path, "running")
                foreground.kill()
                foreground.wait(timeout=5)
                foreground.communicate()

                status = self.run_dmon(root, "stack", "status", "dev")
                self.assertNotEqual(status.returncode, 0)
                self.assertIn("STATUS     : Orphaned", status.stderr)
                self.assertIn("MODE       : foreground", status.stderr)

                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                if foreground.poll() is None:
                    foreground.kill()
                    foreground.wait(timeout=5)
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_foreground_runtime_exit_is_reported_as_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [sys.executable, "-c", "import time; time.sleep(60)"],
                    "short": [sys.executable, "-c", "import time; time.sleep(0.5)"],
                },
                "stacks": {"dev": ["service", "short"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            foreground = subprocess.Popen(
                [sys.executable, "-m", "dmon", "stack", "up", "dev"],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.wait_for_stack_state(meta_path, "degraded")
                status = self.run_dmon(root, "stack", "status", "dev")
                self.assertNotEqual(status.returncode, 0)
                self.assertIn("STATUS     : Degraded", status.stderr)
                self.assertIn("MODE       : foreground", status.stderr)
                self.assertIn("TASKS      : 1/2 running", status.stderr)

                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                foreground.communicate(timeout=15)
                self.assertEqual(foreground.returncode, 0)
            finally:
                if foreground.poll() is None:
                    foreground.kill()
                    foreground.wait(timeout=5)
                foreground.communicate()
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_detached_stack_lifecycle_and_duplicate_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ]
                },
                "stacks": {"dev": ["service"]},
                "default_stack": "dev",
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            (root / ".dmon").mkdir()
            (root / ".dmon" / "dev.stack.json.stop").write_text(
                "stale\n", encoding="utf-8"
            )
            try:
                started = self.run_dmon(root, "stack", "up", "-d")
                self.assert_dmon_success(root, started)
                self.assertIn("STACK      : dev", started.stderr)
                self.assertNotIn("STACK      : 'dev'", started.stderr)
                self.assertIn("STATUS     : Running", started.stderr)
                self.assertIn("EXIT POLICY: keep-running", started.stderr)

                stack_meta_path = root / ".dmon" / "dev.stack.json"
                task_meta_path = root / ".dmon" / "service.meta.json"
                stack_before_logs = stack_meta_path.read_bytes()
                task_before_logs = task_meta_path.read_bytes()
                viewed = self.run_dmon(root, "stack", "logs", "--tail", "1", "dev")
                self.assertEqual(viewed.returncode, 0, viewed.stderr)
                self.assertEqual(stack_meta_path.read_bytes(), stack_before_logs)
                self.assertEqual(task_meta_path.read_bytes(), task_before_logs)

                status = self.run_dmon(root, "stack", "status")
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertIn("TASKS      : 1/1 running", status.stderr)
                self.assertIn("Task Processes:", status.stderr)
                self.assertRegex(status.stderr, r"service\s+\d+\s+\d+\s+Running")

                listed = self.run_dmon(root, "stack", "list")
                self.assertEqual(listed.returncode, 0, listed.stderr)
                self.assertRegex(listed.stderr, r"dev\s+Running\s+\d+\s+1/1")
                self.assertIn("Found 1 stack", listed.stderr)

                duplicate = self.run_dmon(root, "stack", "up", "--detach", "dev")
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn("already active", duplicate.stderr)

                (root / "dmon.yaml").unlink()
                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                self.assertFalse((root / ".dmon" / "dev.stack.json").exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                if (root / ".dmon" / "dev.stack.json").exists():
                    self.run_dmon(root, "stack", "down")

    def test_concurrent_detached_start_has_one_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            command = [
                sys.executable,
                "-m",
                "dmon",
                "stack",
                "up",
                "-d",
                "dev",
            ]
            try:
                processes = [
                    subprocess.Popen(
                        command,
                        cwd=root,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    for _ in range(2)
                ]
                results = [process.communicate(timeout=20) for process in processes]
                self.assertEqual(
                    sorted(process.returncode for process in processes), [0, 1]
                )
                self.assertTrue(
                    any(
                        "another dmon process" in stderr or "already active" in stderr
                        for _, stderr in results
                    ),
                    results,
                )
            finally:
                if (root / ".dmon" / "dev.stack.json").exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_stale_stack_metadata_requires_explicit_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_dir = root / ".dmon"
            meta_dir.mkdir()
            meta_path = meta_dir / "dev.stack.json"
            meta_path.write_text(
                json.dumps(
                    {
                        "stack": "dev",
                        "state": "failed",
                        "pid": -1,
                        "create_time": -1.0,
                        "config_path": str(root / "dmon.yaml"),
                        "log_path": str(root / "logs" / "dev.stack.log"),
                        "tasks": [],
                        "error": "previous failure",
                    }
                ),
                encoding="utf-8",
            )

            refused = self.run_dmon(root, "stack", "up", "-d", "dev")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("run 'dmon stack down'", refused.stderr)
            self.assertTrue(meta_path.exists())

            stopped = self.run_dmon(root, "stack", "down", "dev")
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertFalse(meta_path.exists())

    def test_detached_startup_failure_rolls_back_started_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ],
                    "missing": ["dmon-executable-that-does-not-exist"],
                },
                "stacks": {"dev": ["service", "missing"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            try:
                started = self.run_dmon(root, "stack", "up", "-d", "dev")
                self.assertNotEqual(started.returncode, 0)
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
                self.assertFalse((root / ".dmon" / "missing.meta.json").exists())
            finally:
                if meta_path.exists():
                    stopped = self.run_dmon(root, "stack", "down", "dev")
                    self.assertEqual(stopped.returncode, 0, stopped.stderr)

    def test_down_can_cancel_detached_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": {
                        "cmd": [
                            sys.executable,
                            "-c",
                            "import time; time.sleep(60)",
                        ],
                        "ready": {
                            "command": [
                                sys.executable,
                                "-c",
                                "raise SystemExit(1)",
                            ],
                            "timeout": 30,
                            "interval": 0.1,
                        },
                    }
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            command = [
                sys.executable,
                "-m",
                "dmon",
                "stack",
                "up",
                "-d",
                "dev",
            ]
            starter = subprocess.Popen(
                command,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if meta_path.exists():
                        stack_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        if stack_meta.get("tasks"):
                            break
                    time.sleep(0.05)
                else:
                    self.fail("detached stack did not begin startup")

                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                starter.communicate(timeout=10)
                self.assertNotEqual(starter.returncode, 0)
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                if starter.poll() is None:
                    starter.kill()
                    starter.wait(timeout=5)
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_down_recovers_after_supervisor_is_killed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            try:
                started = self.run_dmon(root, "stack", "up", "-d", "dev")
                self.assert_dmon_success(root, started)
                stack_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                supervisor = psutil.Process(stack_meta["pid"])
                supervisor.kill()
                supervisor.wait(timeout=5)

                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
            finally:
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_runtime_failure_is_recorded_after_owned_tasks_are_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ],
                    "failing": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(0.8); raise SystemExit(7)",
                    ],
                },
                "stacks": {"dev": ["service", "failing"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            try:
                started = self.run_dmon(
                    root, "stack", "up", "-d", "--abort-on-exit", "dev"
                )
                self.assert_dmon_success(root, started)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    status = self.run_dmon(root, "stack", "status", "dev")
                    if "STATUS     : Failed" in status.stderr:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("detached stack did not report its runtime failure")

                self.assertIn("STATUS     : Failed", status.stderr)
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
                self.assertFalse((root / ".dmon" / "failing.meta.json").exists())
                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
            finally:
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_runtime_exit_degrades_detached_stack_until_down(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ],
                    "short": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(0.8)",
                    ],
                },
                "stacks": {"dev": ["service", "short"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            try:
                started = self.run_dmon(root, "stack", "up", "-d", "dev")
                self.assert_dmon_success(root, started)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    status = self.run_dmon(root, "stack", "status", "dev")
                    if "STATUS     : Degraded" in status.stderr:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("detached stack did not report its degraded state")

                self.assertNotEqual(status.returncode, 0)
                self.assertIn("TASKS      : 1/2 running", status.stderr)
                self.assertRegex(status.stderr, r"service\s+\d+\s+\d+\s+Running")
                self.assertRegex(status.stderr, r"short\s+\d+\s+N/A\s+Exited")
                service_meta = json.loads(
                    (root / ".dmon" / "service.meta.json").read_text(encoding="utf-8")
                )
                self.assertTrue(
                    psutil.pid_exists(service_meta["pid"]),
                    "remaining task was stopped by a non-fail-fast stack",
                )

                stopped = self.run_dmon(root, "stack", "down", "dev")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                self.assertFalse(meta_path.exists())
                self.assertFalse((root / ".dmon" / "service.meta.json").exists())
                self.assertFalse((root / ".dmon" / "short.meta.json").exists())
            finally:
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_restart_detached_stack_preserves_exit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "service": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(60)",
                    ]
                },
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            meta_path = root / ".dmon" / "dev.stack.json"
            try:
                started = self.run_dmon(
                    root, "stack", "up", "-d", "--abort-on-exit", "dev"
                )
                self.assert_dmon_success(root, started)
                before = json.loads(meta_path.read_text(encoding="utf-8"))

                restarted = self.run_dmon(root, "stack", "restart", "dev")
                self.assert_dmon_success(root, restarted)
                after = json.loads(meta_path.read_text(encoding="utf-8"))

                self.assertNotEqual(after["run_id"], before["run_id"])
                self.assertTrue(after["abort_on_exit"])
                self.assertEqual(after["state"], "running")
            finally:
                if meta_path.exists():
                    self.run_dmon(root, "stack", "down", "dev")

    def test_restart_does_not_start_a_stack_that_is_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {"service": [sys.executable, "-c", "pass"]},
                "stacks": {"dev": ["service"]},
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

            restarted = self.run_dmon(root, "stack", "restart", "dev")

            self.assertNotEqual(restarted.returncode, 0)
            self.assertIn("is not running", restarted.stderr)
            self.assertFalse((root / ".dmon" / "dev.stack.json").exists())
            self.assertFalse((root / ".dmon" / "service.meta.json").exists())


if __name__ == "__main__":
    unittest.main()
