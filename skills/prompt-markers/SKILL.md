---
name: prompt-markers
description: >-
  Use when a prompt starts with a marker prefix — `h:`/`hint:` (a lead to validate before
  acting), `f:`/`feedback:` (a correction to apply immediately), `e:`/`extension:` (a request
  to widen scope), `q:`/`queue:` (a queued task for after current work), `i:`/`important:`
  (important, high priority) or `i!:`/`important!:` (immediate emergency interrupt) — every
  marker also accepts a `!` importance token between alias and colon, making it
  interrupt-grade — or when the user asks to add, change, or inspect those markers. The
  UserPromptSubmit hook detects them and injects the matching behaviour.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [prompts, markers, hooks, context]
    related_skills: [auto-wm, call-behaviorist]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `prompt-markers` skill: it is `.ai-badger/skills/prompt-markers/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
