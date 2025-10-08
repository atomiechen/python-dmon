import sys
from pathlib import Path
from typing import Dict, Optional, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .types import CmdType, DmonTaskConfig


def load_config(cfg_path: Optional[str] = None):
    """
    Load configuration from the given path, or search it from the current working directory upwards.
    """

    if cfg_path:
        # Load configuration from the given path
        path = Path(cfg_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Config file '{path}' does not exist.")
    else:
        # No path provided, search for config files
        # starting from the current working directory upwards
        current = Path.cwd().resolve()
        path = None
        for parent in [current, *current.parents]:
            for filename in ["dmon.yaml", "dmon.yml", "pyproject.toml"]:
                path = parent / filename
                if path.is_file():
                    break
            else:
                continue  # Only break out of the inner loop if a file was found
            break  # Break out of the outer loop if a file was found
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
            if not isinstance(task["log_max_size"], int) or task["log_max_size"] <= 0:
                raise TypeError(
                    f"Task '{name}' 'log_max_size' field must be a positive integer"
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
                not isinstance(task["rotate_log_max_size"], int)
                or task["rotate_log_max_size"] <= 0
            ):
                raise TypeError(
                    f"Task '{name}' 'rotate_log_max_size' field must be a positive integer"
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


def get_task_config(name: Optional[str], cfg_path: Optional[str]):
    """
    Get the validated task configuration for the given task name.
    If name is None or empty, and there is only one task, return that task; otherwise, raise ValueError.
    If the task is not found, or required fields are missing, raise TypeError or ValueError.

    The config is loaded from the given path, or searched for dmon.yaml or pyproject.toml.
    """
    cfg, path = load_config(cfg_path)
    tasks = cfg.get("tasks", {})

    if not isinstance(tasks, dict):
        raise TypeError("'tasks' must be a table")

    if not name:
        if len(tasks) == 0:
            raise ValueError(f"No task found in {path}")
        elif len(tasks) == 1:
            name = next(iter(tasks))
        else:
            raise ValueError(f"Multiple tasks found in {path}; please specify one.")
    else:
        name = name.lower()
        if name not in tasks:
            raise ValueError(f"Task '{name}' not found in {path}")

    assert isinstance(name, str)
    task = validate_task(tasks[name], name)
    return name, task


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
