# rtk integration research record (task aib-ship-rtk-token-proxy-tool)

Date: 2026-10-17. Goal: ship rtk (https://github.com/rtk-ai/rtk, CLI output-compression proxy) as an ai-badger catalog tool — a new `tools` feature type at `features/common/tools/rtk/` with check/install and opt-in per-harness hook wiring.

User decisions so far: high-effort loop; new `tools` category (not under `mcp/`); install = detect + opt-in per-harness hook wiring (`rtk init`), opt-in via `config.json`.

Three sources, each graded per finding:
- Part A: how the `mcp` feature type flows through ai-badger (lane d-47, read-only code research).
- Part B: rtk install and integration surface, measured against rtk 1.0.1 in HOME-overridden /tmp sandboxes (lanes d-48/d-50).
- Part C: what the user's own machine already has (Claude session 61f1aa82, report from its history).

## Synthesis — load-bearing facts for the plan

1. [MEASURED] A local `rtk init` for Claude writes NO hook and no `.claude/settings.json`; only a `CLAUDE.md` marker block + `.rtk/filters.toml` (B F5). A project-level Claude hook therefore has to be written by ai-badger itself (PreToolUse `Bash` → `rtk hook claude`), or installed user-level with `-g`.
2. [MEASURED] Local `rtk init` for Codex and Copilot edits files ai-badger generates (`AGENTS.md` gets `@RTK.md`, `.github/copilot-instructions.md` gets a marker block) plus `.codex/hooks.json` / `.github/hooks/rtk-rewrite.json` (B F7, F8). Re-scaffolding would overwrite the instruction-file edits and the scaffold freshness guard would flag them (A F25).
3. [MEASURED] pi local writes only `.pi/extensions/rtk.ts`; `--auto-patch` overwrites a user's non-stock `rtk.ts` with no backup (B F9). Hermes has no project scope; it always writes `~/.hermes` (B F10).
4. [MEASURED] init is idempotent (B F11); uninstall leaves residue in 5 of 6 cases and Claude local uninstall is refused (B F12).
5. [MEASURED] Non-interactive recipe: `rtk init [-g] <flags> --auto-patch </dev/null` with `RTK_TELEMETRY_DISABLED=1`; exit 0 ok / 1 refusal / 2 bad args (B F13, F14).
6. [MEASURED/READ] Telemetry is opt-in, off by default; the Homebrew 1.0.1 build has no endpoint compiled in (B F15). Local tracking DB (`history.db`, 90 days) stays on disk.
7. [READ] Licence: CLI Apache-2.0, but the default build links BUSL-1.1 `rtk-engine`; an Apache-only `rtk-oss` edition exists without pipeline/PostToolUse features (B F2).
8. [READ] Floors: `--copilot` 0.34, Codex 0.36, hermes 0.40, pi 0.42; only 1.0.1 measured → pin `>=1.0.1` (B F4). Check: `rtk --version`; hook verification is per harness (`rtk init --show` covers Claude only; B F17).
9. [READ] No non-MCP CLI tool type exists in ai-badger; archify/uv are skill `dependencies.json` entries (A F27). Hook wiring today handles ai-badger's own scripts only; per-agent `adjust_*.py` adjustments are the seam for per-harness tool wiring (A F28). A minimal change set is in A, "Minimal change set".
10. [UNVERIFIED] How rtk's `updatedInput` PreToolUse rewrite composes with ai-badger's own Bash PreToolUse hooks in one Claude session.


# Part A — mcp feature type flow (lane d-47)


# Part B — rtk install and integration surface (lanes d-48/d-50)


# Part C — existing local setup (Claude session 61f1aa82)

- rtk 1.0.1 brew, pre-existing. Ran `rtk init -g --auto-patch` (Claude only). Pre-existing: PreToolUse `rtk hook claude`, ~/.claude/RTK.md (slim), @RTK.md in ~/.claude/CLAUDE.md. init added PostToolUse `rtk hook claude` matcher `Bash|Read|Grep|Glob|WebFetch|WebSearch|mcp__.*`.
- ~/.config/rtk/pipeline.toml rewritten: extends rtk:posthook + rtk:proxy; [upstream.haiku] anthropic claude-haiku-5-5, api_key_command reads 1Password ~/.env FIFO; [task.compact] digest; after-tool rules keep-verbatim(git diff/show, recall), compact shell/web >5000 tok, mcp >6000. ~/Library/Application Support/rtk/pipeline.toml -> symlink to it.
- ~/.config/zsh/dotenv.zsh + ~/.zshenv source line: loads 1Password FIFO ~/.env (ANTHROPIC_API_KEY) — personal, out of scope.
- ANTHROPIC_BASE_URL=http://127.0.0.1:8080 in ~/.claude/settings.json env = rtk llm-proxy (INFERRED from rtk gain + ~/Library/Application Support/rtk/llm-proxy/rtk-proxy.log); start mechanism unknown.
Gotchas: macOS config dir is ~/Library/Application Support/rtk (ignores XDG; RTK_CONFIG_DIR works); `rtk init -g` prompts unless --auto-patch; new after-tool rules need `rtk init -g` (validate says "hook needed"); restart harness after init; haiku-5-5 rejects temperature (silent fallback); `--dry-run -v` rejected; telemetry enabled+consent in config.toml by default.
Unverified: init idempotency, --uninstall, PostToolUse route in live session.
Unresolved: global ANTHROPIC_API_KEY export may override Claude Max login.
