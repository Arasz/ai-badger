---
name: differential-feature-refactor
description: >-
  Use when a feature already exists in code but has drifted from — or was never reconciled
  with — its intended design, and someone must decide what changes before a refactor is
  scoped. Triggers: two parallel implementations of the same thing, code that reads as dead
  but may be a ratified extension point, an architecture nobody can tell from accumulated
  cruft, or a refactor about to be scoped off review documents instead of decisions.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [refactoring, architecture, decisions, design]
    related_skills: [owner-gate-review]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `differential-feature-refactor` skill: it is `.ai-badger/skills/differential-feature-refactor/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
