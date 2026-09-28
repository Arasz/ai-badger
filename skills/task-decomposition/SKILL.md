---
name: task-decomposition
description: >-
  Use when a researched task must become an executable plan — "decompose this", "split this
  into steps", "turn the research into a plan". Turns a brief into a `task-plan`: a DAG of
  steps with acceptance criteria, dependencies, effort and owned files; records it through
  the `task-graph` server (or its CLI twin), re-authors it when review finds defects, and
  names the join rule and the no-server fallback. `task` runs this in its plan phase;
  `quick-task` never does.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [task, planning, decomposition, dag, workflow]
    related_skills: [task, create-task-spec, status-report, design-tests, worktree-agent-isolation]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `task-decomposition` skill: it is `.ai-badger/skills/task-decomposition/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
