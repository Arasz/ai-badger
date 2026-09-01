---
name: send-message
description: >-
  Use when an agent session needs to reach another agent session, every session in a
  project, or every session on this machine without the human relaying between windows —
  1:1, project-broadcast and machine-broadcast sends through the machine-wide user-DB
  message bus.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [message-bus, coordination, agent-messaging]
    related_skills: [task, status-report]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `send-message` skill: it is `.ai-badger/skills/send-message/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
