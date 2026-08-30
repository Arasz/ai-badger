---
name: status-report
description: >-
  Use when the user asks where things stand mid-task — "status", "status report", "where are
  we", "what's the current task", "task progress", "what's next", "subagent status", "is the
  delegation done" — or wants a progress snapshot while work is still running. Answers NOW
  from the /task tracking files: current task, progress as a checklist, what is next, and
  sub-agent/delegation status. Important by default: never deferred to task end, never
  delegated, never turned into analysis.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [task, status, delegation, tracking]
    related_skills: [task, auto-wm, prompt-markers]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `status-report` skill: it is `.ai-badger/skills/status-report/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
