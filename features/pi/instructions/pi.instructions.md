---
description: 'pi coding agent conventions for ai-badger integration.'
applyTo: '**/AGENTS.override.md,**/CLAUDE.md,.pi/**'
---

# pi coding agent

- pi extensions live in `~/.pi/agent/extensions/` (user scope). Project-local `.pi/extensions/` is NOT loaded without `--approve` in headless mode — always install at user scope.
- Use `pi.registerTool()` for custom MCP-like tools, `pi.registerCommand()` for slash commands, `pi.on("event", handler)` for lifecycle hooks.
- MCP servers are configured in `~/.pi/agent/settings.json` under the `mcp` key via the `pi-mcp-tools` extension. The `adjust_mcp.py` adjustment maps `.mcp.json` to the pi-native format.
- Skills load from `~/.claude/skills/` or `--skill` paths — pi implements the Agent Skills standard (79/79 load unmodified).
- Available providers: openrouter, anthropic, deepseek, github-copilot, and 35+ more. Configure via `pi auth login --provider <name>`.
- Cron jobs use `Bun.cron()` for OS-level scheduling (launchd on macOS, crontab on Linux). Always `no_agent=true` for maintenance tasks.
- Event mapping: Claude's `UserPromptSubmit` → pi's `input`, `PreToolUse` → `tool_call`, `PostToolUse` → `tool_result`, `SessionStart` → `session_start`, `SessionEnd` → `session_shutdown`, `Stop` → `agent_settled`.
- pi has no built-in MCP support — use `pi-mcp-tools` extension (install: `pi install npm:@zhafron/pi-mcp-tools`).
- Detection: ai-badger detects pi by the presence of `.pi/` directory in the repo or `~/.pi/` in user scope.
- Token tracking: pi does not expose per-session token usage. Task tracker reports zeroes for pi sessions.