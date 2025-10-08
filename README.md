# python-dmon


[![GitHub](https://img.shields.io/badge/github-python--dmon-blue?logo=github)](https://github.com/atomiechen/python-dmon)
[![PyPI](https://img.shields.io/pypi/v/python--dmon?logo=pypi&logoColor=white)](https://pypi.org/project/python-dmon/)


A lightweight, cross-platform daemon manager that runs any command — called a *task* — as a background process. 
It also supports logging and log rotation out of the box. 
**No Docker or extra dependencies required**. 

Shipped as the CLI tool `dmon`.
It is a Python-based and more powerful successor to the [handy-backend shell scripts](https://github.com/atomiechen/handy-backend).


## Features

- 🖥️ **Cross-platform:** Works on Linux, macOS, and Windows.
- ⚡ **Lightweight:** Pure Python, no Docker or external dependencies needed.
- 🧩 **Flexible tasks:** Tasks can be configured in `pyproject.toml` or `dmon.yaml`; or run ad-hoc commands directly.
- 🪵 **Logging & log rotation:** Automatically manage log files to prevent uncontrolled growth.


## Installation

```sh
pip install python-dmon
```

To get the latest features, install from source:

```sh
pip install git+https://github.com/atomiechen/python-dmon.git
```

## Getting Started

### Prepare Configuration

Create a `dmon.yaml` file:

```yaml
tasks:
  app: ["python", "-u", "server.py"]
```

Or add to your `pyproject.toml`:

```toml
[tool.dmon.tasks]
app = ["python", "-u", "server.py"]
```

Commands can be a single string (run in shell), or list of strings (exec form).
See [Example Task Configuration](#example-task-configuration) for more configuration options.


### Run tasks

Run a configured task by its name:

```sh
# Start a task
dmon start app

# Stop a running task
dmon stop app

# Check task status
dmon status app

# Execute a task in the foreground (useful for debugging)
dmon exec app
```

If only one task is defined in the config file, you can omit the task name:

```sh
dmon start
dmon stop
dmon status
dmon exec
```

You can use `--config` to specify a custom config file:

```sh
dmon start --config /path/to/dmon.yaml app  # YAML
dmon start --config /path/to/pyproject.toml app  # or TOML
```

And yes, you can use `dmon` to run in a nested manner:

```yaml
tasks:
  app: ["python", "-u", "server.py"]
  nested: pwd && dmon exec app  # nest `dmon exec`
  subdir_task1:
    cwd: /path/to/dir
    cmd: ["dmon", "exec", "app"]  # run task defined in another folder
  subdir_task2: dmon exec app --config /path/to/dir/dmon.yaml  # like above
```


### Run an ad-hoc command

```sh
# Run a command with arguments in the background
dmon run --name myserver python -u server.py

# Run a shell command in the background
dmon run --shell echo "Hello World"

# Run a shell script in the background
dmon run --cwd /path/to/script bash myscript.sh
```

> [!NOTE]
> If no name is provided, `dmon` automatically assigns a fixed task name `default_run` to prevent duplicate runs.


### List all running tasks

```sh
dmon list
```


## Example Task Configuration

A task can be a **string**, **list**, or **dictionary**.

Here is a more complete example with default values:

```yaml
tasks:
  your_task_name:
    # Command to run; can be a string (run in shell) or list of strings (exec form)
    cmd: ["python", "server.py"]  # required
    cwd: "/path/to/working/dir"  # (default: current dir)
    env:  # (default: inherit from parent process)
      PYTHONUNBUFFERED: "1"
    override_env: false  # override parent env and only use env defined here
    log_path: "logs/<task>.log" # path to log file
    log_rotate: false  # enable log rotation
    log_max_size: 5  # max log file size before rotation in MB
    rotate_log_path: "logs/<task>.rotate.log"  # path to rotation log
    rotate_log_max_size: 5  # max rotation log file size in MB
    meta_path: ".dmon/<task>.meta.json"  # path to meta file
```

## Under the Hood

Each task is associated with a meta file (e.g. `.dmon/<task>.meta.json`) stored in the current working directory.
The file contains details such as the command, PID, log path, and more.
**Do not** modify or delete these files manually.


## License

[python-dmon](https://github.com/atomiechen/python-dmon) © 2025 by [Atomie CHEN](https://github.com/atomiechen) is licensed under the [MIT License](https://github.com/atomiechen/python-dmon/blob/main/LICENSE).
