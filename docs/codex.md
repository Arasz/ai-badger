# Codex support

ai-badger supports Codex through its project scaffold. Add `codex` to `agents` in
`.ai-badger/config.json`, then run `welcome-ai-badger` or `den-refresh`. Detection proposes
Codex when its project or user configuration directory is present; a generic `AGENTS.md`
alone does not identify the harness.

This route serves local Codex CLI, desktop and IDE sessions. The framework does not install
external Claude plugins into Codex or change user-global Codex settings.

## What is delivered

| Resource | Native discovery path | Canonical content |
|---|---|---|
| Project instructions | `AGENTS.md` | `.ai-badger/AGENTS.md`, rendered from the Codex template |
| Skills | `.agents/skills/<name>` | Relative symlink to `.ai-badger/skills/<name>` |
| Personas | `.codex/agents/<name>.toml` | Rendered from `.ai-badger/agents/<name>.md` |
| MCP servers | `.codex/config.toml` | Selected catalog launch declarations |
| Native hooks | `.codex/hooks.json` | Compatible registrations from the project's hook configuration |

Skill selection follows the common include/exclude policy. Codex follows directory symlinks,
so skill scripts and references remain part of the same package. The scaffold removes stale or declined links only when it recognizes its own target. Existing
user resources stay under user ownership; read preservation and conflict notes before assuming
a resource was replaced.

Standalone persona TOML contains `name`, `description` and `developer_instructions`. The
scaffold omits Claude `model`, `level` and tool frontmatter rather than guessing OpenAI model
names. It also omits `model_reasoning_effort`, so model and effort inherit from Codex's parent
settings. Architect, code-reviewer and QA persona files request read-only sandboxes; Codex's
active parent permission settings still govern the runtime. Project owners can configure
native model settings separately. The common task skill
can use native persona dispatch, but its Claude transcript reader does not establish Codex
usage or model-mix accounting.

## Instruction precedence

Codex reads at most one instruction file per directory. `AGENTS.override.md` wins over
`AGENTS.md`; nested files apply later in the root-to-working-directory chain. The default
combined instruction budget is 32 KiB.

A pi project also has a root `AGENTS.override.md`. The managed pi template includes the same full project guidance, keeping common
policy available when that override wins. A hand-authored override is preserved. Follow the scaffold's warning and
reconcile its content yourself when it masks the generated Codex instructions.

## Configuration and trust

Codex loads project `.codex/config.toml` only for trusted projects. MCP servers use native
`[mcp_servers.<name>]` tables; a Claude `.mcp.json` file is not a Codex registration. Existing
project settings, comments and user-defined server entries are preserved. ai-badger writes
its servers inside a `# ai-badger:mcp-start` / `# ai-badger:mcp-end` block and replaces only
that block on refresh. An existing same-name server outside the block wins; declined servers
leave the owned block. Invalid TOML or incompatible table shapes are refused without writing. Review notes about malformed
or conflicting configuration; a preserved server entry can intentionally differ from the
catalog's launch command.

Native hooks have a second trust check. Start Codex in the project, open `/hooks`, and review
and trust the generated definitions before relying on them. New or changed definitions need
review again. Scaffolding does not grant project trust, alter hook trust, or bypass either.
Use `/mcp` or `codex mcp list` to inspect the MCP connections available in your client.

## Hook scope

Hook parity is partial. The scaffold registers these handlers only when their skill scripts
were delivered:

| Handler | Native event | Matcher |
|---|---|---|
| `prompt-markers/scripts/user_prompt_hook.py` | `UserPromptSubmit` | All submitted prompts |
| `git-work/scripts/git_config_health_hook.py` | `SessionStart` | `startup|resume` |
| `git-work/scripts/git_internals_guard.py` | `PreToolUse` | `^Bash$` |

The native shell tool matches `Bash`, including `exec_command`. User hook handlers are
preserved; re-scaffolding refreshes owned registrations and removes declined ones. The
scaffold supplies the project root to these shared scripts through `CLAUDE_PROJECT_DIR`,
which is a compatibility environment variable rather than a Claude runtime requirement.

No MCP, `Stop`, file-edit, dispatch or transcript-accounting hooks are wired for Codex.
Native patch inputs differ from Claude file-edit inputs, so generated-file and other patch
guard parity is not claimed. The capability matrix records this bounded support.

OpenAI's hook support depends on client version and orchestration mode. Local command hooks
are unsupported with cloud orchestration, even when tools execute locally. Managed workspace
hooks are a separate administrator surface. This scaffold's hook claims apply to local
orchestration only.

## Verify a scaffold

Inspect `AGENTS.md` and any root override first. Check `.agents/skills/` links resolve to the
selected packages and `.codex/agents/` contains the expected role names. Parse the project
TOML and hook JSON, then inspect their loaded state in Codex after reviewing trust. A generated
file proves delivery; the client must still load it successfully.

The research was checked against [OpenAI's instruction documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[skills documentation](https://learn.chatgpt.com/docs/build-skills),
[subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[MCP documentation](https://learn.chatgpt.com/docs/extend/mcp) and
[hook documentation](https://learn.chatgpt.com/docs/hooks) on 2026-10-11.
[ADR-0038](adr/0038-codex-harness-delivery.md) records the delivery decision.
