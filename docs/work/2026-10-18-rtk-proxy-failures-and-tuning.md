# Research: rtk proxy failures, the "missed" commands, and grep / ccr / Haiku thresholds

**Date:** 2026-10-18
**Question:** Why do rtk proxy requests fail, what were the 1,656 missed commands, and which grep, ccr and Haiku thresholds should replace the current ones?

Follow-up to `2026-10-18-rtk-savings-improvements.md`. Diff compaction stays as it is (operator decision).

```chart:bars
title: ccr blocks retrieved by the model, % by block size (tokens_before)
250-500: 9.2
500-1k: 6.6
1k-1.5k: 11.3
1.5-2k: 12.7
2-3k: 21.7
3-5k: 41.9
5-10k: 27.3
```

## Findings

### F1 — 417 of the 437 failed proxy requests are HTTP 429 rate limits from the upstream [MEASURED]

Of the proxy's recorded requests, 6,952 returned 200, 417 returned 429, 17 returned 400 and 3 returned 401. Every
non-200 is on `/v1/messages`. The 429s are on the session models (opus-5-5 252, sonnet-5-5 80,
haiku-4-5-20251001 76, sonnet-5 9) and arrive in bursts: whole minutes where 33 of 33 requests failed
(2026-10-18T02:47), and 132 of 708 in the 02:00 hour. Since 2026-10-18T08:00 only 7 of 2,177 requests
returned 429. The log records the proxy retrying transient upstream statuses.

**Evidence:** `sqlite3 -readonly` on `~/Library/Application Support/rtk/llm-proxy/rtk-proxy.db`, table
`usage_records`, grouped by `status`, `model`, hour and minute; log line
`rtk_proxy::forward: transient upstream status; retrying url="https://api.anthropic.com/v1/messages"`
in `rtk-proxy.log` (2026-10-18T11:24:57Z). macOS, rtk 1.0.1, queried 2026-10-18 ~13:45 local.

### F2 — The 429s are the account's rate limit under parallel load, not a proxy defect [INFERRED]

From F1: the failures cluster in the minutes when many sessions ran at once. Requests of 200–500k input
tokens failed at 8.5%, against 3.2–3.3% for smaller ones, which fits a tokens-per-minute limit. Since this
morning's restart, with a lighter load, they almost vanish. The proxy forwards the upstream status; it does not
create it. It was not checked whether the same requests would also have hit 429 without the proxy.

**Evidence:** same table, 429 rate by `tokens_in` bucket: <100k 89/2,814 (3.2%), 100–200k 38/1,154 (3.3%),
200–500k 290/3,406 (8.5%), ≥500k 0/22.

### F3 — The Haiku compaction worker has failed every call since 2026-10-17 15:10: the API key has no credits [MEASURED]

rtk's own worker calls (client `ureq`, model `claude-haiku-5-5`) succeeded 24 times between 14:54 and 15:10
on 2026-10-17 and have returned 400 on all 18 calls since. Running the task by hand reproduces it 3/3. The
upstream answer is `invalid_request_error`: "Your credit balance is too low to access the Anthropic API". On
failure rtk shows the command's own output, so nothing breaks; the compaction just never happens. The
"compact 13 calls, 90.5K kept out" in `rtk gain --by-rule` is history from those first 16 minutes.

**Evidence:** `rtk compact --question "summarise the numbers" -- seq 1 6000` ×3 in `/private/tmp`
(2026-10-18 11:50Z), each printing `worker call failed (400) … credit balance is too low … request_id
req_011Cg9eoMqbMYTgZ6sJeXsS2`; the three new `usage_records` rows show status 400, tokens_in 7461. History:
`select status,count(*),min(ts),max(ts) from usage_records where client='ureq' group by status`.

### F4 — The Haiku threshold is lowered to 2,500, but it saves nothing until the key has credits [INFERRED]

On the operator's instruction, `haiku-large-shell`, `haiku-large-web` and `haiku-large-mcp` went from 5,000 /
5,000 / 6,000 to `tokens_gt = 2500` (`~/.config/rtk/pipeline.toml:62,68,74`; `rtk pipeline validate` ok).
From F3, until the key has credits, each newly routed output becomes a failed call: 260–600 ms of hook latency
(F3 rows) and nothing saved. The value is not backed by data. There were only 24 successful calls, all on
one afternoon.

### F5 — Claude Code transcripts store the agent's original command, not the hook's rewrite [MEASURED]

In this session's transcript, 2 of 160 Bash `tool_use` commands start with `rtk`, both typed by hand
(`rtk bypass …`). Two commands written without `rtk` have `rtk recall` markers in their stored results:
rtk rewrote and filtered them, and the transcript kept the original text.

**Evidence:** Python scan of
`~/.claude/projects/-Users-arasz-RiderProjects-ai-badger/29e18f8e-e1df-4951-a45a-37faf313727c.jsonl`,
pairing each Bash `tool_use` id with its `tool_result` and matching `rtk recall` in the result against
`"rtk "` absent from the command.

### F6 — `rtk discover`'s "missed" counts include commands rtk did run [INFERRED]

