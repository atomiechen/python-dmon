# Local service ownership

These behaviors are in the working tree and are not part of the published
0.4.0 package yet.

## Verify the service you started

A successful HTTP/TCP request proves that an endpoint responds. By itself it
does not prove that the newly started task serves that endpoint. This matters
when another application already owns the port while your application is still
initializing.

For a task that should own its readiness endpoint, opt in explicitly:

```yaml
tasks:
  api:
    cmd: [uv, run, uvicorn, app:app, --host, 127.0.0.1, --port, "8000"]
    ready:
      http: http://127.0.0.1:8000/health
      require_owned: true
      timeout: 30
stacks:
  dev: [api]
```

The same option works with `tcp: {host: 127.0.0.1, port: 8000}`. It requires a
literal loopback address, such as `127.0.0.1` or `::1`; hostnames, remote
addresses, and command probes are rejected. It is used by stack startup,
configured `dmon wait`, and `Dmon.wait()`.

Before and after a successful probe, dmon looks for a matching listening socket
in the identified task or its descendants. If it cannot verify that listener by
the deadline, the result is `listener-unverified`. This includes permissions that
prevent socket inspection. The result does not assert that a foreign process
exists, and never authorizes reuse, adoption, or termination of another service.
An HTTP failure on a verified listener remains an ordinary readiness timeout.

Leave this option disabled for a task that intentionally probes an external
dependency. Direct `dmon wait --http ...` and `--tcp ...` remain external probes.
Shared listening sockets, forwarded connections, and hostile processes are not
covered by this identity check; it is not cryptographic response authentication.

## Recover a stack after a supervisor crash

Use finite status and logs first:

```sh
dmon stack status dev --format json
dmon stack logs --tail 100 dev
```

An orphaned supervisor does not mean that the application processes have exited.
Stack snapshots include `live_descendant_pids` for descendants whose recorded
PID and creation time still match. Once stopping the stack is appropriate, run:

```sh
dmon stack down dev
```

Down uses the identities recorded by that stack invocation, including observed
descendants whose parent has since exited. It does not search by command name
or terminate whatever currently occupies a port. To restart, stop successfully
before starting the stack again. Stop running stacks before switching between
versions that write different ownership metadata; do not downgrade while a new
version's stack is active.

## Copied or moved projects

Stop running services before copying runtime records or moving a project. A
record whose saved location differs from the file being read is rejected with
`metadata-location-mismatch`; status, start, wait, and stop must not silently
adopt that record. The record stays available for diagnosis and the original
processes stay untouched. Resolve the original run from its original location;
do not edit the stored paths simply to bypass the check.

New stack records save their metadata location explicitly. Published legacy
stacks derive it from their saved configuration path and the fixed `.dmon`
layout. Task records already contain their metadata path. Symlink aliases that
resolve to the same location are accepted. Records without any location
evidence retain legacy behavior; the check is not protection against edited
records, cross-machine copies at identical paths, or hostile local processes.
Moving a live project is deliberately not an automatic ownership transfer.

## What is and is not guaranteed

The supervisor observes ancestry during readiness and runtime polling, persisting
changes to its stack record. It can clean those identified descendants after a
parent exit or supervisor crash. If it sees unverified residual members of a
former task process group on POSIX, it leaves them untouched, returns failure,
and retains metadata. Starting over must not silently discard that evidence.

Polling is not an OS containment primitive. A child that forks and escapes before
observation may remain unknown; Windows and self-daemonizing programs have no
portable equivalent of this POSIX group diagnostic. Prefer foreground commands
under a supervised stack. Standalone `start`/`run` do not continuously observe
descendants. A machine crash, edited metadata, privileged adversaries, and total
cleanup of arbitrary daemonized descendants are outside this contract.

Readiness and status are point-in-time observations. They cannot guarantee the
service stays alive after the command returns. A PID plus its creation time
protects against ordinary PID reuse, but is not an authorization boundary
between processes running as the same OS user. No environment contents are
added to the ownership records.

## Record compatibility and scope

A saved identity needs both a numeric PID and a finite creation time. Missing or invalid
process identities and unrecognized fields cause a read error; control leaves that record
and its processes untouched. The explicit `-1/-1` reservation is allowed before
a process is launched. Legacy records without newly added optional descendant or
stack-location fields remain readable. This is an additive, unversioned format;
unknown fields are rejected rather than silently ignored. Stop active services
before downgrading to a reader that does not know the newer fields.

Records are local to one machine and runtime directory. dmon does not record a
machine or boot identifier. Do not synchronize `.dmon/`, restore it from a backup
onto another machine, or use a shared runtime directory between machines. The
path check cannot distinguish two machines with identical absolute paths.
Creation time rejects ordinary stale identities after restart, but is not a
cross-machine guarantee. A machine restart is outside recoverable run continuity.

Changing valid configuration does not change the identities owned by an existing
stack: stopping it uses its saved ownership. Status describes the saved run, not
proof that it matches the edited configuration. There is no config-drift
reconciler or automatic restart. If configuration becomes invalid or its stack is
removed, restore the last valid configuration before using the normal named CLI
workflow to stop the run. Keep config changes separate from active-run recovery.
