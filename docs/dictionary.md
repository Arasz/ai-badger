# ai-badger Concept Dictionary

How ai-badger's concepts map to each supported agent's native terminology.

## Skills / Plugins

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Skill** (in-repo, `SKILL.md`) | Plugin skill | Skill (`~/.hermes/skills/`) | `.github/skills/*/SKILL.md` | N/A (inline instructions) |
| **External skill** (`skills.json`) | Plugin from marketplace | Hub skill / tap skill / URL skill | N/A | N/A |
| **Skill source** (`skills-source.json`) | Plugin marketplace | Skills Hub / GitHub tap / well-known endpoint | N/A | N/A |
| **Skill installation** (`plugins-instructions.json`) | `claude plugin install` | `hermes skills install` / `hermes skills tap add` | N/A | N/A |
| **Skill scope** (`skillScope`) | `default` / `local` / `user` | Profile-level (`~/.hermes/skills/`) or external dir | N/A | N/A |
| **Skill extension** (`skills/{base}-extensions/`) | Plugin override | Skill patch | N/A | N/A |

## Hooks

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Hooks** (`features/common/hooks/`) | `hooks.json` in plugin root | Plugin hooks (`ctx.register_hook()`) + gateway hooks | `.github/hooks/*.json` (`{version:1, hooks:{...}}`) | N/A |
| **Session start hook** | `SessionStart` event | `on_session_start` plugin hook | `sessionStart` event | N/A |
| **Context injection** | `UserPromptSubmit` event | `pre_llm_call` plugin hook | `userPromptSubmitted` event | N/A |
| **Tool call hook** | `PostToolUse` / `PreToolUse` | `post_tool_call` / `pre_tool_call` | `postToolUse` / `preToolUse` | N/A |
| **Hooks manifest** (`hooks-manifest.json`) | Inline in `hooks.json` | Plugin `register()` function | Copilot entries in manifest → `adjust_hooks.py` | N/A |

## Instructions

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Project instructions** | `CLAUDE.md` | `HERMES.md` / `.hermes.md` | `.github/copilot-instructions.md` | `.junie/AGENTS.md` |
| **Scoped instructions** (`instructions/*.md`) | Referenced in `CLAUDE.md` | Referenced in `HERMES.md` | `.github/instructions/*.md` with `applyTo` frontmatter | Referenced in `AGENTS.md` |
| **Source of truth** | `.ai-badger/CLAUDE.md` | `.ai-badger/HERMES.md` | `.ai-badger/copilot-instructions.md` | `.ai-badger/AGENTS.md` |

## Personas

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Persona** (`personas/*.md`) | Custom slash command / subagent persona | Skill or delegate_task `role` | `.github/agents/*.agent.md` (custom agents) | Inline in instructions |
| **Persona routing** (`config.json`) | Task delegation model | `delegate_task` role routing | Custom agent invocation (`/agent-name`) | N/A |

## Invariants

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Invariant** (`invariants/*.md`) | Section in `CLAUDE.md` | Section in `HERMES.md` | Section in instructions | Section in `AGENTS.md` |

## Scaffolding

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Scaffolding** (`scaffolding.json`) | Plugin install + file copies | Skill symlink + file copies | File copies to `.github/` | File copies to `.junie/` |
| **Manifest** (`manifest.json`) | Plugin provenance | Same | Same | Same |
| **Config** (`config.json`) | Project profile | Same | Same | Same |
| **Adjustment** (`adjustments/`) | N/A (Claude is the "native" agent) | Agent-specific scaffold tweaks | Hooks, skills, agents via adjustments | N/A |

## Task Orchestration

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | JetBrains Junie |
|---|---|---|---|---|
| **Task skill** | `/task` with model dispatch | `delegate_task` with role routing | N/A | N/A |
| **Task extension** (skill-level) | GitHub PR workflow | Delegation model docs | N/A | N/A |
| **Task adjustment** (agent-level) | N/A | `adjust_task.py` — embed Hermes patterns | N/A | N/A |
| **Plan phase** | Fable/Sonnet model dispatch | `delegate_task(role='orchestrator')` | N/A | N/A |
| **Implement phase** | Sonnet/Haiku dispatch | `delegate_task(role='leaf')` | N/A | N/A |
| **Review phase** | Review-loop agent | `delegate_task(role='leaf')` for review | N/A | N/A |

## Progressive Disclosure (Hermes-specific)

| ai-badger | Hermes Agent |
|---|---|
| `index.json` (compact catalog) | Level 0: `skills_list()` — name + description (~3k tokens) |
| Skill content | Level 1: `skill_view(name)` — full SKILL.md |
| Reference files | Level 2: `skill_view(name, path)` — specific file |

## MCP Tool Index

| ai-badger | Claude Code | Hermes Agent |
|---|---|---|
| `mcp-tools.yaml` | N/A | `pre_llm_call` hook injection |
| `mcp-index` skill | N/A | Skill for manual index management |
| `mcp_index_hook.py` | PostToolUse hook (planned) | `post_tool_call` plugin hook |
