# python-dmon


[![GitHub](https://img.shields.io/badge/github-python--dmon-blue?logo=github)](https://github.com/atomiechen/python-dmon)
[![PyPI](https://img.shields.io/pypi/v/python--dmon?logo=pypi&logoColor=white)](https://pypi.org/project/python-dmon/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/atomiechen/python-dmon)


A lightweight, cross-platform daemon manager that runs any command — called a *task* — as a background process. 
It also supports logging and log rotation out of the box. 
**No Docker or extra dependencies required**. 

Shipped as the CLI tool `dmon`.
It is a Python-based and more powerful successor to the [handy-backend shell scripts](https://github.com/atomiechen/handy-backend).


## Features

- 🖥️ **Cross-platform:** Works on Linux, macOS, and Windows.
- ⚡ **Lightweight:** Pure Python, no Docker or external dependencies needed.
- 🧩 **Flexible tasks:** Tasks can be configured in `pyproject.toml` or `dmon.yaml`; or run ad-hoc commands directly.
- 🪵 **Logging & log rotation:** Keep active log files manageable, with optional archive retention limits.

![dmon-demo-gif](https://github.com/user-attachments/assets/9bae2f46-5ef4-4784-aced-18d573204efc)


## Installation

`python-dmon` is available on [PyPI](https://pypi.org/project/python-dmon/):

```sh
pip install python-dmon
```

We recommend installing into an isolated environment, e.g., with `uv` / `pipx`:

```sh
# Install globally with uv tool
uv tool install python-dmon

# Or with pipx
pipx install python-dmon

# Add as a dev dependency in your project
uv add --dev python-dmon
```

You can also invoke without installing:

```sh
# With uvx (uv tool run)
uvx python-dmon

# Or with pipx
pipx run python-dmon
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
  app: ["python", "-u", "server.py"]  # option 1: exec form
  # app: "python -u server.py"  # option 2: shell string
```

Or add to your `pyproject.toml`:

```toml
[tool.dmon.tasks]
app = ["python", "-u", "server.py"]  # option 1: exec form
# app = "python -u server.py"  # option 2: shell string
```

Commands can be a single string (run in shell), or list of strings (exec form).
See [Example Configuration](#example-configuration) for more configuration options.


### Run tasks

Run a configured task by its name:

```sh
# Start a task
dmon start app

# Stop a running task
dmon stop app

# Restart a task
dmon restart app

# Check task status
dmon status app

# Execute a task in the foreground (useful for debugging)
dmon exec app
```

You can specify multiple tasks at once, e.g.: `dmon start app1 app2 app3`, except for `dmon exec` which only accepts one task.

Multi-task `start` is best-effort: dmon attempts every requested task and leaves
successful tasks running if another task cannot start. The command returns a
non-zero status and prints a summary naming the failed tasks. This is useful for
independent background services and does not provide atomic stack semantics.

For related services that should start and stop as one unit, define a stack and
run it in the foreground:

```yaml
tasks:
  database:
    cmd: [python, database.py]
    ready:
      tcp: {host: 127.0.0.1, port: 5432}
      timeout: 20
  api:
    cmd: [python, api.py]
    depends_on: [database]
    ready:
      http: http://127.0.0.1:8000/health
  worker:
    cmd: [python, worker.py]
    depends_on: [api]

stacks:
  dev: [api, worker]
default_stack: dev
```

```sh
dmon up dev
# Or omit the name when default_stack (or only one stack) is configured
dmon up
```

`dmon up` starts dependencies in order and waits for each task's optional
readiness probe. A startup failure, readiness timeout, unexpected task exit,
Ctrl-C, or SIGTERM stops every task started by that invocation in reverse order.
Task output remains in each task's configured `log_path` rather than being
combined in the terminal. Docker Compose is still appropriate when container
behavior itself must be tested. `dmon up` has no detached mode or matching
`down` command; use `dmon start` for independently managed background tasks.

Or use `--all` to operate on all tasks:

```sh
# all configured tasks
dmon start/stop/restart --all
# all running tasks
dmon stop/status --all
```

If you have defined `default_task`, or only one task is defined in the config file, you can omit the task name:

```sh
dmon start
dmon stop
dmon restart
dmon status
dmon exec
```

You can use `-c` / `--config` to specify a custom config file or the directory containing it:

```sh
dmon start --config /path/to/dmon.yaml app  # YAML
dmon start --config /path/to/pyproject.toml app  # or TOML
dmon start -c /path/to/dir app  # shorter, dir with `dmon.y(a)ml` or `pyproject.toml`
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

# Optionally use -- to make the child-command boundary explicit
dmon run --name timer -- python -c 'import time; time.sleep(30)'

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


## Example Configuration

A task can be a **string**, **list**, or **dictionary**.

When rotation is enabled, dmon keeps timestamped archives such as
`app.log.20260807-142106`. Both task and runner logs use this cross-platform
format; a same-second collision adds `.1`, `.2`, and so on. Archives are never
deleted by default. Set a backup count explicitly to enable retention cleanup.
`log_path` contains task output; `rotate_log_path` contains diagnostics from the
dmon process that captures and rotates that output. They are independent log
streams and use independent retention settings.
The size limit is checked at line boundaries, so a single long line may exceed
the configured limit.

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
    # log_backup_count: 10  # optional; omit to retain all task log archives
    rotate_log_path: "logs/<task>.rotate.log"  # path to rotation log
    rotate_log_max_size: 5  # max rotation log file size in MB
    # rotate_log_backup_count: 10  # optional; omit to retain all runner log archives
    meta_path: ".dmon/<task>.meta.json"  # path to meta file
    depends_on: [another_task]  # dependency order used by `dmon up`
    ready:  # optional; exactly one of http, tcp, or command
      command: [python, healthcheck.py]
      timeout: 30  # total seconds to wait (default: 30)
      interval: 0.2  # seconds between attempts (default: 0.2)
default_task: your_task_name  # the default task name
stacks:
  dev: [your_task_name]
default_stack: dev
```

In TOML, write like this:

```toml
[tool.dmon.tasks]
your_task_name = { cmd = [
  "python", "-u", "server.py"
], ... }
another_task = "cd subdir && ls && bash start.sh"

[tool.dmon]
default_task = "your_task_name"
```

All paths can be absolute or relative to the **config file location**.


## Under the Hood

Each task is associated with a meta file (e.g. `.dmon/<task>.meta.json`) stored in the current working directory.
The file contains details such as the command, PID, log path, and more.
**Do not** modify or delete these files manually.

`dmon status` returns a non-zero status if a recorded task has exited. Starting
that task again removes its stale metadata automatically. `dmon stop` terminates
the complete process tree and also cleans stale metadata left by an exited task.


## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, behavioral contracts,
validation, and the release workflow. Process, signal, log-rotation, and stack
changes must also pass the reproducible [manual test lab](tests/manual/README.md).


## License

[python-dmon](https://github.com/atomiechen/python-dmon) © 2025 by [Atomie CHEN](https://github.com/atomiechen) is licensed under the [MIT License](https://github.com/atomiechen/python-dmon/blob/main/LICENSE).
