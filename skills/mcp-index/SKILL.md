---
name: mcp-index
description: >-
  Use when MCP tool selection needs help — the agent keeps picking the wrong tool, server tool
  definitions are bloating the prompt, or MCP servers were just added or removed. Manages
  .ai-badger/mcp-tools.json: tags, intent descriptions, and the hook that recommends tools per
  turn.
version: 0.1.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [mcp, indexing, tool-discovery, prompt-compression]
    related_skills: [hermes-mcp-setup]
---

> **This is the generic copy.** If this project has been scaffolded, prefer the unprefixed
> `mcp-index` skill: it is `.ai-badger/skills/mcp-index/SKILL.md`, and it has this project's
> extensions and any `project-local.md` merged in. This copy has neither.
>
> The full procedure is in `SKILL.full.md` beside this file, unchanged — read it if the project has no
> `.ai-badger/`, or run `welcome-ai-badger` to scaffold one.
