---
name: maintain-agent-instructions
description: >-
  Use when agent instruction files have drifted from each other or from the policy model —
  CLAUDE.md, copilot-instructions.md, AGENTS.md, hosted-review and path-scoped instruction files
  — or when validation/drift checks fail in CI. Reconciles them from the machine-readable model
  in .ai-badger/agent-instructions/.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [agent-instructions, drift, claude, copilot]
    related_skills: [welcome-ai-badger, update-documentation]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `maintain-agent-instructions` skill: it is `.ai-badger/skills/maintain-agent-instructions/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
