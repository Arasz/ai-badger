---
name: multi-agent-communication
description: >-
  Use when multiple agent sessions share one project and must coordinate without stepping
  on each other — announcing started work, touched files, opened PRs, review requests,
  review feedback, and merges to main over the project message bus. Covers when to
  broadcast, the message shape, and the ack-without-reply rule that keeps the bus
  loop-free.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [coordination, message-bus, parallel-agents, review]
    related_skills: [send-message, task, quick-task, worktree-agent-isolation, status-report]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `multi-agent-communication` skill: it is `.ai-badger/skills/multi-agent-communication/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
