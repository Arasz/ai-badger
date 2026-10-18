# Research: an rtk Claude hook that keeps permissions.ask rules working

**Date:** 2026-10-18
**Question:** How can rtk's command rewriting run under Claude Code without bypassing
`permissions.ask` rules, and which fix is cheapest that holds?

Raw outputs and the prototype hook are in `2026-10-18-rtk-ask-preserving-hook/`. Machine: Apple M4,
macOS, Claude Code 2.1.302, rtk 1.0.1 (Homebrew). Live runs reuse the s13 harness from
`docs/work/2026-10-17-rtk-live-verification.md`: headless `claude -p --model haiku`, project settings
only, `--allowedTools Bash` as the broad allow, and a local bare remote for every push.

```chart:range
title: hook latency per Bash call, ms (15 runs each)
native rtk hook claude: 12..12..14
ask-preserving wrapper: 36..38..69
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

### F10 — Codex cannot use this fix; its approval is not driven by Claude's permission rules [INFERRED]

From F2 and ADR 0039's Codex consequences. rtk's checks read Claude Code settings files, while
Codex approval comes from its own policy and classifiers, and rtk's Codex hook always answers
`allow`. The wrapper would detect only rules a Codex project does not have. Codex stays
propose-only.

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
- Whether to ship this in ai-badger: replace `rtk hook claude` in the guarded Claude command with a
  mode-A wrapper, and move Claude from `propose` back to `native`. That decision needs a test that
  goes red with the bypass (v0) and green with the wrapper (v1).
