---
name: git-work
description: "Use when a git push fails for a reason the quality gate did not cause, CI goes red on a pushed branch, or a PR moves through review and merge outside the tracked-task flow: non-fast-forward recovery with force-with-lease, CI log triage and flake attribution, draft-to-squash PR lifecycle, squash-merge conventions, and join-time conflict resolution on plain branches."
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [git, pr, ci, push]
    related_skills: [task, pre-push-gate-debugging, worktree-agent-isolation]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `git-work` skill: it is `.ai-badger/skills/git-work/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
