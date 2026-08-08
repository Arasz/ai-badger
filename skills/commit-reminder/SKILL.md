---
name: commit-reminder
description: >-
  Use when a project has accumulated uncommitted changes and nobody has said so out loud —
  several edits in a row with no commit in between — or when a subagent may be stuck and about
  to lose its work ("did that agent commit?", "is anything at risk?", "ensure work is
  committed"). A PostToolUse hook watches the live `git status --porcelain` count after every
  edit-shaped tool call and commands a commit once it crosses a threshold; after repeated
  unanswered commands it records the work as at risk, and `scripts/ensure_committed.py` reports
  that to a parent.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [git, commits, hooks, safety]
    related_skills: [call-behaviorist, task]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `commit-reminder` skill: it is `.ai-badger/skills/commit-reminder/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
