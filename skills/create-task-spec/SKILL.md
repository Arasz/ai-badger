---
name: create-task-spec
description: >-
  Use when a feature idea needs to become an exact, agreed specification before anyone builds it —
  "spec this out", "create a task spec", "turn this idea into requirements", "what exactly should
  we build". Interrogates the person for what they know instead of proposing content for them to
  approve, using Gherkin's own grammar to decide which questions must be asked and when the
  document is complete. Emits a .feature behavioural contract plus a spec.json manifest that the
  task skill consumes.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [specification, gherkin, requirements, contracts]
    related_skills: [task, behavioral-contracts]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `create-task-spec` skill: it is `.ai-badger/skills/create-task-spec/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
