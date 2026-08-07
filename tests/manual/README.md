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

## Standalone readiness waiting

Configured waits observe an already managed task and do not change its
lifecycle:

```sh
dmon start stack-db stack-api
dmon wait stack-db stack-api
dmon wait stack-db --format json
dmon status stack-db
dmon stop stack-api stack-db
```

Both tasks must report ready, remain running after each wait, and stop only when
explicitly requested. Direct probes work without task metadata:

```sh
dmon start stack-api
dmon wait --http http://127.0.0.1:48732/health
dmon wait --timeout 0.5 --tcp 127.0.0.1:48733; echo "exit=$?"  # expected: non-zero
dmon wait --timeout 1 --command -- python -c "raise SystemExit(0)"
dmon wait --timeout 0.5 --command -- python -c "raise SystemExit(1)"; echo "exit=$?"
dmon stop stack-api
```

The successful probes return zero; the refused TCP connection and failing
command return one after their timeout without a traceback. Finally run the
following and press Ctrl-C; it must return 130, print one interruption message,
and leave no sleeping child process:

```sh
dmon wait --timeout 30 --command -- python -c "import time; time.sleep(30)"
```

## Supervised stacks

### Healthy startup and Ctrl-C cleanup

```sh
dmon stack up healthy
```

Wait for every task to report ready, then press Ctrl-C. Tasks must stop in reverse
dependency order and leave no metadata. Output should distinguish readiness,
runtime logs, shutdown, and errors without relying only on color. New task output
must appear automatically with a task-name prefix; no second `logs -f` command
should be needed.

Repeat once and, while Terminal 1 remains attached, run these in Terminal 2:

```sh
dmon stack status healthy
dmon stack list
dmon stack restart healthy; echo "restart_exit=$?"
dmon stack down healthy
```

Status and list must identify `foreground` mode and all member tasks. Restart
must be rejected without changing the running stack. Down must request clean
reverse-order shutdown; Terminal 1 should then exit successfully with no stale
metadata.

Repeat once more with two terminals. The `exec` keeps the printed shell PID when it
becomes `dmon`, so there is no process-search ambiguity:

```sh
# Terminal 1
sh -c 'echo "dmon stack up PID=$$"; exec dmon stack up healthy'

# Terminal 2: replace 12345 with the PID printed above
kill -TERM 12345
```

It must perform the same reverse-order cleanup without a traceback. This checks
the foreground supervisor; detached supervision is tested separately below.

### Startup rollback

```sh
dmon stack up startup-failure; echo "exit=$?"
dmon status stack-db; echo "exit=$?"
```

The missing task causes non-zero startup failure. `stack-db`, which started first,
must be stopped and have no live metadata.

### Runtime degradation and fail-fast cleanup

Terminal 1:

```sh
dmon stack up runtime-failure
```

After `delayed-failure` exits, inspect the remaining task from Terminal 2:

```sh
dmon status stack-db; echo "exit=$?"
```

The stack first becomes ready; then `delayed-failure` exits. The foreground
supervisor must report degradation while `stack-db` keeps running. Press Ctrl-C;
the remaining task and metadata must then be cleaned.

```sh
dmon stack up --abort-on-exit runtime-failure; echo "exit=$?"
dmon status stack-db; echo "exit=$?"
```

With the explicit policy, the runtime exit must return non-zero and clean the
remaining task automatically.

### Readiness timeout

```sh
dmon stack up readiness-timeout; echo "exit=$?"
dmon status never-ready; echo "exit=$?"
```

The probe must retry quietly until the configured deadline, then report one
actionable timeout, return non-zero, and stop the task without stale metadata.

### Detached lifecycle and recovery

```sh
dmon stack up -d healthy
dmon stack status healthy
dmon stack list
dmon stack up -d healthy; echo "duplicate_exit=$?"
dmon stack restart healthy
dmon stack down healthy
dmon stack status healthy; echo "status_exit=$?"
```

Startup waits for readiness before returning. Status must show one supervisor
and all three member tasks, including their individual states and process trees;
the list must include the stack summary. The duplicate start must fail without
disturbing them. `down` must stop tasks in reverse order and remove stack and
task metadata. Restart must replace the supervisor and leave the stack healthy.

Test degraded detached behavior:

```sh
dmon stack up -d runtime-failure
sleep 2
dmon stack status runtime-failure; echo "status_exit=$?"
dmon stack down runtime-failure
```

Status must be `Degraded`, return non-zero, and show `stack-db` still running.

### Read-only stack logs

```sh
dmon stack up -d healthy
dmon stack logs --tail 2 healthy
dmon stack logs --tail 0 -f healthy
```

The snapshot and follow output must prefix every line with its task name. Press
Ctrl-C while following, then run `dmon stack status healthy`: the same
supervisor and tasks must still be running. Finish with `dmon stack down healthy`.

Test supervisor-crash recovery once on each operating system:

```sh
dmon stack up -d healthy
dmon stack status healthy  # note the SUPERVISOR PID

# Terminate that PID without allowing graceful cleanup. POSIX:
kill -KILL 12345

# PowerShell:
Stop-Process -Id 12345 -Force

dmon stack status healthy; echo "status_exit=$?"
dmon stack down healthy
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
