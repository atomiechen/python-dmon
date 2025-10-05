from os import PathLike
import sys
from typing import Dict, List, TypedDict, Union


if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired


if sys.version_info >= (3, 9):
    PathType = Union[str, PathLike[str]]
else:
    PathType = Union[str, PathLike]


CmdType = Union[str, List[str]]


class DmonCommandConfig(TypedDict):
    cmd: CmdType
    env: NotRequired[Dict[str, str]]
    log_path: NotRequired[str]


class DmonMeta(TypedDict):
    pid: int
    meta_path: str
    log_path: str
    cmd: CmdType
    popen_kwargs: Dict
    start_time: float
    start_time_human: str
