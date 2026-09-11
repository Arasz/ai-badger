---
name: complete-project-scope-code-review
description: >-
  Use when the whole project — not a diff — is the review target and the result must survive being
  acted on: "review the entire codebase", "full quality review", "MoE review", "what is wrong with
  this project", "audit everything before the next release", or a review whose findings will
  become a plan someone implements. Runs ground-truth baseline, parallel expert lanes, integration,
  an adversarial pass that tries to falsify the findings, severity calibration against production
  reality, a reviewed plan, waved implementation in isolated worktrees, and a join review on every
  merge. Not for judging one diff or PR (that is review-changes plus code-review-checklist), one
  design document's gates (design-gate-audit), or one question (evidence-first-research).
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos]
scope: default
metadata:
  hermes:
    tags: [review, parallel, evidence, adversarial, planning]
    related_skills: [evidence-first-research, owner-gate-review, multi-lane-report-assembly, design-gate-audit, task]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `complete-project-scope-code-review` skill: it is `.ai-badger/skills/complete-project-scope-code-review/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
