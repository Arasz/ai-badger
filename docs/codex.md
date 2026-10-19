# Codex support

ai-badger supports Codex through a native plugin and its project scaffold. Add `codex` to `agents` in
`.ai-badger/config.json`, then run `welcome-ai-badger` or `den-refresh`. Detection proposes
Codex when its project or user configuration directory is present; a generic `AGENTS.md`
alone does not identify the harness.

For Codex CLI user-wide skills and hooks, add the native catalog and install its plugin with
`codex plugin marketplace add Arasz/ai-badger` and
`codex plugin add ai-badger@ai-badger-codex`. The repository catalog at
`.agents/plugins/marketplace.json` points to the Codex compatibility plugin, which discovers
the root `skills/` package and registers native hooks from `hooks/codex-hooks.json`. Review
and trust plugin hooks in Codex before relying on them. Codex desktop also reads the legacy
`.claude-plugin/marketplace.json` format. Codex's CLI can add Git-backed marketplaces, but
Claude plugin compatibility depends on each plugin's contents; verify third-party plugin
skills and hooks before installing them. ai-badger emits native Codex marketplace commands
for the marketplace-backed skills it declares.

Use `codexScope: "project"` (the default) for repository skill links and hooks. Set
`codexScope: "user"` in every repository where the ai-badger plugin is installed for your
Codex user. The scaffold then removes its project skill and hook copies, preventing Codex
from listing or running both copies. Installing the user plugin alone cannot change a
repository's project scope. This option does not write to your Codex home; plugin installation
remains an explicit Codex command.

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

The project scaffold writes only `AGENTS.md` for Codex instructions. Codex reads at most one
instruction file per directory, preferring `AGENTS.override.md` and then `AGENTS.md`. It does
not load `CLAUDE.md` by default. A user configured `project_doc_fallback_filenames` can add
other names, so keep `CLAUDE.md` out of that list when it duplicates the shared instructions.

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

Automated MCP delivery follows the catalog's existing stdio declaration format.
Codex also accepts native HTTP servers; configure those directly in its TOML file.
Existing operator HTTP entries are preserved.

## Hook scope

Hook parity is partial. The scaffold registers these handlers only when their skill scripts
were delivered:

| Handler | Native event | Matcher |
|---|---|---|
| `prompt-markers/scripts/user_prompt_hook.py` | `UserPromptSubmit` | All submitted prompts |
| `git-work/scripts/git_config_health_hook.py` | `SessionStart` | `startup|resume` |
| `git-work/scripts/git_internals_guard.py` | `PreToolUse` | `^Bash$` |
| Codex memory gate adapter for `ai-raccoon-memory` | `PreToolUse` | `^Bash$` |
| `ai-raccoon-memory/scripts/memory_first_gate_post_hook.py` | `PostToolUse` | Memory search MCP tool names |
| Codex auto-wm adapter | `PreToolUse` | Supported away-mode questions |
| Codex auto-wm adapter | `PermissionRequest` | Eligible shell approval requests |
| Codex auto-wm context adapter | `UserPromptSubmit` | Prompts inside an armed project |

The native shell tool matches `Bash`, including `exec_command`. The Codex PostToolUse adapter
skips failed MCP results so an unsuccessful memory search cannot credit its query. Its
PreToolUse adapter allows the search when the memory lookup is unavailable, while a reachable
backend with no hits still enforces the gate. Other hosts keep the shared gate's existing
policy. User hook handlers are preserved; re-scaffolding refreshes owned registrations and
removes declined ones.
Deselecting Codex removes its managed MCP block, recognized hook handlers, managed persona
TOMLs and the `.agents/skills/` links that point at ai-badger's own skills, even while
`codex` remains a detected stack; operator entries stay.
Malformed configuration and symlinks remain unchanged so cleanup can retry after repair. The
Codex commands use the native hook payload, and plugin hooks resolve scripts from
`PLUGIN_ROOT`. Project commands do not set Claude home or project variables.
The scaffolded runner exports `AI_BADGER_PROJECT_DIR` from an explicit project-root argument;
hook payload `cwd` remains authoritative for per-call repository resolution. Each approved command
binds to the scaffolded absolute project root and uses isolated Python imports, so nested repository
markers cannot redirect execution. Moving or cloning a project requires re-scaffolding and reviewing
the changed hook commands. Scripts with symlink paths are skipped. The framework repository keeps
`.codex/hooks.json` untracked because its approved root is machine specific;
`.codex/hooks.example.json` shows the generated shape.

No general `PostToolUse`, `Stop`, file-edit, dispatch or transcript-accounting hooks are wired for Codex.
Native patch inputs differ from Claude file-edit inputs, so generated-file and other patch
guard parity is not claimed. The capability matrix records this bounded support.

OpenAI's hook support depends on client version and orchestration mode. Local command hooks
are unsupported with cloud orchestration, even when tools execute locally. Managed workspace
hooks are a separate administrator surface. This scaffold's hook claims apply to local
orchestration only.

## Auto-wm approvals

Codex uses `PermissionRequest` for auto-wm approvals. Its `PreToolUse` adapter emits no
bare `allow` and records no approval for calls that did not ask for one. Eligible shell
requests reuse auto-wm's project scope, expiry and denylist policy. Disabled, expired,
out-of-scope, destructive, network, MCP, patch and unknown requests retain normal approval.
Claude continues to use its existing hook protocol.

Away-mode question denial applies where Codex exposes the question through PreToolUse;
specialized question paths may bypass hooks. AWM does not change the configured sandbox
or approval policy. The prompt banner describes this bounded support and points at the
installed skill's CLI.

After updating the Codex plugin, remove old user-level registrations that directly invoke
`auto-wm/hooks/awm_gate.py` or `awm_context.py` through the Claude skill directory:

```bash
python3 "$PLUGIN_ROOT/features/codex/adjustments/migrate_auto_wm_hooks.py" --plugin-root "$PLUGIN_ROOT"
```

Set `PLUGIN_ROOT` to the installed ai-badger package shown by `codex plugin list`. The
migration checks the replacement hooks, saves a backup of the user hook configuration,
and removes only recognized legacy auto-wm handlers. Operator hooks and group metadata
are preserved. Repeating the migration makes no changes. Review the new hooks in Codex
before relying on them; running the project scaffold never edits user configuration.

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
