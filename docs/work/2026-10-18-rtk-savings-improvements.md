# Research: where rtk savings on this machine can still be improved

**Date:** 2026-10-18
**Question:** Which rtk configuration changes — pipelines included — would raise token savings for this machine's command mix, judged against `rtk gain`?

```chart:bars
title: tokens removed, thousands (rtk gain, all time)
hook filters (rtk gain total): 378.5
proxy ccr trimmed in flight: 60800
```

## Findings

### F1 — The proxy, not the hook table, is where the savings are: 61.0M trimmed vs 378.5K [MEASURED]

The table in the request is the hook layer's "By Command" view: 378.5K tokens saved (17.8%) over 5,327
commands. The same `rtk gain` run reports the LLM proxy trimmed 61.0M input tokens across 3,717 of 7,150
requests, 60.8M of it through the `ccr` rule, with a 97.4% cache hit rate. The proxy removed about 160× what
the hook filters removed. Tuning the hook's top rows (`rtk read`, `rtk grep`) moves the smaller number; the
`ccr` threshold and the proxy's health move the larger one. Both are byte/4 estimates, so the ratio holds
better than the absolutes.

**Evidence:** `rtk gain` (rtk 1.0.1, macOS, 2026-10-18 ~13:30 local), saved verbatim to the session
scratchpad as `gain.txt`: "Tokens saved: 378.5K (17.8%)", "Trimmed in flight: 61.0M removed across the 3717
req", "via ccr: 60.8M", "Cache hit: 97.4%". Estimator: https://www.rtk-ai.app/docs/resources/savings-explained/

### F2 — 437 of 7,150 proxy requests failed (6.1%) [MEASURED]

Failed requests are excluded from the cost figures, so the 61.0M undercounts nothing, but a 6% failure rate
on the path every Claude request takes is the proxy's largest open defect on this machine. The cause was not
investigated (see Still open).

**Evidence:** same `rtk gain` run: "Requests: 7150", "Failed: 437 (excluded from cost)".

### F3 — `git diff` output is truncated by rtk's own filter, and the `keep-verbatim` rule cannot stop it [MEASURED]

`pipeline.toml` declares `keep-verbatim` (`hook.after_tool.shell`, `command_matches = "^(rtk )?(git (diff|show)|recall)\b"`,
`action = "passthrough"`) to give diffs to the agent byte-for-byte. But the PreToolUse rewrite turns
`git diff` into `rtk git diff`, and that filter compacts before PostToolUse ever runs. On the 149-line
`user_hook.py` diff from merge `cbffc5e3`, `rtk git diff` replaced the git headers with a stat summary and
dropped the last 49 added lines behind `... (49 additions truncated)` / `[full diff: rtk git diff --no-compact]`:
155 lines → 110, 6,304 bytes → 4,282. A reviewer reading that diff would not see `main()`.
rtk's own reference pipeline `rtk:verbatim-diffs` puts its `keep-diffs` passthrough under
`hook.before_tool.shell`, not `after_tool` — the placement that would prevent the rewrite.

**Evidence:** `RTK_DISABLED=1 git diff cbffc5e3~1 cbffc5e3 -- features/common/tools/rtk/scripts/user_hook.py`
vs `rtk git diff …` in `/Users/arasz/RiderProjects/ai-badger`, `wc -l`/`wc -c`, then `diff` of the two
(scratchpad `delta.txt`). Rule: `~/.config/rtk/pipeline.toml:52-55`. Reference placement:
https://www.rtk-ai.app/docs/pipelines/reference-pipelines/ (`rtk:verbatim-diffs`).

### F4 — Excluding `git diff`/`git show` in `config.toml` is the fix that reaches ai-badger's guard [INFERRED]

The guard (`features/common/tools/rtk/scripts/rtk_guard.py:24-31`) calls `rtk rewrite`, not `rtk hook claude`,
so a pipeline `before_tool` passthrough may not be consulted by it. `[hooks] exclude_commands` is documented
as matching the command before rewrite, including subcommand patterns (`"git push"`), and `config.toml:40-41`
has it empty. Inferred from the docs plus the guard's call path: `exclude_commands = ["git diff", "git show"]`
would make `rtk rewrite` decline those commands, so the diff reaches the agent whole. Cost: today's discover
shows `git diff` as the third-largest missed saving (~126.9K est./day), so this deliberately gives up savings
for fidelity. Not run, because it edits the operator's config.

### F5 — Hook coverage rose from 1.3% (30 days) to 17.4% (last day) of Bash commands [MEASURED]

`rtk discover --all` over 30 days: 121,227 Bash commands, 1,570 through rtk (1.3%), ~22.9M tokens est.
missed on commands rtk handles. Over the last day: 9,050 commands, 1,572 through rtk (17.4%), ~662.9K est.
missed. The 30-day "22.9M saveable" is almost entirely history from before the hook existed and should not
be read as current loss.

