---
name: task
description: >-
  Use when the user wants to start, continue, or finish a backlog task — "/task <id>", "start
  task X", "work on the next task", "finish this task". Runs it end-to-end as a
  token-tracked unit of work with two effort levels (low/high), plan packaging with
  mandatory integration package, MoE panels for high-effort, and automated task-ID
  derivation ({repo-alias}-{key}). Delegates planning/review to high-reasoning models
  and implementation to persona-routed agents. Project specifics from
  .ai-badger/config.json; source-control and PR behaviour from config-gated extensions.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos]
scope: default
metadata:
  hermes:
    tags: [task, orchestration, delegation, worktree]
    related_skills: [create-task-spec, commit-reminder]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `task` skill: it is `.ai-badger/skills/task/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
