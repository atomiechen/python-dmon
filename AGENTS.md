# Agent instructions

Before changing or reviewing code, read these sources in order:

1. `README.md` for supported behavior and user-facing configuration;
2. `CONTRIBUTING.md`, especially **Core contracts** and **Validation**;
3. the target module and its matching tests;
4. `tests/manual/README.md` when behavior involves processes, signals, terminal
   interaction, logging, or multiple services.

Keep changes inside the smallest relevant layer. Do not duplicate process,
readiness, configuration, or rendering logic to add a new interface. Preserve
human-readable CLI behavior unless a change explicitly updates that contract.

For reviews, inspect the diff only after establishing the context above. Report
findings before changing code unless the user also requested fixes.

When a change alters a durable contract, test workflow, or release procedure,
update the existing documentation rather than appending overlapping guidance.
