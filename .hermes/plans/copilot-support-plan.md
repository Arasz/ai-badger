# Copilot CLI Support Plan

## Research Summary (July 2026)

GitHub Copilot CLI has evolved significantly since the article was written. Current capabilities:

### Hooks
- **Config location**: `.github/hooks/*.json` (any JSON file in the directory)
- **Format**: `{ "version": 1, "hooks": { "<event>": [{ "type": "command", "bash": "...", "powershell": "..." }] } }`
- **Events**: `sessionStart`, `sessionEnd`, `preToolUse`, `postToolUse`, `userPromptSubmitted`, `agentStop`, `subagentStop`, `errorOccurred`
- **Fields**: `type`, `bash`, `powershell`, `cwd`, `timeoutSec`, `env`, `matcher` (optional)
- **Cloud agent**: only `bash` is honored; `powershell` entries are ignored

### Skills
- **Location**: `.github/skills/*/SKILL.md`, `.claude/skills/*/SKILL.md`, `.agents/skills/*/SKILL.md`
- **Format**: YAML frontmatter (`name`, `description`, `license`, `argument-hint`) + markdown body
- **Invocation**: `/skill-name` slash command or auto-loaded when relevant
- **Resources**: scripts, examples, and other files in the skill directory

### Custom Agents
- **Location**: `.github/agents/*.agent.md`
- **Format**: YAML frontmatter (`name`, `description`, `tools`, `model`, `mcp-servers`, `user-invocable`)
- **Capabilities**: own tool set, MCP servers, behavioral instructions
- **Invocation**: `/agent-name` in chat

### Instructions
- **Main**: `.github/copilot-instructions.md` — always loaded
- **Scoped**: `.github/instructions/*.instructions.md` with `applyTo` frontmatter for file patterns
- **Cross-agent**: Copilot also reads `AGENTS.md` and `CLAUDE.md`

## Gap Analysis vs ai-badger

| Capability | ai-badger current | Copilot support needed |
|-----------|-------------------|----------------------|
| Instructions | ✅ scaffolds copilot-instructions.md + scoped | Already done |
| Hooks | ❌ no copilot entries in hooks-manifest.json | **Add copilot hook wiring** |
| Skills | ❌ skills only scaffolded for claude/hermes | **Add copilot skill symlinks** |
| Custom agents | ❌ no concept of custom agents | **Map personas → custom agents** |
| Plugins | ❌ not applicable | Skip — Copilot plugins are a separate ecosystem |

## Implementation Plan

### Phase 1: Hook Wiring for Copilot (high priority)

1. **Add copilot entries to hooks-manifest.json**:
   ```json
   {
     "name": "drift-notice",
     "agents": {
       "copilot": { "type": "hooks-json", "entry": "copilot-hooks.json", "event": "sessionStart" }
     }
   }
   ```

2. **Create `features/common/hooks/copilot-hooks.json`** (Copilot format):
   ```json
   {
     "version": 1,
     "hooks": {
       "sessionStart": [{
         "type": "command",
         "bash": "python3 .ai-badger/skills/task/scripts/drift_notice_hook.py",
         "timeoutSec": 10
       }],
       "userPromptSubmitted": [{
         "type": "command",
         "bash": "python3 .ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py",
         "timeoutSec": 5
       }]
     }
   }
   ```

3. **Update `wire_hooks()` in scaffold.py** to handle copilot agent type:
   - Read copilot-hooks.json from framework
   - Rewrite paths to `.ai-badger/skills/...`
   - Write to `.github/hooks/ai-badger-hooks.json`

4. **Tests**: `test_scaffold_wires_copilot_hooks`

### Phase 2: Skill Symlinks for Copilot (medium priority)

1. **Update `symlink_hermes_skills()` or add `symlink_copilot_skills()`**:
   - Create `.github/skills/` directory
   - Symlink each ai-badger skill into it
   - Skills already have SKILL.md with YAML frontmatter — format is compatible

2. **Tests**: `test_scaffold_creates_copilot_skill_symlinks`

### Phase 3: Custom Agents from Personas (low priority)

1. **Create agent template** for mapping ai-badger personas → Copilot custom agents:
   - `architect` persona → `.github/agents/architect.agent.md`
   - `code-reviewer` persona → `.github/agents/code-reviewer.agent.md`
   - `test-engineer` persona → `.github/agents/test-engineer.agent.md`

2. **Add to copilot scaffolding.json** with `template: true` entries

3. **Tests**: `test_scaffold_creates_copilot_custom_agents`

## Execution Order

1. Phase 1 (hooks) — highest value, maps to existing infrastructure
2. Phase 2 (skills) — medium value, format is already compatible
3. Phase 3 (agents) — low priority, personas work via instructions already
