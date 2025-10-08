# Change Log

All notable changes to HandyLLM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).



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
