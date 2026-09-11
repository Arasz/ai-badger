---
name: worktree-agent-isolation
description: "Use when running multiple agents in parallel, or when the user says 'worktrees only', 'agent isolation', 'parallel workstreams', or 'don't touch main': give each agent its own git worktree branched from origin/main (fetch first), integrate via GitHub PRs, keep the main checkout read-only, and avoid shared obj/ races and file-modification conflicts."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [worktrees, parallel, agents, isolation]
    related_skills: [task, multi-agent-communication]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `worktree-agent-isolation` skill: it is `.ai-badger/skills/worktree-agent-isolation/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
