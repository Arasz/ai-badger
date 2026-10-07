# ai-badger Concept Dictionary

How ai-badger's concepts map to each supported agent's native terminology.

`features/common/support.json` is the machine-readable version of this page, one entry per agent
per capability, and the thing to edit when an agent's surface changes. The tables here are the
prose view of it, plus the places where a concept has no pi equivalent and saying so is the
useful answer.

## Skills / Plugins

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| **Skill** (in-repo, `SKILL.md`) | Plugin skill | Skill (`~/.hermes/skills/`) | `.github/skills/*/SKILL.md` | `<project>/.ai-badger/skills/`, contributed to pi's skill paths by the adapter's `resources_discover` (ADR-0023) |
| **External skill** (`skills.json`) | Plugin from marketplace | Hub skill / tap skill / URL skill | N/A | npm or git package |
| **Skill source** (`skills-source.json`) | Plugin marketplace | Skills Hub / GitHub tap / well-known endpoint | N/A | npm registry / git repository |
| **Skill installation** (`plugins-instructions.json`) | `claude plugin install` | `hermes skills install` / `hermes skills tap add` | N/A | `pi install npm:` / `pi install git:` |
| **Skill scope** (`skillScope`) | `default` / `local` / `user` | Profile-level (`~/.hermes/skills/`) or external dir | N/A | Project `.ai-badger/skills` (contributed ungated) or the user-global `skills` array in `~/.pi/agent/settings.json` |
| **Skill extension** (`<skill>/extensions/<name>/`) | Plugin override | Skill patch | N/A | N/A — no override mechanism; extensions are merged into the skill at scaffold time |

pi does not read `~/.claude/skills/` on its own. That directory loads only when it is named in
the settings `skills` array, which is exactly how ai-badger delivers a project's skills, and
why `pi/adjustments/adjust_skills.py` exists as a migration-only remover of the old global entry.

## Hooks

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| **Hooks** (`features/common/hooks/`) | `hooks.json` in plugin root | Plugin hooks (`ctx.register_hook()`) + gateway hooks | `.github/hooks/*.json` (`{version:1, hooks:{...}}`) | TypeScript extension at `~/.pi/agent/extensions/ai-badger/index.ts` that shells out to the same Python scripts |
| **Session start hook** | `SessionStart` event | `on_session_start` plugin hook | `sessionStart` event | `session_start` arms the bus timer; the `SessionStart` hooks themselves do not run |
| **Context injection** | `UserPromptSubmit` event | `pre_llm_call` plugin hook | `userPromptSubmitted` event | `before_agent_start` carries bus mail only; the enrichment, marker and memory-context hooks do not run |
| **Tool call hook** | `PostToolUse` / `PreToolUse` | `post_tool_call` / `pre_tool_call` | `postToolUse` / `preToolUse` | `tool_call` / `tool_result`, with the payload stamped `PreToolUse` / `PostToolUse` |
| **Turn stop hook** | `Stop` event | `on_session_end` (session-scoped, not per-turn) | `agentStop` event | `turn_end` delivers bus mail as a steer |
| **Session end hook** | `SessionEnd` event | `on_session_end` plugin hook | `sessionEnd` event | `session_shutdown` drops the bus cursor |
| **Generated-file guard** (`generated_file_guard.py`, 0.96.0) | `PreToolUse` — denies `Edit`/`Write`/`MultiEdit`/`NotebookEdit` on a file `manifest.json` records as generated | N/A | N/A | `tool_call` — the same command, run from the project's `hooks.json` |
| **Memory-first gate** (`memory_first_gate_hook.py`, ADR-0017) | `PreToolUse` | `pre_tool_call` plugin hook | `preToolUse` with a `grep\|rg\|Glob\|bash` matcher | `tool_call` for the block, `tool_result` for the consulted marker |
| **Memory context** (`memory_context_hook.py`, ADR-0031, 0.178.0) | `UserPromptSubmit`, `hookSpecificOutput` envelope, `timeout` 100 | `pre_llm_call` plugin hook, CLI sessions only (`(platform or "cli") == "cli"`), 25 s cap | `userPromptSubmitted`, flat `additionalContext`, `timeoutSec` 100; runs only in a `trustedFolders` repo | Not this hook: pi's per-prompt memory comes from the `mem-based-rag` and `query-pipeline` extensions in [pi-badger-integration](https://github.com/Arasz/pi-badger-integration) |
| **Hooks manifest** (`hooks-manifest.json`) | Inline in `hooks.json` | Plugin `register()` function | Copilot entries in manifest → `adjust_hooks.py` | No entry by design: the adapter registers one handler per event family and reads `hooks.json` at event time, so a new tool-event hook arms with no manifest edit (ADR-0022) |

The Claude-vocabulary event names map onto pi's extension API as `UserPromptSubmit` → `input`,
`PreToolUse` → `tool_call`, `PostToolUse` → `tool_result`, `SessionStart` → `session_start`,
`Stop` → `agent_settled`, `SessionEnd` → `session_shutdown`. The ai-badger adapter is the
exception that proves the rule worth knowing: it uses `before_agent_start` and `turn_end` for
the bus seams, because a steer that rides pi's queue is exactly-once where a per-request
context copy would be consumed and vanish (ADR-0026).

Only Claude Code's `Stop` reaches the model: its stdout is read as
`{"decision": "block", "reason": "..."}` and by no other route. `SessionEnd` has no decision
control and its JSON output is ignored, so anything wired there must be disk-side work only,
which is why ai-badger runs the same script on both events and lets it block on one of them.