discover scans transcripts (`--help`: "from Claude Code history"), which by F5 hold the pre-rewrite command,
so a command the hook rewrote looks unconverted. rtk's own `history.db` records 975 runs from an original
`grep -n…`, 197 from `git diff…`, 50 from `ls -la…` and 22 from `gh pr…` since 2026-10-17. discover lists 413
`grep -n` and 474 `git diff` as missed for the same day. The two cannot be joined per command, because the
guard does not write `hook_decisions`: its 2,672 rows stop at 10:53 and come from rtk's native hook. So
the share actually missed is unknown, and lower than discover reports.

**Evidence:** `sqlite3 -readonly ~/Library/Application Support/rtk/history.db`: `commands` filtered by
`timestamp>='2026-10-17'` and `original_cmd like '<prefix>%'`; `hook_decisions` grouped by `decision`
(ask 1,207, defer 1,465, last 2026-10-18T10:53). discover figures from
`rtk discover --all --since 1 --format json`.

### F7 — grep caps can drop: 0 recalls, few large outputs; now set to 100 / 15 [MEASURED]

Of 1,495 `rtk grep` runs, 1,083 saved tokens; mean output 312 tokens; only 50 outputs exceeded 1,000 tokens
and 15 exceeded 2,000. `rtk gain --recalls` shows 0 recalls over 170 grep elisions. `grep_max_results`
200 → 100 and `grep_max_per_file` 25 → 15 in `config.toml` (backup `config.toml.bak-2026-10-18-tune`). Effect
checked on one query: `rtk grep -n "def " -r engine` printed 55 matches against 207 raw. The large outputs
are rare, so the expected saving is small; the recall rate is what to watch.

**Evidence:** `history.db` `commands where rtk_cmd like 'rtk grep%'`; `rtk gain --text --recalls`; the spot
check `rtk grep … | grep -cE "^engine/"` vs `RTK_DISABLED=1 grep -rn "def " engine | wc -l`, run in
`/Users/arasz/RiderProjects/ai-badger`.

### F8 — ccr retrieval rises with block size: 7–13% under 2k tokens, 22–42% at 2–5k [MEASURED]

Across 1,095 `ccr_decisions`, the model retrieved the elided content for 6.6–12.7% of blocks under 2,000
tokens, 21.7% at 2–3k, 41.9% at 3–5k and 27.3% at 5–10k. Blocks of 250–1,500 tokens are already compressed,
so `tokens_gt` gates the whole tool result, not each block. Bash produced 1,068 of the blocks.
Since the 11:01 restart: 694 successful requests, 8.37M tokens saved by ccr (12,054 per request), 21 retrieve
calls. All-time: 7,011 requests, 60.5M saved (8,629 per request), 140 retrieve calls.

**Evidence:** `rtk-proxy.db` `ccr_decisions` bucketed by `tokens_before`, `retrieve_count>0`, grouped by
`tool`; `usage_records` sums of `saved_ccr` and `ccr_retrieve_calls` with `status=200`.

### F9 — ccr `tokens_gt` lowered 1500 → 1000; not live until the proxy restarts [READ]

`pipeline.toml` now reads `when = { tokens_gt = 1000 }` (backup `pipeline.toml.bak-2026-10-18-tune`), and
`rtk pipeline validate` reports `pipeline: ok`. The threshold is not a runtime setting: `rtk llm-proxy config
set` accepts only compression, api_key, providers and upstreams, and the file's own comment says it takes
effect on proxy restart. The lowered threshold brings 1,000–1,500-token results in. By F8's trend that size
should retrieve at around the 7–13% seen for small blocks, but this is extrapolated, not measured.

**Evidence:** `~/.config/rtk/pipeline.toml:37,45`; `rtk llm-proxy config` usage text; `rtk pipeline validate`.

### F10 — The large-block retrieval rate is a bigger ccr cost than the threshold [UNVERIFIED]

F8's 42% retrieval at 3–5k means those compressions are often undone at the price of an extra turn. Whether
that outweighs their savings was not computed. Neither was whether a ccr method parameter (strategy,
elided ranges, pinning) could lower it. The proxy already pins a block it sees retrieved repeatedly (log:
"pinning block — retrieved repeatedly").

## Still open

- **F3:** add credits to the key `anthropic-key.sh` returns, or point `[upstream.haiku]` at a different
  provider. Then re-check with `rtk compact … -- seq 1 6000` before tuning F4.
- **F9:** restart the proxy (`rtk llm-proxy stop && rtk llm-proxy start`), then compare `saved_ccr` per
  request and the retrieve rate after a day against the baseline in F8 (12,054 per request, 21 retrieves / 694).
- **F7:** after a day, `rtk gain --recalls`. A grep recall rate above zero means 100 / 15 is too tight.
- **F6:** an exact missed share needs the guard to log its decisions with the tool_use id, or a join through
  `history.db` timestamps; neither exists.
- **F2:** whether the bursts would have hit 429 without the proxy.
- **F10:** savings minus retrieval cost per block-size bucket.
