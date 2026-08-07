from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import psutil
import yaml

from dmon import Dmon, DmonConfigError
from dmon.types import DmonMeta


class QuietHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(204 if self.path == "/ready" else 503)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class WaitTest(unittest.TestCase):
    def run_dmon(
        self, root: Path, *args: str, timeout: float = 10
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "dmon", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )

    def test_direct_http_and_tcp_probes_report_success_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            tcp_port = listener.getsockname()[1]
            refused = socket.socket()
            refused.bind(("127.0.0.1", 0))
            refused_port = refused.getsockname()[1]
            refused.close()
            try:
                http = self.run_dmon(
                    root,
                    "wait",
                    "--http",
                    f"http://127.0.0.1:{server.server_port}/ready",
                    "--timeout",
                    "1",
                )
                tcp = self.run_dmon(
                    root,
                    "wait",
                    "--tcp",
                    f"127.0.0.1:{tcp_port}",
                    "--timeout",
                    "1",
                )
                http_error = self.run_dmon(
                    root,
                    "wait",
                    "--http",
                    f"http://127.0.0.1:{server.server_port}/error",
                    "--timeout",
                    "0.15",
                    "--interval",
                    "0.05",
                )
                tcp_error = self.run_dmon(
                    root,
                    "wait",
                    "--tcp",
                    f"127.0.0.1:{refused_port}",
                    "--timeout",
                    "0.15",
                    "--interval",
                    "0.05",
                )
            finally:
                listener.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(http.returncode, 0, http.stderr)
        self.assertEqual(tcp.returncode, 0, tcp.stderr)
        self.assertEqual(http_error.returncode, 1, http_error.stderr)
        self.assertIn("timeout", http_error.stderr)
        self.assertEqual(tcp_error.returncode, 1, tcp_error.stderr)
        self.assertIn("timeout", tcp_error.stderr)

    def test_direct_command_preserves_arguments_with_optional_separator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for separator in ((), ("--",)):
                with self.subTest(separator=separator):
                    result = self.run_dmon(
                        root,
                        "wait",
                        "--timeout",
                        "1",
                        "--command",
                        *separator,
                        sys.executable,
                        "-c",
                        "import sys; raise SystemExit(sys.argv[1] != '雪')",
                        "雪",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("'command' is ready", result.stderr)

            failed = self.run_dmon(
                root,
                "wait",
                "--timeout",
                "0.15",
                "--interval",
                "0.05",
                "--command",
                sys.executable,
                "-c",
                "raise SystemExit(4)",
            )
            self.assertEqual(failed.returncode, 1, failed.stderr)
            self.assertIn("'command' is not ready (timeout)", failed.stderr)

            invalid = self.run_dmon(
                root, "wait", "--timeout", "nan", "--command", "probe"
            )
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("must be finite and greater than zero", invalid.stderr)

    def test_configured_wait_uses_task_cwd_environment_and_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "probe-marker").touch()
            probe = (
                "import os, pathlib; "
                "raise SystemExit(os.environ.get('DMON_TEST_VALUE') != 'snow' or "
                "not pathlib.Path('probe-marker').is_file())"
            )
            config = project / "dmon.yaml"
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
                                "env": {"DMON_TEST_VALUE": "snow"},
                                "ready": {
                                    "command": [sys.executable, "-c", probe],
                                    "timeout": 2,
                                },
                            }
                        },
                        "default_task": "service",
                    }
                ),
                encoding="utf-8",
            )
            client = Dmon(config=config)
            previous = Path.cwd()
            output = StringIO()
            try:
                self.assertTrue(client.start("service").ok)
                with redirect_stdout(output), redirect_stderr(output):
                    result = client.wait("SERVICE", timeout=1, interval=0.05)
                    with self.assertRaises(DmonConfigError):
                        client.wait("service", timeout=float("inf"))
                    with self.assertRaises(DmonConfigError):
                        client.wait("service", interval=True)
                cli = self.run_dmon(root, "wait", "-c", str(config), "--format", "json")
            finally:
                client.stop("service")

            self.assertEqual(Path.cwd(), previous)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(len(result), 1)
            self.assertTrue(result[0].ready)
            self.assertEqual(result[0].reason, "ready")
            self.assertEqual(cli.returncode, 0, cli.stderr)
            payload = json.loads(cli.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["waits"][0]["target"], "service")
            self.assertNotIn("\x1b", cli.stdout)

    def test_multiple_tasks_require_every_target_to_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "tasks": {
                    "ready": {
                        "cmd": [sys.executable, "-c", "import time; time.sleep(60)"],
                        "ready": {"command": [sys.executable, "-c", "pass"]},
                    },
                    "not-ready": {
                        "cmd": [sys.executable, "-c", "import time; time.sleep(60)"],
                        "ready": {
                            "command": [sys.executable, "-c", "raise SystemExit(1)"],
                            "timeout": 0.15,
                            "interval": 0.05,
                        },
                    },
                }
            }
            (root / "dmon.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            client = Dmon(config=root / "dmon.yaml")
            try:
                self.assertTrue(client.start("ready", "not-ready").ok)
                result = self.run_dmon(
                    root,
                    "wait",
                    "ready",
                    "not-ready",
                    "--format",
                    "json",
                )
            finally:
                client.stop("ready", "not-ready")

            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(
                [(item["target"], item["reason"]) for item in payload["waits"]],
                [("ready", "ready"), ("not-ready", "timeout")],
            )

    def test_configured_wait_reports_runtime_and_configuration_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dmon.yaml").write_text(
                yaml.safe_dump(
                    {
                        "tasks": {
                            "missing": {
                                "cmd": [sys.executable, "-c", "pass"],
                                "ready": {"command": [sys.executable, "-c", "pass"]},
                            },
                            "plain": [sys.executable, "-c", "pass"],
                            "exited": {
                                "cmd": [sys.executable, "-c", "pass"],
                                "ready": {"command": [sys.executable, "-c", "pass"]},
                            },
                            "corrupt": {
                                "cmd": [sys.executable, "-c", "pass"],
                                "ready": {"command": [sys.executable, "-c", "pass"]},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            meta = root / ".dmon"
            meta.mkdir()
            DmonMeta(
                task="exited",
                pid=-1,
                create_time=-1,
                meta_path=str(meta / "exited.meta.json"),
            ).dump(meta / "exited.meta.json")
            (meta / "corrupt.meta.json").write_text("{broken", encoding="utf-8")

            result = self.run_dmon(
                root,
                "wait",
                "missing",
                "plain",
                "exited",
                "corrupt",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            reasons = {item["target"]: item["reason"] for item in payload["waits"]}
            self.assertEqual(
                reasons,
                {
                    "missing": "not-running",
                    "plain": "invalid",
                    "exited": "process-exited",
                    "corrupt": "metadata-error",
                },
            )
            self.assertTrue((meta / "corrupt.meta.json").exists())

    @unittest.skipIf(os.name == "nt", "POSIX signal semantics")
    def test_ctrl_c_returns_130_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            child_pid_path = Path(temporary) / "child.pid"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dmon",
                    "wait",
                    "--timeout",
                    "30",
                    "--command",
                    sys.executable,
                    "-c",
                    "import os, pathlib, time; "
                    f"pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid())); "
                    "time.sleep(30)",
                ],
                cwd=temporary,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            deadline = time.monotonic() + 5
            while not child_pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(child_pid_path.exists(), "probe command did not start")
            child_pid = int(child_pid_path.read_text())
            os.kill(process.pid, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=10)

            deadline = time.monotonic() + 5
            while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
                time.sleep(0.02)

        self.assertEqual(process.returncode, 130, stdout + stderr)
        self.assertIn("Readiness wait interrupted", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertFalse(psutil.pid_exists(process.pid))
        self.assertFalse(psutil.pid_exists(child_pid))


if __name__ == "__main__":
    unittest.main()
