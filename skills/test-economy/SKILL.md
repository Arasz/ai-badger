---
name: test-economy
description: >-
  Use when a change's tests are about to run — deciding what to run locally (the modified
  surface and its consumers, once), what to leave to CI (the full suite, when CI is alive),
  and what to do when CI is dead (hooked-up local gates once, else one manual full-suite run
  before push) — or when full-suite runs start repeating and something must say stop. A
  PostToolUse hook counts shell test-runner commands, classifies full vs filtered, and
  commands the economy on the run past the session's budget; deliberate flake diagnosis is
  the one exempted repetition.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [testing, ci, hooks, discipline]
    related_skills: [commit-reminder, task, review-tests, dotnet-flaky-test-diagnosis]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `test-economy` skill: it is `.ai-badger/skills/test-economy/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
