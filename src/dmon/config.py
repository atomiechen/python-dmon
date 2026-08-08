import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union, cast
from urllib.parse import urlsplit

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .types import CmdType, DmonTaskConfig
from .constants import LOG_PATH_TEMPLATE, META_PATH_TEMPLATE, ROTATE_LOG_PATH_TEMPLATE


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
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise TypeError(f"Config in '{path}' must be a table")
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

        if "env_file" in task:
            env_file = task["env_file"]
            if isinstance(env_file, str):
                env_files = [env_file]
            elif isinstance(env_file, list) and all(
                isinstance(item, str) and item for item in env_file
            ):
                env_files = env_file
            else:
                raise TypeError(
                    f"Task '{name}' 'env_file' field must be a non-empty string "
                    "or list of non-empty strings"
                )
            if not env_files or any(not item for item in env_files):
                raise TypeError(
                    f"Task '{name}' 'env_file' field must be a non-empty string "
                    "or list of non-empty strings"
                )
            ret.env_files = env_files

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

        if "log_backup_count" in task:
            value = task["log_backup_count"]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise TypeError(
                    f"Task '{name}' 'log_backup_count' field must be a positive integer"
                )
            ret.log_backup_count = value

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

        if "rotate_log_backup_count" in task:
            value = task["rotate_log_backup_count"]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise TypeError(
                    f"Task '{name}' 'rotate_log_backup_count' field must be a positive integer"
                )
            ret.rotate_log_backup_count = value

        if "meta_path" in task:
            if not isinstance(task["meta_path"], str):
                raise TypeError(f"Task '{name}' 'meta_path' field must be a string")
            ret.meta_path = task["meta_path"]

        if "depends_on" in task:
            if not isinstance(task["depends_on"], list) or not all(
                isinstance(item, str) and item for item in task["depends_on"]
            ):
                raise TypeError(
                    f"Task '{name}' 'depends_on' field must be a list of non-empty task names"
                )
            ret.depends_on = [item.lower() for item in task["depends_on"]]

        if "ready" in task:
            ret.ready = validate_ready(task["ready"], name)
    else:
        raise TypeError(
            f"Task '{name}' must be a string, list of strings, or a table; got {type(task)}"
        )
    return ret


def validate_ready(ready, name: str) -> Dict[str, object]:
    if not isinstance(ready, dict):
        raise TypeError(f"Task '{name}' 'ready' field must be a table")
    allowed = {"http", "tcp", "command", "timeout", "interval"}
    unknown = set(ready) - allowed
    if unknown:
        raise TypeError(
            f"Task '{name}' 'ready' field has unknown keys: {', '.join(sorted(unknown))}"
        )
    probes = [key for key in ("http", "tcp", "command") if key in ready]
    if len(probes) != 1:
        raise TypeError(
            f"Task '{name}' 'ready' field must define exactly one of: http, tcp, command"
        )
    if "http" in ready:
        url = ready["http"]
        if not isinstance(url, str) or not url:
            raise TypeError(
                f"Task '{name}' readiness 'http' value must be a URL string"
            )
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as error:
            raise TypeError(
                f"Task '{name}' readiness 'http' value must be a valid HTTP(S) URL"
            ) from error
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise TypeError(
                f"Task '{name}' readiness 'http' value must be a valid HTTP(S) URL"
            )
    if "command" in ready:
        command = validate_cmd_type(ready["command"], f"{name}.ready")
        if not command:
            raise TypeError(f"Task '{name}' readiness 'command' must not be empty")
    if "tcp" in ready:
        tcp = ready["tcp"]
        if (
            not isinstance(tcp, dict)
            or not isinstance(tcp.get("host"), str)
            or not tcp.get("host")
            or not isinstance(tcp.get("port"), int)
            or isinstance(tcp.get("port"), bool)
            or not 1 <= tcp["port"] <= 65535
            or set(tcp) != {"host", "port"}
        ):
            raise TypeError(
                f"Task '{name}' readiness 'tcp' value must contain a host string and valid port"
            )
    for key, default in (("timeout", 30.0), ("interval", 0.2)):
        value = ready.get(key, default)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise TypeError(
                f"Task '{name}' readiness '{key}' value must be a positive number"
            )
    return cast(Dict[str, object], ready)


def get_task_config(
    names: Union[Sequence[str], str, None], cfg_path: Optional[str], all: bool = False
) -> Tuple[Sequence[str], List[DmonTaskConfig], Path]:
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

    ret_names = []
    ret_tasks = []
    for name in names:
        name = name.lower()
        if name not in tasks:
            raise ValueError(f"Task '{name}' not found in {path}")

        task = validate_task(tasks[name], name)
        ret_names.append(name)
        ret_tasks.append(task)
    return ret_names, ret_tasks, path


