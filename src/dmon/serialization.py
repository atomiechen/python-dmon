from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from .results import StackResult, TaskResult


def task_result_data(result: TaskResult) -> Dict[str, Any]:
    return {
        "name": result.name,
        "ok": result.ok,
        "error": result.error or None,
        "snapshot": asdict(result.snapshot) if result.snapshot is not None else None,
    }


def stack_result_data(result: StackResult) -> Dict[str, Any]:
    return {
        "name": result.name,
        "ok": result.ok,
        "error": result.error or None,
        "snapshot": asdict(result.snapshot) if result.snapshot is not None else None,
    }
