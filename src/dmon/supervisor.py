from __future__ import annotations

from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Sequence
from urllib.request import urlopen

from termcolor import colored

from .control import (
    check_running,
    get_unique_process,
    start_single_result,
    task_environment,
    terminate_process,
)
from .types import CmdType, DmonMeta, DmonTaskConfig


def task_label(task: str) -> str:
    return colored(f"'{task}'", color="cyan", attrs=["bold"])


def task_message(task: str, message: str, color: str) -> str:
    return (
        colored("Task ", color=color, attrs=["bold"])
        + task_label(task)
        + colored(message, color=color, attrs=["bold"])
    )


def up(configs: Sequence[DmonTaskConfig], poll_interval: float = 0.2) -> int:
    started: list[tuple[DmonTaskConfig, DmonMeta]] = []
    exit_code = 1

    def terminate(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, terminate)
    try:
        for config in configs:
            result = start_single_result(config)
            if result.exit_code:
                print_startup_failure(config.task)
                break
            meta = result.meta
            if meta is None:
                print_startup_failure(config.task)
                break
            started.append((config, meta))
            if not wait_ready(config, meta):
                print_startup_failure(config.task)
                break
        else:
            print(
                colored("Stack is ready (", color="green", attrs=["bold"])
                + ", ".join(task_label(config.task) for config in configs)
                + colored(").", color="green", attrs=["bold"]),
                file=sys.stderr,
            )
            exit_code = monitor(started, poll_interval)
    except KeyboardInterrupt:
        print(
            colored("\nStopping stack...", color="yellow", attrs=["bold"]),
            file=sys.stderr,
        )
        exit_code = 0
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        cleanup_code = cleanup(started)
    if cleanup_code:
        return 1
    return exit_code


def print_startup_failure(task: str) -> None:
    print(
        colored("Stack startup failed at task ", color="red", attrs=["bold"])
        + task_label(task)
        + colored(
            "; stopping tasks started by this run.",
            color="red",
            attrs=["bold"],
        ),
        file=sys.stderr,
    )


def monitor(
    started: Sequence[tuple[DmonTaskConfig, DmonMeta]], poll_interval: float
) -> int:
    while True:
        for config, meta in started:
            if not check_running(meta.pid, meta.create_time):
                print(
                    task_message(
                        config.task,
                        " exited; stopping the remaining stack.",
                        "red",
                    ),
                    file=sys.stderr,
                )
                return 1
        time.sleep(poll_interval)


def cleanup(started: Sequence[tuple[DmonTaskConfig, DmonMeta]]) -> int:
    failed = []
    for config, meta in reversed(started):
        process = get_unique_process(meta.pid, meta.create_time)
        if process is not None and terminate_process(process, timeout=5.0):
            failed.append(config.task)
            continue

        meta_path = Path(config.meta_path).resolve()
        try:
            current = DmonMeta.load(meta_path)
        except (OSError, ValueError, TypeError) as error:
            print(
                task_message(
                    config.task,
                    f" stopped, but its metadata could not be cleaned: {error}",
                    "red",
                ),
                file=sys.stderr,
            )
            failed.append(config.task)
            continue
        if current is not None and same_process(current, meta):
            meta_path.unlink(missing_ok=True)

    if failed:
        print(
            colored("Stack cleanup incomplete for: ", color="red", attrs=["bold"])
            + ", ".join(task_label(task) for task in failed)
            + colored(".", color="red", attrs=["bold"]),
            file=sys.stderr,
        )
        return 1
    return 0


def same_process(first: DmonMeta, second: DmonMeta) -> bool:
    return first.pid == second.pid and first.create_time == second.create_time


def wait_ready(config: DmonTaskConfig, meta: DmonMeta) -> bool:
    ready = config.ready
    timeout = float(ready.get("timeout", 30.0)) if ready else 0.2
    interval = float(ready.get("interval", 0.2)) if ready else 0.05
    deadline = time.monotonic() + timeout
    while True:
        if not check_running(meta.pid, meta.create_time):
            print(
                task_message(
                    config.task,
                    " exited before becoming ready.",
                    "red",
                ),
                file=sys.stderr,
            )
            return False
        remaining = max(0.0, deadline - time.monotonic())
        if remaining == 0:
            if not ready:
                return True
            print(
                task_message(
                    config.task,
                    f" did not become ready within {timeout:g} seconds.",
                    "red",
                ),
                file=sys.stderr,
            )
            return False
        probe_timeout = min(max(1.0, interval), remaining)
        if ready and readiness_probe(config, ready, probe_timeout):
            print(task_message(config.task, " is ready.", "green"), file=sys.stderr)
            return True
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def readiness_probe(
    config: DmonTaskConfig, ready: dict[str, object], timeout: float
) -> bool:
    try:
        if "http" in ready:
            with urlopen(str(ready["http"]), timeout=max(0.01, timeout)) as response:
                return 200 <= response.status < 400
        if "tcp" in ready:
            tcp = ready["tcp"]
            assert isinstance(tcp, dict)
            with socket.create_connection(
                (str(tcp["host"]), int(tcp["port"])),
                timeout=max(0.01, timeout),
            ):
                return True
        command = ready["command"]
        assert isinstance(command, (str, list))
        return run_probe_command(config, command, timeout) == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def run_probe_command(config: DmonTaskConfig, command: CmdType, timeout: float) -> int:
    if isinstance(command, str):
        prepared = command
        shell = True
    else:
        prepared = command
        shell = False
    result = subprocess.run(
        prepared,
        cwd=Path(config.cwd).resolve(),
        env=task_environment(config),
        shell=shell,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=max(0.01, timeout),
        check=False,
    )
    return result.returncode