def get_stack_config(
    name: Optional[str], cfg_path: Optional[str] = None
) -> Tuple[str, List[DmonTaskConfig], Path]:
    name, cfg, path = resolve_stack(name, cfg_path)
    tasks = cfg.get("tasks", {})
    stacks = cfg["stacks"]
    selected = stacks[name]
    assert isinstance(tasks, dict)
    assert isinstance(selected, list)

    normalized_tasks = {}
    for task_name, task in tasks.items():
        if not isinstance(task_name, str):
            raise TypeError("Task names must be strings")
        normalized = task_name.lower()
        if normalized in normalized_tasks:
            raise ValueError(f"Duplicate task name after normalization: '{normalized}'")
        normalized_tasks[normalized] = task
    validated = {}
    order: List[str] = []
    visiting: List[str] = []
    visited = set()

    def visit(task_name: str) -> None:
        task_name = task_name.lower()
        if task_name in visited:
            return
        if task_name in visiting:
            cycle = " -> ".join([*visiting[visiting.index(task_name) :], task_name])
            raise ValueError(f"Task dependency cycle in stack '{name}': {cycle}")
        if task_name not in normalized_tasks:
            raise ValueError(
                f"Task '{task_name}' referenced by stack '{name}' is not defined"
            )
        if task_name not in validated:
            validated[task_name] = validate_task(normalized_tasks[task_name], task_name)
        visiting.append(task_name)
        for dependency in validated[task_name].depends_on:
            visit(dependency)
        visiting.pop()
        visited.add(task_name)
        order.append(task_name)

    for task_name in selected:
        visit(task_name)
    configs = [validated[task_name] for task_name in order]
    return name, configs, path


def resolve_stack(
    name: Optional[str], cfg_path: Optional[str] = None
) -> Tuple[str, Dict[str, object], Path]:
    cfg, path = load_config(cfg_path)
    tasks = cfg.get("tasks", {})
    stacks = cfg.get("stacks", {})
    if not isinstance(tasks, dict):
        raise TypeError("'tasks' must be a table")
    if not isinstance(stacks, dict):
        raise TypeError("'stacks' must be a table")

    normalized_stacks: Dict[str, object] = {}
    for stack_name, stack in stacks.items():
        if not isinstance(stack_name, str):
            raise TypeError("Stack names must be strings")
        normalized = stack_name.lower()
        if normalized in normalized_stacks:
            raise ValueError(
                f"Duplicate stack name after normalization: '{normalized}'"
            )
        normalized_stacks[normalized] = stack
    if name is None:
        default_stack = cfg.get("default_stack")
        if default_stack is not None:
            if not isinstance(default_stack, str) or not default_stack:
                raise TypeError("'default_stack' must be a non-empty string")
            name = default_stack
        elif len(normalized_stacks) == 1:
            name = next(iter(normalized_stacks))
        elif not normalized_stacks:
            raise ValueError(f"No stack found in {path}")
        else:
            raise ValueError(f"Multiple stacks found in {path}; please specify one.")
    name = name.lower()
    if name not in normalized_stacks:
        raise ValueError(f"Stack '{name}' not found in {path}")
    selected = normalized_stacks[name]
    if (
        not isinstance(selected, list)
        or not selected
        or not all(isinstance(item, str) and item for item in selected)
    ):
        raise TypeError(f"Stack '{name}' must be a non-empty list of task names")
    cfg = dict(cfg)
    cfg["stacks"] = normalized_stacks
    return name, cast(Dict[str, object], cfg), path


def fill_default_paths(configs: Sequence[DmonTaskConfig]) -> None:
    for config in configs:
        config.meta_path = config.meta_path or META_PATH_TEMPLATE.format(
            task=config.task
        )
        config.log_path = config.log_path or LOG_PATH_TEMPLATE.format(task=config.task)
        config.rotate_log_path = (
            config.rotate_log_path or ROTATE_LOG_PATH_TEMPLATE.format(task=config.task)
        )


def check_name_in_config(name: str) -> bool:
    """
    Check if the given task name exists in the tasks.
    Return True if found, False otherwise.
    """
    try:
        cfg, _ = load_config()
    except FileNotFoundError:
        return False
    tasks = cfg.get("tasks", {})

    if not isinstance(tasks, dict):
        return False

    return name.lower() in tasks
