# Native Windows validation of stack repair

This is the unreleased repair candidate, not the published 0.4.0 package. Use the
exact commit supplied in the handoff message. Continue the existing Windows
validation task; this is engineering verification, not a fresh-agent benchmark.
Do not launch additional model trials or delegate to other models.

## Git handoff

Fetch `origin/codex/stack-repair-validation` from this repository. Preserve the
current checkout and its local files: use a dedicated worktree or clean clone
at the supplied SHA rather than resetting or cleaning an existing worktree.
Record the baseline SHA and confirm a clean status before testing.

Read `AGENTS.md`, `CONTRIBUTING.md`, `docs/ownership.md`, and
`docs/windows-validation.md`. The latter explains the native runner and evidence
collection. From the pinned checkout, run:

```powershell
uv run --no-project --python 3.13 scripts/validate_checkout.py --python 3.13
uv run --no-project --python 3.13 scripts/validate_checkout.py --python 3.8
```

The runner builds from Git, verifies the wheel's source bytes, and tests the
installed wheel. This avoids uv reusing an older wheel at the same pathname and
version. Keep the failed baseline if anything fails. Never substitute PyPI dmon.

## Scope

The Mac baseline has 157 total tests, including 14 new repair tests. Report actual
Windows counts and skip reasons; existing POSIX-only skips do not validate Windows
behavior. All repair tests should execute on native Windows.

Use the suite evidence for retained environments, readiness rollback, foreign
listeners, concurrent requests, repeated operation IDs, supervisor crash recovery,
uncertain-launch records, and repair/down interaction. Do not repeat those cases
manually without a gap or failure to investigate.

Additionally run the repair section of `tests/manual/README.md` in an isolated
fixture with native Windows processes, including these observable outcomes:

- Detached: stop one recorded worker; repair from a new terminal; healthy API
  and dependency PID/creation-time pairs remain the same, real HTTP works, and
  subsequent down stops the new worker as well as original members.
- Foreground: repair from a second terminal while the original terminal stays
  attached; worker output resumes; cross-terminal down stops the owned tree.
- Exercise a Windows command wrapper (reuse the earlier dependency-free npm
  fixture if available). Verify repair and cleanup include its observed children.

Reuse earlier console/key/Unicode evidence where the changed path does not affect
it. Do not claim physical keyboard or visual review unless actually performed.
Track and verify test-owned process identities; no kill-by-name/port or cleanup
of unrelated services. WSL and Docker are not native Windows evidence.

## Fixes and return path

Small genuine Windows fixes and their regression tests are authorized for this
validation. Use `codex/windows-stack-repair-validation` based on the pinned
candidate; if that name is already in use, preserve it and choose a fresh suffix.
Do not merge, rebase someone else's branch, force-push, change main/dev, tag,
release, manually dispatch CI, or broaden product scope. Stop and report a problem
that would require architectural redesign or weaken ownership guarantees.

Commit intended fixes before re-running the clean-commit runner. Push only the
validation/fix branch, using a normal push. Even if no code fix is needed, return
one sanitized report at `docs/windows-stack-repair-results.md` on that branch:

- baseline SHA, exact tested code SHA, OS/architecture and Python versions;
- actual suite totals, skips, failures and fixes;
- native scenarios performed, observed identities/responses and cleanup outcome;
- outstanding limitations, clearly separated from passing checks.

A documentation-only summary commit may follow the tested code commit; identify
both rather than implying code tests ran on a different SHA. Keep credentials,
raw machine paths, runtime records, caches, and unredacted logs out of Git. Leave
raw evidence under ignored `.local/validation/` on Windows; the public report may
include archive hashes and sanitized reproductions. Return branch name, final SHA
and a short conclusion in the existing task. No zip transfer is needed unless a
specific failure later requires raw evidence that Git cannot safely carry.
