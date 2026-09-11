---
name: artifact-verification
description: "Use when verifying changed artifacts that lack a canonical test gate — specs, docs, manifests, generated files, published packages: use the workflow-defined checker first (spec_holes.py), review manual fresh-install protocols against the false-pass checklist, and verify 'installed build contains merged PR X' by tree comparison, never squash-ancestry."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [verification, artifacts, evidence, testing]
    related_skills: [evidence-first-research, code-review-evidence]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `artifact-verification` skill: it is `.ai-badger/skills/artifact-verification/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
