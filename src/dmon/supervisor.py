from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence, Tuple
from urllib.request import urlopen
import uuid

import psutil
from termcolor import colored

from .control import (
    background_process_kwargs,
    check_running,
    ensure_log_dir,
    ensure_meta_dir,
    get_unique_process,
    start_single_result,
    task_environment,
    terminate_process,
)
from .types import (
    CmdType,
    DmonMeta,
    DmonStackMeta,
    DmonStackTask,
    DmonTaskConfig,
)


StackStateCallback = Callable[[str, Sequence[Tuple[DmonTaskConfig, DmonMeta]]], None]
StopCheck = Callable[[], bool]


def task_label(task: str) -> str:
    return colored(f"'{task}'", color="cyan", attrs=["bold"])


def task_message(task: str, message: str, color: str) -> str:
    return (
        colored("Task ", color=color, attrs=["bold"])
        + task_label(task)
        + colored(message, color=color, attrs=["bold"])
    )


def stack_label(stack: str) -> str:
    return colored(f"'{stack}'", color="cyan", attrs=["bold"])


def stack_table_value(stack: str) -> str:
    return colored(stack, color="cyan", attrs=["bold"])


def stack_message(stack: str, message: str, color: str) -> str:
    return (
        colored("Stack ", color=color, attrs=["bold"])
        + stack_label(stack)
        + colored(message, color=color, attrs=["bold"])
    )


def up(
    configs: Sequence[DmonTaskConfig],
    poll_interval: float = 0.2,
    state_callback: Optional[StackStateCallback] = None,
    stop_requested: Optional[StopCheck] = None,
) -> int:
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
            notify_state(state_callback, "starting", started)
            if not wait_ready(config, meta, stop_requested=stop_requested):
                print_startup_failure(config.task)
                break
        else:
            notify_state(state_callback, "running", started)
            print(
                colored("Stack is ready (", color="green", attrs=["bold"])
                + ", ".join(task_label(config.task) for config in configs)
                + colored(").", color="green", attrs=["bold"]),
                file=sys.stderr,
            )
            exit_code = monitor(started, poll_interval, stop_requested=stop_requested)
    except KeyboardInterrupt:
        print(
            colored("\nStopping stack...", color="yellow", attrs=["bold"]),
            file=sys.stderr,
        )
        exit_code = 0
    finally:
        previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            try:
                notify_state(state_callback, "stopping", started)
            finally:
                cleanup_code = cleanup(started)
            notify_state(state_callback, "stopped", started)
        finally:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
    if cleanup_code:
        return 1
    return exit_code


def notify_state(
    callback: Optional[StackStateCallback],
    state: str,
    started: Sequence[tuple[DmonTaskConfig, DmonMeta]],
) -> None:
    if callback is not None:
        callback(state, started)


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
    started: Sequence[tuple[DmonTaskConfig, DmonMeta]],
    poll_interval: float,
    stop_requested: Optional[StopCheck] = None,
) -> int:
    while True:
        if stop_requested is not None and stop_requested():
            print("Stopping stack by request...", file=sys.stderr)
            return 0
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


def wait_ready(
    config: DmonTaskConfig,
    meta: DmonMeta,
    stop_requested: Optional[StopCheck] = None,
) -> bool:
    ready = config.ready
    timeout = float(ready.get("timeout", 30.0)) if ready else 0.2
    interval = float(ready.get("interval", 0.2)) if ready else 0.05
    deadline = time.monotonic() + timeout
    while True:
        if stop_requested is not None and stop_requested():
            return False
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


def stack_stop_path(meta_path: Path) -> Path:
    return meta_path.with_name(f"{meta_path.name}.stop")


def stack_process(meta: DmonStackMeta) -> Optional[psutil.Process]:
    return get_unique_process(meta.pid, meta.create_time)


def same_stack_process(first: DmonStackMeta, second: DmonStackMeta) -> bool:
    return (
        first.pid == second.pid and abs(first.create_time - second.create_time) < 1e-3
    )


def stack_tasks_running(meta: DmonStackMeta) -> bool:
    return any(
        check_running(task.pid, task.create_time) for task in meta.tasks if task.pid > 0
    )


