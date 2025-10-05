from os import PathLike
import sys
from typing import Dict, List, TypedDict, Union


if sys.version_info >= (3, 9):
    PathType = Union[str, PathLike[str]]
else:
    PathType = Union[str, PathLike]


CmdType = Union[str, List[str]]


class DmonCommandConfig(TypedDict):
    name: str
    cmd: CmdType
    env: Dict[str, str]
    meta_path: str
    log_path: str


class DmonMeta(DmonCommandConfig):
    pid: int
    popen_kwargs: Dict
    create_time: float
    create_time_human: str
