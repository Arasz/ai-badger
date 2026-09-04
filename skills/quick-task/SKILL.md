---
name: quick-task
description: >-
  Use when a change is small enough to skip the full task pipeline — one focused fix or
  small feature that fits a single commit pushed straight to main with no PR: a minimal
  plan, touched-surface tests only, the project's fast gates (lint, docs), one quick
  focused review, one commit. Escalate to `task` the moment the change outgrows that shape.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [workflow, fast-path, single-commit, tests, review]
    related_skills: [task, test-economy, code-review-checklist, status-report, multi-agent-communication]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `quick-task` skill: it is `.ai-badger/skills/quick-task/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
