# Research: an rtk Claude hook that keeps permissions.ask rules working

**Date:** 2026-10-18
**Question:** How can rtk's command rewriting run under Claude Code without bypassing
`permissions.ask` rules, and which fix is cheapest that holds? Follow-up, same day: can one
ai-badger-owned hook, replacing `rtk hook <agent>`, keep both Claude's ask rules and Codex's
approval rules judging the original command?

Raw outputs and the prototype hook are in `2026-10-18-rtk-ask-preserving-hook/`. Machine: Apple M4,
macOS, Claude Code 2.1.302, rtk 1.0.1 (Homebrew). Live runs reuse the s13 harness from
`docs/work/2026-10-17-rtk-live-verification.md`: headless `claude -p --model haiku`, project settings
only, `--allowedTools Bash` as the broad allow, and a local bare remote for every push.

```chart:range
title: hook latency per Bash call, ms (15 runs each)
native rtk hook claude: 12..12..14
ask-preserving wrapper: 36..38..69
rtk_guard codex, one rule file: 104..116..141
codex execpolicy check, native binary: 11..11..20
codex execpolicy check, npm launcher: 100..112..186
```

## Findings

### F1 — Claude evaluates permission rules against the hook's rewritten input, by design [READ]

The hooks reference says Claude Code "evaluates permission rules … against the input your hook
returns, not the input Claude sent". The ask bypass is documented behaviour, not a Claude Code
defect, so waiting for Claude Code to change is not a fix. The same table says `updatedInput`
combines "with `"ask"` to show the modified input to the user", and that multiple hooks resolve as
`deny > defer > ask > allow`.

**Evidence:** https://code.claude.com/docs/en/hooks, PreToolUse decision control table, rows
`permissionDecision` and `updatedInput` (fetched 2026-10-18; read the sections matching
`updatedInput` and `permissionDecision`, not the whole page).

### F2 — `rtk rewrite` already checks Claude's rules on the original command, and can isolate "an ask rule matched" [READ]

`rtk rewrite --help` defines exit 0 (allow rules cover every command), 1 (no rewrite), 2 (a deny
matched) and 3 (an ask rule matched, or allow rules do not cover every command). With
`RTK_REWRITE_HOST=openclaw`, "every 3 but an ask rule's" becomes 0. So a second call with that
variable answers exactly the question the hook needs: did an ask rule match the original command?

**Evidence:** `rtk rewrite --help`, rtk 1.0.1.

### F3 — rtk's reference hook drops that signal: on exit 3 it omits permissionDecision and assumes Claude will prompt [READ]

`hooks/claude/rtk-rewrite.sh` handles exit 3 as "rewrite the command, omit permissionDecision so
Claude Code prompts". By F1, Claude then matches the rewrite, so an ask rule for the original stops
applying whenever a broader rule or flag allows the rewritten command. In the usual setup, a broad
Bash allow with `ask` carving out risky commands, the ask is lost. Upstream #886 (closed, fixed in
0.35.0) fixed the no-rule case only. #1771 (open) asks for the opposite change, adding `"allow"` on
every rewrite, which would widen this hole.

**Evidence:** https://raw.githubusercontent.com/rtk-ai/rtk/develop/hooks/claude/rtk-rewrite.sh
(the `case $EXIT_CODE` block); https://github.com/rtk-ai/rtk/issues/886;
https://github.com/rtk-ai/rtk/issues/1771 (both fetched 2026-10-18).

### F4 — The openclaw call detects the ask rule from every settings source and every rule shape tried, except a bare `Bash` [MEASURED]

The ask rule was detected (exit 3 under openclaw) when placed in project `settings.json`, in
`settings.local.json`, or in the user's `~/.claude/settings.json`; with cwd in a subdirectory; and
inside a chain (`git status && git push …`). It was detected for eight rule shapes: `:*`, ` *`,
`*`, exact, `git:*`, `* push *`, `git * main` and bare `git push`. It was not detected for a bare
`Bash` ask rule, which returned 0. Managed (enterprise) settings were not tested.

**Evidence:** `sources.sh` and `shapes.py.txt` in the raw-output directory, one fresh temp repo and
temp HOME per case, `rtk rewrite "git push origin main"`; results in `sources.txt` and
`shapes.txt`.

