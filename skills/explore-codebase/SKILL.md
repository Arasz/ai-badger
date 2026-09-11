---
name: explore-codebase
description: >-
  Use when arriving at an unfamiliar codebase, or an unfamiliar region of a known one, and the
  question is "what is here and how is it arranged" rather than "where is this specific thing".
  Trigger phrases: "help me understand this repo", "what does this project do", "where does X
  live", "walk me through the architecture", "I'm new to this codebase", "what are the main
  modules". Not for tracing one symptom to its cause — that is `debug-issue`; not for judging a
  diff — that is `review-changes`. Reach for this one when orienting, and switch to those once
  you know where to look.
version: 1.0.0
author: ai-badger, after the code-review-graph skill templates
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [exploration, architecture, orientation, onboarding]
    related_skills: [debug-issue, review-changes, refactor-safely]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `explore-codebase` skill: it is `.ai-badger/skills/explore-codebase/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
