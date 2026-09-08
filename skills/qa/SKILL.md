---
name: qa
description: >-
  Use when the user wants a question-and-answer session against a context — "qa {context}",
  "I have questions about X", or a question asked against supplied material — or wants the
  session's questions and grounded answers saved as a summary. If no context is given, ask
  for it first; every answer carries its grounding, and the session closes with a summary
  in docs.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [questions, answers, grounding, sessions]
    related_skills: [evidence-first-research, explore-codebase, semantica-knowledge-graph, task]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `qa` skill: it is `.ai-badger/skills/qa/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
