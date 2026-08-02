# Research: How ai-badger task tracking hooks into Hermes, what it emits, and whether emitting is possible

**Date:** 2026-08-02
**Question:** How is ai-badger's task tracking (the `/task` skill + task_tracker.py) hooked into Hermes Agent, do we emit all the data, and is emitting even possible?

## Findings

### F1 — The four task-tracking hooks are wired for Claude only; Hermes gets no entry [READ]

The framework's `hooks-manifest.json` declares eight hooks. Three have Hermes equivalents
(`drift-notice` → `on_session_start`, `context-enrichment` → `pre_llm_call`, `commit-reminder` →
`post_tool_call`). The four task-tracking hooks — `session-start-tracking`, `task-checkpoint`,
`task-checkpoint-session-end`, `dispatch-gate` — list **only** `claude` in their `agents` map.
Hermes is not wired to any of them.

**Evidence:** `features/common/hooks/hooks-manifest.json:12-56` — the four hooks have
`"agents": { "claude": {...} }` and no `hermes` key; the three with Hermes support list
`"hermes": { "type": "plugin", "entry": "ai_badger_hooks.py", ... }`.

### F2 — validate.py's exemption reasons claim Hermes task tracking is impossible by design [READ]

`HOOKS_MANIFEST_AGENT_EXEMPTIONS` exempts Hermes from all four task hooks with reasons:
"recording the session id/transcript path ... are all Claude Code concepts (transcript files,
Claude's own usage limits) with no Hermes analogue to wire onto" (session-start-tracking); "the
numbers come from parsing that session's Claude transcript JSONL, which Hermes does not produce"
(task-checkpoint); "Hermes' on_session_end carries completed/interrupted booleans and neither a
session id nor a transcript path to checkpoint from" (task-checkpoint-session-end); "Hermes has
no custom-agent files ... its subagent roles (leaf/orchestrator) carry no per-dispatch model
parameter" (dispatch-gate).

These reasons are the design position: the framework treats Hermes task metering as impossible.
F5–F10 show the underlying premise (no session id, no transcript, no usage data) is false.

**Evidence:** `tooling/validate.py:84-130` (HOOKS_MANIFEST_AGENT_EXEMPTIONS dict).

### F3 — The installed Hermes plugin registers no task-tracking hooks [READ]

`~/.hermes/plugins/ai_badger_hooks.py` is byte-identical to the project copy at
`.ai-badger/hooks/ai_badger_hooks.py` (verified by diff). Its `register()` registers exactly
three hooks: `on_session_start` (drift notice only), `pre_llm_call` (context injection), and
`post_tool_call` (tool observer, learned-skill sync, commit reminder). Nothing touches
task_tracker.py, current-session.json, or token checkpoints. The file's own docstring says
"Provides feature-parity with Claude Code hooks" — but the task hooks are the gap.

**Evidence:** `~/.hermes/plugins/ai_badger_hooks.py:798-815` (register); diff of
`~/.hermes/plugins/ai_badger_hooks.py` vs `.ai-badger/hooks/ai_badger_hooks.py` → "IDENTICAL".

### F4 — The scaffold contradicts its own extension doc: task hook scripts ARE present in a hermes-scaffolded project [MEASURED]

