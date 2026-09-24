from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import threading
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import psutil
import yaml

from dmon.control import check_running
from dmon.repair import operation_path, support_path


class RepairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack_path = self.root / ".dmon/dev.stack.json"
        self.procs = []
        self.identities = []
        self.write_config()

    def write_config(self, ready=None):
        script = "import os,pathlib,time; pathlib.Path('worker-env').write_text(os.environ.get('REPAIR_VALUE','')); time.sleep(120)"
        config = {
            "tasks": {
                "api": [sys.executable, "-c", "import time; time.sleep(120)"],
                "worker": {"cmd": [sys.executable, "-c", script], "env_file": ".env"},
            },
            "stacks": {"dev": ["api", "worker"]},
        }
        if ready:
            config["tasks"]["worker"]["ready"] = ready
        (self.root / ".env").write_text("REPAIR_VALUE=original-secret\n")
        (self.root / "dmon.yaml").write_text(yaml.safe_dump(config))

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "dmon", *args, "-c", str(self.root)],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=25,
        )

    def start(self, foreground=False):
        if foreground:
            self.procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", "dmon", "stack", "up", "dev"],
                    cwd=self.root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        else:
            result = self.run_cli("stack", "up", "-d", "dev")
            if result.returncode:
                # Preserve startup evidence in CI before tearDown removes it.
                logs = "\n".join(
                    f"{path.name}:\n{path.read_text(errors='replace')}"
                    for path in sorted((self.root / "logs").glob("*.log"))
                )
                self.fail(result.stderr + "\n" + logs)
        meta = self.wait_state("running")
        self.identities.extend((m["pid"], m["create_time"]) for m in meta["tasks"])
        return meta

    def wait_state(self, state):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                m = json.loads(self.stack_path.read_text())
                if m["state"] == state:
                    return m
            except (OSError, ValueError):
                pass
            time.sleep(0.03)
        self.fail(f"No stack state {state}")

    def kill_worker(self):
        m = json.loads(self.stack_path.read_text())["tasks"][1]
        p = psutil.Process(m["pid"])
        self.assertEqual(p.create_time(), m["create_time"])
        p.terminate()
        self.wait_state("degraded")

    def repair(self, *extra):
        return self.run_cli(
            "stack", "repair", "dev", "worker", "--format", "json", *extra
        )

    def tearDown(self):
        if self.stack_path.exists():
            self.run_cli("stack", "down", "dev")
        self.run_cli("stop", "worker", "api")
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for pid, birth in self.identities:
            if check_running(pid, birth):
                p = psutil.Process(pid)
                p.terminate()
                try:
                    p.wait(timeout=5)
                except psutil.TimeoutExpired:
                    p.kill()
        self.temp.cleanup()

    def test_repair_preserves_api_updates_membership_and_down(self):
        for foreground in (False, True):
            with self.subTest(foreground=foreground):
                original = self.start(foreground)
                self.kill_worker()
                # Both config and dotenv edits must not silently change the launch definition.
                (self.root / ".env").write_text("REPAIR_VALUE=changed-secret\n")
                (self.root / "dmon.yaml").write_text("invalid: [")
                result = self.repair()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                repaired = self.wait_state("running")
                self.assertEqual(repaired["tasks"][0], original["tasks"][0])
                self.assertTrue(
                    check_running(
                        original["tasks"][0]["pid"], original["tasks"][0]["create_time"]
                    )
                )
                new = repaired["tasks"][1]
                self.identities.append((new["pid"], new["create_time"]))
                self.assertNotEqual(new["pid"], original["tasks"][1]["pid"])
                self.assertEqual(
                    (self.root / "worker-env").read_text(), "original-secret"
                )
                for p in (self.root / ".dmon").rglob("*.json"):
                    self.assertNotIn("original-secret", p.read_text())
                op = json.loads(result.stdout)["operation_id"]
                self.assertEqual(self.repair("--operation-id", op).returncode, 0)
                self.assertEqual(
                    json.loads(self.stack_path.read_text())["tasks"][1]["pid"],
                    new["pid"],
                )
                down = self.run_cli("stack", "down", "dev")
                self.assertEqual(down.returncode, 0, down.stderr)
                self.assertFalse(check_running(new["pid"], new["create_time"]))
                self.write_config()

    def test_readiness_failure_rolls_back_only_replacement(self):
        (self.root / "ready").touch()
        self.write_config(
            {
                "command": [
                    sys.executable,
                    "-c",
                    "import pathlib,sys;sys.exit(0 if pathlib.Path('ready').exists() else 1)",
                ],
                "timeout": 0.5,
                "interval": 0.05,
            }
        )
        original = self.start()
        self.kill_worker()
        (self.root / "ready").unlink()
        result = self.repair()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        meta = self.wait_state("degraded")
        self.assertTrue(
            check_running(
                original["tasks"][0]["pid"], original["tasks"][0]["create_time"]
            )
        )
        new = meta["tasks"][1]
        self.assertFalse(check_running(new["pid"], new["create_time"]))
        (self.root / "ready").touch()
        retry = self.repair()
        self.assertEqual(retry.returncode, 0, retry.stdout)

    def test_standalone_replacement_is_refused(self):
        self.start()
        self.kill_worker()
        self.assertEqual(self.run_cli("start", "worker").returncode, 0)
        m = json.loads((self.root / ".dmon/worker.meta.json").read_text())
        result = self.repair()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another instance", result.stdout)
        self.assertTrue(check_running(m["pid"], m["create_time"]))

    def test_running_member_is_not_restarted(self):
        old = self.start()
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("no replacement", result.stdout)
        self.assertEqual(json.loads(self.stack_path.read_text())["tasks"], old["tasks"])

    def test_timeout_can_recheck_and_concurrent_requests_do_not_duplicate(self):
        self.start()
        self.kill_worker()
        op = uuid.uuid4().hex
        result = self.repair("--timeout", ".001", "--operation-id", op)
        self.assertEqual(json.loads(result.stdout)["state"], "unconfirmed")
        result = self.repair("--operation-id", op)
        self.assertEqual(result.returncode, 0, result.stdout)
        repaired = self.wait_state("running")
        again = self.repair()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(
            json.loads(self.stack_path.read_text())["tasks"], repaired["tasks"]
        )

    def test_concurrent_clients_with_same_operation_execute_once(self):
        self.start()
        self.kill_worker()
        op = uuid.uuid4().hex
        args = [
            sys.executable,
            "-m",
            "dmon",
            "stack",
            "repair",
            "dev",
            "worker",
            "--operation-id",
            op,
            "--format",
            "json",
            "-c",
            str(self.root),
        ]
        clients = [
            subprocess.Popen(
                args,
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        try:
            answers = [p.communicate(timeout=20) for p in clients]
            for p, (out, err) in zip(clients, answers):
                self.assertEqual(p.returncode, 0, out + err)
            self.assertEqual(answers[0][0], answers[1][0])
            repaired = self.wait_state("running")
            self.assertEqual(
                len(list(support_path(self.stack_path).parent.glob("*-*.json"))), 1
            )
            self.assertTrue(
                check_running(
                    repaired["tasks"][1]["pid"], repaired["tasks"][1]["create_time"]
                )
            )
        finally:
            for p in clients:
                if p.poll() is None:
                    p.kill()
                p.communicate()

    def test_old_supervisor_and_invalid_requests_are_refused(self):
        self.start()
        support = support_path(self.stack_path)
        support.unlink()
        result = self.repair()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not support repair", result.stdout)
        for args in (("--operation-id", "../invalid"), ("--timeout", "nan")):
            result = self.repair(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)

    def test_start_failure_does_not_stop_healthy_member(self):
        self.write_config()
        program = self.root / "worker.py"
        program.write_text("import time; time.sleep(120)")
        config = yaml.safe_load((self.root / "dmon.yaml").read_text())
        config["tasks"]["worker"]["cmd"] = [sys.executable, str(program)]
        (self.root / "dmon.yaml").write_text(yaml.safe_dump(config))
        original = self.start()
        self.kill_worker()
        program.unlink()
        result = self.repair()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            check_running(
                original["tasks"][0]["pid"], original["tasks"][0]["create_time"]
            )
        )

    def test_supervisor_crash_during_unconfirmed_spawn_preserves_evidence(self):
        meta = self.start()
        self.kill_worker()
        # Simulate the persisted crash boundary, not a guessed delay during spawn.
        supervisor = psutil.Process(meta["pid"])
        supervisor.kill()
        deadline = time.monotonic() + 5
        while (
            check_running(meta["pid"], meta["create_time"])
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        op = uuid.uuid4().hex
        p = operation_path(self.stack_path, meta["run_id"], op)
        p.write_text(
            json.dumps(
                {
                    "run_id": meta["run_id"],
                    "operation_id": op,
                    "task": "worker",
                    "expected": [
                        meta["tasks"][1]["pid"],
                        meta["tasks"][1]["create_time"],
                    ],
                    "state": "starting",
                }
            )
        )
        down = self.run_cli("stack", "down", "dev")
        self.assertNotEqual(down.returncode, 0)
        self.assertIn("unconfirmed", down.stderr)
        self.assertTrue(self.stack_path.exists())
        self.assertTrue(p.exists())
        p.unlink()  # Test controller knows it did not actually spawn a process.

    def test_crashed_supervisor_after_recording_replacement_can_be_cleaned(self):
        (self.root / "ready").touch()
        self.write_config(
            {
                "command": [
                    sys.executable,
                    "-c",
                    "import pathlib,sys;sys.exit(0 if pathlib.Path('ready').exists() else 1)",
                ],
                "timeout": 10,
                "interval": 0.05,
            }
        )
        old = self.start()
        self.kill_worker()
        (self.root / "ready").unlink()
        op = uuid.uuid4().hex
        self.repair("--timeout", ".001", "--operation-id", op)
        waiting = self.wait_state("repairing")
        new = waiting["tasks"][1]
        self.identities.append((new["pid"], new["create_time"]))
        path = operation_path(self.stack_path, old["run_id"], op)
        deadline = time.monotonic() + 5
        while (
            json.loads(path.read_text())["state"] != "waiting"
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        self.assertEqual(json.loads(path.read_text())["state"], "waiting")
        psutil.Process(old["pid"]).kill()
        deadline = time.monotonic() + 5
        while (
            check_running(old["pid"], old["create_time"])
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        down = self.run_cli("stack", "down", "dev")
        self.assertEqual(down.returncode, 0, down.stderr)
        self.assertFalse(check_running(new["pid"], new["create_time"]))
        self.assertFalse(
            check_running(old["tasks"][0]["pid"], old["tasks"][0]["create_time"])
        )

    def test_graceful_down_preserves_unconfirmed_launch_record(self):
        meta = self.start()
        self.kill_worker()
        op = uuid.uuid4().hex
        path = operation_path(self.stack_path, meta["run_id"], op)
        path.write_text(
            json.dumps(
                {
                    "run_id": meta["run_id"],
                    "operation_id": op,
                    "task": "worker",
                    "expected": [
                        meta["tasks"][1]["pid"],
                        meta["tasks"][1]["create_time"],
                    ],
                    "state": "starting",
                }
            )
        )
        down = self.run_cli("stack", "down", "dev")
        self.assertNotEqual(down.returncode, 0)
        self.assertTrue(self.stack_path.exists())
        self.assertTrue(path.exists())
        self.assertIn("unconfirmed", down.stderr)
        path.unlink()  # Controller knows this synthetic journal did not spawn anything.

    def test_foreign_ready_endpoint_is_not_adopted(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                pass

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        program = self.root / "server.py"
        program.write_text(
            "import pathlib,time,http.server\n"
            "print('fixture imported', flush=True)\n"
            "if pathlib.Path('serve').exists():\n"
            f" server = http.server.HTTPServer(('127.0.0.1',{port}),http.server.SimpleHTTPRequestHandler)\n"
            " print('fixture listening', flush=True)\n"
            " server.serve_forever()\n"
            "else: time.sleep(120)\n"
        )
        (self.root / "serve").touch()
        config = yaml.safe_load((self.root / "dmon.yaml").read_text())
        config["tasks"]["worker"].update(
            cmd=[sys.executable, str(program)],
            ready={
                "http": f"http://127.0.0.1:{port}/",
                "require_owned": True,
                # This budget also covers the initial real server launch and
                # listener inspection, which can exceed 0.5s on Windows 3.8.
                # Keep the foreign-listener rejection assertions below intact.
                "timeout": 5,
                "interval": 0.05,
            },
        )
        (self.root / "dmon.yaml").write_text(yaml.safe_dump(config))
        old = self.start()
        self.kill_worker()
        (self.root / "serve").unlink()
        server = HTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.repair()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("listener-unverified", result.stdout)
            self.assertTrue(
                check_running(old["tasks"][0]["pid"], old["tasks"][0]["create_time"])
            )
            import urllib.request

            self.assertEqual(
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).status,
                200,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_corrupt_operation_does_not_stop_peers_or_fake_cleanup(self):
        meta = self.start()
        path = operation_path(self.stack_path, meta["run_id"], uuid.uuid4().hex)
        path.write_text("[]")
        time.sleep(0.7)
        self.assertTrue(check_running(meta["pid"], meta["create_time"]))
        result = self.repair()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(
            check_running(meta["tasks"][0]["pid"], meta["tasks"][0]["create_time"])
        )
        down = self.run_cli("stack", "down", "dev")
        self.assertNotEqual(down.returncode, 0)
        self.assertTrue(self.stack_path.exists())
        self.assertEqual(path.read_text(), "[]")
        path.unlink()

    def test_down_cancels_inflight_readiness(self):
        (self.root / "ready").touch()
        self.write_config(
            {
                "command": [
                    sys.executable,
                    "-c",
                    "import pathlib,sys;sys.exit(0 if pathlib.Path('ready').exists() else 1)",
                ],
                "timeout": 10,
                "interval": 0.05,
            }
        )
        old = self.start()
        self.kill_worker()
        (self.root / "ready").unlink()
        op = uuid.uuid4().hex
        self.repair("--timeout", ".001", "--operation-id", op)
        waiting = self.wait_state("repairing")
        new = waiting["tasks"][1]
        self.identities.append((new["pid"], new["create_time"]))
        down = self.run_cli("stack", "down", "dev")
        self.assertEqual(down.returncode, 0, down.stderr)
        self.assertFalse(check_running(new["pid"], new["create_time"]))
        self.assertFalse(
            check_running(old["tasks"][0]["pid"], old["tasks"][0]["create_time"])
        )


if __name__ == "__main__":
    unittest.main()
