---
name: review-changes
description: >-
  Use when reviewing a diff, PR, or a batch of changed files and you need to know where the risk
  concentrates — which changed units have the largest blast radius, whether the highest-risk ones
  are actually covered by tests, and whether the result is safe to merge. Trigger phrases: "review
  these changes", "how risky is this diff", "what's the blast radius", "did anything untested
  change", "rank these changes by risk". Not for a pass/fail preflight of style, security, and
  layering checks — that is `code-review-checklist`; run the checklist for the mechanical gates and
  reach for this skill to decide where its attention should concentrate. The two compose: checklist
  for gates, this skill for prioritization.
version: 1.0.0
author: ai-badger, after the code-review-graph skill templates
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [code-review, risk, blast-radius, testing]
    related_skills: [code-review-checklist, refactor-safely, debug-issue]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `review-changes` skill: it is `.ai-badger/skills/review-changes/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
