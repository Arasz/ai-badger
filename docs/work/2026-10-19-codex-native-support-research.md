# Codex native support research

**Date:** 2026-10-19  
**Question:** Which Codex-specific plugin, skill, instruction, and hook surfaces should ai-badger use to add user scope and project scope without duplicate discovery, and which hook event can enforce the memory-first gate?

## Findings

- **READ (official Codex skills documentation):** Codex discovers repository skills from `.agents/skills` and user skills from `$HOME/.agents/skills`. It follows symlinked folders. Skills with the same `name` do not merge, and both can appear in selectors. Reusable distribution is supported through plugins. https://learn.chatgpt.com/docs/build-skills
- **READ (official Codex instructions documentation):** Codex selects at most one instruction file per directory, in this order: `AGENTS.override.md`, `AGENTS.md`, then configured fallback names. `CLAUDE.md` is not a default filename. https://learn.chatgpt.com/docs/agent-configuration/agents-md
- **READ (official Codex hooks documentation):** `PreToolUse` can deny a supported call using `hookSpecificOutput.permissionDecision = "deny"`; Codex hook input carries `tool_name`, `tool_input`, `cwd`, `turn_id`, and `tool_use_id`. `PostToolUse` runs after side effects and cannot undo them. https://learn.chatgpt.com/docs/hooks
- **READ (official Codex hooks documentation):** `PostToolUse` also observes MCP results in `tool_response`, including error status. The memory-first query-credit observer is advisory, so `PostToolUse` is appropriate for crediting successful user-issued searches; the Codex adjustment filters failed responses before calling the shared observer. https://learn.chatgpt.com/docs/hooks
- **READ (official Codex plugin documentation):** Codex plugin manifests can expose skills and hooks. A compatibility manifest can live under `.codex-plugin/plugin.json`; plugin hook commands receive `PLUGIN_ROOT`. Codex CLI accepts Git-backed marketplace roots and native marketplace metadata is `.agents/plugins/marketplace.json`; desktop also reads the legacy `.claude-plugin/marketplace.json` format. https://developers.openai.com/plugins/build/plugins and https://learn.chatgpt.com/docs/developer-commands
- **READ (repository):** `features/codex/adjustments/adjust_hooks.py` wrote `CLAUDE_PROJECT_DIR` into project command hooks and supported three hook scripts. The shared hook scripts read per-call `cwd` from the payload; the Codex runner now exports `AI_BADGER_PROJECT_DIR` from its explicit project-root argument. `features/codex/adjustments/adjust_skills.py` linked only project skills. Marketplace sources were declared Claude-only and there was no Codex plugin installation recipe.
- **INFERRED:** `PreToolUse` is the correct memory-first enforcement boundary because it runs before the repository search. `PostToolUse` cannot stop that operation, but is required to credit successful user-issued `memory_search` calls. Codex-specific adjustment code filters MCP error responses before invoking the shared observer.
- **INFERRED:** A Codex user plugin and project scaffold must be mutually exclusive for a given ai-badger delivery. Since Codex does not merge duplicate skill names, `codexScope: user` should remove project copies.
- **UNVERIFIED:** Codex CLI behavior with arbitrary Claude-formatted marketplace catalogs and plugins depends on their contents and client version. The native ai-badger catalog removes that format ambiguity; third-party plugin compatibility still needs validation by its owner.

## Repository scope

Codex-specific delivery is implemented under `features/codex/adjustments` and `.codex-plugin`. Shared skills remain canonical and unmodified. The user-scope plugin hooks are limited to hooks whose Codex event, command path, and payload have been checked. Other hook registrations remain unsupported until an adapter and behavior test exist.
