from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
import math
import os
from pathlib import Path
from typing import Iterator, Optional, Sequence, Tuple, Union

from .config import fill_default_paths, get_task_config, load_config
from .constants import DEFAULT_META_DIR, STACK_META_SUFFIX
from .control import (
    check_running,
    diagnostic_output,
    restart,
    start_single_result,
    stop_single,
    task_snapshot,
    task_environment,
)
from .results import (
    ActionResult,
    BatchResult,
    StackResult,
    TaskResult,
    WaitResult,
)
from .inspection import inspect_stack, inspect_task
from .readiness import ready_spec, wait_for_readiness
from .types import DmonMeta


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
                        inspect_task(
                            path.name[: -len(".meta.json")],
                            path,
                            require_running=False,
                        )
                    )
        return tuple(results)

    def stack_status(self, stack: str) -> StackResult:
        if not isinstance(stack, str) or not stack:
            raise DmonConfigError("stack name must not be empty")
        project = self._project()
        name = stack.lower()
        with self._operation():
            return inspect_stack(
                name,
                project / DEFAULT_META_DIR / f"{name}{STACK_META_SUFFIX}",
                require_running=True,
            )

    def list_stacks(self) -> Tuple[StackResult, ...]:
        project = self._project()
        results = []
        with self._operation():
            meta_dir = project / DEFAULT_META_DIR
            if meta_dir.is_dir():
                for path in sorted(meta_dir.glob(f"*{STACK_META_SUFFIX}")):
                    name = path.name[: -len(STACK_META_SUFFIX)]
                    results.append(inspect_stack(name, path, require_running=False))
        return tuple(results)

    def wait(
        self,
        *tasks: str,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
    ) -> Tuple[WaitResult, ...]:
        for name, value in (("timeout", timeout), ("interval", interval)):
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise DmonConfigError(f"{name} must be finite and greater than zero")
        names, configs, _ = self._tasks(tasks)
        results = []
        with self._operation():
            for name, config in zip(names, configs):
                if not config.ready:
                    results.append(
                        WaitResult(
                            name,
                            False,
                            "invalid",
                            0.0,
                            0,
                            "task has no readiness probe",
                        )
                    )
                    continue
                try:
                    meta = DmonMeta.load(config.meta_path)
                except (OSError, ValueError, TypeError) as error:
                    results.append(
                        WaitResult(name, False, "metadata-error", 0.0, 0, str(error))
                    )
                    continue
                if meta is None:
                    results.append(
                        WaitResult(
                            name,
                            False,
                            "not-running",
                            0.0,
                            0,
                            "task metadata not found",
                        )
                    )
                    continue
                spec = ready_spec(config.ready, timeout=timeout, interval=interval)
                results.append(
                    wait_for_readiness(
                        name,
                        spec,
                        cwd=config.cwd,
                        env=task_environment(config),
                        process_running=lambda meta=meta: check_running(
                            meta.pid, meta.create_time
                        ),
                    )
                )
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
        return inspect_task(name, path, require_running=True)

    @staticmethod
    def _load_task_meta(path: Path) -> Optional[DmonMeta]:
        return DmonMeta.load(path)
