---
description: 'Claude Code prompt-cache conventions for always-loaded agent files.'
applyTo: '**/CLAUDE.md,.claude/**'
---

# Claude Code

- Keep the prompt prefix byte-stable. Claude Code caches the prompt up to the system prompt and
  tools, and one changed byte reprices everything after it at full input cost. CLAUDE.md,
  `.claude/agents/*`, skill descriptions and MCP tool lists stay a pure function of the
  catalog and the config: no timestamps, run ids, counters or session data in them.
- Context that changes per turn (hook output, memory snippets, status) goes into the latest
  message — a `UserPromptSubmit` hook's `additionalContext` — never back into CLAUDE.md or a
  settings file mid-session.
- Cache breakpoints are the harness's job: Claude Code sets `cache_control` itself, and a
  markdown file cannot carry one. Rewrite always-loaded files between tasks, not during one.
