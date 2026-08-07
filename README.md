# python-dmon


[![GitHub](https://img.shields.io/badge/github-python--dmon-blue?logo=github)](https://github.com/atomiechen/python-dmon)
[![PyPI](https://img.shields.io/pypi/v/python--dmon?logo=pypi&logoColor=white)](https://pypi.org/project/python-dmon/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/atomiechen/python-dmon)


A lightweight, cross-platform daemon manager that runs any command — called a *task* — as a background process.
It also supports logging and log rotation out of the box.
**No external runtime required**.

Shipped as the CLI tool `dmon`.
It is a Python-based and more powerful successor to the [handy-backend shell scripts](https://github.com/atomiechen/handy-backend).


## Features

- 🖥️ **Cross-platform:** Works on Linux, macOS, and Windows.
- ⚡ **Lightweight:** No daemon service or container runtime required.
- 🧩 **Flexible tasks:** Tasks can be configured in `pyproject.toml` or `dmon.yaml`; or run ad-hoc commands directly.
- 🔗 **Supervised stacks:** Start dependent tasks in order, wait for HTTP, TCP,
  or command readiness, and report runtime degradation.
- 🌙 **Foreground or detached:** Keep a stack attached for development, or run
  it under a recoverable background supervisor with `dmon stack up -d` and
  `dmon stack down`.
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
Without `--config`, dmon searches the current directory and its parents for
`dmon.yaml`, `dmon.yml`, or `pyproject.toml`.


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
dmon stack up dev
# Or omit the name when default_stack (or only one stack) is configured
dmon stack up

# Keep the supervised stack running in the background
dmon stack up -d dev
dmon stack status dev
dmon stack restart dev
dmon stack logs --tail 100 dev
dmon stack logs -f dev
dmon stack list
dmon stack down dev

# Optional fail-fast policy for foreground or detached stacks
dmon stack up --abort-on-exit dev
```

`dmon stack up` starts dependencies in order and waits for each task's optional
readiness probe. A startup failure or readiness timeout rolls back every task
started by that invocation. After startup, an exited task marks the stack as
degraded while unrelated tasks continue running, matching Docker Compose's
default behavior. Use `--abort-on-exit` when the whole stack should stop after
any runtime exit. Ctrl-C or SIGTERM cleans up a foreground stack in reverse
order. Use `dmon stack down` to clean up a detached stack.

Foreground `dmon stack up` displays new task output with task-name prefixes,
while retaining it in each task's configured `log_path`. Detached mode does not
attach output. `dmon stack logs` reads the latest 100 lines per task by default;
`--tail` changes that count and `-f` follows new output. Log viewing never
modifies the underlying files and never controls running processes. Docker
Compose is still appropriate when container behavior itself must be tested.

Detached mode waits for the same startup and readiness checks before returning.
A lightweight background supervisor keeps monitoring the stack; `dmon stack down`
requests the same graceful reverse-order cleanup on every platform. If that
supervisor is killed, its persisted ownership metadata lets `down` recover and
clean the tasks it started. Supervisor diagnostics are written to
`logs/<stack>.stack.log`. `dmon stack status` includes every owned task and its
process tree; `dmon stack list` summarizes all recorded stacks. `dmon stack
restart` performs a clean `down` followed by a detached `up` and preserves the
stack's exit policy.

Or use `--all` to operate on all tasks:

```sh
# All configured tasks
dmon start --all
dmon restart --all

# All recorded task metadata in the project
dmon status --all
dmon stop --all
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

The same config discovery and selection rules apply to stacks. A stack name can
be omitted when `default_stack` is set or only one stack is configured. Options
belonging to a stack operation go after that operation and may appear before or
after the stack name; for example, `dmon stack up -d dev` and `dmon stack up dev
-d` are equivalent.

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


### List recorded tasks and their status

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
    depends_on: [another_task]  # dependency order used by `dmon stack up`
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

Each task has `.dmon/<task>.meta.json`, which records its command, PID, process
creation time, and log paths. A detached stack also has
`.dmon/<stack>.stack.json`, which records its supervisor and the exact task
processes it owns. Metadata paths are reserved exclusively and subsequent
updates replace the JSON atomically; a per-run ID isolates stop requests, while
PID plus creation time prevents a recycled PID from being mistaken for the
original process.

`dmon stack down` normally asks the supervisor to stop tasks in reverse order.
If the supervisor has crashed, it uses the persisted process identities to
recover the orphaned stack without inferring ownership from current
configuration. Existing or unreadable stack metadata is preserved rather than
overwritten; use `dmon stack down` for stale, readable state. **Do not** edit or
delete `.dmon` files manually.

The log viewer is deliberately separate from process control. It opens task log
files only while reading, closes them before waiting for more output, and uses
file identity to reopen a replacement after rotation. Stopping `dmon stack logs
-f` cannot stop or restart a task or stack. The same read-only component powers
foreground log attachment; a display failure does not change stack lifecycle.

`dmon status` returns a non-zero status if a recorded task has exited. Starting
that task again removes its stale metadata automatically. `dmon stop` terminates
the complete process tree and also cleans stale metadata left by an exited task.


## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, behavioral contracts,
validation, and the release workflow. Process, signal, log-rotation, and stack
changes must also pass the reproducible [manual test lab](tests/manual/README.md).


## License

[python-dmon](https://github.com/atomiechen/python-dmon) © 2025 by [Atomie CHEN](https://github.com/atomiechen) is licensed under the [MIT License](https://github.com/atomiechen/python-dmon/blob/main/LICENSE).
