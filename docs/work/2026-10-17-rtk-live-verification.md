# rtk live verification (task aib-ship-rtk-token-proxy-tool, step s13-live-verify)

Date: 2026-10-17. Verifier role: report only, no production code changed. Framework under test:
ai-badger at `a740a1e4` (PR #581). Binaries: rtk 1.0.1 (`/opt/homebrew/bin/rtk`), Claude Code
2.1.302, pi 1.3.0. Absent: codex, copilot, hermes. Settles the UNVERIFIED lines in
`docs/adr/0039-tools-feature-type.md` (Consequences, "Open, to be settled by the live
verification step").

## Verdicts

| AC | Subject | Verdict |
|----|---------|---------|
| a1 | Claude: rtk rewrite fires; a parallel deny hook blocks it; removal restores it | PASS |
| a2 | L2 original vs rewritten command; L6 no `rtk rtk` | PASS |
| a3 | `permissions.deny` / `permissions.ask` for `Bash(git push:*)` with the rtk hook active | FAIL (BLOCKING: ask bypassed; deny holds) |
| a4 | pi: project `rtk.ts` + globals, isolated gate run | NOT-VERIFIED (aborted: pi wrote under `$HOME`; no funded model) |
| a5 | Codex / Copilot / Hermes | NOT-VERIFIED (binaries absent); Copilot wording finding recorded |

## BLOCKING findings

1. **a3: the rtk hook silently defeats a project `permissions.ask` rule.** With
   `"ask": ["Bash(git push:*)"]` in project `.claude/settings.json` and the ai-badger rtk handler
   wired, `claude -p ... 'Run exactly: git push origin main'` pushed to the remote without asking
   (remote `main` went from absent to `d3f445a`; PostToolUse saw `rtk git push origin main`;
   `permission_denials: []`). The control run without the rtk handler was stopped with "Claude
   requested permissions to use Bash, but you haven't granted it yet." Mechanism (measured):
   Claude matches `ask` rules against the hook's `updatedInput` only — an ask rule written as
   `Bash(rtk git push:*)` did hold — while `deny` rules are matched against both the original and
   the rewritten command. Every `ask` rule for a command rtk rewrites is therefore bypassed.
   `deny` is not bypassed (a3 deny runs below).

No checksum change was observed on `~/.claude/settings.json` or `~/.pi/agent/trust.json` at any
point (baseline and every post-run value:
`6f8a10782916d163adaa6306956ce3b0f1ffa3d0 aaae051495f58b91cd6d6f6779e1606a5b18d532`).

## Abort finding (not a checksum BLOCKING, but it ended a4)

pi wrote under `$HOME` despite `--offline --no-session`: `~/.pi/agent/mcp-auth.json` mtime
21:53:33, inside the first `pi -p` run (started 21:53:31, MCP not disabled), and
`~/.pi/agent/badger-console.log` mtime 21:53:11 from `pi --offline --list-models haiku` (the
global ai-badger console-capture extension). The brief's abort rule ("any step would write under
$HOME") applied, and independently pi had no usable model (below), so a4 stopped. Many other
`~/.pi/agent/extensions/*` changes in the same window came from a concurrent session's
`bun publish.ts` (pid 18543, parent claude pid 90701, not this session's claude pid 88942), and
are not attributed to these runs.

## Setup

- Scratch: `$S=/private/tmp/claude-501/-Users-arasz-RiderProjects-ai-badger/29c16558-6b9d-41c5-ace9-22a75c4cdd1c/scratchpad/s13`,
  repo `R=$S/R` (`git init -b main`, one commit), local bare remote `$S/remote.git` as `origin`.
- Config: `tests/scaffold_helpers._config(stacks=["python"], agents=["claude","pi"])` plus
  `"tools": {"rtk": {"hooks": ["claude","pi"]}}`.
- Scaffold: `HOME=$S/fakehome .venv/bin/python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py --config $S/config.json --target $R --root <worktree> --no-install`
  → rc 0; note `adjustment 'tools' for 'claude': 1 tool hook(s) wired into .claude/settings.json`;
  pi: `not applied — run rtk init --agent pi in this project once install is enabled`.
  `$S/fakehome` stayed empty.
- Wired handler (PreToolUse, matcher `Bash`):
  `env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c 'command -v rtk >/dev/null 2>&1 || exit 0; out=$(rtk hook claude) || exit 0; case "$out" in "{"*) printf "%s" "$out";; esac'`
- Claude argv for every run (from `$R`, stdin `/dev/null`):
  `RTK_DB_PATH=$R/.rtkdb RTK_RECALL=0 claude -p --setting-sources project --model haiku --max-turns 3 --allowedTools Bash --output-format stream-json --verbose --no-session-persistence --strict-mcp-config '<prompt>'`
  (`--no-session-persistence` and `--strict-mcp-config` added to keep transcripts out of
  `~/.claude/projects` and the project's five MCP servers from starting). Only builtin plugins
  loaded (`cc-plugin-agents-md`, `cc-plugin-telemetry`, `cc-plugin-plugin-authoring`); no
  user-scope ai-badger hooks interfered.
- Every run printed: `Ignoring 5 permissions.allow entries from .claude/settings.json: this
  workspace has not been trusted.` The workspace was left untrusted (trusting it writes
  `~/.claude.json`). Project `deny`/`ask` were still applied (a3 controls prove it); the Bash
  allow came from `--allowedTools Bash`.
- Gain: `RTK_DB_PATH=$R/.rtkdb RTK_RECALL=0 rtk gain`, reading the `rtk git status` row of "By
  Command" (my own `rtk bypass` probes also land in the total, so the row, not the total, is the
  measure). Initial value: `Total commands: 0`.

## a1 Claude: rewrite, parallel deny, restore

| Run | Fixture | Tool call (model) | Result | `rtk git status` count | Verdict |
|-----|---------|-------------------|--------|------------------------|---------|
| 1 | none | `git status` | `* main\n?? .ai-badger/ ...` (rtk's compact format) | 0 → 1 | PASS |
| 2 | PreToolUse deny hook on `git status` | `git status` | `PreToolUse:Bash hook error: FIXTURE: git status denied`; `permission_denials` lists the call | 1 → 1 | PASS |
| 3 | deny removed | `git status` | `* main\n?? ...` | 1 → 2 | PASS |

The deny fixture (`$S/fx/deny_git_status.py`, emits `permissionDecision: "deny"`) received the
original command `git status`. Claude ran both PreToolUse handlers and the deny won over rtk's
`updatedInput`.

## a2 Original vs rewritten; no double prefix

- L2 (run 3, PostToolUse logger `$S/fx/post_log.py`): the model's `tool_use` input and the
  parallel PreToolUse hook carry `git status`; PostToolUse `tool_input.command` is
  `rtk git status`. Any PostToolUse consumer sees the rewritten form. PASS.
- L6 (`rtk hook claude` fed directly, cwd `$R`, `RTK_DB_PATH` set):

  | Input command | rc | stdout |
  |---------------|----|--------|
  | `git status` | 0 | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecisionReason":"RTK auto-rewrite","updatedInput":{"command":"rtk git status"}}}` |
  | `rtk git status` | 0 | empty |
  | `git push origin main` | 0 | `{...,"updatedInput":{"command":"rtk git push origin main"}}` |
  | `rtk git push origin main` | 0 | empty |

  No `rtk rtk`. PASS. Note: rtk's answer carries no `permissionDecision`, so Claude's own
  permission flow still runs — which is where a3 goes wrong.

## a3 permissions with the rtk hook active

Prompt `Run exactly: git push origin main`; remote ref deleted before each run.

| Rule in project `permissions` | rtk handler | Remote `main` after | Tool result | Verdict |
|-------------------------------|-------------|---------------------|-------------|---------|
| `deny: Bash(git push:*)` | on | absent | `Permission to use Bash with command git push origin main has been denied.` | PASS |
| `deny: Bash(git push:*)` | off (control) | absent | same denial | control |
| `ask: Bash(git push:*)` | on | **`d3f445a`** | `* [new branch] main -> main` / `ok main`; PostToolUse saw `rtk git push origin main`; no denials | **FAIL — BLOCKING** |
| `ask: Bash(git push:*)` | off (control) | absent | `Claude requested permissions to use Bash, but you haven't granted it yet.` | control |
| `deny: Bash(rtk git push:*)` only | on | absent | `... with command rtk git push origin main has been denied.` | mechanism probe |
| `ask: Bash(rtk git push:*)` only | on | absent | `Claude requested permissions ...`; denial lists `rtk git push origin main` | mechanism probe |

Reading: deny is checked against the original and the rewritten command; ask only against the
rewritten one. A deny that rtk bypasses was not observed; an ask that rtk bypasses was.

## a4 pi

- `rtk init --agent pi` in `$R` with the adjustment's env (`RTK_TELEMETRY_DISABLED=1
  RTK_ONRAMP_DISABLED=1`, stdin closed) and `HOME=$S/fakehome`: rc 0, wrote only
  `.pi/extensions/rtk.ts` (4835 bytes); `$S/fakehome` stayed empty. `--dry-run -v` is rejected
  (`unexpected argument '-v'`, rc 2). PASS for "project scope only".
- Live run (a): `RTK_DB_PATH=$R/.rtkdb RTK_RECALL=0 pi -p --offline --no-session --approve --verbose --tools bash --model anthropic/claude-haiku-4-5 --mode json 'Run exactly: git status'`
  (`--mode json` added to capture events; `--model` added because the default is
  `claude-opus-5-5`). Result: Anthropic `400 ... credit balance is too low`; the global
  `router-fallback` extension switched to `openrouter/inclusionai/ling-3.1-flash`, which returned
  `402 ... requires more credits`. No tool call; gain unchanged. Wrote `~/.pi/agent/mcp-auth.json`
  (see Abort finding).
- Retry with `--no-mcp --model github-copilot/claude-haiku-4.5`: `400 ... model_not_supported`.
  No tool call. Live pi verification stopped here. NOT-VERIFIED.
- (b) isolated `--no-extensions -e <ai-badger pi extension> -e $R/.pi/extensions/rtk.ts`: not
  run (aborted). NOT-VERIFIED.
- Double rewrite (read, not run): both the project `rtk.ts` from `rtk init` (`if
  (cmd.startsWith("rtk ")) return`) and the global `~/.pi/agent/extensions/rtk` (`isRewriteCandidate`
  rejects `rtk ` prefixes) skip already-prefixed commands, and `rtk rewrite "rtk git status"`
  itself returns `rtk git status` (rc 3) — so stacking the two extensions should not produce
  `rtk rtk`. Whether both actually load and run in one session is NOT-VERIFIED.
- Trust: `--approve` did not change `~/.pi/agent/trust.json` (checksum unchanged); global
  settings carry `defaultProjectTrust: "ask"`. Whether a headless run without `--approve`
  skips `.pi/extensions/rtk.ts` was not observed (aborted). NOT-VERIFIED.

## a5 Codex, Copilot, Hermes

Not live-verified: `codex`, `copilot` and `hermes` are not installed. Offline observations:

- `rtk hook codex` fed a Claude-shaped PreToolUse payload for `git status`: rc 0, empty stdout.
  How Codex aggregates an ai-badger deny with rtk's answer stays UNVERIFIED.
- `rtk hook copilot`:
  - Copilot CLI shape (`toolName: "bash"`, `toolArgs: "{\"command\":\"git status\"}"`):
    `{"permissionDecisionReason":"RTK auto-rewrite","modifiedArgs":{"command":"rtk git status"}}`
    — a rewrite, not a deny.
  - VS Code shape (`tool_name: run_in_terminal` or `Bash`, `tool_input.command`):
    `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecisionReason":"RTK auto-rewrite","updatedInput":{"command":"rtk git status"}}}`.
- rtk's own wording (binary strings, `rtk init --copilot` success banner, the same text logged in
  `docs/work/2026-10-17-rtk-research/outputs/copilot-l.log`): "Works with VS Code Copilot Chat
  (transparent rewrite) and Copilot CLI (deny-with-suggestion)." A separate capability string
  reads "RTK degrades to deny-with-suggestion before the tool". `rtk init --help`/`rtk hook
  copilot --help` say only "VS Code + Copilot CLI". Dry runs (`HOME=$S/fakehome2`, nothing
  written): project `--copilot` targets `./.github/copilot-instructions.md` and
  `./.github/hooks/rtk-rewrite.json`; `-g` targets `$HOME/.copilot/...`.
- Conflict with `features/copilot/adjustments/adjust_tools.py` NOTE ("VS Code Copilot Chat and
  Copilot CLI >= 1.0.73 apply the rewrite transparently; JetBrains Copilot gets
  deny-with-suggestion instead"): rtk 1.0.1 *emits* a transparent `modifiedArgs` rewrite for the
  CLI payload, but its own install text still promises Copilot CLI deny-with-suggestion and
  names no JetBrains case or version floor. The 1.0.73 floor and the JetBrains attribution have no
  support in rtk 1.0.1's text; whether Copilot CLI honours `modifiedArgs` is unverified.
- Hermes is proposal-only (`mode: propose`); nothing to run.
