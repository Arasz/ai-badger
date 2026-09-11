---
name: documentation-drift-audit
description: "Use when auditing docs for drift vs code ('audit and fix documentation drift'): inventory claims with path:line, verify each against real files (scaffolders, manifests, hooks), classify verifiably-false vs design-position vs ambiguous vs historical, fix only the false, and report A/B/C. Also for post-merge doc-gap audits and user-facing doc compaction rewrites."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [documentation, drift, audit, verification]
    related_skills: [documentation, maintain-agent-instructions]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `documentation-drift-audit` skill: it is `.ai-badger/skills/documentation-drift-audit/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
