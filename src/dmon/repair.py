"""Run-scoped repair requests; the existing supervisor is the only executor."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
import uuid
from typing import Optional

from .control import check_running, refresh_descendants, start_single_result
from .types import DmonMeta, DmonStackMeta, dump_json, read_json, verify_saved_identity


def support_path(path: Path) -> Path:
    return path.with_name(path.name + ".repair") / "support.json"


def operation_path(path: Path, run_id: str, operation_id: str) -> Path:
    # Both components originate in records, so validate before constructing paths.
    for value in (run_id, operation_id):
        if not isinstance(value, str) or uuid.UUID(hex=value).hex != value:
            raise ValueError("Invalid repair operation or run ID")
    return support_path(path).parent / f"{run_id}-{operation_id}.json"


def operations(path: Path, run_id: str):
    operation_path(path, run_id, "0" * 32)
    return sorted(support_path(path).parent.glob(f"{run_id}-*.json"))


def read_operation(path: Path):
    record = read_json(path)
    required = {"run_id", "operation_id", "task", "expected", "state"}
    if not isinstance(record, dict) or not required.issubset(record):
        raise ValueError("Incomplete repair record; evidence preserved")
    if set(record) - (required | {"exit_code", "message"}):
        raise ValueError("Unknown repair record fields; evidence preserved")
    for key in ("run_id", "operation_id"):
        value = record[key]
        if not isinstance(value, str) or uuid.UUID(hex=value).hex != value:
            raise ValueError("Invalid repair record identity")
    if path.name != f"{record['run_id']}-{record['operation_id']}.json":
        raise ValueError("Repair record location mismatch")
    if not isinstance(record["task"], str) or not record["task"]:
        raise ValueError("Invalid repair task")
    expected = record["expected"]
    if not isinstance(expected, list) or len(expected) != 2:
        raise ValueError("Invalid expected member identity")
    verify_saved_identity({"pid": expected[0], "create_time": expected[1]})
    if record["state"] not in ("pending", "starting", "waiting", "done"):
        raise ValueError("Unknown repair state")
    if record["state"] == "done" and (
        type(record.get("exit_code")) is not int
        or record["exit_code"] not in (0, 1)
        or not isinstance(record.get("message"), str)
    ):
        raise ValueError("Invalid repair result")
    return record


def unresolved_start(path: Path, run_id: str) -> bool:
    if not support_path(path).exists():
        return False
    for record_path in operations(path, run_id):
        record = read_operation(record_path)
        if record.get("state") == "starting":
            return True
    return False


class RepairServer:
    def __init__(self, path: Path, owner: DmonStackMeta):
        self.path = path
        self.owner = owner
        support_path(path).parent.mkdir(parents=True, exist_ok=True)
        dump_json(support_path(path), {"run_id": owner.run_id, "version": 1})

    def poll(self, started, persist, stop_requested):
        from .supervisor import cleanup, same_process, wait_ready

        for path in operations(self.path, self.owner.run_id):
            request = None
            try:
                request = read_operation(path)
                if request.get("state") != "pending":
                    continue
                if request.get("run_id") != self.owner.run_id:
                    continue
                if stop_requested():
                    return
                if unresolved_start(self.path, self.owner.run_id):
                    raise ValueError(
                        "An earlier launch is unconfirmed; inspect its preserved evidence"
                    )
                index = next(
                    (
                        i
                        for i, (cfg, _) in enumerate(started)
                        if cfg.task == request.get("task")
                    ),
                    None,
                )
                if index is None:
                    raise ValueError("Task is not a member of this stack")
                config, old = started[index]
                if request.get("expected") != [old.pid, old.create_time]:
                    raise ValueError(
                        "Member identity changed; inspect the stack before retrying"
                    )
                current = DmonMeta.load(old.meta_path)
                if current is not None and not same_process(current, old):
                    raise ValueError(
                        "Task record belongs to another instance; no process was adopted"
                    )
                if check_running(old.pid, old.create_time):
                    self.finish(
                        path,
                        request,
                        0,
                        "Member is still running; no replacement was started (readiness not rechecked)",
                    )
                    continue
                # Dependencies must be usable; do not silently restart them.
                for dependency in config.depends_on:
                    dep = next((m for c, m in started if c.task == dependency), None)
                    if dep is None or not check_running(dep.pid, dep.create_time):
                        raise ValueError(
                            f"Dependency {dependency!r} is not running; repair it first"
                        )
                refresh_descendants(old)
                persist("degraded", started)
                if cleanup([(config, old)]):
                    raise ValueError(
                        "Old member cleanup is incomplete; evidence was preserved"
                    )
                if stop_requested():
                    raise ValueError(
                        "Stack stop requested; replacement was not started"
                    )
                request["state"] = "starting"
                dump_json(path, request)
                result = start_single_result(config)
                if result.exit_code or result.meta is None:
                    self.finish(
                        path, request, 1, f"Replacement start failed: {result.error}"
                    )
                    continue
                new = result.meta
                verify_saved_identity({"pid": new.pid, "create_time": new.create_time})
                # Retain ownership before readiness, including on cancellation.
                started[index] = (config, new)
                try:
                    persist("repairing", started)
                    request["state"] = "waiting"
                    dump_json(path, request)
                    failures = []

                    def observe():
                        for _, member in started:
                            refresh_descendants(member)
                        persist("repairing", started)

                    ready = wait_ready(
                        config,
                        new,
                        stop_requested=stop_requested,
                        observed=observe,
                        failure_callback=failures.append,
                    )
                    if not ready or stop_requested():
                        raise ValueError(
                            failures[-1]
                            if failures
                            else "Repair cancelled by stack stop"
                        )
                except (OSError, ValueError, RuntimeError) as error:
                    # Only this repair's replacement is rolled back, never healthy peers.
                    code = cleanup([(config, new)])
                    persist("degraded", started)
                    self.finish(
                        path,
                        request,
                        1,
                        str(error)
                        + ("; replacement cleanup incomplete" if code else ""),
                    )
                    continue
                state = (
                    "running"
                    if all(check_running(m.pid, m.create_time) for _, m in started)
                    else "degraded"
                )
                persist(state, started)
                self.finish(
                    path, request, 0, "Member repaired; stack owns the replacement"
                )
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                # Bad request files and normal repair failures must not tear down peers.
                print(f"Repair request {path.name}: {error}", file=sys.stderr)
                try:
                    if isinstance(request, dict) and request.get("state") != "starting":
                        self.finish(path, request, 1, str(error))
                except OSError:
                    pass  # Preserve the existing journal for inspection.

    @staticmethod
    def finish(path, request, code, message):
        request.update(state="done", exit_code=code, message=message)
        dump_json(path, request)


def request_repair(
    meta_path: Path,
    task: str,
    timeout: float = 30,
    operation_id: Optional[str] = None,
    json_output: bool = False,
) -> int:
    from .supervisor import stack_process, stack_stop_path, stack_stop_requested

    meta_path = meta_path.absolute().resolve()
    operation_id = operation_id or uuid.uuid4().hex

    def emit(code, message, state="failed"):
        data = {
            "operation_id": operation_id,
            "task": task,
            "state": state,
            "exit_code": code,
            "message": message,
        }
        if json_output:
            print(json.dumps(data))
        else:
            print(f"Repair {operation_id}: {message}", file=sys.stderr)
        return code

    try:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Repair timeout must be finite and positive")
        meta = DmonStackMeta.load(meta_path)
        if meta is None:
            raise ValueError("Stack metadata not found")
        path = operation_path(meta_path, meta.run_id, operation_id)
        if path.exists():
            request = read_operation(path)
            if request.get("task") != task or request.get("run_id") != meta.run_id:
                raise ValueError("Operation ID belongs to another repair")
        else:
            if meta.abort_on_exit:
                raise ValueError("Repair is unavailable for abort-on-exit stacks")
            if stack_process(meta) is None or meta.state not in (
                "running",
                "degraded",
                "repairing",
            ):
                raise ValueError("Repair requires a live, running supervisor")
            if not support_path(meta_path).exists():
                raise ValueError("This supervisor does not support repair")
            support = read_json(support_path(meta_path))
            if support != {"run_id": meta.run_id, "version": 1}:
                raise ValueError("This supervisor does not support repair")
            if stack_stop_requested(stack_stop_path(meta_path), meta.run_id):
                raise ValueError("Stack is stopping")
            member = next((m for m in meta.tasks if m.task == task), None)
            if member is None:
                raise ValueError("Task is not a member of this stack")
            request = {
                "run_id": meta.run_id,
                "operation_id": operation_id,
                "task": task,
                "expected": [member.pid, member.create_time],
                "state": "pending",
            }
            try:
                dump_json(path, request, exclusive=True)
            except FileExistsError:
                request = read_operation(path)
                if request.get("task") != task or request.get("run_id") != meta.run_id:
                    raise ValueError("Operation ID belongs to another repair")
        deadline = time.monotonic() + timeout
        while True:
            request = read_operation(path)
            if request.get("state") == "done":
                return emit(request["exit_code"], request["message"], "done")
            if stack_process(meta) is None or time.monotonic() >= deadline:
                return emit(
                    1,
                    "Outcome unconfirmed; inspect status and retry with the same --operation-id. This does not cancel the operation.",
                    "unconfirmed",
                )
            time.sleep(0.05)
    except KeyboardInterrupt:
        return emit(
            1,
            "Interrupted while waiting; operation may still run. Recheck with the same --operation-id.",
            "unconfirmed",
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        return emit(1, str(error))