def start_detached_stack(
    stack: str,
    configs: Sequence[DmonTaskConfig],
    config_path: Path,
    meta_path: Path,
    log_path: Path,
    poll_interval: float = 0.05,
) -> int:
    meta_path = meta_path.resolve()
    log_path = log_path.resolve()
    stop_path = stack_stop_path(meta_path)
    try:
        existing = DmonStackMeta.load(meta_path)
    except (OSError, ValueError, TypeError) as error:
        print(f"Detached stack metadata cannot be read: {error}", file=sys.stderr)
        return 1
    if existing is not None:
        if stack_process(existing) is not None or stack_tasks_running(existing):
            print(
                stack_message(stack, " is already active; run 'dmon down'.", "red"),
                file=sys.stderr,
            )
        else:
            print(
                stack_message(
                    stack,
                    " has stale metadata; run 'dmon down' before starting it again.",
                    "red",
                ),
                file=sys.stderr,
            )
        return 1
    ensure_meta_dir(meta_path)
    ensure_log_dir(log_path)
    meta = DmonStackMeta(
        stack=stack,
        run_id=uuid.uuid4().hex,
        state="reserved",
        pid=os.getpid(),
        create_time=psutil.Process(os.getpid()).create_time(),
        config_path=str(config_path.resolve()),
        log_path=str(log_path),
    )
    try:
        meta.dump(meta_path, exclusive=True)
    except FileExistsError:
        print(
            colored(
                f"Detached stack '{stack}' is being started by another dmon process.",
                color="red",
                attrs=["bold"],
            ),
            file=sys.stderr,
        )
        return 1

    try:
        with log_path.open("ab", buffering=0) as log:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dmon.stack_runner",
                    str(meta_path),
                    meta.run_id,
                ],
                cwd=config_path.resolve().parent,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **background_process_kwargs(),
            )
    except OSError as error:
        meta_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)
        print(f"Detached stack '{stack}' failed to start: {error}", file=sys.stderr)
        return 1

    startup_timeout = 10.0 + sum(
        float(config.ready.get("timeout", 30.0)) if config.ready else 0.2
        for config in configs
    )
    deadline = time.monotonic() + startup_timeout
    previous_int = signal.getsignal(signal.SIGINT)

    def interrupt_startup(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, interrupt_startup)
    claimed = False
    try:
        while time.monotonic() < deadline:
            try:
                current = DmonStackMeta.load(meta_path)
            except (OSError, ValueError, TypeError) as error:
                print(
                    f"Detached stack metadata cannot be read: {error}", file=sys.stderr
                )
                request_stack_stop(stop_path, meta.run_id)
                return 1
            if claimed and (current is None or current.run_id != meta.run_id):
                print(
                    f"Detached stack '{stack}' was stopped during startup.",
                    file=sys.stderr,
                )
                return 1
            if (
                current is not None
                and current.run_id == meta.run_id
                and current.state != "reserved"
            ):
                claimed = True
            if current is not None and current.state == "running":
                print_stack_status(current)
                return 0
            if current is not None and current.state == "failed":
                print_stack_status(current)
                return 1
            if (
                current is not None
                and current.run_id == meta.run_id
                and current.state != "reserved"
                and not check_running(current.pid, current.create_time)
            ):
                print(
                    f"Detached stack '{stack}' exited before becoming ready. "
                    f"See {log_path}.",
                    file=sys.stderr,
                )
                return 1
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("\nCancelling detached stack startup...", file=sys.stderr)
        request_stack_stop(stop_path, meta.run_id)
        stop_detached_stack(meta_path)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)

    print(
        f"Timed out waiting for detached stack '{stack}' to report readiness. "
        f"See {log_path}.",
        file=sys.stderr,
    )
    request_stack_stop(stop_path, meta.run_id)
    stop_detached_stack(meta_path)
    return 1


def request_stack_stop(stop_path: Path, run_id: str) -> None:
    stop_path.parent.mkdir(parents=True, exist_ok=True)
    stop_path.write_text(f"{run_id}\n", encoding="utf-8")


