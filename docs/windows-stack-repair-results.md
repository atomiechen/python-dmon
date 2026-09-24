# Windows stack repair validation — 2026-09-24

## Identity and environment

- Baseline SHA: `7d0e084dddaf2e4f61a49765d60074205a32cd62`.
- Exact final tested commit: `e34bcad6ef9e9bf2dd068da99469b515db7b61a4`.
- Input branch: `codex/stack-repair-validation`.
- Return branch: `codex/windows-stack-repair-validation`.
- Product code is unchanged. A small test-fixture timing correction is described
  below. This report is a subsequent documentation-only commit; the final suite
  tests ran on the tested commit above. The final report commit is identified in
  the Git handoff response.
- Native Windows 11 build 22631, AMD64, non-administrator;
  CPython 3.13.7 and 3.8.6; uv 0.10.8 (c021be36a 2026-03-03); Node v22.23.2,
  npm 10.8.1; PowerShell 7.6.5.
- Used an independent worktree, preserving the previous checkout and Windows
  evidence. Dependencies and fixtures were isolated; environment changes were
  process-local. No WSL, Docker, model trials or model delegation were used.

## Installed-wheel results

| Python (final tested commit) | Total | Passed | Skipped | Failures/errors | Repair tests |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.13.7 | 157 | 148 | 9 | 0 | 14/14 passed, none skipped |
| 3.8.6 | 157 | 148 | 9 | 0 | 14/14 passed, none skipped |

Both clean-commit runs of `scripts/validate_checkout.py` passed all steps:
locked dependency export/install, wheel build, byte comparison against archived
Git source, installed-package import identity outside the source path, complete
unittest discovery, Ruff checks and Ruff format checks. The build is unreleased;
the shared package version `0.4.0` is not used as its identity.

### Preserved baseline failure and test-fixture correction

The pinned baseline ran 157 tests per interpreter. Python 3.13 passed with nine
skips. Python 3.8 had one failure and nine skips: the foreign-listener repair
test could not establish its initial owned HTTP server within the fixture's
0.5-second readiness budget. It failed before the foreign-listener phase.
The same unmodified test failed on three isolated reruns, without the process
observer or concurrent native scenarios.

Only this fixture's readiness budget was changed from 0.5 to 5 seconds, allowing
native Windows interpreter launch and socket-ownership inspection to complete.
The negative repair still waits out its configured readiness deadline and must
return nonzero with `listener-unverified`; the foreign HTTP server must still
respond and the healthy peer must remain alive. Every ownership/result assertion
and `require_owned: true` remain unchanged. Three isolated Python 3.8 reruns then
passed, followed by the complete source quick-start sequence and both clean-commit
installed-wheel suites. No product change, new skip or additional model trial
was introduced. Original failure logs are preserved locally.

All 14 repair tests ran natively on both interpreters. These include preserved
launch environments despite config/dotenv edits; replacement-only readiness
rollback; foreign-listener rejection; standalone replacement refusal; concurrent
clients and repeated operation IDs; client timeout/recheck; supervisor crashes
before/after recording a replacement; unresolved spawn-journal preservation;
corrupt operation records; and repair/down interaction. Adequate suite evidence
was reused rather than repeating these scenarios manually.

Existing skips on each interpreter (no new skips or weakened assertions):

- `test_exec_delivers_terminal_sigint_once`: 'POSIX foreground process groups only'
- `test_stop_kills_process_group_after_grace_period`: 'POSIX process groups only'
- `test_foreground_sigterm_cleans_owned_tasks_and_metadata`: 'SIGTERM is POSIX-specific'
- `test_copied_or_moved_records_cannot_control_original_processes`: "Windows may lock a running process's cwd"
- `test_foreground_incomplete_cleanup_retains_stack_evidence`: 'POSIX process groups'
- `test_unobserved_orphan_is_not_killed_or_reported_as_cleaned`: 'POSIX process groups'
- `test_archive_discovery_accepts_legacy_runner_timestamp`: "legacy ':' filenames cannot exist on Windows"
- `test_configured_backup_count_recognizes_legacy_runner_archives`: "legacy ':' filenames cannot exist on Windows"
- `test_ctrl_c_returns_130_without_a_traceback`: 'POSIX signal semantics'

The copied-record test completed its task, stack, orphaned and legacy subcases
before skipping only the Windows-inapplicable running-directory move subcase.

## Native repair scenarios

Each scenario ran on both baseline installed wheels, using separate hidden native
Windows consoles (`CREATE_NEW_CONSOLE`) with their HWND and console membership
recorded. CLI stdout/stderr, exit codes, before/after stack records, HTTP bodies,
and PID/creation-time identities remain in private evidence.
`git diff` confirms that product source under `src/` is identical between the
baseline and final tested commit, and all four baseline/final wheel SHA-256
hashes are identical. The same native evidence therefore covers the product
bytes in the final tested commit.

