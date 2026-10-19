---
description: 'Native OpenAI Codex harness conventions.'
applyTo: '**/AGENTS.md,**/AGENTS.override.md,.codex/**,.agents/skills/**'
---

<!-- Managed by ai-badger. Source of truth: .ai-badger/instructions/codex.instructions.md. Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->


# Codex

- Codex reads one instruction file per directory: nonempty AGENTS.override.md takes precedence over AGENTS.md. Keep shared guidance in the override when both harnesses coexist.
- Repository skills live in .agents/skills/<name>/SKILL.md; relative symlinks are supported. Keep user-owned skills and discovery collisions intact.
- `codexScope: user` selects the ai-badger plugin installed from its marketplace and prunes project skill and hook copies to prevent duplicate discovery.
- Native custom agents are standalone .codex/agents/<name>.toml files with name, description and developer_instructions. Omit model and model_reasoning_effort to inherit the parent; Claude model aliases and tools lists are not native Codex settings.
- Project MCP configuration lives in .codex/config.toml under mcp_servers. Preserve operator settings and user-scoped declarations. Project config loads only for trusted projects.
- Native hooks live beside config layers in hooks.json or inline TOML, and sources accumulate. Preserve user hooks; project trust and exact hook review are operator actions. Command hooks receive JSON on stdin, can inject hookSpecificOutput.additionalContext, and can deny through PreToolUse permissionDecision. Tool inputs must be verified before reusing a guard; apply_patch does not provide the same file_path fields as Claude Edit.
- ai-badger currently ports prompt marker injection, Git config health and the Bash Git storage guard. Patch guards, delegation gates, transcript accounting, and automatic plugin installation remain unsupported.

Sources reviewed 2026-10-11: https://learn.chatgpt.com/docs/agent-configuration/agents-md, https://learn.chatgpt.com/docs/build-skills, https://learn.chatgpt.com/docs/agent-configuration/subagents, https://learn.chatgpt.com/docs/hooks, https://developers.openai.com/codex/mcp.