A Copilot hook entry accepts both `bash` and `powershell`, but Copilot's cloud agent runs in a
Linux sandbox and honours only `bash`, which is why `adjust_hooks.py` emits `bash` alone and
Windows-only hook commands have no path into a scaffolded repo.

## Instructions

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| **Project instructions** | `CLAUDE.md` | `HERMES.md` / `.hermes.md` | `.github/copilot-instructions.md` | `AGENTS.override.md` |
| **Scoped instructions** (`instructions/*.md`) | Referenced in `CLAUDE.md` | Referenced in `HERMES.md` | `.github/instructions/*.md` with `applyTo` frontmatter | N/A — pi reads no scoped-instruction directory; a `features/pi/instructions/*.md` file is delivered as a pi instruction file instead |
| **Invariants** | `CLAUDE.md` sections | `HERMES.md` sections | `copilot-instructions.md` sections | Read from the root `CLAUDE.md`: pi loads `AGENTS.md`, `AGENTS.override.md` and `CLAUDE.md`, and the keep region carries none of the invariant text itself |
| **Source of truth** | `.ai-badger/CLAUDE.md` | `.ai-badger/HERMES.md` | `.ai-badger/copilot-instructions.md` | `features/pi/templates/AGENTS.override.md.tmpl`, rendered to the repo root with a keep region |

## Personas

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| **Persona** (`personas/*.md`) | `.claude/agents/*.md` (subagents) | Skill or delegate_task `role` | `.github/agents/*.agent.md` (custom agents) | `<project>/.pi/agents/*.md`, read by the subagent extension through `fs` |
| **Persona routing** (`config.json`) | Agent tool dispatch (`subagent_type`) | `delegate_task` role routing | Custom agent invocation (`/agent-name`) | The subagent extension's delegation tool |
| **Read-only persona** | `disallowedTools:` denylist (keeps Bash and MCP) | Role prompt | `tools:` list | Not carried: pi's `tools` key becomes a `--tools` argument in Claude's vocabulary, so it is dropped and each delegation inherits the session's tool set |
| **Model lane** (persona frontmatter `model:`, `level:`) | `model:` in `.claude/agents/*.md` | N/A — no custom-agent files to carry a lane | Dropped — Copilot picks its own model | `level:` passes through and the reader resolves it against the model-groups registry; `model:` passes when it is a valid `<provider>/<model>` pin, and a bare Claude lane is stripped (ADR-0027) |

Delivering `.pi/agents/*.md` without the subagent extension leaves them inert: pi core has no
custom-agent feature of its own, so a machine that never ran
[pi-badger-integration](https://github.com/Arasz/pi-badger-integration)'s publish flow gets
files nothing reads. The scaffold cannot detect that, because it must not write user-global
state, so the prerequisite is named in the project's docs instead.

## Scaffolding

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| **Scaffolding** (`scaffolding.json`) | Plugin install + file copies | Skill symlink + file copies | File copies to `.github/` | `AGENTS.override.md` at the project root |
| **Manifest** (`manifest.json`) | Plugin provenance | Same | Same | Same |
| **Config** (`config.json`) | Project profile | Same | Same | Same |
| **Adjustment** (`adjustments/`) | Skill discovery symlinks, retrieval module delivery, MCP server approval/denial in `.claude/settings.json` | Agent-specific scaffold tweaks | Hooks, skills, agents, retrieval module delivery via adjustments | Hooks adapter install, persona delivery, the pi session source embedded in `task`, plus migration-only removers for the global `mcp` and `skills` settings keys |

## Task Orchestration

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| **Task skill** | `/task` with model dispatch | `delegate_task` with role routing | N/A | `task` with the pi session source embedded, dispatched through the subagent extension |
| **Task extension** (skill-level) | GitHub PR workflow | Delegation model docs | N/A | Config-gated, same as the base |
| **Task adjustment** (agent-level) | N/A | `adjust_task.py` — embed Hermes patterns | N/A | `adjust_task.py` — embed the pi session source |
| **Plan phase** | Opus model dispatch (`architect`) | `delegate_task(role='orchestrator')` | N/A | `architect` persona, `level: high` resolved by the reader |
| **Implement phase** | Sonnet/Haiku dispatch | `delegate_task(role='leaf')` | N/A | Persona dispatch through the subagent extension |
| **Review phase** | Review-loop agent | `delegate_task(role='leaf')` for review | N/A | Persona dispatch through the subagent extension |

## Progressive Disclosure (Hermes-specific)

| ai-badger | Hermes Agent |
|---|---|
| `index.json` (compact catalog) | Level 0: `skills_list()` — name + description (~3k tokens) |
| Skill content | Level 1: `skill_view(name)` — full SKILL.md |
| Reference files | Level 2: `skill_view(name, path)` — specific file |

## MCP Tool Index

| ai-badger | Claude Code | Hermes Agent | GitHub Copilot | pi |
|---|---|---|---|---|
| `mcp-tools.json` | `context_enrichment_hook.py` (`UserPromptSubmit`) | `pre_llm_call` hook injection | `context_enrichment_hook.py` (`userPromptSubmitted`) | N/A — the enrichment hook is a `UserPromptSubmit` hook, which the adapter does not run |
| `mcp-index` skill | Skill for manual index management, ships the hook's retrieval modules | Skill for manual index management | Skill for manual index management, ships the hook's retrieval modules | Skill for manual index management; the hook half does not arm |
| `mcp_index_hook.py` | PostToolUse hook (planned) | `post_tool_call` plugin hook | PostToolUse hook (planned) | Would arm as `tool_result` if it lands |