### F5 — Mirroring each ask rule as `Bash(rtk …)` cannot work in general, because rtk renames commands [MEASURED]

Most rewrites prefix `rtk ` per chain segment, after any env assignment (`FOO=1 rtk git push`).
Some replace the command name: `cat README.md` becomes `rtk read README.md`. A mirrored
`Bash(rtk cat:*)` would never match that. Some commands are not rewritten at all (`npm test`,
`sudo …`, `rm -rf …`). A mirror list would also be one more hand-kept twin of the user's rules.

**Evidence:** `probe.sh` over the 17 commands in `cmds.txt`, temp `RTK_DB_PATH`, telemetry off;
results in `rewrite.tsv`.

### F6 — An ask-preserving wrapper closes the bypass live; both variants stop the push and still compress other commands [MEASURED]

The prototype `rtk_ask_safe.py.txt` calls `rtk rewrite`, and on exit 3 calls it again with
`RTK_REWRITE_HOST=openclaw`. If that also returns 3, an ask rule matched. Mode A then emits nothing,
so Claude sees the original command. Mode B emits the rewrite with `permissionDecision: "ask"`.
Otherwise it emits the rewrite, with `allow` only on exit 0, as rtk's reference hook does.

Results, same project, ask rule `Bash(git push:*)`, Bash allowed via `--allowedTools`:

| Run | Hook | Command | Remote `main` after | Executed | Denials |
|---|---|---|---|---|---|
| v0 | 0.194.0 native (`rtk hook claude`) | `git push origin main` | **pushed** | `rtk git push origin main` | 0 |
| v1 | wrapper, mode A | `git push origin main` | none | — | 1 (`git push origin main`) |
| v2 | wrapper, mode B | `git push origin main` | none | — | 1 (`rtk git push origin main`) |
| v3 | wrapper, mode A | `git status` | — | `rtk git status` | 0 |
| v4 | wrapper, mode B | `git status` | — | `rtk git status` | 0 |

v0 reproduces the s13 bypass. In v1 the tool result was Claude's own "Claude requested permissions
to use Bash", the same denial as the no-rtk control in s13. In v2 the tool result carried the hook's
reason, "rtk rewrite". `~/.claude/settings.json` was unchanged across all five runs (shasum before
and after).

**Evidence:** `run.sh <name> <hook> <ask> <command>` with `case.py.txt`, rewiring
`scratchpad/s13/R/.claude/settings.json` and a fresh bare remote per run; transcripts
`v0…v4.jsonl`; summary lines in `live.txt`.

### F7 — The wrapper costs about 26 ms more per Bash call than rtk's native hook [MEASURED]

Native `rtk hook claude`: 12–14 ms, median 12. Python wrapper: 36–69 ms, median 38. The wrapper
pays for one Python start plus one or two `rtk rewrite` processes. A shell version would be cheaper.
This is well inside the hook's 5 s timeout and below a Bash command's own run time.

**Evidence:** 15 runs each with `subprocess.run` on Apple M4, `git status` and
`git push origin main` payloads, in a temp repo with an ask rule and an allow rule.

### F8 — Mode A is the safer default: the host sees exactly what it would see without rtk [INFERRED]

From F1 and F6. In mode A an ask-matched command reaches Claude unrewritten, so every permission
path behaves as if rtk were absent: matching, the prompt text, the approved command, and auto-mode
and sandbox behaviour. The only cost is that those few commands are not compressed. Mode B keeps
compression, but the prompt shows `rtk git push …` rather than what the model asked for. It also
depends on Claude honouring a hook `ask` with `updatedInput`. A comment on #1771 links
anthropics/claude-code#75915: when one hook allows with `updatedInput` and a sibling asks,
approving runs the original and drops the rewrite. That behaviour is untested here.

### F9 — The bare `Bash` ask rule that rtk misses is still safe, because the host's own rule matches the rewrite too [INFERRED]

From F4 and F1. `Bash` with no specifier matches every Bash command, including `rtk git push`, so
Claude still asks after the rewrite. This was reasoned from the rule semantics, not run live.

### F10 — Codex cannot use the openclaw check; its rules are not Claude's [INFERRED]

