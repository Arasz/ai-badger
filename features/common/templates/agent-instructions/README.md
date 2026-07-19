# Agent instruction model template

This directory ships the **agnostic** half of the agent-instructions model consumed by the
`maintain-agent-instructions` skill:

- `schema.json` — the model shape. Copied as-is into every scaffolded project; never edited
  per-project.
- `model.template.json` — a minimal, valid-but-empty skeleton conforming to `schema.json`: no
  files, directories, instruction sets, invariants, or agents declared yet.

## How it gets filled in

`model.json` is project-specific — it lists this project's actual instruction files, directories,
non-negotiable invariants, and required headings — so it is never shipped by the framework.
Instead, `welcome-ai-badger`'s `scaffold.py` copies `schema.json` and `model.template.json` (as
`model.json`) into `.ai-badger/agent-instructions/`, and the agent then fills `model.json` in
during scaffolding: it records the entrypoint files chosen for the detected agents, the
path-scoped instruction sets selected for the project's stacks, and any invariants pulled in from
`common/invariants/` or `<stack>/invariants/`.

After scaffolding, treat `.ai-badger/agent-instructions/model.json` as the source of truth for
agent-instruction policy in that project and maintain it with the
`maintain-agent-instructions` skill's standard workflow (validate → drift-check → fix →
re-validate).
