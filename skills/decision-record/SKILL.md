---
name: decision-record
description: >-
  Use when a change adds a feature or meaningfully changes how something works and the decision
  behind it has to be written down before implementation — "record this decision", "write an
  ADR", "open a spec change", "decision record", or the task skill's decision-record step.
  Detects what the project already uses (an ADR log in MADR, adr-tools or log4brains shape;
  OpenSpec, Spec Kit or Kiro specs; the CLIs on PATH), writes into that format, and writes a
  linked ADR-plus-spec pair when the project keeps both.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [adr, decisions, specification, openspec, documentation]
    related_skills: [task, create-task-spec, evidence-first-research]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `decision-record` skill: it is `.ai-badger/skills/decision-record/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
