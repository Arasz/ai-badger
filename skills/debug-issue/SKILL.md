---
name: debug-issue
description: >-
  Use when a bug report or failing test names a symptom and the code path producing it is not yet
  known — trace the call chain from symptom to entry point before proposing a fix. Trigger
  phrases: "why does this fail", "trace this bug", "find where this is called from", "what calls
  this function", "did a recent change cause this". Not a replacement for the general
  reproduce-isolate-fix discipline (a `systematic-debugging` skill, if present, governs that
  overall loop); reach for this skill specifically for the tracing step — once a symptom is
  located and the call chain to its entry point still needs walking before a hypothesis is formed.
version: 1.0.0
author: ai-badger, after the code-review-graph skill templates
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [debugging, tracing, call-graph]
    related_skills: [review-changes, refactor-safely]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `debug-issue` skill: it is `.ai-badger/skills/debug-issue/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
