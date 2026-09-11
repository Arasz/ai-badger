---
name: review-gate-diff-verification
description: "Use when a review gate judges a branch diff: verify the diff base FIRST — merge-base vs moved origin/main ref (phantom D/M files), grep anchors after the status tab, exclude bin/obj from symbol greps, and diff the committed plan against the accepted amended version before judging implementation."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [review, git, diff, gates]
    related_skills: [review-changes, pre-push-gate-debugging]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `review-gate-diff-verification` skill: it is `.ai-badger/skills/review-gate-diff-verification/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