def stack_stop_requested(stop_path: Path, run_id: str) -> bool:
    try:
        return stop_path.read_text(encoding="utf-8").strip() == run_id
    except FileNotFoundError:
        return False


def run_detached_stack(meta_path: Path, run_id: str, poll_interval: float = 0.5) -> int:
    from .config import fill_default_paths, get_stack_config

    meta_path = meta_path.resolve()
    stop_path = stack_stop_path(meta_path)
    deadline = time.monotonic() + 5.0
    meta = None
    read_error: Optional[Exception] = None
    own_pid = os.getpid()
    own_create_time = psutil.Process(own_pid).create_time()
    while time.monotonic() < deadline:
        try:
            meta = DmonStackMeta.load(meta_path)
            read_error = None
        except (OSError, ValueError, TypeError) as error:
            read_error = error
            time.sleep(0.02)
            continue
        if meta is not None and meta.run_id == run_id:
            if meta.state == "reserved":
                meta.pid = own_pid
                meta.create_time = own_create_time
                meta.state = "starting"
                try:
                    meta.dump(meta_path)
                except OSError as error:
                    read_error = error
                    time.sleep(0.02)
                    continue
                break
            if meta.pid == own_pid and meta.state == "starting":
                break
        time.sleep(0.02)
    else:
        if read_error is not None:
            print(
                f"Detached supervisor could not read metadata {meta_path}: "
                f"{read_error}",
                file=sys.stderr,
                flush=True,
            )
        else:
            observed = (
                "missing"
                if meta is None
                else f"run_id={meta.run_id!r}, pid={meta.pid}, state={meta.state!r}"
            )
            print(
                "Detached supervisor could not claim metadata "
                f"{meta_path}; expected run_id={run_id!r}, state='reserved'; "
                f"observed {observed}.",
                file=sys.stderr,
                flush=True,
            )
        return 1
    assert meta is not None

    try:
        _, configs, config_path = get_stack_config(meta.stack, meta.config_path)
        fill_default_paths(configs)
        os.chdir(config_path.parent)

        def persist(
            state: str,
            started: Sequence[tuple[DmonTaskConfig, DmonMeta]],
        ) -> None:
            current = DmonStackMeta.load(meta_path)
            if (
                current is None
                or current.run_id != run_id
                or current.pid != os.getpid()
            ):
                raise RuntimeError("detached stack ownership metadata was lost")
            current.state = state
            current.tasks = [DmonStackTask.from_meta(task) for _, task in started]
            current.dump(meta_path)

        result = up(
            configs,
            poll_interval=poll_interval,
            state_callback=persist,
            stop_requested=lambda: stack_stop_requested(stop_path, meta.run_id),
        )
    except Exception as error:
        try:
            current = DmonStackMeta.load(meta_path)
            if (
                current is not None
                and current.run_id == run_id
                and current.pid == os.getpid()
            ):
                current.state = "failed"
                current.error = str(error)
                current.dump(meta_path)
        except (OSError, ValueError, TypeError):
            pass
        return 1

    try:
        current = DmonStackMeta.load(meta_path)
        if (
            current is not None
            and current.run_id == run_id
            and current.pid == os.getpid()
        ):
            if result == 0 and stop_path.exists():
                meta_path.unlink(missing_ok=True)
                stop_path.unlink(missing_ok=True)
            else:
                current.state = "failed"
                current.error = "stack supervision ended unexpectedly"
                current.dump(meta_path)
    except (OSError, ValueError, TypeError):
        return 1
    return result