From F2. rtk's checks read Claude Code settings files, and Codex's rules live in its own `.rules`
files, so the Claude wrapper detects nothing a Codex project has. F11–F16 replace the earlier
reading here that Codex's `allow` is what skips approval: it is not (F11), and the Codex half needs
its own adapter (F14).

### F11 — In Codex, a hook rewrite swaps the command before every approval step; `allow` approves nothing [READ]

Codex's hook result type has two variants, `Continue { updated_input }` and `Blocked`, and no
approved state. The tool registry replaces the invocation with the rewritten one and then
dispatches the normal handler, so `exec_command`'s approval, execpolicy and sandbox handling all
run on the rewritten command. The rewrite replaces only the `cmd` argument, and keeps
`sandbox_permissions` and `justification`. The docs agree: `updatedInput` is accepted only with
`permissionDecision: "allow"`, and `"ask"` is "parsed but not supported yet".

**Evidence:** openai/codex at `8c076942cb70fba8e5c4732c23f1faabc4aed484`:
`codex-rs/core/src/hook_runtime.rs:81-84` (the enum), `codex-rs/core/src/tools/registry.rs:712-751`
(the swap before dispatch), `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs:512-529`
(`cmd` rewritten in place). https://learn.chatgpt.com/docs/hooks, PreToolUse section, the
paragraphs after "To rewrite a supported tool call without blocking" (fetched 2026-10-18).

### F12 — With `rtk` prepended, Codex `prompt` and `forbidden` rules both stop matching [MEASURED]

`codex execpolicy check` with `prefix_rule(["git","push"], "prompt")` and
`prefix_rule(["rm"], "forbidden")`: `git push origin main` gives `prompt`, and
`rtk git push origin main` matches nothing; `rm -r build` gives `forbidden`, and `rtk rm -r build`
matches nothing. Codex has no counterpart to Claude checking deny against both forms, so the Codex
hole includes `forbidden`. rtk does not rewrite `rm` (F5), but it does rewrite `git push` (F6 v0).

**Evidence:** codex-cli 0.163.0 (npm `@openai/codex`, installed into the session scratchpad only),
Apple M4, `codex execpolicy check --rules r.rules -- <argv>` (rules file saved as `r.rules.txt`); results in `codex-execpolicy.txt`.

### F13 — Output-side compression is not a substitute: rtk's pipe filters lose data, and rtk-proxy does not compress Codex traffic [MEASURED]

