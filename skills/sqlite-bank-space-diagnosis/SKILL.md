---
name: sqlite-bank-space-diagnosis
description: "Use when a SQLite bank file or WAL is bloated: diagnose space read-only first (snapshot backup, sqlite3_analyzer, wal_checkpoint(TRUNCATE), VACUUM INTO to quantify reclaim), explain WAL growth mechanics (checkpointed-but-untruncated frames under pooling), the vec0 chunk count(*) trap, and VACUUM/checkpoint/ANALYZE ordering."
platforms: [macos, linux]
scope: default
metadata:
  hermes:
    tags: [sqlite, wal, vacuum, disk-space, diagnostics]
    related_skills: [evidence-first-research]
version: 1.0.0
author: ai-badger
license: MIT
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `sqlite-bank-space-diagnosis` skill: it is `.ai-badger/skills/sqlite-bank-space-diagnosis/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
