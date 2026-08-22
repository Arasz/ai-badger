---
name: review-tests
description: >-
  Use when tests that already exist have to be judged rather than written — "are these tests any
  good", "review the tests in this PR", "why did the suite stay green while that shipped", a
  coverage number nobody trusts, a gate nobody has watched fail, a lane that flakes, or a test
  file a reviewer flagged. Takes a directory, a file list, a diff, or "the tests for X"; refuses
  to run with no target. Returns findings, not edits.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [testing, test-quality, review, mutation, flakiness]
    related_skills: [design-tests, code-review-checklist, review-changes, task]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `review-tests` skill: it is `.ai-badger/skills/review-tests/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
