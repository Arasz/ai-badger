---
name: task
description: >-
  Use when the user wants to start, continue, or finish a backlog task — "/task <id>", "start
  task X", "work on the next task", "finish this task". Runs it end-to-end as a cleanly
  separated, token-tracked unit of work with model delegation: a high-reasoning model plans and
  reviews, implementation models do the hands-on work. Project specifics come from
  .ai-badger/config.json; source-control and PR behaviour from config-gated extensions.
platforms: [linux, macos]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `task` skill: it is `.ai-badger/skills/task/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
