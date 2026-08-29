---
description: 'pi coding agent conventions for ai-badger integration.'
applyTo: '**/AGENTS.override.md,**/CLAUDE.md,.pi/**'
---

# pi coding agent

Measured against pi 0.84.3. Re-measure before trusting any line here after a pi upgrade.

- ai-badger installs pi extensions user-scope, at `~/.pi/agent/extensions/<name>/index.ts`.
  `index.ts` is the filename pi discovers for a subdirectory extension — it is mandatory, not a
  convention, and `package.json` does not register it (`pi.extensions` there is package-loading
  machinery for npm/git packages). Project-local `.pi/extensions/` is trust-gated: `-p`,
  `--mode json` and `--mode rpc` show no trust prompt and fall back to `defaultProjectTrust`
  (default `"ask"`), which ignores project resources. A project-local gate would gate nothing in
  exactly the headless runs it exists for.
- Use `pi.registerTool()` for custom tools, `pi.registerCommand()` for slash commands, and
  `pi.on("event", handler)` for lifecycle hooks. A `tool_call` handler blocks by returning
  `{ block: true, reason }`; returning nothing allows.
- `ctx.hasUI` is false in print (`-p`) and JSON modes — guard `confirm`, `select` and `input` with
  it. `ctx.signal` is the turn's abort signal; pass it to any subprocess or fetch a handler starts.
- Hooks: ai-badger's adapter extension (`~/.pi/agent/extensions/ai-badger/`) runs the project's
  Claude-shaped PreToolUse gates listed in `<cwd>/.ai-badger/hooks/hooks.json`. Set
  `AI_BADGER_PI_AWAY=1` or run `/away` to auto-approve gates that *ask*; denials, gate errors and a
  missing hooks config are never auto-approved.
- Skills: pi loads them from `~/.pi/agent/skills/`, `~/.agents/skills/`, project `.pi/skills/` and
  `.agents/skills/` (trust-gated), a settings `skills` array, and `--skill <path>`. It does **not**
  read `~/.claude/skills/` on its own — that directory only loads when it is listed in the settings
  `skills` array, which is how ai-badger delivers `.ai-badger/skills/`.
- MCP: pi core has no MCP support and no consumer for the `mcp` settings key (it appears nowhere in
  pi's docs or dist). That key is read solely by the `pi-mcp-tools` extension, which must be
  installed for any MCP configuration to have an effect.
- Cron: pi's bin is `#!/usr/bin/env node`, so there is no `Bun` global at runtime and `Bun.cron()`
  cannot fire from inside an extension today. ai-badger's cron extension uses `Bun.cron` only when
  the process really is bun, and self-managed launchd agents otherwise. `noAgent` defaults to true —
  only an explicit `false` opts a job out. The launchd fallback caps a schedule at 366
  `StartCalendarInterval` dicts, so `* * * * *` is refused rather than mis-scheduled.
- Event mapping: Claude's `UserPromptSubmit` → pi's `input`, `PreToolUse` → `tool_call`,
  `PostToolUse` → `tool_result`, `SessionStart` → `session_start`, `SessionEnd` →
  `session_shutdown`, `Stop` → `agent_settled`.
- Providers: openrouter, anthropic, deepseek, github-copilot and more. Configure with
  `pi auth login --provider <name>`.
- Detection: ai-badger detects pi by `.pi` in the repo or `~/.pi/agent` in user scope.
- Token tracking: pi exposes no per-session usage API, but the session JSONL does carry it —
  `~/.pi/agent/sessions/--<path>--/<timestamp>_<uuid>.jsonl`, `usage` on assistant entries (pi
  `docs/session-format.md`).
