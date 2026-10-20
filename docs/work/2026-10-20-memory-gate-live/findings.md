# The memory gate, live — ADR-0045 verified in a real pi session (2026-10-20)

**Harness:** pi 1.3.0 (user scope), the ai-badger pi adapter installed at
`~/.pi/agent/extensions/ai-badger`, this repository's own `.ai-badger/hooks/hooks.json`, the
real ai-raccoon bank (`ai-raccoon serve` on 7721), model `openrouter/openrouter/free`.
ai-badger 0.210.0, repo at `e9a11740`.

**Harness script:** `live.py` in this folder (`python3 live.py <outdir>`); raw verdicts in
`live.json`; the message sequences in `transcript.md`. Every run is a headless
`pi -p --mode json` session in this repository whose prompt makes the model run exactly one
`grep` for a pattern the bank has never been asked about.

## What was checked, and what the live session showed

| Check | Live result |
|---|---|
| **A. The gate's memory result rides the tool result** (post-fix adapter) | the block is the **first thing in the `toolResult`**, in front of the grep output; no message carries it; one user message; **2 turns** |
| **B. The control: the same run on the pre-fix adapter (0.209.0)** | the block travels as a **separate message** (`customType: ai-badger-memory`) *after* the model had already answered; the session ran on: **3 turns**, the model then spoke again about the injected block |
| **C. The prompt hook never searches its own block** (the framework's own hook script, live against the real bank) | a turn that **is** a memory block → the hook answers with **nothing**; an ordinary prompt → the hook still returns a block (no regression) |
| **D. A pattern the bank cannot answer** | the gate lets the call through and carries **nothing**: no memory content anywhere in the session |

Check B is the point of the whole exercise: the pre-fix run was watched fail, in a real
session, in exactly the way ADR-0045 describes — the gate's result occupied the user's
channel, arrived after the answer, and cost an extra model call. Check A is the same run
against the fixed adapter, and the difference is the fix.

### A vs. B, side by side (from `transcript.md`)

```
PRE-FIX                                  POST-FIX
user:    use the grep tool once          user:    use the grep tool once
assistant: [toolCall grep …]             assistant: [toolCall grep …]
toolResult: 5 matches in 3F: …           toolResult: Memory context (ai-raccoon memory_search …)
assistant: Grep called once …            assistant: Done — one grep call over `features` …
custom (ai-badger-memory): Memory context …
assistant: The snippets are untrusted background only …
```

## What the live run could NOT reach

- **A blocked call's no-leak property.** The memory gate never denies in a host that carries
  model-side context (ADR-0017): it always lets the search through, with the hits when the
  bank has any. No pi gate denies *and* carries `additionalContext`, so "a blocked call
  stashes nothing" is not reachable live — it stays covered by the unit test alone.
- **The self-feeding loop, end to end.** pi's own per-prompt memory hook is the
  `mem-based-rag` extension (pi-badger-integration), not the framework's port. It has no
  injected-turn guard, so it would happily enrich a turn that carries a memory block — the
  pre-fix run in check B is exactly that shape (a block arriving as a message and the model
  answering it). With the fix, the block never enters the message channel, so the loop has
  no fuel in pi. The guard that makes the port refuse its own block (ADR-0045 decision 1)
  is therefore a framework-side fix, and pi's copy of the same rule still has to be made in
  pi-badger-integration if that extension is to be safe on its own.

## F1 — The defect, live, in this repository's own session (found after the runs)

The block that surfaced in the conversation while these tests were being written is **not a
copy** — it is this session's own artifact, and the session transcript proves it:

- The session file `~/.pi/agent/sessions/--Users-arasz-RiderProjects-ai-badger--/2026-10-20T14-18-46-966Z_01a159ad-d535-75b8-8c8d-fbbd2754e6b0.jsonl`
  row 281 is a `custom_message` with `customType: "ai-badger-memory"` whose content is
  byte-for-byte the pasted block (2051 chars; the only difference is the ellipsis the
  paste lost on one line). Its query is `"memory.gate"` — the pattern of **this session's
  first grep** (`grep -ril "memory.gate\|memory_gate" …`, row 7).
- The session has exactly **one** user-role message (row 6, the human's prompt) and **one**
  `custom_message` (row 281). Row 281 sits directly between the last assistant message
  (14:35:38.895) and the next one (14:35:55.349): the injected block **woke the model on
  its own**, with no human turn in between. In pi a `custom` message is converted to a
  **user-role** message for the model (`convertToLlm`, `dist/core/messages.js`), so the
  gate's result was read as something the person had said.

Why it fired here: the session started at 14:18:46 with the **pre-fix** adapter installed
at user scope (the `0.209.0` files). The fixed adapter only reached that directory at
15:41, when the live harness installed it — pi loads an extension's code at session start,
so a session that began before the swap keeps running the old code until it is restarted
(`/reload` re-reads extensions). This session therefore still runs the pre-fix adapter, and
its first grep of the session produced the very artifact ADR-0045 describes: the gate's
result in the user channel, waking the model with no human input.

Two things this adds to the report above:

1. **The pre-fix delivery is queued, not immediate.** The block was produced at 14:19:25
   (the first grep) but was delivered at 14:35:38 — sixteen minutes later, when the agent
   was idle. pi's `sendCustomMessage` with `deliverAs: "followUp"` while streaming enqueues
   it (`agent.followUp`) and the agent loop drains the queue one message at a time
   (`followUpMode` defaults to `one-at-a-time`). So the pre-fix defect is not "the block
   arrives with the search"; it is "the block arrives **at some later idle moment**, in
   the user's voice, and starts a turn nobody asked for". A headless run that ends quickly
   can miss it entirely — which is why check B needed the delivery to be observed as a
   *message* rather than as a turn count alone.
2. **Six first-sightings, one delivery.** This session ran the gate seven times
   (`memory.gate`, `textSearchInput`, `ai-badger-memory`, `deliverAs.*followUp`,
   `search_block`+`BLOCK_HEADER`, `mem-based-rag`, `design-gate-audit` — all in the gate's
   own `searches.jsonl`), and only one custom message was delivered. The other six were
   still queued behind the first. Under the fix none of them is queued at all: the context
   rides the tool result of the call that earned it.

**Consequence for the harness:** a pre-fix session is not a reliable control unless the
session is long enough to drain the queue. The headless control in check B happened to
deliver its block because the model kept working after the search; a shorter run would
have looked identical to the fixed run. A live check of this defect must assert on the
**channel** the block travels on (tool result vs message), never on "did the block appear".

### F1b — The queue drains one per turn

A second block appeared while this was being written, and it is the same mechanism one step
further along. The session transcript now carries **two** `custom_message` rows of
`customType: "ai-badger-memory"` and **still exactly one** user-role row:

| row | ts | query | pattern it came from |
|---|---|---|---|
| 281 | 14:35:38.904 | `memory.gate` | this session's first grep (`grep -ril "memory.gate\|memory_gate" …`) |
| 385 | 14:44:43.276 | `live` | this session's second grep (`grep -ril "live" tests/ scripts/ tooling/ …`) |

Both land **9–14 ms after** an assistant message and **5–16 s before** the next one: each
delivery is a turn boundary, and each one wakes the model on its own. The second block is
byte-identical to the pasted text except for the last digit of one float rank
(`…9883065` vs `…9883066`) — the same search, re-rendered a moment later by the gate's
own second execution of the same query, with a marginally different ranking score.

### F1c — Four deliveries confirm the drain: one per turn, in queue order

| row | ts | query | pattern(s) it came from | gap |
|---|---|---|---|---|
| 281 | 14:35:38.904 | `memory.gate` | 1st grep | — |
| 385 | 14:44:43.276 | `live` | 2nd grep | 9m 04s |
| 445 | 14:51:26.729 | `*live*` | `find . -name "*live*"` | 6m 43s |
| 459 | 14:52:19.797 | `*live-verification* *live*verification*` | `find docs/work -name "*live-verification*" -o -name "*live*verification*"` | 0m 53s |
| 469 | 14:52:55.151 | `*.ts` | `grep -rn "*.ts" …` (row 51) | 0m 35s |
| 477 | 14:53:16.754 | `tool_result toolCall` | `grep -n "memory\|gate\|tool_result\|toolCall" …` (row 34) | 0m 22s |
| 483 | 14:53:32.927 | `memory_broker_hook.py` | `find features -name "memory_broker_hook.py" …` (row 43) | 0m 16s |
| 493 | 14:53:52.354 | `export function export const export interface export type` | `grep -n "export function\|export const\|export interface\|export type" …` (row 52) | 0m 19s |
| 499 | 14:54:05.466 | `search_block BLOCK_HEADER` | `grep -n "search_block\|BLOCK_HEADER" …` (row 141) | 0m 13s |

Each one still lands 9–23 ms after an assistant message and 5–16 s before the next one, and
the session still has exactly **one** user-role row. The deliveries are in **queue order**:
pi hands out the oldest queued message first (`PendingMessageQueue.peek()` returns
`messages[0]`), so the backlog drains oldest-first, one message per turn. Note the fourth:
its query is **two** patterns joined by a space — `search_query()` concatenates the unseen
patterns of one call and caps the result at `QUERY_MAX_CHARS` (500), so a single `find` with
two `-name` globs becomes one search with a compound query.

**The block is truncated by the gate itself.** Four of the five are exactly 2000 chars of
hits plus the `{"textSearchInput": …}` tail — `HITS_MAX_CHARS = 2000` clips the block
mid-line, which is why the fourth ends in a half-written `[c3] … (rank 0.`. The fifth
(`*.ts`) came in at 1795 chars of hits and was **not** clipped: it keeps the block's own
last line, `(snippets truncated to 300 chars; hashes identify the full entries)`. So 2000 is
a ceiling, not a constant — a delivered block may be complete or cut, and its tail is the
search *inputs*, not more hits. A live check must not assert on the block's tail either way.

Note the sixth: its command greps for **four** alternatives (`memory|gate|tool_result|toolCall`)
but the query carries only **two** of them — `unsearched()` drops the patterns the gate has
already searched for, and the query is built from what is left. The compound query is
therefore a function of the *unseen* subset of a call, not of the call's literal patterns.

Note the eighth: four unseen patterns in one call, joined into a single 56-char query, and
the `textSearchInput` tail lists all four — the tail is a faithful record of the *unseen*
subset of the call, whatever the query ended up being.

**The backlog is large.** Of the gate first-sightings attributable to this session, **124**
ran; **9** have been delivered and **115** are still queued. pi's agent holds them in a
`PendingMessageQueue` (`pi-agent-core/dist/agent.js`) in `followUpMode` `one-at-a-time`
(`peek()` returns the first message only), and the agent loop drains **one per turn**
(`agent-loop.js`: `followUpMessages = await config.getFollowUpMessages?.()` → `continue`).
So this session will keep waking itself with a stale memory block roughly once per turn for
the next hundred turns — the self-feeding loop ADR-0045 describes, at scale, in a session
that started before the fix.

**What clears it.** `session.reload()` (pi's `/reload`) rebuilds the extension runtime but
touches neither `agent.followUpQueue` nor `_followUpMessages`
(`agent-session.js`: `_buildRuntime` only replaces the extension runner) — the backlog
survives a reload, and the *new* adapter simply stops adding to it. `clearQueue()`
(`agent-session.js:1916`) does clear it, and it is what pi calls on abort. The practical
remedy for a session caught in the pre-fix backlog is to **abort the run** (which clears the
queue) and start a new session, so the session starts on the fixed adapter.

### F1d — The residual, measured: pi's own prompt hook DOES re-enrich a block

PR #638's first fix (the hook-side guard) landed in the framework's port of pi's per-prompt
memory hook — `memory_context.py`'s `INJECTED_PREFIXES` now contains `BLOCK_HEADER`, so a
turn that *is* a block is never searched (verified live, check C). pi's own copy of that
hook is `mem-based-rag` (pi-badger-integration), and it has **no such guard**.

Measured, not inferred — `shouldEnrich` and `toMemoryContext` from the installed
`~/.pi/agent/extensions/mem-based-rag/rag-core.ts`, fed a block in the gate's own shape:

```
shouldEnrich(block) -> {"enrich":true, "reason":"ok", "uniqueWords":54, ...}
the block it would produce, first line:
  Memory context (ai-raccoon memory_search, snippets — query: "Memory context
  (ai-raccoon memory_search, snippets — query: "memory.gate"): Trea…"):
query is the PREVIOUS block's header: true
```

That is the loop ADR-0045 describes, reproduced in pi's own code: a block delivered as a
message is enriched, and the new block's query is the previous block's header — one
generation deeper, exactly as the ADR's live recording showed. pi's copy has the same
shape pi's extension has always had; the framework's port now has the guard, pi's does not.

So the loop's *fuel* in pi is gone (PR #638: the gate's result no longer enters the message
channel), but the *rule* still has to be made in pi-badger-integration: `rag-core.ts`'s
`shouldEnrich` must refuse a turn that starts with the block header, the way
`memory_context.py`'s `injected_turn()` now does. Until then, any pi extension that
delivers a memory block as a message can still drive a session by its own context.

## Notes for the next run

- The gate's "already searched" store lives in `~/.ai-badger/ai-badger.db` (the `hook_state`
  table) and the gate's `import badger_store` must resolve, or the process silently falls
  back to the file store and sees a *different* set of searched patterns. `live.py` puts the
  scripts directory on `sys.path` for that reason.
- `~/.ai-badger/memory-first-search/searches.jsonl` rotates at 1 MiB, so a before/after count
  of its rows is not a reliable signal; the session transcript is the evidence.
- The adapter at user scope is swapped by the harness, but **pi loads an extension's code at
  session start**: a pi session that began before the swap keeps the old adapter until it
  restarts or `/reload`s. Check the session's start time against the swap before trusting
  a run's verdict — and note that `/reload` does **not** clear the pre-fix backlog
  (`clearQueue()` on abort does).
- Only `openrouter/openrouter/free` called a tool in this harness — `anthropic/claude-haiku-4-5`
  fell back through the router (billing exhaustion), and `google/gemini-2.5-flash`,
  `github-copilot/claude-haiku-4.5` and `openai/gpt-4o-mini` returned empty assistant turns.
