---
name: design-gate-audit
description: "Use when auditing a design doc's acceptance gates BEFORE implementation: check every gate would fail if the feature were broken (HONEST) and the named test file/framework/seam exists (FEASIBLE). Attacks vacuous negatives, timing-window vacuity, port races, env poisoning, unprovable real-time halves. Pairs with dotnet-hosted-service-testing for FakeTimeProvider mechanics."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [design, gates, acceptance, honesty]
    related_skills: [create-task-spec, dotnet-hosted-service-testing]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `design-gate-audit` skill: it is `.ai-badger/skills/design-gate-audit/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
