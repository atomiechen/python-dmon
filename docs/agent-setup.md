# Try dmon with a coding agent

The portable workflow is [skills/dmon/SKILL.md](../skills/dmon/SKILL.md).
It helps an agent assess an existing project, configure suitable host services,
verify the application, and leave instructions for the next session. It does
not require an MCP server or change the CLI's ownership rules.

This is an unreleased preview. The recovery examples need the candidate below;
do not substitute a same-version PyPI package. Python 3.8+ and `uv` are needed
for this installation path; Git is needed to fetch the source. No system daemon,
Docker, global Python package installation, or MCP server is required.

## Pinned preview

From your target project, verify the exact candidate's command first:

```sh
uv tool run --from "git+https://github.com/atomiechen/python-dmon.git@ae576e8a8a85a7c7723f04f99d2b8113573d8d46" dmon stack repair --help
```

Use that same `uv tool run --from ... dmon` prefix for subsequent commands.
This pins the tested implementation while keeping its dependencies isolated.
Keep the skill from the same candidate. A local wheel is also supported: use
its supplied checksum and a checksum-named directory, since candidate version
numbers alone may match other builds. An installation error is a blocker to
report, not a reason to switch silently to the public package.

## Message to give your agent

Replace `TARGET_PROJECT` with the project you want assessed:

> In TARGET_PROJECT, read the dmon skill at
> https://github.com/atomiechen/python-dmon/blob/ae576e8a8a85a7c7723f04f99d2b8113573d8d46/skills/dmon/SKILL.md
> and assess its local development services. Set up dmon where appropriate,
> using `uv tool run --from "git+https://github.com/atomiechen/python-dmon.git@ae576e8a8a85a7c7723f04f99d2b8113573d8d46" dmon`
> as the CLI prefix. Preserve existing running services
> and container management, verify the application, and leave concise commands
> for the next session. If the existing workflow already fits, keep it.

The agent needs local command execution; reading the skill alone installs nothing.

For Codex, the `skills/dmon` directory can be copied into a target project's
`.agents/skills/dmon`. Follow that project's conventions before committing
these files. Verify the skill is visible, then invoke `$dmon` explicitly for
the first trial. Other local agents can read `SKILL.md` directly; their native
installation mechanisms have not been tested here. Installing a skill does not
guarantee that a model selects it automatically.

## Check the result

For the handoff trial, start a new agent task and ask it to inspect the existing
services and check the application without restarting or stopping anything.
Compare the process identities before and after. Request cleanup explicitly when
finished and verify that the owned services stop. See [ownership.md](ownership.md)
for recovery behavior and limits.

## Reproduce partial recovery without an agent

From this source checkout:

```sh
uv sync --locked --dev
uv run python scripts/demo_repair.py
```

The script creates a new temporary project with two loopback HTTP services,
starts a stack, terminates only its verified worker, and repairs that member.
It checks that API identity and in-memory state remain unchanged and that one
`stack down` stops the original supervisor and both current members. Each CLI
operation is a separate process. It preserves a transcript and JSON evidence in
the printed temporary directory; failed cleanup is reported rather than hidden.
It does not operate on your project's existing services. Ports are selected at
runtime; a collision fails startup rather than killing another listener.

This is a deterministic demonstration, not a fresh-agent or competitive benchmark.
It illustrates [repair's boundaries](ownership.md#repair-an-exited-stack-member),
including the requirement for the original live supervisor.

Keep feedback small and voluntary: platform, project language, installation
blocker, first-run result, handoff result, and redacted error output. Do not
publish project logs or secrets by default.

Created by [Atomie CHEN](https://github.com/atomiechen).

Distribution references: [Codex skills](https://learn.chatgpt.com/docs/build-skills)
and [plugin skills](https://developers.openai.com/plugins/build/skills).
