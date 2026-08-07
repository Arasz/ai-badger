# ai-badger Concept Dictionary

How ai-badger's concepts map to each supported agent's native terminology.

## Skills / Plugins

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Skill** (in-repo, `SKILL.md`) | Plugin skill | Skill (`~/.hermes/skills/`) | `.github/skills/*/SKILL.md` |
| **External skill** (`skills.json`) | Plugin from marketplace | Hub skill / tap skill / URL skill | N/A |
| **Skill source** (`skills-source.json`) | Plugin marketplace | Skills Hub / GitHub tap / well-known endpoint | N/A |
| **Skill installation** (`plugins-instructions.json`) | `claude plugin install` | `hermes skills install` / `hermes skills tap add` | N/A |
| **Skill scope** (`skillScope`) | `default` / `local` / `user` | Profile-level (`~/.hermes/skills/`) or external dir | N/A |
| **Skill extension** (`<skill>/extensions/<name>/`) | Plugin override | Skill patch | N/A |

## Hooks

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Hooks** (`features/common/hooks/`) | `hooks.json` in plugin root | Plugin hooks (`ctx.register_hook()`) + gateway hooks | `.github/hooks/*.json` (`{version:1, hooks:{...}}`) |
| **Session start hook** | `SessionStart` event | `on_session_start` plugin hook | `sessionStart` event |
| **Context injection** | `UserPromptSubmit` event | `pre_llm_call` plugin hook | `userPromptSubmitted` event |
| **Tool call hook** | `PostToolUse` / `PreToolUse` | `post_tool_call` / `pre_tool_call` | `postToolUse` / `preToolUse` |
| **Turn stop hook** | `Stop` event | `on_session_end` (session-scoped, not per-turn) | `agentStop` event |
| **Session end hook** | `SessionEnd` event | `on_session_end` plugin hook | `sessionEnd` event |
| **Generated-file guard** (`generated_file_guard.py`, 0.96.0) | `PreToolUse` — denies `Edit`/`Write`/`MultiEdit`/`NotebookEdit` on a file `manifest.json` records as generated | N/A | N/A |
| **Memory-first gate** (`memory_first_gate_hook.py`, ADR-0017) | `PreToolUse` | `pre_tool_call` plugin hook | `preToolUse` with a `grep\|rg\|Glob\|bash` matcher |
| **Hooks manifest** (`hooks-manifest.json`) | Inline in `hooks.json` | Plugin `register()` function | Copilot entries in manifest → `adjust_hooks.py` |

Only Claude Code's `Stop` reaches the model: its stdout is read as
`{"decision": "block", "reason": "..."}` and by no other route. `SessionEnd` has no decision
control and its JSON output is ignored, so anything wired there must be disk-side work only —
which is why ai-badger runs the same script on both events and lets it block on one of them.

A Copilot hook entry accepts both `bash` and `powershell`, but Copilot's cloud agent runs in a
Linux sandbox and honours only `bash` — which is why `adjust_hooks.py` emits `bash` alone and
Windows-only hook commands have no path into a scaffolded repo.

## Instructions

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Project instructions** | `CLAUDE.md` | `HERMES.md` / `.hermes.md` | `.github/copilot-instructions.md` |
| **Scoped instructions** (`instructions/*.md`) | Referenced in `CLAUDE.md` | Referenced in `HERMES.md` | `.github/instructions/*.md` with `applyTo` frontmatter |
| **Source of truth** | `.ai-badger/CLAUDE.md` | `.ai-badger/HERMES.md` | `.ai-badger/copilot-instructions.md` |

## Personas

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Persona** (`personas/*.md`) | `.claude/agents/*.md` (subagents) | Skill or delegate_task `role` | `.github/agents/*.agent.md` (custom agents) |
| **Persona routing** (`config.json`) | Agent tool dispatch (`subagent_type`) | `delegate_task` role routing | Custom agent invocation (`/agent-name`) |
| **Read-only persona** | `disallowedTools:` denylist (keeps Bash and MCP) | Role prompt | `tools:` list |
| **Model lane** (persona frontmatter `model:`) | `model:` in `.claude/agents/*.md` | N/A — no custom-agent files to carry a lane | Dropped — Copilot picks its own model |

## Invariants

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Invariant** (`invariants/*.md`) | Section in `CLAUDE.md` | Section in `HERMES.md` | Section in instructions |

## Scaffolding

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Scaffolding** (`scaffolding.json`) | Plugin install + file copies | Skill symlink + file copies | File copies to `.github/` |
| **Manifest** (`manifest.json`) | Plugin provenance | Same | Same |
| **Config** (`config.json`) | Project profile | Same | Same |
| **Adjustment** (`adjustments/`) | Skill discovery symlinks, retrieval module delivery, MCP server approval/denial in `.claude/settings.json` | Agent-specific scaffold tweaks | Hooks, skills, agents, retrieval module delivery via adjustments |

## Task Orchestration

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| **Task skill** | `/task` with model dispatch | `delegate_task` with role routing | N/A |
| **Task extension** (skill-level) | GitHub PR workflow | Delegation model docs | N/A |
| **Task adjustment** (agent-level) | N/A | `adjust_task.py` — embed Hermes patterns | N/A |
| **Plan phase** | Opus model dispatch (`architect`) | `delegate_task(role='orchestrator')` | N/A |
| **Implement phase** | Sonnet/Haiku dispatch | `delegate_task(role='leaf')` | N/A |
| **Review phase** | Review-loop agent | `delegate_task(role='leaf')` for review | N/A |

## Progressive Disclosure (Hermes-specific)

| ai-badger | Hermes Agent |
|---|---|
| `index.json` (compact catalog) | Level 0: `skills_list()` — name + description (~3k tokens) |
| Skill content | Level 1: `skill_view(name)` — full SKILL.md |
| Reference files | Level 2: `skill_view(name, path)` — specific file |

## MCP Tool Index

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot |
|---|---|---|---|
| `mcp-tools.json` | `context_enrichment_hook.py` (`UserPromptSubmit`) | `pre_llm_call` hook injection | `context_enrichment_hook.py` (`userPromptSubmitted`) |
| `mcp-index` skill | Skill for manual index management, ships the hook's retrieval modules | Skill for manual index management | Skill for manual index management, ships the hook's retrieval modules |
| `mcp_index_hook.py` | PostToolUse hook (planned) | `post_tool_call` plugin hook | PostToolUse hook (planned) |