def stop_detached_stack(meta_path: Path, poll_interval: float = 0.1) -> int:
    meta_path = meta_path.resolve()
    stop_path = stack_stop_path(meta_path)
    try:
        meta = DmonStackMeta.load(meta_path)
    except (OSError, ValueError, TypeError) as error:
        print(f"Detached stack metadata cannot be read: {error}", file=sys.stderr)
        return 1
    if meta is None:
        print(f"Detached stack metadata not found: {meta_path}", file=sys.stderr)
        return 1

    process = stack_process(meta)
    if process is not None:
        request_stack_stop(stop_path, meta.run_id)
        deadline = time.monotonic() + max(10.0, 6.0 * len(meta.tasks))
        while time.monotonic() < deadline:
            if not check_running(meta.pid, meta.create_time):
                break
            time.sleep(poll_interval)
        else:
            print(
                colored(
                    f"Detached stack supervisor {meta.pid} did not stop; terminating it.",
                    color="yellow",
                    attrs=["bold"],
                ),
                file=sys.stderr,
            )
            if terminate_process(process, timeout=2.0) and stack_process(meta):
                print(
                    f"Detached stack supervisor {meta.pid} could not be stopped; "
                    "metadata was preserved.",
                    file=sys.stderr,
                )
                return 1

    try:
        current = DmonStackMeta.load(meta_path)
        if current is not None and (
            same_stack_process(current, meta)
            or (meta.state == "reserved" and current.run_id == meta.run_id)
        ):
            meta = current
    except (OSError, ValueError, TypeError) as error:
        print(f"Detached stack metadata cannot be read: {error}", file=sys.stderr)
        return 1

    cleanup_code = cleanup_stack_tasks(meta.tasks)
    if cleanup_code:
        print(
            f"Detached stack '{meta.stack}' cleanup is incomplete; metadata was preserved.",
            file=sys.stderr,
        )
        return 1
    meta_path.unlink(missing_ok=True)
    stop_path.unlink(missing_ok=True)
    print(
        colored(
            f"Detached stack '{meta.stack}' stopped.",
            color="green",
            attrs=["bold"],
        ),
        file=sys.stderr,
    )
    return 0


def cleanup_stack_tasks(tasks: Sequence[DmonStackTask]) -> int:
    started = [
        (
            DmonTaskConfig(task=task.task, meta_path=task.meta_path),
            DmonMeta(
                task=task.task,
                pid=task.pid,
                create_time=task.create_time,
                meta_path=task.meta_path,
            ),
        )
        for task in tasks
    ]
    return cleanup(started)


def status_detached_stack(meta_path: Path) -> int:
    try:
        meta = DmonStackMeta.load(meta_path.resolve())
    except (OSError, ValueError, TypeError) as error:
        print(f"Detached stack metadata cannot be read: {error}", file=sys.stderr)
        return 1
    if meta is None:
        print(
            f"Detached stack metadata not found: {meta_path.resolve()}", file=sys.stderr
        )
        return 1
    print_stack_status(meta)
    supervisor_running = stack_process(meta) is not None
    tasks_running = all(
        check_running(task.pid, task.create_time) for task in meta.tasks
    )
    return 0 if meta.state == "running" and supervisor_running and tasks_running else 1


def print_stack_status(meta: DmonStackMeta) -> None:
    supervisor_running = stack_process(meta) is not None
    running_tasks = sum(
        1 for task in meta.tasks if check_running(task.pid, task.create_time)
    )
    if meta.state == "failed":
        status = "Failed"
    elif not supervisor_running:
        status = "Orphaned" if running_tasks else "Exited"
    elif meta.state == "running":
        status = "Running" if running_tasks == len(meta.tasks) else "Degraded"
    else:
        status = meta.state.capitalize()
    status_color = {
        "Running": "green",
        "Starting": "yellow",
        "Stopping": "yellow",
        "Exited": "yellow",
    }.get(status, "red")
    print(f"STACK      : {stack_table_value(meta.stack)}", file=sys.stderr)
    print(
        "STATUS     : " + colored(status, color=status_color, attrs=["bold"]),
        file=sys.stderr,
    )
    print(
        f"SUPERVISOR : {colored(str(meta.pid), 'cyan', attrs=['bold'])}",
        file=sys.stderr,
    )
    print(f"TASKS      : {running_tasks}/{len(meta.tasks)} running", file=sys.stderr)
    print(f"CONFIG     : {meta.config_path}", file=sys.stderr)
    print(f"LOG        : {meta.log_path}", file=sys.stderr)
    if meta.error:
        print(f"ERROR      : {meta.error}", file=sys.stderr)
