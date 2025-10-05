import sys
from pathlib import Path
from typing import Dict, Optional, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .types import CmdType, DmonCommandConfig


def find_pyproject_toml(start: Optional[Path] = None) -> Path:
    """
    Search for pyproject.toml from the current directory (or specified directory) upwards.
    Return a Path object if found, otherwise raise FileNotFoundError.
    """
    start = start or Path.cwd()
    current = start.resolve()

    for parent in [current, *current.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(f"No pyproject.toml found from {start} upwards.")


def load_pyproject_toml():
    pyproject_path = find_pyproject_toml()
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found in current directory")

    with open(pyproject_path, "rb") as f:
        cfg = tomllib.load(f)
    return cfg, pyproject_path


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
    ret: DmonCommandConfig = {
        "name": name,
        "cmd": "",
        "env": {},
        "override_env": False,
        "log_path": "",
        "meta_path": "",
    }
    if isinstance(command, str) or isinstance(command, list):
        ret["cmd"] = validate_cmd_type(command, name)
    elif isinstance(command, dict):
        if "cmd" not in command:
            raise TypeError(f"Command '{name}' must have a 'cmd' field")
        ret["cmd"] = validate_cmd_type(command["cmd"], name)

        if "env" in command:
            if not isinstance(command["env"], dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in command["env"].items()
            ):
                raise TypeError(
                    f"Command '{name}' 'env' field must be a table of string to string"
                )
            ret["env"] = cast(Dict[str, str], command["env"])

        if "log_path" in command:
            if not isinstance(command["log_path"], str):
                raise TypeError(f"Command '{name}' 'log_path' field must be a string")
            ret["log_path"] = command["log_path"]

        if "meta_path" in command:
            if not isinstance(command["meta_path"], str):
                raise TypeError(f"Command '{name}' 'meta_path' field must be a string")
            ret["meta_path"] = command["meta_path"]
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
    cfg, path = load_pyproject_toml()
    commands = cfg.get("tool", {}).get("dmon", {}).get("commands", {})

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
    Check if the given command name exists in the [tool.dmon.commands] section of pyproject.toml.
    Return True if found, False otherwise.
    """
    cfg, _ = load_pyproject_toml()
    commands = cfg.get("tool", {}).get("dmon", {}).get("commands", {})

    if not isinstance(commands, dict):
        return False

    return name.lower() in commands
