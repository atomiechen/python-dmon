# Contributing

This document is the shared development contract for humans and coding agents.
Start with the invariants; read the detailed workflow only when needed.

## Quick start

```sh
uv sync --locked --dev
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
uv run ruff format src tests --check --diff
uv build
```

Use `uv sync` after intentionally changing dependencies or the project version,
and commit the resulting `uv.lock` change. Use `uv sync --locked --dev` in clean
validation and CI to detect an out-of-date lockfile.

## Architecture

- `cli.py` parses arguments and selects an operation.
- `config.py` loads, normalizes, and validates YAML/TOML configuration.
- `control.py` owns individual task lifecycle and process metadata.
- `runner.py` captures task output and rotates logs.
- `supervisor.py` coordinates dependent tasks, readiness, monitoring, and
  reverse-order cleanup, including persisted detached-stack ownership.
- `stack_runner.py` is the minimal background entry point for a detached stack;
  lifecycle behavior remains in `supervisor.py`.
- `types.py` contains persisted and runtime data structures.

Keep process and readiness behavior in these core layers. A future CLI format or
Python interface should consume structured core results instead of reimplementing
operations or parsing human-readable output. Keep diagnostics separate from data
output so machine-readable output can be added without breaking terminal use.

## Core contracts

### Lifecycle and process ownership

- A successful start owns a unique metadata file. Reserve it atomically; never
  let concurrent starts silently manage the same task.
- Metadata identifies a process by PID and creation time. A recycled PID is not
  the same process.
- Stale metadata is cleaned when safe. Corrupt metadata is reported and
  preserved for diagnosis, not silently discarded.
- Stop the complete process tree. Try graceful termination first, then force
  termination after the bounded grace period. Never leave descendants behind.
- Forward a foreground terminal signal once. Do not both manually forward a
  signal and let the terminal deliver the same signal to the child group.
- Multi-task `start` is best-effort. A supervised stack is fail-fast and cleans
  up only tasks started by that invocation, in reverse dependency order.
- An interrupt, startup failure, readiness timeout, runtime exit, or unexpected
  supervisor error must still run cleanup.
- A detached stack persists the supervisor identity and immutable task process
  identities it owns. `down` uses a per-run, cross-platform stop request, then
  falls back to those identities if the supervisor has crashed; it must never
  infer ownership from task names or the current configuration.
- Reserve detached stack metadata atomically. Concurrent `up -d` calls must have
  exactly one owner, and failed or corrupt metadata remains diagnosable.

### CLI behavior

- Exit zero only for successful operations. Status of an exited task and partial
  multi-task failure are non-zero.
- Errors name the affected task and remain actionable without a traceback.
- Child command options work with or without an explicit `--` boundary.
- Configured task and stack names are case-insensitive; displayed canonical names
  remain stable.
- Paths and commands from a config file resolve relative to that file, not the
  caller's current directory. Ad-hoc commands do not require a config file.
- Render task names consistently in bold cyan; use state-appropriate colors for
  surrounding diagnostics. Color must add meaning without becoming the only way
  to distinguish a task name, state, warning, or error. Respect non-interactive
  output.
- Render task and stack identifiers without quotes in structured tables. Quote
  them in prose diagnostics so their boundaries remain unambiguous.

### Logging

- `log_path` is task output. `rotate_log_path` is runner diagnostics. They are
  independent streams with independent size and retention settings.
- Archive names use the Windows-safe local timestamp `YYYYMMDD-HHMMSS`. Same-
  second collisions append `.1`, `.2`, and so on without overwriting or merging.
- Rotation limits the active file, not total archive storage. Archives are never
  deleted by default. Cleanup occurs only when a positive backup count is
  explicitly configured; the active file is not part of that count.
- Recognize legacy numeric padding and the pre-0.3.1 colon timestamp where the
  host filesystem permits it. Never create new filenames containing `:`.
- Rotation is checked at line boundaries, so one long line may exceed the limit.

### Configuration and readiness

- Validate configuration once at the boundary. Runtime code consumes normalized
  values rather than maintaining a second set of rules.
- Dependency graphs reject missing tasks and cycles before starting anything.
- Readiness supports one probe per task: HTTP, TCP, or command. Timeout and retry
  interval are bounded and use a monotonic clock.
- A task exiting before readiness is a failure. Probe failures are retryable
  until the overall timeout; they should not emit repeated tracebacks.
- Reuse readiness primitives for future waiting or hook interfaces instead of
  adding parallel URL, socket, or command implementations.

## Validation

Use the narrowest relevant tests while iterating, then run the complete quick-
start sequence before committing. Any lifecycle change also requires the manual
lab in [`tests/manual/README.md`](tests/manual/README.md).

The validation layers have different purposes:

1. Unit/integration tests assert deterministic behavior, exit codes, cleanup,
   collisions, and failure paths.
2. Real-process tests verify process trees, signals, stale state, and rotation.
3. Manual terminal tests judge readability, colors, timing, Ctrl-C, and concurrent
   commands that assertions cannot evaluate well.
4. CI is required before release. Linux, macOS, Windows, the minimum Python, and
   the current Python can expose different failures.

Do not create Windows-invalid fixtures such as filenames containing `:` on
Windows. Test legacy formats on filesystems that support them and test the
platform-independent parser separately. POSIX process-group tests must be
skipped or replaced by Windows-appropriate lifecycle assertions.

When a manual experiment finds a deterministic regression, add an automated
test before considering the issue closed. Keep subjective presentation checks in
the manual checklist.

## Change and release workflow

- Separate fixes from new features so a patch release can be validated and
  published without unreleased feature work.
- Keep commits cohesive even when several commits will ship in one release.
- Do not push, tag, publish, or rewrite shared history unless explicitly asked.
- New behavior belongs in a minor release; patch releases contain compatible
  fixes. During `0.x`, still avoid unnecessary incompatibility.
- Before release, require a clean worktree, the full local validation sequence,
  and successful CI for the exact candidate commit.
- Follow the repository's release history: first replace `Unreleased` with the
  local release date in a changelog commit, then update `pyproject.toml`, run
  `uv sync`, and commit `pyproject.toml` plus `uv.lock` as
  `Bump version to X.Y.Z`. Run local validation and CI again on that exact commit.
- Move the main branch and create the version tag only after the final CI passes.

Never weaken tests merely to make CI green. First determine whether the failure
is a product defect, a platform-invalid test, or a formatting/lockfile mismatch.
