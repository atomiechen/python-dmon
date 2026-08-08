from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import signal
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
    start_single_result,
    status,
    stop_single,
    task_environment,
    terminate_process_tree,
)
from dmon.types import DmonMeta, DmonTaskConfig


FIXTURE = Path(__file__).parent / "fixtures" / "process_tree.py"
SIGNAL_FIXTURE = Path(__file__).parent / "fixtures" / "count_signals.py"


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

    def test_start_result_returns_the_managed_process_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "captured",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            try:
                with redirect_stderr(StringIO()):
                    result = start_single_result(config)
                self.assertEqual(result.exit_code, 0)
                self.assertIsNotNone(result.meta)
                assert result.meta is not None
                persisted = DmonMeta.load(config.meta_path)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(result.meta.pid, persisted.pid)
                self.assertEqual(result.meta.create_time, persisted.create_time)
                self.assertTrue(check_running(result.meta.pid, result.meta.create_time))
            finally:
                self.cleanup_config(config)

    def test_started_task_metadata_does_not_contain_configured_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "private",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            config.env = {"SECRET_TOKEN": "do-not-store"}
            try:
                with redirect_stderr(StringIO()):
                    self.assertEqual(start_single(config), 0)
                text = Path(config.meta_path).read_text(encoding="utf-8")
                self.assertNotIn("SECRET_TOKEN", text)
                self.assertNotIn("do-not-store", text)
            finally:
                self.cleanup_config(config)

    def test_environment_files_are_layered_without_mutating_the_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.env"
            local = root / "local.env"
            base.write_text(
                "FILE_ONLY=base\nHOST_WINS=file\nBASE=from-file\n"
                "EXPANDED=${BASE}/child\n",
                encoding="utf-8",
            )
            local.write_text(
                "FILE_ONLY=local\nLOCAL_ONLY=yes\nNESTED=${EXPANDED}/nested\n",
                encoding="utf-8",
            )
            config = DmonTaskConfig(
                task="layered",
                env_files=[str(base), str(local)],
                env={"EXPLICIT": "yes", "FILE_ONLY": "explicit"},
            )
            with patch.dict(
                os.environ,
                {"HOST_WINS": "host", "HOST_ONLY": "yes"},
                clear=True,
            ):
                result = task_environment(config)
                self.assertEqual(os.environ, {"HOST_WINS": "host", "HOST_ONLY": "yes"})

            self.assertEqual(
                result,
                {
                    "FILE_ONLY": "explicit",
                    "HOST_WINS": "host",
                    "BASE": "from-file",
                    "EXPANDED": "from-file/child",
                    "LOCAL_ONLY": "yes",
                    "NESTED": "from-file/child/nested",
                    "HOST_ONLY": "yes",
                    "EXPLICIT": "yes",
                },
            )

            config.override_env = True
            local.write_text(
                "FILE_ONLY=local\nLOCAL_ONLY=${HOST_ONLY:-fallback}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"HOST_ONLY": "hidden"}, clear=True):
                isolated = task_environment(config)
            self.assertNotIn("HOST_ONLY", isolated)
            self.assertEqual(isolated["FILE_ONLY"], "explicit")
            self.assertEqual(isolated["LOCAL_ONLY"], "fallback")

    def test_started_task_receives_environment_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "environment.txt"
            env_file = root / "service.env"
            env_file.write_text("DMON_CHILD_VALUE=from-file\n", encoding="utf-8")
            config = self.make_config(
                root,
                "environment-child",
                [
                    sys.executable,
                    "-c",
                    "import os, pathlib; pathlib.Path(os.environ['DMON_OUTPUT'])"
                    ".write_text(os.environ['DMON_CHILD_VALUE'])",
                ],
            )
            config.env_files = [str(env_file)]
            config.env = {"DMON_OUTPUT": str(output)}

            with redirect_stderr(StringIO()):
                self.assertEqual(start_single(config), 0)
            wait_until(output.exists)

            self.assertEqual(output.read_text(encoding="utf-8"), "from-file")
            metadata = Path(config.meta_path).read_text(encoding="utf-8")
            stored = json.loads(metadata)
            self.assertNotIn("env", stored)
            self.assertNotIn("env_files", stored)
            self.assertNotIn("from-file", metadata)
            self.assertNotIn(str(env_file), metadata)

    def test_missing_environment_file_fails_before_reserving_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(
                root,
                "missing-env",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            config.env_files = [str(root / "missing.env")]
            output = StringIO()

            with redirect_stderr(output):
                result = start_single(config)

            self.assertEqual(result, 1)
            self.assertIn("environment file not found", output.getvalue())
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
                self.assertIn("failed to start: 'missing'", output.getvalue())
            finally:
                self.cleanup_config(running)

    @unittest.skipIf(sys.platform == "win32", "POSIX foreground process groups only")
    def test_exec_delivers_terminal_sigint_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signal_file = root / "signals.txt"
            config = root / "dmon.yaml"
            config.write_text(
                "tasks:\n"
                "  foreground:\n"
                f"    cmd: [{sys.executable!r}, {str(SIGNAL_FIXTURE)!r}, {str(signal_file)!r}]\n",
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "dmon", "exec", "-c", str(config), "foreground"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                assert process.stdout is not None
                self.assertTrue(process.stdout.readline().strip().isdigit())
                os.killpg(process.pid, signal.SIGINT)
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(
                    signal_file.read_text(encoding="utf-8"), f"{signal.SIGINT}\n"
                )
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)

    def test_exec_loads_config_relative_environment_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / ".env").write_text(
                "DMON_EXEC_VALUE=from-file\n", encoding="utf-8"
            )
            config = project / "dmon.yaml"
            config.write_text(
                "tasks:\n"
                "  foreground:\n"
                f"    cmd: [{sys.executable!r}, -c, "
                "\"import os; print(os.environ['DMON_EXEC_VALUE'])\"]\n"
                "    env_file: .env\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "dmon",
                    "exec",
                    "-c",
                    str(config),
                    "foreground",
                ],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "from-file")

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

    @unittest.skipIf(sys.platform == "win32", "POSIX process groups only")
    def test_stop_kills_process_group_after_grace_period(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_pid_file = root / "child.pid"
            config = self.make_config(
                root,
                "stubborn",
                [
                    sys.executable,
                    str(FIXTURE),
                    "--child-pid-file",
                    str(child_pid_file),
                    "--ignore-term",
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

                output = StringIO()
                with redirect_stderr(output):
                    self.assertEqual(stop_single(config.meta_path, timeout=0.1), 0)
                self.assertIn("did not exit in time; killing it", output.getvalue())
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