The hermes extension.md claims `session_start_hook.py` and `poll_limit.py` "are Claude-specific
and are NOT scaffolded when `hermes` is in the agent list" and that Hermes session tracking is
"all native, no custom code". But ai-raccon's `config.json` lists agents `[claude, copilot,
hermes]` and its `.ai-badger/skills/task/scripts/` **does** contain `session_start_hook.py`,
`stop_hook.py`, and `poll_limit.py`. The claim in the extension doc is aspirational, not what the
scaffold does. (The scripts are scaffolded but nothing fires them under Hermes — F3.)

**Evidence:** `ls .ai-badger/skills/task/scripts/` in ai-raccon → `poll_limit.py`,
`session_start_hook.py`, `stop_hook.py` present; `.ai-badger/config.json` → `"agents":
["claude","copilot","hermes"]`; `features/common/skills/task/extensions/hermes/extension.md:161-174`.

### F5 — Every tracked task under Hermes has all-zero token checkpoints [MEASURED]

ai-raccon's `.ai-badger/task-tracking/token-usage.json` holds three tasks. Every checkpoint
(start/latest/finish) for every task is all-zero: `contextTokens: 0`, `assistantMessages: 0`,
`byModel: {}`, `cumulative` all zeros. The `usage` blocks show `outputByModel: {}`, `modelMix:
{}`, `cacheEfficiency: null`, `subagentTokens` 0 (except one manual 85000 entry), `grandTotal: 0`.
`executed-tasks.json` shows `transcriptPath: null` on every task, and `resumeCommand` strings
like `claude --resume 20260802_213638_435316` — a Claude command for a Hermes session id.

**Evidence:** `cat .ai-badger/task-tracking/token-usage.json` and `executed-tasks.json` in
ai-raccon; `python3 .../task_tracker.py status` → `tokens=0 cacheEff=- mix=-` on all rows.

### F6 — The tracker's session resolution does not know Hermes's env var [READ]

`tracker_lib.py` resolves the calling session from `CLAUDE_CODE_SESSION_ID` (line 35,
`CLAUDE_SESSION_ENV`), then PID ancestry / cwd match against `current-session.json` — a file
only `session_start_hook.py` writes, which under Hermes never runs (F3). Hermes sets
`HERMES_SESSION_ID` (measured live: `20260802_232735_2286e6`), but the tracker never reads it.
So `resolve_own_session()` returns `{}` under Hermes and `task_tracker.py start` demands
`--session-id` explicitly; the recorded ids `20260802_213638_435316` and
`hermes-agent-memory-20260802` were passed manually.

**Evidence:** `tracker_lib.py:35,373-406` (env var + resolve_own_session); `env | grep -i
session` in a live Hermes session → `HERMES_SESSION_ID=20260802_232735_2286e6`.

### F7 — Two of the three recorded task session ids do not exist in Hermes's session store [MEASURED]

`~/.hermes/state.db` holds 362 sessions from 2026-07-22 onward (retention is months, not
hours; the count grows as sessions run). `SELECT id FROM sessions WHERE id=?` returns zero rows
for `20260802_213638_435316` (initialize-dotnet-project) and `hermes-agent-memory-20260802`
(agent-memory-server) — the latter is not even a Hermes id shape. But `20260802_222214_fed404`
(docs-init) exists with title "Initialize Docs from ai-badger" and 309344 input / 82112 output
tokens. The tracker attached tasks to session ids that either never existed or were invented, so
the checkpoint pipeline had nothing to read.

**Evidence:** sqlite3 `SELECT` queries against `~/.hermes/state.db` (see F8 for the positive case).

### F8 — Hermes's state.db stores everything the tracker's checkpoints need, including per-model and per-subagent tokens [MEASURED]

`sessions` has `input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
reasoning_tokens, api_call_count, estimated_cost_usd, model, cwd, git_repo_root`. The
`session_model_usage` table carries a per-(session, model) breakdown — exactly the `byModel`
shape `parse_transcript_usage` builds. Delegations create child sessions: `async_delegations`
records `delegation_id → origin_session` (e.g. `deleg_a7fa2015` → `20260802_222214_fed404`),
and the child session `20260802_223850_7430ea` has `parent_session_id =
20260802_222214_fed404`, started at 1785703130.745 = `deleg_a7fa2015`'s dispatched_at
1785703130.630. That child's `session_model_usage` row: 13 api_calls, 59265 input / 27117
output / 629632 cache_read tokens — matching the docs-init subagent note "13 api_calls, 307s".
So per-dispatch subagent tokens are recoverable from the DB, which the current tracker gets
from `<dir>/<session>/subagents/*.jsonl` — a file layout Hermes does not produce.

**Evidence:** sqlite3 PRAGMA table_info + SELECTs against `~/.hermes/state.db`; the
delegation→child mapping verified by epoch timestamps.

### F9 — Hermes natively tracks and reports subagent spend [MEASURED]

`hermes insights --days 2` prints a Platforms table with a `subagent` platform row (23
sessions, ~102M tokens in the observed window) plus per-model token totals. Hermes already
aggregates the delegation spend the tracker tries to measure; the tracker just never queries it.

**Evidence:** `hermes insights --days 2` run on 2026-08-02.

### F10 — Hermes hook payloads carry session_id, and per-call usage is available [READ]

Hermes plugin hook payloads include `session_id` (pre_tool_call, post_tool_call, pre_llm_call,
on_session_start, on_session_end, post_api_request); `post_api_request` carries a `usage`
dict `{input_tokens, output_tokens}` per API call; `subagent_stop` carries
`parent_session_id` + `child_status`. So a Hermes plugin hook could checkpoint per-turn usage
without parsing any transcript file — the channel F2 claims does not exist does exist.

**Evidence:** `hermes_cli/hooks.py:112-216` (`_DEFAULT_PAYLOADS` for each event, used verbatim by
`hermes hooks test/doctor`).

### F11 — Hermes ships a JSON usage-file writer and session-export CLI [READ]

`hermes --usage-file PATH` (one-shot `-z` runs) writes a JSON report with
input/output/cache_read/cache_write/reasoning tokens, total_tokens, api_calls, model, provider,
session_id, completed. `hermes sessions export` exports sessions to JSONL. Both are emission
paths a tracker could consume; neither is used by the current tracker.

**Evidence:** `hermes_cli/oneshot.py:127-165` (`_write_usage_file`); `hermes sessions --help`.

### F12 — Session ids recorded by the tracker under Hermes are unverifiable after the fact [INFERRED]

Because the tracker stores only the id string and null transcript path (F5), and because two of
three recorded ids do not exist in the store (F7), a finished task's recorded numbers cannot be
reconciled with what actually ran. Even where the id is real (docs-init), the null transcript
path means the finish-time checkpoint computation (F5) had nothing to read and wrote zeros.
This reasons from F5 and F7: the inference is that under Hermes the tracking record is
decoupled from the ground truth, not that the ids were deliberately fabricated.

### F13 — Hermes does not auto-delete sessions; the missing ids were never in the store [READ]

`expiry_finalized` in `hermes_state.py` is a gateway lifecycle flag — it mirrors
`SessionEntry.expiry_finalized` (sessions.json), set when a gateway session's memory is flushed
(`set_expiry_finalized`). It is not a retention/deletion policy. Session deletion is manual
(`hermes sessions prune`, `session_filters.build_prune_filters`), and `sessions.auto_prune`
defaults to False in `config_defaults.py` — the only `auto_prune: True` default is the separate
checkpoints store. Even a configured prune would not explain the missing ids: the default
`retention_days: 90` far exceeds the hours-old sessions, and the DB shows 0 archived rows over
11 days of history. Combined with F7, this confirms `20260802_213638_435316` and
`hermes-agent-memory-20260802` were never in the store — ids passed to `--session-id` that do
not correspond to any real Hermes session (the agent-memory-server id is not even in Hermes's
`YYYYMMDD_HHMMSS_xxxxxx` shape). Nor were they Claude sessions on this machine: `~/.claude/projects/`
has no directory for ai-raccon at all, so there is no transcript for either id anywhere.

**Evidence:** `hermes_state.py:2981-2996` (`set_expiry_finalized`, "survives even if the JSON
index is pruned or lost"); `gateway/session.py:1911-1938`; `hermes_cli/config_defaults.py:2596-2619`
(session storage section: `auto_prune` False, `retention_days` 90); `hermes sessions --help`
(prune is a manual subcommand); sqlite: 0 archived rows, 362 sessions from 2026-07-22;
`ls ~/.claude/projects/` → no ai-raccon entry.

## Still open

- **Is the `contextTokens` (latest-message context occupancy) derivable from Hermes data?**
  `messages.token_count` exists in the schema but is NULL on every row observed
  (`SELECT COUNT(*) FROM messages WHERE token_count IS NOT NULL` → 0). Per-message usage may be
  recoverable from request dumps in `~/.hermes/sessions/request_dump_*.json` (a sample dump had
  `usage` present in its JSON) or from `post_api_request` hook payloads, but the canonical
  session store alone does not expose it. Settles with: check whether any dump/table carries
  per-message usage, or whether Hermes can populate `messages.token_count`.
- **Would wiring task hooks onto Hermes be worth it?** The data exists (F8–F11), but the
  checkpoint pipeline is Claude-transcript-shaped. A Hermes backend (query state.db) or a
  plugin-hook backend (per-turn checkpoint from post_api_request) are both possible; which is
  simpler is a design decision this record does not make.
