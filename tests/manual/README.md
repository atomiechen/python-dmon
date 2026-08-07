# Manual lifecycle test lab

Run this lab after changes to process lifecycle, signals, logs, CLI presentation,
configuration paths, or stack supervision. Automated tests remain mandatory;
this lab covers terminal behavior and real-process interaction.

## Setup and cleanup

From the repository root:

```sh
uv sync --locked --dev
cd tests/manual
export PATH="$(git rev-parse --show-toplevel)/.venv/bin:$PATH"
dmon --version
python reset.py
```

PowerShell setup:

```powershell
uv sync --locked --dev
Set-Location tests/manual
$repo = git rev-parse --show-toplevel
$env:Path = "$repo\.venv\Scripts;$env:Path"
dmon --version
python reset.py
```

Run `python reset.py` between scenarios. It stops recorded tasks before deleting
runtime state. Use `python reset.py --force` only after inspecting a failure and
confirming no test process should be preserved.

The examples below use POSIX exit-code syntax; use `$LASTEXITCODE` in PowerShell.
The forced process-group and `/tmp` scenarios are POSIX-specific. Windows-native
process cleanup remains covered by the automated Windows CI matrix.

## Individual task lifecycle

### Normal operation and foreground signals

```sh
dmon start heartbeat
dmon status heartbeat
dmon list
dmon restart heartbeat
dmon stop heartbeat
dmon status heartbeat; echo "exit=$?"  # expected: non-zero
dmon exec heartbeat                    # press Ctrl-C after several ticks
```

Status fields should be readable, restart should change the PID, and Ctrl-C
should produce one signal message followed by a clean exit.

### Config-relative paths and case normalization

```sh
cd /tmp
dmon start -c /absolute/path/to/python-dmon/tests/manual HEARTBEAT
dmon stop -c /absolute/path/to/python-dmon/tests/manual heartbeat
cd -
```

Replace the example with the real absolute path. Runtime files must remain under
`tests/manual`, regardless of the caller's directory.

### Best-effort multi-start

```sh
dmon start heartbeat missing; echo "exit=$?"
dmon status heartbeat
dmon stop heartbeat
```

Expected: non-zero, a concise error naming `missing`, an explicit best-effort
summary, and `heartbeat` remains running until stopped.

### Exited and corrupt metadata

```sh
dmon start short
sleep 1
dmon status short; echo "exit=$?"
dmon stop short
dmon start short
sleep 1
dmon start short

mkdir -p .dmon
printf '{broken' > .dmon/heartbeat.meta.json
dmon status heartbeat; echo "exit=$?"
dmon start heartbeat; echo "exit=$?"
test -f .dmon/heartbeat.meta.json && echo "corrupt file preserved"
python reset.py --force
```

Exited state returns non-zero and can be cleaned or restarted. Corrupt metadata
produces no traceback and remains available for diagnosis.

### Process-tree cleanup and escalation

```sh
dmon start tree
sleep 1
python check_pids.py state/tree.pids; echo "exit=$?"  # expected: 1 while live
dmon stop tree
python check_pids.py state/tree.pids; echo "exit=$?"  # expected: 0

dmon start stubborn
sleep 1
time dmon stop stubborn
python check_pids.py state/stubborn.pids; echo "exit=$?"
```

Parent and child must both exit. The stubborn tree should be force-killed after
about five seconds, with a clear escalation message and no residual PID.

### Rotation and retention

```sh
dmon start burst
sleep 2
dmon stop burst
ls -lh logs/burst*
```

Both log streams use `YYYYMMDD-HHMMSS`; same-second collisions use numeric
suffixes. Because the fixture has no backup counts, multiple archives must remain.
The active files should stay near their configured limits, allowing one long line.

### Concurrent start and ad-hoc command parsing

Run `dmon start heartbeat` in two terminals at nearly the same time. Exactly one
must succeed. Stop the successful task afterward.

```sh
cd /tmp
dmon run --name adhoc --meta-file /tmp/adhoc.meta.json \
  --log-file /tmp/adhoc.log python -c 'import time; time.sleep(30)'
dmon status --meta-file /tmp/adhoc.meta.json
dmon stop --meta-file /tmp/adhoc.meta.json
```

No config is required. Child options work without `--`; adding it remains valid.

## Supervised stacks

### Healthy startup and Ctrl-C cleanup

```sh
dmon up healthy
```

Wait for every task to report ready, then press Ctrl-C. Tasks must stop in reverse
dependency order and leave no metadata. Output should distinguish readiness,
runtime logs, shutdown, and errors without relying only on color.

Repeat once with two terminals. The `exec` keeps the printed shell PID when it
becomes `dmon`, so there is no process-search ambiguity:

```sh
# Terminal 1
sh -c 'echo "dmon up PID=$$"; exec dmon up healthy'

# Terminal 2: replace 12345 with the PID printed above
kill -TERM 12345
```

It must perform the same reverse-order cleanup without a traceback. This checks
the foreground supervisor; detached supervision is tested separately below.

### Startup rollback

```sh
dmon up startup-failure; echo "exit=$?"
dmon status stack-db; echo "exit=$?"
```

The missing task causes non-zero startup failure. `stack-db`, which started first,
must be stopped and have no live metadata.

### Runtime failure cleanup

```sh
dmon up runtime-failure; echo "exit=$?"
dmon status stack-db; echo "exit=$?"
```

The stack first becomes ready; then `delayed-failure` exits. The command returns
non-zero and cleans the remaining task.

### Readiness timeout

```sh
dmon up readiness-timeout; echo "exit=$?"
dmon status never-ready; echo "exit=$?"
```

The probe must retry quietly until the configured deadline, then report one
actionable timeout, return non-zero, and stop the task without stale metadata.

### Detached lifecycle and recovery

```sh
dmon up -d healthy
dmon status --stack healthy
dmon up -d healthy; echo "duplicate_exit=$?"
dmon down healthy
dmon status --stack healthy; echo "status_exit=$?"
```

Startup waits for readiness before returning. Status must show one supervisor
and all three tasks running; the duplicate start must fail without disturbing
them. `down` must stop tasks in reverse order and remove stack and task metadata.

Test supervisor-crash recovery once on each operating system:

```sh
dmon up -d healthy
dmon status --stack healthy  # note the SUPERVISOR PID

# Terminate that PID without allowing graceful cleanup. POSIX:
kill -KILL 12345

# PowerShell:
Stop-Process -Id 12345 -Force

dmon status --stack healthy; echo "status_exit=$?"
dmon down healthy
```

Replace `12345` with the displayed PID. Status should report an orphaned stack,
and `down` must still remove every owned process and metadata file. The recovery
must use persisted PID plus creation time; it must not stop an unrelated process
that reused a PID or merely shares a task name.

## Presentation checklist

- Can a user distinguish task names, states, warnings, and errors immediately?
- Are exit codes intuitive and error messages actionable without a traceback?
- Is signal escalation clear without being noisy?
- Are status tables readable at a normal terminal width?
- Does every scenario leave no process or metadata after cleanup?
