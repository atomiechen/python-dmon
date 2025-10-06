import sys
from pathlib import Path
from typing import Dict, Optional, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .types import CmdType, DmonCommandConfig


def find_pyproject_toml(start: Optional[Path] = None):
    """
    Search for pyproject.toml from the current directory (or specified directory) upwards.
    Return a Path object if found.
    """
    start = start or Path.cwd()
    current = start.resolve()

    for parent in [current, *current.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate

    # raise FileNotFoundError(f"No pyproject.toml found from {start} upwards.")


def find_dmon_yaml(start: Optional[Path] = None):
    """
    Search for dmon.yaml / dmon.yml from the current directory (or specified directory) upwards.
    Return a Path object if found.
    """
    start = start or Path.cwd()
    current = start.resolve()

    for parent in [current, *current.parents]:
        for filename in ["dmon.yaml", "dmon.yml"]:
            candidate = parent / filename
            if candidate.is_file():
                return candidate

    # raise FileNotFoundError(f"No dmon.yaml or dmon.yml found from {start} upwards.")


def load_config():
    path = find_dmon_yaml()
    if path:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    else:
        path = find_pyproject_toml()
        if not path:
            raise FileNotFoundError(
                "No dmon.yaml or pyproject.toml found in current or any parent directory."
            )

        with path.open("rb") as f:
            cfg = tomllib.load(f)
        cfg = cfg.get("tool", {}).get("dmon", {})
    return cfg, path


def validate_cmd_type(cmd, name: str) -> CmdType:
    if isinstance(cmd, str):
        return cmd
    elif isinstance(cmd, list):
        if not all(isinstance(item, str) for item in cmd):
            # check if it's a list of strings
            raise TypeError(f"Command '{name}' list items must be strings")
        return cmd
    else:
        raise TypeError(
            f"Command '{name}' 'cmd' field must be a string, or list of strings; got {type(cmd)}"
        )


def validate_command(command, name: str) -> DmonCommandConfig:
    ret = DmonCommandConfig(name=name)
    if isinstance(command, str) or isinstance(command, list):
        ret.cmd = validate_cmd_type(command, name)
    elif isinstance(command, dict):
        if "cmd" not in command:
            raise TypeError(f"Command '{name}' must have a 'cmd' field")
        ret.cmd = validate_cmd_type(command["cmd"], name)

        if "cwd" in command:
            if not isinstance(command["cwd"], str):
                raise TypeError(f"Command '{name}' 'cwd' field must be a string")
            ret.cwd = command["cwd"]

        if "env" in command:
            if not isinstance(command["env"], dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in command["env"].items()
            ):
                raise TypeError(
                    f"Command '{name}' 'env' field must be a table of string to string"
                )
            ret.env = cast(Dict[str, str], command["env"])

        if "override_env" in command:
            if not isinstance(command["override_env"], bool):
                raise TypeError(
                    f"Command '{name}' 'override_env' field must be a boolean"
                )
            ret.override_env = command["override_env"]

        if "log_path" in command:
            if not isinstance(command["log_path"], str):
                raise TypeError(f"Command '{name}' 'log_path' field must be a string")
            ret.log_path = command["log_path"]

        if "log_rotate" in command:
            if not isinstance(command["log_rotate"], bool):
                raise TypeError(
                    f"Command '{name}' 'log_rotate' field must be a boolean"
                )
            ret.log_rotate = command["log_rotate"]

        if "log_max_size" in command:
            if (
                not isinstance(command["log_max_size"], int)
                or command["log_max_size"] <= 0
            ):
                raise TypeError(
                    f"Command '{name}' 'log_max_size' field must be a positive integer"
                )
            ret.log_max_size = command["log_max_size"]

        if "rotate_log_path" in command:
            if not isinstance(command["rotate_log_path"], str):
                raise TypeError(
                    f"Command '{name}' 'rotate_log_path' field must be a string"
                )
            ret.rotate_log_path = command["rotate_log_path"]

        if "rotate_log_max_size" in command:
            if (
                not isinstance(command["rotate_log_max_size"], int)
                or command["rotate_log_max_size"] <= 0
            ):
                raise TypeError(
                    f"Command '{name}' 'rotate_log_max_size' field must be a positive integer"
                )
            ret.rotate_log_max_size = command["rotate_log_max_size"]

        if "meta_path" in command:
            if not isinstance(command["meta_path"], str):
                raise TypeError(f"Command '{name}' 'meta_path' field must be a string")
            ret.meta_path = command["meta_path"]
    else:
        raise TypeError(
            f"Command '{name}' must be a string, list of strings, or a table; got {type(command)}"
        )
    return ret


def get_command_config(name: Optional[str] = None):
    """
    Get the command configuration for the given command name from [tool.dmon.commands].
    Validate the structure and return a DmonCommand dictionary.

    If name is None or empty, and there is only one command, return that command; otherwise, raise ValueError.
    If the command is not found, or required fields are missing, raise TypeError or ValueError.
    """
    cfg, path = load_config()
    commands = cfg.get("commands", {})

    if not isinstance(commands, dict):
        raise TypeError("[tool.dmon.commands] must be a table (not [[array]])")

    if not name:
        if len(commands) == 0:
            raise ValueError(f"No command found in {path}")
        elif len(commands) == 1:
            name = next(iter(commands))
        else:
            raise ValueError(f"Multiple commands found in {path}; please specify one.")
    else:
        name = name.lower()
        if name not in commands:
            raise ValueError(f"Command '{name}' not found in {path}")

    assert isinstance(name, str)
    command = validate_command(commands[name], name)
    return name, command


def check_name_in_config(name: str) -> bool:
    """
    Check if the given command name exists in the commands.
    Return True if found, False otherwise.
    """
    cfg, _ = load_config()
    commands = cfg.get("commands", {})

    if not isinstance(commands, dict):
        return False

    return name.lower() in commands
