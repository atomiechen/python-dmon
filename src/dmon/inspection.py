from __future__ import annotations

from pathlib import Path

from .control import task_snapshot
from .results import StackResult, TaskResult
from .supervisor import stack_snapshot
from .types import DmonMeta, DmonStackMeta


def inspect_task(name: str, path: Path, *, require_running: bool) -> TaskResult:
    try:
        meta = DmonMeta.load(path)
    except (OSError, ValueError, TypeError) as error:
        return TaskResult(name=name, error=str(error))
    if meta is None:
        return TaskResult(name=name, error="task metadata not found")
    snapshot = task_snapshot(meta)
    error = "task has exited" if require_running and not snapshot.running else ""
    return TaskResult(name=name, snapshot=snapshot, error=error)


def inspect_stack(name: str, path: Path, *, require_running: bool) -> StackResult:
    try:
        meta = DmonStackMeta.load(path)
    except (OSError, ValueError, TypeError) as error:
        return StackResult(name=name, error=str(error))
    if meta is None:
        return StackResult(name=name, error="stack metadata not found")
    snapshot = stack_snapshot(meta)
    error = (
        f"stack is {snapshot.status}"
        if require_running and not snapshot.running
        else ""
    )
    return StackResult(name=name, snapshot=snapshot, error=error)
