---
name: review-flow
description: >-
  Use when a pull request needs a coordinator-driven review — gather context, build a change
  model, run parallel review lanes, check global scope, post compact GitHub comments, and carry
  learned review rules across rounds. Trigger phrases: "review this PR end to end", "run the
  review flow", "coordinate a PR review", "re-review after changes". Not for ranking one diff by
  blast radius (that is `review-changes`) or the mechanical pass/fail gates (that is
  `code-review-checklist`).
version: 0.1.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [code-review, coordinator, pull-request]
    related_skills: [code-review, review-changes, code-review-checklist, review-tests, code-review-evidence]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `review-flow` skill: it is `.ai-badger/skills/review-flow/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
