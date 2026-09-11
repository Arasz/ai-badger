---
name: spec-driven-refactoring
description: "Use when the user says 'refactor', 'migrate', or 'rename across the codebase', or a change touches 5+ files across schemas, scripts, tests, and docs: write a spec, run two review gates (pre-implementation consistency + post-implementation quality), then implement against it. Covers schema migrations, concept renames, structural reorganizations."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [refactoring, specs, planning, migration]
    related_skills: [refactor-safely, scripts-tooling-refactor]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `spec-driven-refactoring` skill: it is `.ai-badger/skills/spec-driven-refactoring/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
