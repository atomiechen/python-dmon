from __future__ import annotations

from dataclasses import dataclass
import socket
import subprocess
import time
from typing import Callable, Mapping, Optional
from urllib.request import urlopen

from .results import CommandSnapshot, WaitResult


Check = Callable[[], bool]


@dataclass(frozen=True)
class ReadySpec:
    kind: str
    timeout: float
    interval: float
    http_url: str = ""
    tcp_host: str = ""
    tcp_port: int = 0
    command: CommandSnapshot = ""


def ready_spec(
    ready: Mapping[str, object],
    *,
    timeout: Optional[float] = None,
    interval: Optional[float] = None,
) -> ReadySpec:
    resolved_timeout = float(
        timeout if timeout is not None else ready.get("timeout", 30.0)
    )
    resolved_interval = float(
        interval if interval is not None else ready.get("interval", 0.2)
    )
    if "http" in ready:
        return ReadySpec(
            "http",
            resolved_timeout,
            resolved_interval,
            http_url=str(ready["http"]),
        )
    if "tcp" in ready:
        tcp = ready["tcp"]
        assert isinstance(tcp, dict)
        return ReadySpec(
            "tcp",
            resolved_timeout,
            resolved_interval,
            tcp_host=str(tcp["host"]),
            tcp_port=int(tcp["port"]),
        )
    command = ready.get("command", "")
    if isinstance(command, list):
        command = tuple(command)
    return ReadySpec(
        "command",
        resolved_timeout,
        resolved_interval,
        command=command,
    )


def process_stabilization_spec() -> ReadySpec:
    return ReadySpec("process", timeout=0.2, interval=0.05)


def wait_for_readiness(
    target: str,
    spec: ReadySpec,
    *,
    cwd: str,
    env: Optional[Mapping[str, str]],
    process_running: Optional[Check] = None,
    stop_requested: Optional[Check] = None,
) -> WaitResult:
    started = time.monotonic()
    deadline = started + spec.timeout
    attempts = 0
    while True:
        if stop_requested is not None and stop_requested():
            return WaitResult(
                target, False, "stopped", time.monotonic() - started, attempts
            )
        if process_running is not None and not process_running():
            return WaitResult(
                target,
                False,
                "process-exited",
                time.monotonic() - started,
                attempts,
            )
        remaining = max(0.0, deadline - time.monotonic())
        if remaining == 0:
            ready = spec.kind == "process"
            return WaitResult(
                target,
                ready,
                "ready" if ready else "timeout",
                time.monotonic() - started,
                attempts,
            )
        if spec.kind != "process":
            attempts += 1
            attempt_timeout = min(max(1.0, spec.interval), remaining)
            if probe(spec, cwd=cwd, env=env, timeout=attempt_timeout):
                return WaitResult(
                    target, True, "ready", time.monotonic() - started, attempts
                )
        time.sleep(min(spec.interval, max(0.0, deadline - time.monotonic())))


def probe(
    spec: ReadySpec,
    *,
    cwd: str,
    env: Optional[Mapping[str, str]],
    timeout: float,
) -> bool:
    try:
        if spec.kind == "http":
            with urlopen(spec.http_url, timeout=max(0.01, timeout)) as response:
                return 200 <= response.status < 400
        if spec.kind == "tcp":
            with socket.create_connection(
                (spec.tcp_host, spec.tcp_port), timeout=max(0.01, timeout)
            ):
                return True
        if spec.kind == "command":
            command = spec.command
            prepared = list(command) if isinstance(command, tuple) else command
            result = subprocess.run(
                prepared,
                cwd=cwd,
                env=env,
                shell=isinstance(command, str),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(0.01, timeout),
                check=False,
            )
            return result.returncode == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return False
