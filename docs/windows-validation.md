# Validate a Git checkout on Windows

The [2026-09-23 native validation findings](windows-native-results.md) record
the pinned baseline, reproduced defects, and the console method and its limits.

Use native Windows Python and PowerShell/cmd. WSL or Linux containers do not
validate Windows process and console behavior. Read `AGENTS.md`, `README.md`,
`CONTRIBUTING.md`, `docs/ownership.md`, and `tests/manual/README.md` first.

## Pin and collect the baseline

Use a dedicated checkout at the commit supplied with the validation request.
Record `git rev-parse HEAD` and `git status --short`. Do not silently pull midway
through a test. The checkout must be clean; commit any subsequent intended fixes
on a separate branch before collecting their results.

Use existing Git, uv, Python and Node when available. Missing tools can be
provisioned from their official sources into a user-writable test directory.
Keep environment changes local to the shell; no administrator access, global
PATH changes, execution-policy changes, or user agent configuration is needed.

From the repository root:

```powershell
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.local\python'
$env:UV_CACHE_DIR = Join-Path $PWD '.local\uv-cache'
uv run --no-project --python 3.13 scripts/validate_checkout.py --python 3.13
uv run --no-project --python 3.13 scripts/validate_checkout.py --python 3.8
```

Alternatively, invoke the script with an existing Python 3.8+ interpreter. It
archives the exact commit into `.local/validation/`, exports locked dependencies,
builds a wheel, verifies its Python source bytes, and tests the installed wheel
outside the source import path. It records the commit, archive/wheel hashes,
actual interpreter/import path, commands, exit codes and raw logs in `evidence.zip`.
It runs on other platforms too, recording them accurately; that is not Windows
evidence. The repository package version may still be 0.4.0 during development:
identify this unreleased build by commit and hash, never by version alone.

Keep failed baseline evidence. A download failure is an environment failure,
not a product failure or passing test. After a timeout, inspect test-owned
children before continuing: terminating the test runner alone may leave children.
If only lint installation failed, complete that step without repeating unrelated
successful lifecycle tests. Do not install the older public PyPI build instead.

## Native scenarios beyond CI

Use the generated `venv/Scripts/python.exe -m dmon` consistently. Create isolated
fixtures under `.local/`; bind only loopback and choose unused ports. Capture
PID plus creation time for processes you start, including wrappers and children.
Never kill by executable name or by port, or change unrelated running services.
No Docker, real accounts, paid APIs or external database is required.

| Scenario | Required evidence |
| --- | --- |
| npm wrapper | A dependency-free `npm run dev` starts a Node HTTP server through a Windows-appropriate npm.cmd/cmd invocation. Owned readiness succeeds, actual responses are checked, and down removes the wrapper and Node descendants. |
| Closing a terminal | Start detached in terminal A, close A, and inspect from a new terminal B. Same PID/creation time, working endpoint, finite logs, then complete cleanup. Two CLI calls in one shell do not establish terminal-close behavior. |
| Foreground console | Ctrl+C cleans the owned process tree. Separately, another terminal's down stops the foreground stack. TerminateProcess is not a substitute for Ctrl+C. If the available console cannot receive a real interrupt, report this as untested and provide the shortest manual steps. |
| Recovery | Confirm automated supervisor-crash/parent-exit recovery actually ran on Windows. Previously observed children must remain identifiable and cleanable through a new CLI. |
| Ownership failures | Confirm copied records, invalid identities, foreign listeners, and partial-start rollback ran and passed. Preserve original/foreign processes and ambiguous records. Reuse adequate suite evidence rather than repeat it mechanically. |
| Paths and logs | Use a directory containing spaces and non-ASCII characters, and invoke config from another cwd. Check rotation, closed/reopened log handles, and that interrupting log follow leaves the services unchanged. |

Record OS/build/architecture, Python/uv/Node/npm versions, terminal, privileges,
and every skip with its reason. Existing POSIX-only skips are legitimate but do
not satisfy the native console checks above. Use the manual lab's behavior as
the contract, translating commands to Windows syntax.

## Fix and return evidence

When the task authorizes fixes and Git synchronization, create a dedicated fix
branch from the recorded baseline. Preserve the failing reproduction, fix the
smallest relevant layer, and add a regression test for deterministic defects.
Distinguish product defects, platform-invalid fixtures, and harness failures.
Do not weaken ownership checks, add unjustified skips, or loosen assertions to
obtain a green run. Commit fixes and validate the resulting clean commit, then
push only that fix branch when authorized. Do not merge the validation branch,
change main/dev, force-push, tag or publish a release.

Return the baseline and final commit IDs, fix branch (or `no product changes`),
and a small `windows-results.zip` containing:

- Summary of environment, baseline/final results, test and skip counts/reasons,
  unresolved failures, and each native scenario's actual completion status.
- Raw automated evidence archives and native fixture scripts, command results,
  actual responses, and process identities needed to reproduce findings.
- Cleanup report verifying only the test-owned PID/creation-time pairs, with any
  preserved failure evidence. A closed window is not cleanup evidence.

Keep runtime files, virtual environments, caches, real environment variables,
unrelated machine logs, and personal paths out of public commits. Raw diagnostic
archives remain local and are returned privately to the owner. Public commits
may contain sanitized findings and reproductions. Continue follow-up validation
in the same agent task; a separate fresh-agent experiment is a different test.
