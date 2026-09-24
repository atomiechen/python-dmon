"""Demonstrate partial recovery in a new disposable project; no model required."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import socket
from socketserver import TCPServer
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

import psutil


def serve(port: int) -> None:
    instance = uuid.uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"instance": instance}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    class Server(TCPServer):
        allow_reuse_address = True

    # TCPServer avoids reverse DNS during this loopback-only fixture's startup.
    with Server(("127.0.0.1", port), Handler) as server:
        server.serve_forever()


def alive(identity):
    try:
        process = psutil.Process(identity["pid"])
        return (
            process.create_time() == identity["create_time"]
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return False


def demo() -> None:
    # Keep logs and evidence for review, including on failure.
    root = Path(tempfile.mkdtemp(prefix="dmon-repair-demo-"))
    print(f"Disposable project: {root}", flush=True)
    ports = []
    with socket.socket() as api, socket.socket() as worker:
        for sock in (api, worker):
            sock.bind(("127.0.0.1", 0))
            ports.append(sock.getsockname()[1])
    tasks = {
        name: {
            "cmd": [sys.executable, str(Path(__file__).resolve()), "serve", str(port)],
            "ready": {
                "http": f"http://127.0.0.1:{port}",
                "require_owned": True,
                "timeout": 15,
            },
        }
        for name, port in zip(("api", "worker"), ports)
    }
    (root / "dmon.yaml").write_text(
        json.dumps({"tasks": tasks, "stacks": {"demo": ["api", "worker"]}}),
        encoding="utf-8",
    )
    state_path = root / ".dmon/demo.stack.json"

    def state():
        return json.loads(state_path.read_text(encoding="utf-8"))

    def cli(*args, check=True):
        print("$ dmon " + " ".join(args), flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "dmon", *args, "--config", str(root)],
            capture_output=True,
            text=True,
            timeout=40,
        )
        with (root / "transcript.log").open("a", encoding="utf-8") as log:
            log.write(f"$ dmon {' '.join(args)}\n{result.stdout}{result.stderr}\n")
        if check and result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result

    def response(port):
        with urlopen(f"http://127.0.0.1:{port}", timeout=2) as answer:
            return json.load(answer)

    tracked = []
    evidence = {"checks": {}, "project": str(root)}
    try:
        cli("stack", "up", "-d", "demo")
        before = state()
        tracked.extend([before, *before["tasks"]])
        api_before = response(ports[0])
        old_worker = next(t for t in before["tasks"] if t["task"] == "worker")
        assert alive(old_worker)
        process = psutil.Process(old_worker["pid"])
        assert process.create_time() == old_worker["create_time"]
        process.terminate()
        deadline = time.monotonic() + 10
        while state()["state"] != "degraded":
            if time.monotonic() > deadline:
                raise RuntimeError("Stack did not report the injected worker exit")
            time.sleep(0.05)
        print("Worker exited; API remains running.", flush=True)
        cli("stack", "status", "demo", "--format", "json", check=False)
        cli("stack", "repair", "demo", "worker", "--format", "json")
        after = state()
        tracked.extend(after["tasks"])
        api_after = next(t for t in after["tasks"] if t["task"] == "api")
        original_api = next(t for t in before["tasks"] if t["task"] == "api")
        worker_after = next(t for t in after["tasks"] if t["task"] == "worker")
        checks = evidence["checks"]
        checks["api_identity_preserved"] = all(
            api_after[k] == original_api[k] for k in ("pid", "create_time")
        ) and alive(original_api)
        checks["api_memory_preserved"] = response(ports[0]) == api_before
        checks["replacement_owned"] = (
            after["run_id"] == before["run_id"]
            and worker_after != old_worker
            and alive(worker_after)
        )
        checks["worker_responds"] = bool(response(ports[1])["instance"])
        evidence.update(before=before, after=after, api_memory=api_before)
        assert all(checks.values()), checks
        print("PASS: same API identity and memory; replacement belongs to stack.")
    finally:
        # Include any identity persisted during an interrupted startup or repair.
        if state_path.exists():
            remaining = state()
            tracked.extend([remaining, *remaining["tasks"]])
        down = cli("stack", "down", "demo", check=False)
        survivors = [i for i in tracked if alive(i)]
        evidence["checks"]["cleanup"] = down.returncode == 0 and not survivors
        evidence["survivors"] = survivors
        (root / "result.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        if down.returncode or survivors:
            raise RuntimeError(f"Cleanup incomplete; retain evidence at {root}")
    print(
        f"PASS: one stack down cleaned all tracked identities. Evidence: {root / 'result.json'}"
    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "serve":
        serve(int(sys.argv[2]))
    elif len(sys.argv) == 1:
        demo()
    else:
        raise SystemExit("Usage: python scripts/demo_repair.py")
