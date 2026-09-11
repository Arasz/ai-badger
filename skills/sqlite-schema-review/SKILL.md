---
name: sqlite-schema-review
description: "Use when reviewing SQLite schema/migration changes: DDL, on-open migrations, unique indexes, insert-path dedup, ON CONFLICT DO NOTHING scope, last_insert_rowid staleness, trigger fire-time failures, UNIQUE-index NULL semantics. Core rule: verify every semantics claim against a scratch DB — never the plan, PR, or docs."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [sqlite, schema, migrations, review]
    related_skills: [sqlite-bank-space-diagnosis, code-review-checklist]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `sqlite-schema-review` skill: it is `.ai-badger/skills/sqlite-schema-review/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
