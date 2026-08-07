from dataclasses import asdict, dataclass, field
import json
import os
from os import PathLike
from pathlib import Path
import sys
import tempfile
from typing import Dict, List, Optional, Union


if sys.version_info >= (3, 9):
    PathType = Union[str, PathLike[str]]
else:
    PathType = Union[str, PathLike]


CmdType = Union[str, List[str]]


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

    def dump(self, path: PathType, *, exclusive: bool = False):
        target = Path(path)
        data = asdict(self)
        if exclusive:
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
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
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def load(path: PathType) -> Optional["DmonMeta"]:
        p = Path(path)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return DmonMeta(**data)
        return None
