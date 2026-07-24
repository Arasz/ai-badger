# Article Update Note: Feature Support by Agent

## Issue

The article's feature matrix for Copilot is outdated. GitHub Copilot CLI gained hooks, skills, and custom agents support in early 2026.

## Corrected Matrix

| Feature | Claude Code | Hermes | Copilot | Junie | Generic |
|---------|------------|--------|---------|-------|---------|
| Personas | native | native | native (custom agents) | native | via AGENTS.md |
| Invariants | CLAUDE.md | always-loaded | native | native | via AGENTS.md |
| Cache-aware dispatch | native | native | — | — | — |
| Skill catalog | native | native | native | native | manual |
| Hooks | plugin hooks | plugin + gateway | `.github/hooks/*.json` (8 events) | — | — |
| Adjustments | native | native | — | — | — |
| Feed-back loop | native | native | partial | — | manual |

## Key Changes

### Copilot Hooks (was `—`, now `native`)
- Config: `.github/hooks/*.json` — any JSON file in the directory
- Format: `{ "version": 1, "hooks": { "<event>": [...] } }`
- Events: `sessionStart`, `sessionEnd`, `preToolUse`, `postToolUse`, `userPromptSubmitted`, `agentStop`, `subagentStop`, `errorOccurred`
- Cloud agent: only `bash` field honored (Linux sandbox)
- Reference: https://docs.github.com/en/copilot/concepts/agents/hooks

### Copilot Skills (was `native`, confirmed)
- Location: `.github/skills/*/SKILL.md`, `.claude/skills/*/SKILL.md`, `.agents/skills/*/SKILL.md`
- Format: YAML frontmatter (`name`, `description`, `license`, `argument-hint`) + markdown body
- Invocation: `/skill-name` slash command or auto-loaded when relevant
- Reference: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills

### Copilot Custom Agents (new row or update Personas)
- Location: `.github/agents/*.agent.md`
- Format: YAML frontmatter (`name`, `description`, `tools`, `model`, `mcp-servers`, `user-invocable`)
- Capabilities: own tool set, MCP servers, behavioral instructions
- Reference: https://docs.github.com/en/copilot/reference/custom-agents-configuration

## ai-badger Support Status

| Capability | Copilot support in ai-badger |
|-----------|----------------------------|
| Instructions | ✅ scaffolded (`.github/copilot-instructions.md` + scoped) |
| Hooks | ❌ not yet wired (planned: Phase 1) |
| Skills | ❌ not yet symlinked (planned: Phase 2) |
| Custom agents | ❌ not yet mapped from personas (planned: Phase 3) |

## Sources

- https://docs.github.com/en/copilot/concepts/agents/hooks
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
- https://docs.github.com/en/copilot/reference/custom-agents-configuration
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions
- https://github.blog/changelog/2026-02-25-github-copilot-cli-is-now-generally-available/
