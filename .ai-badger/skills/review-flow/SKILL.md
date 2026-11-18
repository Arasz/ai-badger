---
name: review-flow
description: >-
  Use when a pull request needs a coordinator-driven review — gather context, build a change
  model, run parallel review lanes, check global scope, post compact GitHub comments, and carry
  learned review rules across rounds. Trigger phrases: "review this PR end to end", "run the
  review flow", "coordinate a PR review", "re-review after changes". Not for ranking one diff by
  blast radius (that is `review-changes`) or the mechanical pass/fail gates (that is
  `code-review-checklist`).
version: 0.1.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [code-review, coordinator, pull-request]
    related_skills: [code-review, review-changes, code-review-checklist, review-tests, code-review-evidence]
---

# Review flow

Skeleton. The coordinator procedure lands in a later step; the design is in
`docs/adr/0051-review-flow-coordinator.md`.

## Gotchas

- CLI-only in v1: this skill ships scripts and no MCP server, so nothing here appears in the MCP tool list.
