# Change Log

All notable changes to python-dmon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).



## [0.3.1] - 2026-08-07

### Added

- All paths in the config file are relative to the config file location, and the command will be executed in the config file directory as well. This allows more flexible usage such as running `dmon` from anywhere with `--config` pointing to another directory, or running from a subdirectory, which will search for config file in parent directories.
- Add `-c` alias of `--config` option for shorter command line usage.
- Add automated tests on Linux, macOS, and Windows, including Python 3.8 compatibility.
- Add opt-in backup counts for task and runner logs; archives remain unlimited when omitted.

### Fixed

- Stop the complete child process tree instead of leaving descendants running when the parent exits quickly.
- Report missing executables without a Python traceback and summarize partial multi-task start failures.
- Reserve and update metadata atomically to prevent concurrent duplicate starts and corrupted partial writes.
- Treat zombie and exited processes as stopped, return a failing status for exited tasks, and clean stale metadata safely.
- Resolve explicit `stop` and `status` task metadata relative to the selected config file.
- Allow ad-hoc `dmon run` outside a directory containing a dmon config file.
- Accept child-command options in `dmon run` with or without a `--` separator.
- Deliver Ctrl-C only once to foreground tasks run with `dmon exec`.
- Use one consistent, cross-platform timestamp format for task and runner log archives.


## [0.3.0] - 2026-01-09

### Added

- Multiple task names support for `start`, `restart`, `stop`, and `status` commands
- `--all` flag for `start`, `restart`, `stop`, and `status` commands to operate on all tasks


### Changed

- `stop` and `status` commands can combine task names, `--meta-file`, and (newly added) `--all` flag simultaneously



## [0.2.4] - 2025-12-16

### Added

- Config `log_max_size` and `rotate_log_max_size` now support float values representing size in MB.



## [0.2.3] - 2025-10-25

### Added

- Add `default_task` key to config to specify the default task to run when no task name is provided.
- `--config` now supports specifying a directory to search in, not just a file path.
- Add `python-dmon` as CLI alias in addition to `dmon` for better package name consistency.


### Fixed

- Fix `--config` non-existing path



## [0.2.2] - 2025-10-09

### Fixed

- `exec` use full path for the executable on windows when `shell=False`
- One pass searching for both `dmon.y(a)ml` and `pyproject.toml` when going up the directory tree. The previous behavior will search for `dmon.y(a)ml` first, then if not found, start over and search for `pyproject.toml`.
- Fix "AttributeError: 'DmonMeta' object has no attribute 'name'" when listing processes (should be `task` instead of `name`)



## [0.2.1] - 2025-10-09

### Added

- Support `--config` option to specify custom config file path
- Add `exec` subcommand to run task in the foreground (maybe for test or debug purpose)
- CLI now prints version information


### Changed

- Rename `name` key to `task` (task name) in meta files and rename any other related variables in the codebase.



## [0.2.0] - 2025-10-08

### Changed

Change distribution name from `dmon` to `python-dmon` to pass PyPI name allowance check.


## [0.1.0] - 2025-10-07

### Added

Initial release of dmon, a lightweight and handy daemon manager for running and managing background processes.
