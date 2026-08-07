from __future__ import annotations

from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from dmon.control import check_running, start_single, stop_single
from dmon.supervisor import cleanup, readiness_probe, task_message, up
from dmon.types import DmonMeta, DmonTaskConfig


class SupervisorTest(unittest.TestCase):
    def test_task_diagnostics_style_name_separately_from_state(self) -> None:
        def mark(text: str, **style: object) -> str:
            return f"<{style['color']}>{text}</{style['color']}>"

        with patch("dmon.supervisor.colored", side_effect=mark):
            message = task_message(
                "never-ready",
                " did not become ready within 0.5 seconds.",
                "red",
            )

        self.assertEqual(
            message,
            "<red>Task </red><cyan>'never-ready'</cyan>"
            "<red> did not become ready within 0.5 seconds.</red>",
        )

    def make_config(self, root: Path, task: str, command: list[str]) -> DmonTaskConfig:
        return DmonTaskConfig(
            task=task,
            cmd=command,
            cwd=str(root),
            log_path=str(root / "logs" / f"{task}.log"),
            meta_path=str(root / ".dmon" / f"{task}.meta.json"),
        )

    def assert_not_running(self, config: DmonTaskConfig) -> None:
        meta = DmonMeta.load(config.meta_path)
        self.assertIsNone(meta)

    def assert_process_stopped(self, meta: DmonMeta) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and check_running(meta.pid, meta.create_time):
            time.sleep(0.05)
        self.assertFalse(check_running(meta.pid, meta.create_time))

    def test_start_failure_rolls_back_tasks_started_by_up(self) -> None:
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
            with redirect_stderr(StringIO()):
                self.assertEqual(up([running, missing], poll_interval=0.05), 1)
            self.assert_not_running(running)
            self.assert_not_running(missing)

    def test_up_does_not_stop_a_task_that_was_already_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "existing",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            try:
                with redirect_stderr(StringIO()):
                    self.assertEqual(start_single(running), 0)
                    self.assertEqual(up([running], poll_interval=0.05), 1)
                meta = DmonMeta.load(running.meta_path)
                self.assertIsNotNone(meta)
                assert meta is not None
                self.assertTrue(check_running(meta.pid, meta.create_time))
            finally:
                with redirect_stderr(StringIO()):
                    stop_single(running.meta_path, timeout=1.0)

    def test_runtime_failure_stops_remaining_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "running",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            failing = self.make_config(
                root,
                "failing",
                [
                    sys.executable,
                    "-c",
                    "import sys,time; time.sleep(0.4); sys.exit(7)",
                ],
            )
            with redirect_stderr(StringIO()):
                self.assertEqual(up([running, failing], poll_interval=0.05), 1)
            self.assert_not_running(running)
            self.assert_not_running(failing)

    def test_interrupt_stops_the_stack_and_returns_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "running",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            with patch("dmon.supervisor.wait_ready", return_value=True), patch(
                "dmon.supervisor.time.sleep", side_effect=KeyboardInterrupt
            ), redirect_stderr(StringIO()):
                self.assertEqual(up([running], poll_interval=0.05), 0)
            self.assert_not_running(running)

    def test_cleanup_uses_captured_process_when_metadata_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "running",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            captured = []

            def remove_metadata(_config, meta, **_kwargs):
                captured.append(meta)
                Path(running.meta_path).unlink()
                return True

            with patch(
                "dmon.supervisor.wait_ready", side_effect=remove_metadata
            ), patch(
                "dmon.supervisor.time.sleep", side_effect=KeyboardInterrupt
            ), redirect_stderr(StringIO()):
                self.assertEqual(up([running], poll_interval=0.05), 0)

            self.assertEqual(len(captured), 1)
            self.assert_process_stopped(captured[0])
            self.assert_not_running(running)

    def test_unexpected_supervisor_error_still_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "running",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            captured = []

            def fail_supervision(_config, meta, **_kwargs):
                captured.append(meta)
                raise RuntimeError("simulated supervisor failure")

            with patch(
                "dmon.supervisor.wait_ready", side_effect=fail_supervision
            ), redirect_stderr(StringIO()), self.assertRaisesRegex(
                RuntimeError, "simulated supervisor failure"
            ):
                up([running], poll_interval=0.05)

            self.assertEqual(len(captured), 1)
            self.assert_process_stopped(captured[0])
            self.assert_not_running(running)

    def test_readiness_timeout_rolls_back_the_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            running = self.make_config(
                root,
                "not-ready",
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            running.ready = {
                "command": [sys.executable, "-c", "raise SystemExit(1)"],
                "timeout": 0.15,
                "interval": 0.02,
            }
            with redirect_stderr(StringIO()):
                self.assertEqual(up([running], poll_interval=0.05), 1)
            self.assert_not_running(running)

    def test_task_exit_before_readiness_fails_without_waiting_for_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            short = self.make_config(root, "short", [sys.executable, "-c", "pass"])
            short.ready = {
                "command": [sys.executable, "-c", "raise SystemExit(1)"],
                "timeout": 30,
                "interval": 0.02,
            }
            started_at = time.monotonic()
            with redirect_stderr(StringIO()):
                self.assertEqual(up([short], poll_interval=0.05), 1)
            self.assertLess(time.monotonic() - started_at, 2)
            self.assert_not_running(short)

    def test_cleanup_stops_tasks_in_reverse_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = []
            processes = {}
            for pid, task in enumerate(("database", "api", "worker"), start=1):
                config = self.make_config(root, task, ["unused"])
                meta = DmonMeta(
                    task=task,
                    pid=pid,
                    create_time=float(pid),
                    meta_path=config.meta_path,
                )
                Path(meta.meta_path).parent.mkdir(parents=True, exist_ok=True)
                meta.dump(meta.meta_path)
                process = object()
                processes[pid] = process
                started.append((config, meta))

            stopped = []

            def terminate(process, timeout):
                self.assertEqual(timeout, 5.0)
                stopped.append(process)
                return 0

            with patch(
                "dmon.supervisor.get_unique_process",
                side_effect=lambda pid, _create_time: processes[pid],
            ), patch("dmon.supervisor.terminate_process", side_effect=terminate):
                self.assertEqual(cleanup(started), 0)

            self.assertEqual(stopped, [processes[3], processes[2], processes[1]])
            self.assertTrue(
                all(not Path(config.meta_path).exists() for config, _ in started)
            )

    def test_http_readiness_probe(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(204)
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = DmonTaskConfig(cwd=".")
            ready = {"http": f"http://127.0.0.1:{server.server_port}/health"}
            self.assertTrue(readiness_probe(config, ready, 1.0))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_tcp_and_command_readiness_probes(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        try:
            host, port = listener.getsockname()
            config = DmonTaskConfig(cwd=".")
            self.assertTrue(
                readiness_probe(
                    config,
                    {"tcp": {"host": host, "port": port}},
                    1.0,
                )
            )
            self.assertTrue(
                readiness_probe(
                    config,
                    {"command": [sys.executable, "-c", "pass"]},
                    1.0,
                )
            )
        finally:
            listener.close()

    def test_command_readiness_uses_task_cwd_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = DmonTaskConfig(cwd=str(root), env={"DMON_READY": "yes"})
            command = [
                sys.executable,
                "-c",
                (
                    "import os,pathlib,sys; "
                    "sys.exit(0 if os.environ.get('DMON_READY') == 'yes' "
                    "and pathlib.Path.cwd().resolve() "
                    "== pathlib.Path(sys.argv[1]).resolve() else 1)"
                ),
                str(root),
            ]
            self.assertTrue(readiness_probe(config, {"command": command}, 1.0))


if __name__ == "__main__":
    unittest.main()
