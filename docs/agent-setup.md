# Try dmon with a coding agent

The portable workflow is [skills/dmon/SKILL.md](../skills/dmon/SKILL.md).
It helps an agent assess an existing project, configure suitable host services,
verify the application, and leave instructions for the next session. It does
not require an MCP server or change the CLI's ownership rules.

This is currently an unreleased preview. Use the wheel or source checkout
provided with the preview, not the published PyPI 0.4.0 package. A skill is
instructions, not a CLI installer. The agent must be able to execute commands
on the machine running the development services.

Give the agent the skill path, the exact CLI build, and the target project:

> Read the supplied dmon skill and assess this project's local development
> services. Set up dmon only where appropriate, preserving existing running
> services and container management. Use the supplied preview build, verify the
> application, and leave concise instructions for the next session.

For Codex, the `skills/dmon` directory can be copied into a target project's
`.agents/skills/dmon`. Follow that project's conventions before committing
these files. Verify the skill is visible, then invoke `$dmon` explicitly for
the first trial. Other local agents can read `SKILL.md` directly; their native
installation mechanisms have not been tested here. Installing a skill does not
guarantee that a model selects it automatically.

For the handoff trial, start a new agent task and ask it to inspect the existing
services and check the application without restarting or stopping anything.
Compare the process identities before and after. Request cleanup explicitly when
finished and verify that the owned services stop. See [ownership.md](ownership.md)
for recovery behavior and limits.

Keep feedback small and voluntary: platform, project language, installation
blocker, first-run result, handoff result, and redacted error output. Do not
publish project logs or secrets by default.

Created by [Atomie CHEN](https://github.com/atomiechen).

Distribution references: [Codex skills](https://learn.chatgpt.com/docs/build-skills)
and [plugin skills](https://developers.openai.com/plugins/build/skills).
