from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union


CommandSnapshot = Union[str, Tuple[str, ...]]


@dataclass(frozen=True)
class TaskSnapshot:
    task: str
    pid: int
    status: str
    command: CommandSnapshot
    working_directory: str
    create_time: float
    create_time_human: str
    meta_path: str
    log_rotate: bool
    log_path: str
    rotate_log_path: str
    log_max_size: float
    log_backup_count: Optional[int]
    rotate_log_max_size: float
    rotate_log_backup_count: Optional[int]

    @property
    def running(self) -> bool:
        return self.status == "running"


@dataclass(frozen=True)
class StackSnapshot:
    stack: str
    status: str
    mode: str
    supervisor_pid: int
    supervisor_create_time: float
    state: str
    running_tasks: int
    total_tasks: int
    abort_on_exit: bool
    config_path: str
    log_path: str
    error: str
    tasks: Tuple[TaskSnapshot, ...]

    @property
    def exit_policy(self) -> str:
        return "abort-on-exit" if self.abort_on_exit else "keep-running"

    @property
    def running(self) -> bool:
        return self.status == "running"
