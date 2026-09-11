---
name: scripts-tooling-refactor
description: "Use when refactoring a repo's scripts/ directory: convert non-python scripts to the repo's tooling language, move logic to src/ with tests in tests/ (TDD first), prune dead scripts on usage evidence (git ls-files inventory, LIVE/HISTORICAL classification, three-way sync contracts), and preserve call sites with thin wrappers."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [refactoring, scripts, tooling, testing]
    related_skills: [refactor-safely, spec-driven-refactoring]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `scripts-tooling-refactor` skill: it is `.ai-badger/skills/scripts-tooling-refactor/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
