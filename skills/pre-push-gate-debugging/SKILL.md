---
name: pre-push-gate-debugging
description: "Use when a pre-push quality gate blocks git push or a lane fails: read the gate's own logs first (reproduce one lane), run single lanes for fast iteration, test the working tree you intend to push, handle E2E/infra cross-run state contamination, worktree node_modules gotchas, and build a manual repro harness when lane output hides the real error."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [gates, debugging, ci, pre-push]
    related_skills: [debug-issue, commit-reminder]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `pre-push-gate-debugging` skill: it is `.ai-badger/skills/pre-push-gate-debugging/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
