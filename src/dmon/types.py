from dataclasses import asdict, dataclass, field
import json
from os import PathLike
from pathlib import Path
import sys
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
    log_max_size: int = 5
    """Size in MB to rotate log file"""
    rotate_log_path: str = ""
    """Path to rotation log file"""
    rotate_log_max_size: int = 5
    """Size in MB to rotation log file"""
    meta_path: str = ""
    """Path to meta file"""


@dataclass
class DmonMeta(DmonTaskConfig):
    pid: int = -1
    shell: bool = False
    popen_kwargs: Dict = field(default_factory=dict)
    create_time: float = -1
    create_time_human: str = "N/A"

    def dump(self, path: PathType):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @staticmethod
    def load(path: PathType) -> Optional["DmonMeta"]:
        p = Path(path)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return DmonMeta(**data)
        return None
