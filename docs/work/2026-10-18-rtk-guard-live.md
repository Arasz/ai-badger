# Live check: the rtk guard hook under headless Claude Code

**Date:** 2026-10-18
**Question:** With the 0.197.0 guard wired the way the scaffold wires it, does a project
`permissions.ask` rule still stop `git push`, and is an unrelated command still compressed?

Raw outputs and the harness are in `2026-10-18-rtk-guard-live/`. Machine: Apple M4, macOS,
Claude Code 2.1.302, rtk 1.0.1 (Homebrew). Harness (`live.py.txt`): one fresh temp repo per run
with an initial commit on `main` and a local bare remote as `origin`; a project
`.claude/settings.json` holding one PreToolUse `Bash` handler whose command is
`tool_hooks.guarded_command("rtk", "claude", <rtk_guard.py>)` from this branch, timeout 5; then
`claude -p --setting-sources project --model haiku --max-turns 3 --allowedTools Bash
--output-format stream-json --verbose --no-session-persistence --strict-mcp-config` with
`RTK_DB_PATH` inside the temp dir and `RTK_RECALL=0`. `--allowedTools Bash` is the broad allow
the ask rule has to carve out. The rtk tracking database shows what rtk actually ran.

## Results [MEASURED]

| Run | Hook | Ask rule | Command | Remote `main` after | rtk ran | Denials |
|---|---|---|---|---|---|---|
| g0 | 0.194.0 `rtk hook claude` (control) | `Bash(git push:*)` | `git push origin main` | **pushed** | `rtk git push origin main` | 0 |
| g1 | guard | `Bash(git push:*)` | `git push origin main` | none | — | 1 (`git push origin main`) |
| g2 | guard | `Bash(git push:*)` | `git status` | — | `rtk git status` | 0 |
| g3 | guard | none | `git push origin main` | pushed | `rtk git push origin main` | 0 |

g0 reproduces the bypass that made 0.195.1 switch Claude to propose. In g1 the tool result was
Claude's own "Claude requested permissions to use Bash", the same denial the no-rtk control gave
on 2026-10-17, and the denial names the original command. g2's tool result was rtk's compressed
`* main` / `?? .claude/`. g3 shows the guard still rewrites a push when no rule names it.
`shasum -a 256 ~/.claude/settings.json` was the same before and after every run.

## Probes behind the review-driven fixes [MEASURED]

- `nl_probe.txt`: with `Bash(git push:*)` in a temp project's `ask`,
  `RTK_REWRITE_HOST=openclaw rtk rewrite "git status\ngit push origin main"` exits 3, so rtk's own
  matcher sees an ask rule on a second line. Without the variable, `git status` alone exits 3, and
  with it 0: an inherited `RTK_REWRITE_HOST` would have turned "no allow rule covers this" into
  `allow`. The guard therefore strips the variable from its first call.
- `wrap_probe.txt`: rtk rewrites inside `bash -c '…'`, `env …`, `time …`, `nice …` and
  `command …`, and every line of a multi-line command. A Codex prefix rule checked against the
  wrapper's argv cannot see those, so the Codex adapter fails closed when the rewrite is not
  `rtk` put in front of whole commands, and on any newline.

## Still open

- No live Codex run (codex is not logged in here); Codex stays `propose`. The Codex adapter is
  covered offline by `tests/test_rtk_guard.py` against a stub `codex execpolicy check`.
- An interactive (non `-p`) session: the prompt for g1 should show the original command.
