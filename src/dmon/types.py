from dataclasses import asdict, dataclass, field
import json
import math
import os
from os import PathLike
from pathlib import Path
import sys
import tempfile
import time
from typing import Dict, List, Optional, Union

from .constants import DEFAULT_META_DIR, STACK_META_SUFFIX


if sys.version_info >= (3, 9):
    PathType = Union[str, PathLike[str]]
else:
    PathType = Union[str, PathLike]


CmdType = Union[str, List[str]]


def verify_metadata_path(recorded: str, actual: PathType) -> None:
    """Reject accidentally copied records, without claiming a security boundary."""
    if not isinstance(recorded, str):
        raise TypeError("metadata location must be a string")
    if not recorded:
        return  # Legacy records may not contain location evidence.
    expected = Path(recorded)
    if not expected.is_absolute() or expected.resolve() != Path(actual).resolve():
        raise ValueError(
            f"metadata-location-mismatch: record belongs at {recorded}, "
            f"not {Path(actual).resolve()}; copied or moved metadata is not valid "
            "here. Manage this run from its original location; the record was preserved."
        )


def dump_json(path: PathType, data: Dict, *, exclusive: bool = False) -> None:
    target = Path(path)
    if exclusive:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary_path, target)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def replace_file(source: Path, target: Path, timeout: float = 0.5) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


@dataclass
class DmonTaskConfig:
    task: str = ""
    """Name of the task"""
    cmd: CmdType = ""
    """Command to run, either a string (for shell) or a list of strings (for exec)"""
    cwd: str = ""
    """Working directory to run the command in"""
    env: Dict[str, str] = field(default_factory=dict)
    """Environment variables to set for the command"""
    env_files: List[str] = field(default_factory=list)
    """Dotenv files to load before applying explicit environment values"""
    override_env: bool = False
    """Whether to override the entire environment with the provided env"""
    log_path: str = ""
    """Path to log file"""
    log_rotate: bool = False
    """Whether to rotate log file"""
    log_max_size: float = 5
    """Size in MB to rotate log file"""
    log_backup_count: Optional[int] = None
    """Number of task log archives to retain; None keeps all archives"""
    rotate_log_path: str = ""
    """Path to rotation log file"""
    rotate_log_max_size: float = 5
    """Size in MB to rotation log file"""
    rotate_log_backup_count: Optional[int] = None
    """Number of runner log archives to retain; None keeps all archives"""
    meta_path: str = ""
    """Path to meta file"""
    depends_on: List[str] = field(default_factory=list)
    """Tasks that must become ready before this task starts"""
    ready: Dict[str, object] = field(default_factory=dict)
    """Optional readiness probe configuration"""


@dataclass
class DmonMeta(DmonTaskConfig):
    pid: int = -1
    state: str = "running"
    shell: bool = False
    popen_kwargs: Dict = field(default_factory=dict)
    create_time: float = -1
    create_time_human: str = "N/A"
    descendants: List["ProcessIdentity"] = field(default_factory=list)

    def dump(self, path: PathType, *, exclusive: bool = False):
        data = asdict(self)
        # Configuration environment values are needed only while spawning the
        # process. Persisting them would turn routine process metadata into a
        # secret store.
        data.pop("env", None)
        data.pop("env_files", None)
        dump_json(path, data, exclusive=exclusive)

    @staticmethod
    def load(path: PathType) -> Optional["DmonMeta"]:
        p = Path(path)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise TypeError("task metadata must be a JSON object")
                verify_metadata_path(data.get("meta_path", ""), p)
                data["descendants"] = load_identities(data.get("descendants", []))
                verify_saved_identity(data, allow_reservation=True)
                return DmonMeta(**data)
        return None


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    create_time: float

    def __post_init__(self):
        if (
            not isinstance(self.pid, int)
            or isinstance(self.pid, bool)
            or self.pid <= 0
            or not isinstance(self.create_time, (int, float))
            or isinstance(self.create_time, bool)
            or not math.isfinite(self.create_time)
            or self.create_time < 0
        ):
            raise ValueError("invalid descendant process identity")


def load_identities(values) -> List[ProcessIdentity]:
    if not isinstance(values, list) or not all(
        isinstance(value, dict) for value in values
    ):
        raise TypeError("descendants must be a list of process identities")
    return [ProcessIdentity(**value) for value in values]


def verify_saved_identity(data: Dict, *, allow_reservation: bool = False) -> None:
    """Missing identity evidence is corruption, not evidence that a task exited."""
    if "pid" not in data or "create_time" not in data:
        raise ValueError(
            "metadata must contain both pid and create_time; record preserved"
        )
    pid, created = data["pid"], data["create_time"]
    if (
        allow_reservation
        and type(pid) is int
        and pid == -1
        and type(created) in (int, float)
        and created == -1
    ):
        return
    ProcessIdentity(pid, created)


@dataclass
class DmonStackTask:
    task: str
    pid: int
    create_time: float
    meta_path: str
    descendants: List[ProcessIdentity] = field(default_factory=list)
    new_session: bool = False

    @staticmethod
    def from_meta(meta: DmonMeta) -> "DmonStackTask":
        return DmonStackTask(
            task=meta.task,
            pid=meta.pid,
            create_time=meta.create_time,
            meta_path=meta.meta_path,
            descendants=list(meta.descendants),
            new_session=bool(meta.popen_kwargs.get("start_new_session")),
        )


@dataclass
class DmonStackMeta:
    stack: str
    run_id: str = ""
    mode: str = "detached"
    abort_on_exit: bool = False
    state: str = "starting"
    pid: int = -1
    create_time: float = -1
    config_path: str = ""
    meta_path: str = ""
    log_path: str = ""
    tasks: List[DmonStackTask] = field(default_factory=list)
    error: str = ""

    def dump(self, path: PathType, *, exclusive: bool = False) -> None:
        dump_json(path, asdict(self), exclusive=exclusive)

    @staticmethod
    def load(path: PathType) -> Optional["DmonStackMeta"]:
        target = Path(path)
        if not target.exists():
            return None
        with target.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise TypeError("stack metadata must be a JSON object")
        recorded = data.get("meta_path", "")
        if not recorded and data.get("config_path"):
            if not isinstance(data.get("stack"), str):
                raise TypeError("stack metadata must contain a stack name")
            # Published stacks used a fixed config-relative metadata location.
            recorded = str(
                Path(data["config_path"]).parent
                / DEFAULT_META_DIR
                / (data["stack"] + STACK_META_SUFFIX)
            )
        verify_metadata_path(recorded, target)
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list) or not all(
            isinstance(task, dict) for task in tasks
        ):
            raise TypeError("stack metadata tasks must be a list of objects")
        for task in tasks:
            verify_saved_identity(task)
            task["descendants"] = load_identities(task.get("descendants", []))
        # Empty legacy stack records carry no process ownership. Active records
        # must never fill a missing half of an identity with a default value.
        if tasks or "pid" in data or "create_time" in data:
            verify_saved_identity(data, allow_reservation=True)
        data["tasks"] = [DmonStackTask(**task) for task in tasks]
        return DmonStackMeta(**data)