Rewriting to `<cmd> | rtk pipe -f <filter>` would keep the original command as its own pipe
segment, which both hosts' rule matchers see. But the pipe filters expect the formats rtk's own
proxy commands force. `git log -n 30` (31,991 bytes) came back as one commit plus
"[+427 lines omitted]", and `git diff HEAD~5 --stat` came back empty with exit 0. A pipe also
reports the filter's exit status, not the command's. rtk-proxy's router intercepts only
`/v1/messages` (Anthropic, compressed) and `/v1/chat/completions` (OpenAI, "forward and measure;
not compressed"), and answers anything else with 404.

**Evidence:** `bash -c` loop in this repo, rtk 1.0.1 with temp `RTK_DB_PATH`, raw vs `rtk <cmd>` vs
`<cmd> | rtk pipe -f <filter>` byte counts; rtk-ai/rtk at `e542dca0bdcc262fa035dcf7fc33910cdcc8cdaf`:
`proxy/src/server.rs:41-43` and `docs/guide/proxy/configuration.md:40-56`.

### F14 — One guard hook with two host adapters keeps the original command in front of each host's rules, offline [MEASURED]

`rtk_guard.py.txt` runs `rtk rewrite` and emits the rewrite only when no host rule names the
original command. Claude adapter: the F6 mode-A check (openclaw exit 3 means hand the original
over). Codex adapter: find `.rules` files under `$CODEX_HOME` (default `~/.codex`) and under each
`.codex/` from cwd up to the git root, split the original command into chain segments (dropping
leading `NAME=value` words), and run `codex execpolicy check` on each. Any matched rule, of any
decision, means hand the original over. It fails closed: when rule files exist but `codex` is
missing, or the text is not a plain chain, the command passes through unrewritten. No rule files
means rewrite. All 8 Codex cases passed: no rules; a user `prompt` rule; a project `forbidden`
rule; a rule for another command; a chain; an env assignment; codex missing; subdirectory cwd. The
env-assignment case failed on the first draft and passed after the fix. The 3 Claude cases repeat
F6: `git push` and the chain unchanged, `git status` rewritten.

**Evidence:** `guard_cases.py.txt` (one temp repo and temp `CODEX_HOME` per case, Codex-shaped
`PreToolUse` payload) plus three Claude payloads against a temp repo with
`ask: Bash(git push:*)`; results in `guard_cases.txt`.

### F15 — The Codex adapter costs about 116 ms per Bash call, so it must call the native binary [MEASURED]

`codex execpolicy check`: median 11 ms through the native binary, 112 ms through the npm launcher.
The whole guard with one rule file: 104–141 ms, median 116 ms, across 15 runs. That is ten times rtk's native hook, so a shipped version wants the native binary
path and one check per command.

**Evidence:** `subprocess.run` loops, 15 runs each, Apple M4; results in `codex-latency.txt` and
the last line of `guard_cases.txt`.

### F16 — Replacing `rtk hook <agent>` in ai-badger is a one-function swap [READ]

ai-badger already owns the hook command: `tool_hooks.guarded_command(tool, hook_arg)` builds the
marked shell line that runs `<tool> hook <hook_arg>` behind a fail-open guard, and the arms
recognise their entries by the `AI_BADGER_TOOL` marker alone. A guard script shipped beside
`features/common/tools/rtk/scripts/` can take the place of `rtk hook claude|codex` in that line.
Marker matching, merge order and the propose notes stay as they are.

**Evidence:** `features/common/skills/welcome-ai-badger/scripts/tool_hooks.py:16-31`;
`features/claude/adjustments/adjust_tools.py:3`; `features/common/tools/rtk/scripts/` lists
`check.py` and `install.py`.

### F17 — The guard's rule search is a list that can drift from Codex's own [INFERRED]

From F14 and the Codex rules docs. Codex also loads rules from Team Config layers and admin
`requirements.toml`, and loads project rules only when the project `.codex/` is trusted. The
prototype reads the user and project layers only. A rule in a layer it misses is bypassed exactly
as before, so a shipped guard should fail closed when any layer it cannot read is present. The
search is still a copy of Codex's discovery, and an upstream fix inside `rtk hook codex` would
carry the same copy.

## Still open

- A live interactive (non `-p`) session with mode A, a broad allow and an ask rule. Expected: the
  prompt shows the original command, and approving runs it uncompressed. Only headless was run.
- Managed (enterprise) settings as an ask-rule source for rtk's matcher (F4 tested project, local
  and user only).
- Whether rtk's matcher drifts from Claude Code's on edge shapes: compound commands with `$(...)`,
  redirects, `bash -c` wrappers, and Claude's own compound-command splitting. F4 covers eight shapes
  and one chain.
- The upstream fix: rtk's `hook claude` should emit `permissionDecision: "ask"`, or skip the
  rewrite, when the openclaw check says an ask rule matched. Not filed yet; issue #1771 shows
  pressure toward the opposite change.
- Mode B with a sibling hook (anthropics/claude-code#75915) was not reproduced.
- No live Codex run: codex is not logged in here. The Codex adapter is proven against
  `codex execpolicy check` offline. A real Codex session, with rtk running inside its sandbox and a
  `prompt` rule for `git push`, is the gate before Codex goes `native`. Whether rtk's tracking
  database write survives the workspace-write sandbox is also unknown.
- Codex under `approval_policy = "untrusted"`: its built-in safe-command list would likely treat
  `rtk git status` as unknown and prompt where `git status` ran freely. That is the safe direction,
  but untested.
- Team Config, `requirements.toml` and trusted-project detection for the Codex rule search (F17).
- Whether a matched `allow` rule should still let the rewrite through. The prototype hands the
  original over for any matched rule. That is simplest, but it gives up compression on
  allow-listed commands.
- Whether to ship this in ai-badger: swap `rtk hook claude|codex` in
  `tool_hooks.guarded_command` for the guard (F16). Claude can then go back to `native`; Codex
  stays `propose` until the live Codex run above. The decision needs a test that goes red with
  the bypass (v0, and F12 for Codex) and green with the guard.
