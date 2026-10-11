# Codex harness research

Research date: 2026-10-11. Scope: local Codex CLI, desktop and IDE project configuration.

## Initial finding

At the starting revision, `features/common/support.json` named Claude, Copilot, Hermes and pi.
`schemas/config.schema.json` accepted those four agents. `features/codex/` did not exist.
A root `AGENTS.md` was present in this repository, but that file alone did not constitute
catalog support: detection, persona delivery, skill discovery, MCP and hooks lacked a Codex route.

## Evidence and delivery decisions

| Surface | Verified upstream behavior | ai-badger decision |
|---|---|---|
| Instructions | Codex chooses one nonempty file per directory, preferring `AGENTS.override.md` to `AGENTS.md`; the root-to-CWD chain has a default 32 KiB cap | Emit a full managed `AGENTS.md`; keep scoped instruction paths explicit and reconcile pi override precedence |
| Skills | Repository discovery scans `.agents/skills` from CWD to Git root and follows directory symlinks | Link embedded `.ai-badger/skills` packages into native discovery |
| Personas | Project `.codex/agents/*.toml` files require `name`, `description`, `developer_instructions`; model and effort are optional | Render canonical persona bodies to TOML; inherit the Codex model rather than carrying Claude lane pins |
| MCP | Local clients share configuration; project `.codex/config.toml` only loads in trusted projects | Deliver project `mcp_servers` tables, preserving existing project settings |
| Hooks | Codex reads `.codex/hooks.json` and inline TOML hooks; project trust and exact-definition hook trust are separate prerequisites | Emit prompt-markers, git configuration health and Bash git-internals guard hooks; preserve user hooks and claim partial parity |
| Tool hook payload | `exec_command` matches `Bash`; `apply_patch` uses `tool_input.command`; MCP arguments retain their tool-specific structure | Omit unadapted file-edit gates; do not claim patch guard parity |
| Distribution | Local skills can be used directly; Codex supports plugins too | Support the scaffold route without claiming ai-badger's external Claude plugin install recipes work on Codex |
| Cloud | Local command hooks are unsupported with cloud orchestration, including local tool execution | Limit native hook support claims to local orchestration |

## Primary sources

These official OpenAI URLs were retrieved on 2026-10-11. The older `developers.openai.com/codex/`
URLs redirect to the listed ChatGPT Learn pages.

- [Instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Skills and symlink discovery](https://learn.chatgpt.com/docs/build-skills)
- [Custom subagents and configuration inheritance](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Project MCP and client scope](https://learn.chatgpt.com/docs/extend/mcp)
- [Configuration precedence and project trust](https://learn.chatgpt.com/docs/config-file/config-basic)
- [Native hook events, payloads, trust and cloud limits](https://learn.chatgpt.com/docs/hooks)

Local CLI inspection found `codex-cli 0.162.0-alpha.17.2`. `codex --help` exposed `mcp`,
`plugin`, `agents`, `--strict-config` and hook trust control. `codex mcp --help` listed
list/get/add/remove/login/logout; `codex plugin --help` listed add/list/marketplace/remove.
`codex features list` reported `hooks` and `multi_agent` stable and enabled. These observations
verify the installed client surface; they do not establish a minimum version for all clients.

## Limits

A generated file and a passing unit test do not prove a live Codex session loaded it. Consumer
checks must inspect emitted TOML/JSON, discovery links and ownership behavior. Live sessions
also depend on the user's project trust, hook trust, runtime executables and available models.
No unattended model session or external plugin installation was needed for this research.
