---
name: code-review-evidence
description: "Use when reviewing code that wraps external libs/extensions/SDKs/CLIs, or QA-reviewing a test harness: verify wrapped-library semantics from the upstream source (not comments/spec), query the real store read-only for data claims, and hunt tautological tests that assert values the code constructed itself. Catches spec-vs-coverage gaps, fake honesty, hygiene."
version: 1.0.0
author: hermes-curator
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [code-review, verification, integration-tests, third-party]
    related_skills: [code-review-checklist, review-changes]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `code-review-evidence` skill: it is `.ai-badger/skills/code-review-evidence/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