**Evidence:** `rtk discover --all --limit 25` and `rtk discover --all --since 1 --limit 12`, rtk 1.0.1, scanning
Claude Code history (scratchpad `discover.txt`, `discover1.txt`).

### F6 — The common shapes rewrite correctly through the guard's probes [MEASURED]

`rtk rewrite` rewrites `grep -n … | head`, `git diff A...B -- x`, `git diff --stat 2>&1 | tail`, `ls -la`,
`wc -l`, `gh pr view`, `cd /tmp && grep …` and trailing `# memory-checked` comments. Every exit-3 case
returned 0 under `RTK_REWRITE_HOST=openclaw`, so no ask rule matched and the guard rewrites them. Not
rewritten: `sed -n …`, `git grep …`, and `/…/.venv/bin/python3 -m pytest …`, while `python3 -m pytest …` is
rewritten to `rtk pytest`.

**Evidence:** `rtk rewrite "<cmd>"; echo $?` and the same under `RTK_REWRITE_HOST=openclaw`, run in
`/Users/arasz/RiderProjects/ai-badger`, 2026-10-18.

### F7 — This repo's mandated venv pytest never reaches `rtk pytest` [INFERRED]

The project invariant `local/venv-python` requires `.venv/bin/python3` for tests, and F6 measured that spelling
is not rewritten. Discover lists `/Users/arasz/RiderPro…` → `rtk pytest` as 46 missed commands (~8.8K est.)
in the last day, consistent with this. Small, but it is every test run here. Whether `transparent_prefixes`
or a `filters.toml` entry can peel an absolute interpreter path is unverified.

### F8 — The remaining 1,656 missed handled commands today are not explained [UNVERIFIED]

F6 shows the shapes rewrite, yet discover still counts 235 `cat -n`, 413 `grep -n`, 474 `git diff` missed in
the last day. Candidates: sessions started before today's hook change keep their old hook, other harnesses,
or ask-rule matches. None was checked; discover's text output gives no timestamps.

### F9 — Filter caps are not too aggressive: 0 recalls across 170 grep and 97 ls elisions [MEASURED]

`rtk gain --recalls` reports a 0% recall rate for every filter. rtk defines "too aggressive" as a high recall
rate, so there is room to tighten `grep_max_results = 200` / `grep_max_per_file = 25` (`config.toml:46-47`).
The data does not show the gain, since a tighter cap that triggers recalls costs an extra turn plus the full output.

**Evidence:** `rtk gain --text --recalls` (scratchpad `g-recalls.txt`), and its own explanation line
"too aggressive means the filter hides output the agent comes back for".

### F10 — The "PreToolUse hook missing" warning is a false alarm under ai-badger's guard [INFERRED]

`rtk gain` and `rtk pipeline validate` both print "hook needed: PreToolUse hook missing". ai-badger wires
PreToolUse through the guard command, which rtk does not recognise (`features/common/tools/rtk/tool.md`: "rtk
does not recognise ai-badger's guarded hook"). The only `before_tool` rule active is the inherited
`rtk-rewrite`, which the guard performs via `rtk rewrite` (F6). Running the suggested `rtk init -g` would add
the bare `rtk hook claude` PreToolUse that bypasses `permissions.ask` rules. `[hooks] suppress_hook_warning`
exists in `config.toml:43` to silence it.

### F11 — The `haiku-large-*` routes fire rarely; `compact` kept 90.5K out over 13 calls [MEASURED]

Per rule over 30 days: `term-default` 19 calls / 10.3K saved, `haiku-large-shell` 1 call / 7.3K, `compact`
task 13 calls / 90.5K kept out (99%). The Haiku compaction works when it fires; the 5,000-token threshold means
it seldom does. Lowering it trades seconds of hook latency per call (`timeout_secs = 15`) for more digests.

**Evidence:** `rtk gain --text --by-rule` (scratchpad `g-by-rule.txt`); thresholds `~/.config/rtk/pipeline.toml:60-76`.

## Still open

- **F2:** why 437 proxy requests failed. Settle with the proxy log, or `rtk gain --watch` while failures occur.
- **F4:** confirm `rtk rewrite` honours `exclude_commands`. Settle by adding `"git diff"` and checking that
  `rtk rewrite "git diff"` exits 1, then reverting if unwanted.
- **F7:** whether `transparent_prefixes` (empty at `config.toml:42`, undocumented on the configuration page)
  can map `.venv/bin/python3 -m pytest` to `rtk pytest`.
- **F8:** what the 1,656 missed commands are. Needs `rtk discover --format json` with session ids, matched
  against session start times relative to today's hook change.
- **F9/F11:** neither threshold change was measured. Each needs a before/after `rtk gain --by-rule` over a
  comparable workload, and a recall-rate check.
- The `ccr` threshold (`tokens_gt = 1500`) was not examined, though F1 makes it the largest lever.
  134 recovery calls over 3,717 touched requests is the starting data.
