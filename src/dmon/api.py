from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
import os
from pathlib import Path
from typing import Iterator, Optional, Sequence, Tuple, Union

from .config import fill_default_paths, get_task_config, load_config
from .constants import DEFAULT_META_DIR, STACK_META_SUFFIX
from .control import (
    diagnostic_output,
    restart,
    start_single_result,
    stop_single,
    task_snapshot,
)
from .results import (
    ActionResult,
    BatchResult,
    StackResult,
    TaskResult,
)
from .supervisor import stack_snapshot
from .types import DmonMeta, DmonStackMeta


class DmonError(Exception):
    """Base exception for invalid Python API requests."""


class DmonConfigError(DmonError):
    """Configuration could not be loaded or validated."""


class Dmon:
    def __init__(self, config: Optional[Union[str, os.PathLike]] = None) -> None:
        self.config = str(config) if config is not None else None

    def start(self, *tasks: str) -> BatchResult:
        names, configs, _ = self._tasks(tasks)
        results = []
        with self._operation():
            for name, config in zip(names, configs):
                result = start_single_result(config)
                snapshot = (
                    task_snapshot(result.meta) if result.meta is not None else None
                )
                results.append(
                    ActionResult(
                        action="start",
                        name=name,
                        ok=result.exit_code == 0,
                        exit_code=result.exit_code,
                        snapshot=snapshot,
                        error="" if result.exit_code == 0 else "task did not start",
                    )
                )
        return BatchResult("start", tuple(results))

    def stop(self, *tasks: str) -> BatchResult:
        names, configs, _ = self._tasks(tasks)
        results = []
        with self._operation():
            for name, config in zip(names, configs):
                exit_code = stop_single(config.meta_path)
                results.append(
                    ActionResult(
                        action="stop",
                        name=name,
                        ok=exit_code == 0,
                        exit_code=exit_code,
                        error="" if exit_code == 0 else "task did not stop",
                    )
                )
        return BatchResult("stop", tuple(results))

    def restart(self, *tasks: str) -> BatchResult:
        names, configs, _ = self._tasks(tasks)
        results = []
        with self._operation():
            for name, config in zip(names, configs):
                exit_code = restart([config])
                meta = self._load_task_meta(Path(config.meta_path))
                snapshot = task_snapshot(meta) if meta is not None else None
                results.append(
                    ActionResult(
                        action="restart",
                        name=name,
                        ok=exit_code == 0,
                        exit_code=exit_code,
                        snapshot=snapshot,
                        error="" if exit_code == 0 else "task did not restart",
                    )
                )
        return BatchResult("restart", tuple(results))

    def status(self, task: Optional[str] = None) -> TaskResult:
        names, configs, _ = self._tasks(() if task is None else (task,))
        if len(names) != 1:
            raise DmonConfigError("status requires exactly one task")
        with self._operation():
            return self._task_result(names[0], Path(configs[0].meta_path))

    def list_tasks(self) -> Tuple[TaskResult, ...]:
        project = self._project()
        results = []
        with self._operation():
            meta_dir = project / DEFAULT_META_DIR
            if meta_dir.is_dir():
                for path in sorted(meta_dir.glob("*.meta.json")):
                    results.append(
                        self._task_result(path.name[: -len(".meta.json")], path)
                    )
        return tuple(results)

    def stack_status(self, stack: str) -> StackResult:
        if not isinstance(stack, str) or not stack:
            raise DmonConfigError("stack name must not be empty")
        project = self._project()
        name = stack.lower()
        with self._operation():
            return self._stack_result(
                name, project / DEFAULT_META_DIR / f"{name}{STACK_META_SUFFIX}"
            )

    def list_stacks(self) -> Tuple[StackResult, ...]:
        project = self._project()
        results = []
        with self._operation():
            meta_dir = project / DEFAULT_META_DIR
            if meta_dir.is_dir():
                for path in sorted(meta_dir.glob(f"*{STACK_META_SUFFIX}")):
                    name = path.name[: -len(STACK_META_SUFFIX)]
                    results.append(self._stack_result(name, path))
        return tuple(results)

    def _tasks(self, tasks: Sequence[str]):
        if any(not isinstance(task, str) or not task for task in tasks):
            raise DmonConfigError("task names must be non-empty strings")
        try:
            names, configs, path = get_task_config(tasks, self.config)
            fill_default_paths(configs)
        except (OSError, ValueError, TypeError) as error:
            raise DmonConfigError(str(error)) from error
        project = path.parent.resolve()
        for config in configs:
            config.cwd = self._resolve_path(project, config.cwd or ".")
            config.meta_path = self._resolve_path(project, config.meta_path)
            config.log_path = self._resolve_path(project, config.log_path)
            config.rotate_log_path = self._resolve_path(project, config.rotate_log_path)
        return names, configs, project

    def _project(self) -> Path:
        try:
            _, path = load_config(self.config)
        except (OSError, ValueError, TypeError) as error:
            raise DmonConfigError(str(error)) from error
        return path.parent

    @contextmanager
    def _operation(self) -> Iterator[None]:
        with diagnostic_output(StringIO()):
            yield

    @staticmethod
    def _resolve_path(project: Path, value: str) -> str:
        path = Path(value)
        return str(path.resolve() if path.is_absolute() else (project / path).resolve())

    def _task_result(self, name: str, path: Path) -> TaskResult:
        try:
            meta = self._load_task_meta(path)
        except (OSError, ValueError, TypeError) as error:
            return TaskResult(name=name, error=str(error))
        if meta is None:
            return TaskResult(name=name, error="task metadata not found")
        snapshot = task_snapshot(meta)
        return TaskResult(
            name=name,
            snapshot=snapshot,
            error="" if snapshot.running else "task has exited",
        )

    def _stack_result(self, name: str, path: Path) -> StackResult:
        try:
            meta = DmonStackMeta.load(path)
        except (OSError, ValueError, TypeError) as error:
            return StackResult(name=name, error=str(error))
        if meta is None:
            return StackResult(name=name, error="stack metadata not found")
        snapshot = stack_snapshot(meta)
        return StackResult(
            name=name,
            snapshot=snapshot,
            error="" if snapshot.running else f"stack is {snapshot.status}",
        )

    @staticmethod
    def _load_task_meta(path: Path) -> Optional[DmonMeta]:
        return DmonMeta.load(path)
