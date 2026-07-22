---
description: 'Hermes Agent conventions for authoring skills, configuration, and agent behavior.'
applyTo: 'skills/**/SKILL.md,**/*.hermes.md,**/HERMES.md,.hermes/**'
---

# Hermes Agent

- Author skills as self-contained `SKILL.md` files with YAML frontmatter (`name`, `description`, `version`) and numbered procedural steps. Every skill must include pitfalls and verification sections.
- Use `skill_view(name=<skill>)` to load a skill, never re-implement from memory. When a skill proves incomplete or wrong, patch it immediately with `skill_manage(action='patch')`.
- Prefer `delegate_task` for parallel subagent work over spawning separate `hermes` processes. Use `role='orchestrator'` for planning agents and `role='leaf'` for implementers.
- Save durable facts with the `memory` tool (user preferences, environment quirks, tool conventions). Keep memory entries compact — one declarative fact each. Never save transient task progress or TODOs to memory.
- Use `session_search` to recall past conversations and decisions instead of asking the user to repeat themselves. Prefer FTS5 discovery (`query=...`) over full transcript dumps.
- Skills live under `.ai-badger/skills/` and are the project's procedural memory. Load them via `/skill <name>` or preload with `hermes -s <name>`.
- Project context files follow Hermes priority order: HERMES.md (walks parents to git root) > AGENTS.md > CLAUDE.md. The `.ai-badger/HERMES.md` file is the authoritative project configuration for Hermes agents.
- Cron jobs are durable (survive process exit) and should use `notify_on_complete=true` for bounded tasks. Use `cronjob(action='create')` for recurring work, not ad-hoc loops.
- Every tool call must produce verifiable output. When an external operation succeeds (HTTP POST, file write, gateway send), verify with a follow-up read/fetch/stat before reporting success.
- Use `computer_use` for desktop automation: capture with `mode='som'` for element indexing, click by element index, and escalate to `delivery_mode='foreground'` only when background delivery fails.
- Hermes works with any LLM provider. Never assume a specific model or provider is available — read the active model from the session context.
- Run `hermes doctor` to verify configuration after changes. Use `hermes config set <key> <value>` for configuration, never hand-edit config.yaml.