1. **Detached repair from a new console:** launched three dependent services,
   checked and terminated only the saved worker identity, observed degradation,
   and repaired through a new console. Supervisor/run identity, database and API
   identity pairs were unchanged. The worker received a new identity in the same
   stack. API `/health` returned HTTP 200 with body `ok` before failure, while
   degraded, and after repair. Down from another console stopped originals and
   replacement and removed task/stack metadata.
2. **Foreground repair from a second console:** the original console stayed
   attached while another repaired the worker. Output containing the replacement
   worker's actual PID resumed in the original console. Healthy peers and the
   supervisor were unchanged; cross-console down exited the supervisor cleanly
   and stopped the complete owned tree.
3. **Windows npm wrapper:** dependency-free `npm.cmd run dev` launched a Node
   HTTP worker. Required owned-listener readiness passed before and after repair;
   response token and actual Node PID matched the recorded descendant. Before
   terminating the old root, the harness waited for its live children to appear
   in the supervisor's persisted ancestry. Repair cleaned the old observed tree,
   created a new wrapper/Node tree, preserved healthy peers, and subsequent down
   removed both original members and the replacement's observed children.

All fixture paths contained spaces and Chinese characters, and commands selected
config from another working directory. Repair JSON was finite, parseable, free
of ANSI and unrelated output; successful repairs returned `state: done` and
`exit_code: 0` with empty stderr. All fixture listener ports were closed after
down. No process was selected for termination by name or port.

The following are short SHA-256 fingerprints of `[PID, creation_time]`, not raw
runtime records. Healthy fingerprints were explicitly compared before/after;
the child counts include observed wrapper/console descendants where applicable.

| Python | Scenario | Database | API | Worker before → after | Worker children before → after |
| --- | --- | --- | --- | --- | --- |
| 3.13 | detached | 9a4d51804216 (unchanged) | 017e7cbc05fd (unchanged) | df9b152f1b86 → 4a1ddb20d7f9 | 2 → 2 |
| 3.13 | foreground | 802063c7b52f (unchanged) | b89da3bf0109 (unchanged) | dc2e972d69ae → 4e7bbea44486 | 2 → 2 |
| 3.13 | npm-wrapper | 8575f1dd986a (unchanged) | eb8b2367bb9e (unchanged) | 871f8103b7e9 → 23c7e9a4535b | 4 → 4 |
| 3.8 | detached | 2a93dc615aa4 (unchanged) | feeda152d5f8 (unchanged) | 80a55d5e6b47 → 5ed3bf4eec98 | 2 → 2 |
| 3.8 | foreground | b74b319699e2 (unchanged) | 3bafc6e7d155 (unchanged) | b8db8a3bd195 → ad93e7d39434 | 2 → 2 |
| 3.8 | npm-wrapper | f231625c34a7 (unchanged) | 39b2b8a6419d (unchanged) | c66ce774b436 → f98df5140875 | 4 → 4 |

## Cleanup and limitations

The final suite observers recorded 1037 identities for 3.13 and 1040 for 3.8.
Native console scenarios recorded 67 and 67, respectively. Final PID/creation-time
rechecks, also including both preserved baseline suite runs, covered **4291
distinct identities, zero still alive**; a read-only scan found no remaining
processes referencing this worktree.
The suite's normal fixture cleanup and native `stack down` performed cleanup;
the observers did not terminate anything. Polling does not establish universal
containment of arbitrary unobserved descendants.

No required repair scenario remains incomplete. The baseline timing failure was
resolved by the test-only correction above. Physical keyboard input, visible
Windows Terminal/PowerShell tab behavior and subjective color/layout review were
not performed or claimed. Unaffected
Ctrl+C, terminal-close, Unicode and log-follow behavior reuses the earlier
[native Windows evidence](windows-native-results.md), as permitted by the repair
handoff; this run additionally exercised Unicode paths through repair itself.
This is local Windows validation, not a claim that other platforms or remote CI
passed. No CI was manually dispatched, no branch was merged or force-pushed,
and no tag or release was published.

## Evidence location and hashes

Raw logs, commands, fixtures, observations and summary are retained locally under
the worktree's ignored `.local/validation/`. They contain local paths and runtime
records and are deliberately excluded from Git. The standard runner's evidence
archives stay local; no transfer bundle was requested or produced.

| Python | Wheel SHA-256 | Local evidence archive SHA-256 |
| --- | --- | --- |
| 3.13 | `29eaeae2e80b2ba22dc0749c608320fc4dc70dbba7ef4a9f9d3deab076eea1ef` | `9445e915fcf854f9be4c471e0a973d28221320f706d695663b9a656f7b765614` |
| 3.8 | `29eaeae2e80b2ba22dc0749c608320fc4dc70dbba7ef4a9f9d3deab076eea1ef` | `92126c1a9b6e5ea7daa6e7a7b716276a5db8456bb57699342043a44cb3354a24` |
