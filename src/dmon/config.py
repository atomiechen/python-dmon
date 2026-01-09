import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .types import CmdType, DmonTaskConfig


def search_config(start_dir: Path, recursive: bool) -> Optional[Path]:
    """
    Search for dmon.yaml, dmon.yml, or pyproject.toml from the given directory upwards.
    Return the path if found, None otherwise.
    """
    current = start_dir.resolve()
    directories = [current] if not recursive else [current, *current.parents]
    for parent in directories:
        for filename in ["dmon.yaml", "dmon.yml", "pyproject.toml"]:
            path = parent / filename
            if path.is_file():
                return path
    return None


def load_config(cfg_path: Optional[str] = None):
    """
    Load configuration from the given path, or search it from the current working directory upwards.
    """

    if cfg_path:
        # Load configuration from the given path
        path = Path(cfg_path).resolve()
        if not path.exists():
            raise FileNotFoundError(
                f"Config file or directory '{path}' does not exist."
            )
        elif path.is_dir():
            # If it's a directory, search for config files in it
            result = search_config(path, recursive=False)
            if not result:
                raise FileNotFoundError(
                    f"No dmon.yaml or pyproject.toml found in directory '{path}'."
                )
            path = result
    else:
        # No path provided, search from the current working directory upwards
        path = search_config(Path.cwd(), recursive=True)
        if not path:
            raise FileNotFoundError(
                "No dmon.yaml or pyproject.toml found in current or any parent directory."
            )

    if path.suffix in [".yaml", ".yml"]:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    elif path.suffix == ".toml":
        with path.open("rb") as f:
            cfg = tomllib.load(f)
        cfg = cfg.get("tool", {}).get("dmon", {})
    else:
        raise ValueError("Config file must be YAML (.yaml/.yml) or TOML (.toml)")
    return cfg, path


def validate_cmd_type(cmd, name: str) -> CmdType:
    if isinstance(cmd, str):
        return cmd
    elif isinstance(cmd, list):
        if not all(isinstance(item, str) for item in cmd):
            # check if it's a list of strings
            raise TypeError(f"Task '{name}' list items must be strings")
        return cmd
    else:
        raise TypeError(
            f"Task '{name}' 'cmd' field must be a string, or list of strings; got {type(cmd)}"
        )


def validate_task(task, name: str) -> DmonTaskConfig:
    ret = DmonTaskConfig(task=name)
    if isinstance(task, str) or isinstance(task, list):
        ret.cmd = validate_cmd_type(task, name)
    elif isinstance(task, dict):
        if "cmd" not in task:
            raise TypeError(f"Task '{name}' must have a 'cmd' field")
        ret.cmd = validate_cmd_type(task["cmd"], name)

        if "cwd" in task:
            if not isinstance(task["cwd"], str):
                raise TypeError(f"Task '{name}' 'cwd' field must be a string")
            ret.cwd = task["cwd"]

        if "env" in task:
            if not isinstance(task["env"], dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in task["env"].items()
            ):
                raise TypeError(
                    f"Task '{name}' 'env' field must be a table of string to string"
                )
            ret.env = cast(Dict[str, str], task["env"])

        if "override_env" in task:
            if not isinstance(task["override_env"], bool):
                raise TypeError(f"Task '{name}' 'override_env' field must be a boolean")
            ret.override_env = task["override_env"]

        if "log_path" in task:
            if not isinstance(task["log_path"], str):
                raise TypeError(f"Task '{name}' 'log_path' field must be a string")
            ret.log_path = task["log_path"]

        if "log_rotate" in task:
            if not isinstance(task["log_rotate"], bool):
                raise TypeError(f"Task '{name}' 'log_rotate' field must be a boolean")
            ret.log_rotate = task["log_rotate"]

        if "log_max_size" in task:
            if (
                not isinstance(task["log_max_size"], (int, float))
                or task["log_max_size"] <= 0
            ):
                raise TypeError(
                    f"Task '{name}' 'log_max_size' field must be a positive number"
                )
            ret.log_max_size = task["log_max_size"]

        if "rotate_log_path" in task:
            if not isinstance(task["rotate_log_path"], str):
                raise TypeError(
                    f"Task '{name}' 'rotate_log_path' field must be a string"
                )
            ret.rotate_log_path = task["rotate_log_path"]

        if "rotate_log_max_size" in task:
            if (
                not isinstance(task["rotate_log_max_size"], (int, float))
                or task["rotate_log_max_size"] <= 0
            ):
                raise TypeError(
                    f"Task '{name}' 'rotate_log_max_size' field must be a positive number"
                )
            ret.rotate_log_max_size = task["rotate_log_max_size"]

        if "meta_path" in task:
            if not isinstance(task["meta_path"], str):
                raise TypeError(f"Task '{name}' 'meta_path' field must be a string")
            ret.meta_path = task["meta_path"]
    else:
        raise TypeError(
            f"Task '{name}' must be a string, list of strings, or a table; got {type(task)}"
        )
    return ret


def get_task_config(
    names: Union[Sequence[str], str, None], cfg_path: Optional[str], all: bool = False
) -> Tuple[Sequence[str], List[DmonTaskConfig]]:
    """
    Get the validated task configurations for the given task names.
    If 'all' is True, return all tasks.
    If no name specified, and there is only one task, return that task; otherwise, raise ValueError.
    If any task is not found, or required fields are missing, raise TypeError or ValueError.

    The config is loaded from the given path, or searched for dmon.yaml or pyproject.toml.
    """
    cfg, path = load_config(cfg_path)
    tasks = cfg.get("tasks", {})

    if not isinstance(tasks, dict):
        raise TypeError("'tasks' must be a table")

    if all:
        names = list(tasks.keys())
    elif isinstance(names, str):
        names = [names]
    elif names is None or len(names) == 0:
        default_task_name = cfg.get("default_task", None)
        if default_task_name:
            if not isinstance(default_task_name, str):
                raise TypeError("'default_task' must be a string")
            names = [default_task_name]
        else:
            if len(tasks) == 0:
                raise ValueError(f"No task found in {path}")
            elif len(tasks) == 1:
                name = next(iter(tasks))
                assert isinstance(name, str)
                names = [name]
            else:
                raise ValueError(f"Multiple tasks found in {path}; please specify one.")

    ret_tasks = []
    for name in names:
        name = name.lower()
        if name not in tasks:
            raise ValueError(f"Task '{name}' not found in {path}")

        task = validate_task(tasks[name], name)
        ret_tasks.append(task)
    return names, ret_tasks


def check_name_in_config(name: str) -> bool:
    """
    Check if the given task name exists in the tasks.
    Return True if found, False otherwise.
    """
    cfg, _ = load_config()
    tasks = cfg.get("tasks", {})

    if not isinstance(tasks, dict):
        return False

    return name.lower() in tasks
