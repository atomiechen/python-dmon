# Native Windows validation, 2026-09-23

Baseline: `43dad2714de251302af8ec1415fa3ffb8c115660` from
`codex/windows-validation`. Fix branch: `codex/windows-native-validation`.
This is an unreleased checkout; the package's `0.4.0` version alone does not
identify it. Private evidence records exact commits and archive/wheel hashes.

## Environment and baseline

Native Windows 11 build 22631, AMD64, non-administrator; CPython 3.13.7 and
3.8.6, uv 0.10.8, Node 22.23.2, npm 10.8.1. Dependencies, fixtures and caches
were isolated; no global settings, WSL, containers or unrelated services were
used. Only loopback listeners and identified test process trees were controlled.

The baseline installed-wheel suite ran 137 tests per interpreter: Python 3.13
passed, while Python 3.8 had four failures. Each reported nine existing skips:
POSIX signal/process-group cases, Windows-invalid legacy colon filenames, and
moving a running process's working directory. The copied-record subcases before
that move-only skip actually ran; the whole ownership scenario was not omitted.
One Python 3.8 development-dependency download timed out. The original archive
was retained, and installation/lint were completed separately through a
process-local proxy without rerunning successful lifecycle tests.

## Reproduced defects and fixes

- Python 3.8 on Windows can return a relative path from `Path.resolve()` when
  parent directories do not exist. New standalone records then fail their own
  absolute-location ownership check. Anchor new task/stack output paths before
  resolution, including the CLI's selected metadata paths. Keep location and
  PID/creation-time checks intact. Regression coverage starts and stops tasks
  with new nested relative paths both with and without rotation.
- The rotation launcher split shell text and later joined it, losing quoting.
  A quoted absolute `npm.cmd` path containing spaces failed under rotation.
  Pass the original shell text as one runner argument. A real-process regression
  checks a script path containing spaces, a spaced argument and a quoted shell
  metacharacter.
- A subsequent full run encountered transient `PermissionError` while reading
  stack metadata. A native `CreateFileW` exclusive handle released after 50 ms
  reproduced the baseline failure. Retry Windows read permission errors for at
  most 0.5 seconds, then propagate failure. Tests cover transient recovery,
  bounded persistent denial with record preservation, and location rejection
  after retry. Invalid JSON, identity and ownership checks are not bypassed.

An initial npm invocation failed its six-second owned-readiness deadline before
producing output. The unchanged baseline fixture passed on retry; its original
failure is retained as an unexplained one-off startup delay, not counted as a
fixed product defect. No readiness assertion or deadline was relaxed.

## Native scenarios

All scenarios below passed with the fixes. The final installed-wheel reruns and
their exact commit IDs are recorded in the private `windows-results.zip`.

| Scenario | Evidence and result |
| --- | --- |
| npm wrapper | Dependency-free `npm.cmd run dev`, direct and rotating, plus quoted shell form; owned readiness and response token/PID checked; wrappers and Node descendants removed. |
| Terminal close | Detached startup in a private native console A; `WM_CLOSE` sent to that console window; A exited; new consoles inspected logs/status and stopped the same surviving PID/creation-time identities. |
| Foreground Ctrl+C | Real `GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0)` delivered to a private console; stack exited successfully and owned trees disappeared. No `TerminateProcess` substituted for the interrupt. |
| Cross-terminal down | Separate native consoles for foreground supervision and down; supervisor exited and metadata/processes were removed. |
| Paths/logs | Chinese and spaced directories, config invoked from another cwd, retained rotation archives, follow interrupted by a console Ctrl+C event, same services still healthy afterward, and archive opened exclusively to verify handle release. |
| Direct exec | A signal-counting child recorded one SIGINT and exited successfully under the same native console event. |
| Recovery/ownership | Installed-wheel tests exercised supervisor crash and observed-child recovery, copied records, invalid identities, foreign listeners and rollback. |
| Manual lab | Isolated copy with free ports: start/status/restart/stop, partial multi-start, exited state, trees, rotation, concurrent start, rollback, detached restart, foreground restart rejection, reverse-order three-service Ctrl+C cleanup, degradation and abort-on-exit. |

The consoles were hidden classic Windows consoles created with
`CREATE_NEW_CONSOLE`, with their HWND and console membership recorded. Output was
captured to files. This verifies OS console events and console destruction; it
does not claim physical keyboard input, Windows Terminal tab behavior, or a
human assessment of colors and layout. For that optional visual check, use the
installed-wheel Python path as `$py` and an evidence fixture's config as `$cfg`:

```powershell
& $py -m dmon stack up dev -c $cfg
# Press Ctrl+C, then confirm status is no longer running.
& $py -m dmon stack up -d dev -c $cfg
# Close this terminal; in a new terminal set the same $py and $cfg:
& $py -m dmon stack status dev -c $cfg
& $py -m dmon stack logs -f dev -c $cfg
# Press Ctrl+C; status must still be running, then clean up:
& $py -m dmon stack down dev -c $cfg
```

Raw failures, commands, process identities, responses and machine paths remain
private. Public changes contain only fixes, regressions and this sanitized
summary. No main/dev merge, force push, tag or release is part of this validation.
