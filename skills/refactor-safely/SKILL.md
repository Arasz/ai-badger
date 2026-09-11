---
name: refactor-safely
description: >-
  Use when renaming, moving, extracting, or removing code and every affected location must be
  known before the first edit — a rename that spans call sites, an extraction that changes a
  signature, or a removal that might delete something still in use. Trigger phrases: "refactor
  this safely", "rename X everywhere", "is this code still used", "find everything that calls this
  before I change it", "preview this refactor". Not for reconciling a feature whose implementation
  has drifted from its intended design — that is `differential-feature-refactor`, a design
  question to answer first; this skill is the mechanical preview-apply-verify discipline once the
  refactor's scope is already known.
version: 1.0.0
author: ai-badger, after the code-review-graph skill templates
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [refactoring, dependency-analysis, safety]
    related_skills: [debug-issue, review-changes, differential-feature-refactor]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `refactor-safely` skill: it is `.ai-badger/skills/refactor-safely/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
