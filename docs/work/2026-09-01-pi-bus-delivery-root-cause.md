# Research: Where pi-session bus mail is delayed, dropped, or never delivered

**Date:** 2026-09-01
**Question:** On this machine, at which points in the send_message.py → pi-session delivery path is a sent message delayed, dropped, or never delivered, and which of those points dominates the observed "pi sessions almost never get the messages"?

**Method note.** Read-only lane. The user DB was opened with `sqlite3.connect("file:…?mode=ro", uri=True)`. No `pi -p` probe was run — both identity questions it could have settled were settled cheaper (see F8, F10), so its cost was avoided. One file written (this record); no memory-bank writes; no code or config touched.

## Findings

### F1 — The installed pi adapter is byte-identical to the vendored copy; every wired project runs the same delivery hook [MEASURED]

The "stale installed adapter" suspect is dead. `~/.pi/agent/extensions/ai-badger/` (index.ts, hook-bridge.ts, package.json, capability marker) matches `features/pi/adjustments/adapter/` exactly, and the delivery hook plus store copies in all four scaffolded projects share one md5.

**Evidence:** `diff -r /Users/arasz/RiderProjects/ai-badger/features/pi/adjustments/adapter/ ~/.pi/agent/extensions/ai-badger/` → `IDENTICAL` (this machine, 2026-09-01); `md5 -q /Users/arasz/RiderProjects/*/. ai-badger/hooks/message_delivery_hook.py` → all four `0dc386e5d6e4f7d2d048151ab79041c8` (ai-badger, ai-badger-code-review-entry-point, job-search-ai-assistant, pi-badger-integration).

### F2 — The live DB shows the 30-minute first-read gate dropped all four of today's real messages for nearly every consumer [MEASURED]

The user DB (~/.ai-badger/ai-badger.db, 3.4 MB) holds 13 messages sent today: 9 test probes (07:29–07:30 UTC) and 4 real ones — id 10 (09:57, project broadcast to `job-search-ai-assistant`), id 11 (11:15, machine broadcast), ids 12–13 (17:52 / 18:04, project broadcasts to `b0e32c16-f502-4896-9b97-0bbee0fb321d`). Gate arithmetic per cursor (window = last-read-ts − 30 min): msg 11 — deliverable to everyone — was outside the window of every read that ever reached it (earliest cursor at id ≥ 11 is 16:03, 4 h 48 min after send); no cursor shows any read in 11:15–11:45. Msgs 12–13 were in-window for at most the two cursors read at 18:19:16 / 18:19:51; the 13 cursors read 19:07–19:22 (63–90 min after send) had both outside their windows and delivered nothing. On the strongest reading, zero to two of twenty known consumers ever received a real message today.

**Evidence:** python3 read-only session on `file:/Users/arasz/.ai-badger/ai-badger.db?mode=ro`: full dump of `messages` (id, ts, targets) and `cursors` (20 rows), then per-cursor `SELECT … WHERE id > cursor AND ts >= read_ts − interval '30 min' AND sender_session <> session_id`. Raw rows quoted in the analysis log of this lane; reproducible by re-running the same two queries.

### F3 — Message 10 was addressed to a project id that resolves nowhere on this machine — undeliverable by construction [MEASURED]

Msg 10's `target_project` is the literal string `job-search-ai-assistant`. Only four `.ai-badger/project-id` files exist machine-wide (home scan, depth ≤ 4): `024ef989-…` (ai-badger AND ai-badger-code-review-entry-point), `b0e32c16-…` (job-search-ai-assistant), `50a8bb05-…` (pi-badger-integration). Receivers resolve projects by the ADR-0025 cwd walk against those file contents, so no session anywhere can match `target_project = 'job-search-ai-assistant'`. The sender side accepts any string; nothing validates the target resolves.

**Evidence:** `python3` walk over `~` for `.ai-badger/project-id` printing value → path (4 hits, none matching the literal); msg row 10 read from the user DB (`target_project='job-search-ai-assistant'`); `cat /Users/arasz/RiderProjects/job-search-ai-assistant/.ai-badger/project-id` → `b0e32c16-f502-4896-9b97-0bbee0fb321d`.

### F4 — The delivery hook is failing in production, silently: 44 content-free error lines today [MEASURED]

`~/.ai-badger/hook-errors.log` records 44 `message_delivery_hook OperationalError at badger_store.py:959` lines today (39 in hour 09, cluster 09:46–09:55 — minutes before msg 10 was sent at 09:57). Each line is deliberately content-free (type + location only), so the underlying error is unrecoverable; the line number may even refer to a different project's vendored store copy, making attribution impossible. Each failure is a turn where delivery did not run — fail-open keeps the turn alive but the mail waits.

**Evidence:** `tail` + count over `~/.ai-badger/hook-errors.log` (85,931 bytes): 44 lines matching `message_delivery_hook` on 2026-09-01, all `OperationalError at badger_store.py:959`; log format inspected — no message text by design (`record_hook_failure`, message_delivery_hook.py:131-149).

### F5 — There is no machine-wide registry of live sessions: the user-DB sessions table is empty [MEASURED]

`sessions` in the user DB has 0 rows. The only sessions registry is per-project tracking.db (this project's has 1 row; job-search-ai-assistant's has 2 — including a stale row `d9e90bb1…` recorded 2026-07-29 with `pid=1`). Consequence: no sender can discover which pi sessions exist; 1:1 addressing to a pi session is impractical, and send_message's fallback derivation (env → pid ancestry → unique cwd) resolved the sender of msgs 10–11 to that month-old stale row via the unique-cwd leg.

**Evidence:** read-only `SELECT COUNT(*) FROM sessions` on the user DB → 0; read-only sessions dumps from both tracking DBs (`…/ai-badger/.ai-badger/task-tracking/tracking.db`, `…/job-search-ai-assistant/.ai-badger/task-tracking/tracking.db`); grep shows the only `session_upsert(` caller is `tracker_lib.py:641` (tracking store, not user store).

### F6 — Store delivery semantics: 30-min gate, 16-cap, cursor jumps past the gated window, exactly-once, 4-day retention [READ]

First read of a cursor-less session is gated to the last 30 minutes, capped at the 16 oldest, and — when the project leg ran — the cursor lands at `MAX(id)` globally, permanently discarding everything older and the overflow. Existing-cursor reads are pure `id > cursor`, uncapped. Sender's own rows are excluded (R2). With no resolved project only the 1:1 leg runs (D7) and the cursor lands past that leg's window only. Messages and cursors are pruned at 4 days.

**Evidence:** `badger_store.py:40` (`_GATE_WINDOW = timedelta(minutes=30)`), `:45` (`_START_CAP = 16`), `:50` (4-day retention), `:1886-1951` (`deliver_for_session` — gate, cap, MAX(id) landing, D7 leg), `:1953-1979` (`_read_addressed` — three shapes, R2 exclusion), `:2139-2151` (`open_user` prune on every open).

### F7 — The pi adapter delivers only from two seams; a project without the hook file is silently unwired; errors never break the turn [READ]

Delivery spawns happen in `before_agent_start` (per new user prompt) and the per-turn `context` event; `session_shutdown` only drops the cursor. `runDelivery` returns `{kind:"empty"}` without spawning when `<cwd>/.ai-badger/hooks/message_delivery_hook.py` does not exist — no notice. Spawn timeout is 5 s; any error becomes a warning notice and the turn continues. Session id for the payload: `ctx.sessionManager.getSessionId()` first, `PI_SESSION_ID` env fallback, empty string last resort; project addressing uses `CLAUDE_PROJECT_DIR = ctx.cwd`.

**Evidence:** `features/pi/adjustments/adapter/index.ts:244-312` (runDelivery + existsSync silent-empty), `:338-360` (the three `pi.on` registrations), `hook-bridge.ts:313-341` (`resolveSessionId`), `:437-469` (router — both seams route as `UserPromptSubmit`, shutdown as `SessionEnd`), `index.ts:18` (`GATE_TIMEOUT_MS = 5000`).

### F8 — pi 0.84.4 exports PI_SESSION_ID to bash subprocesses; sender and receiver identity coincide [READ]

The bash tool sets `PI_SESSION_ID = session id` on every child (`exposeSessionEnvironment` defaults true), and the system prompt tells the agent to inspect `PI_*` vars. The adapter-side payload takes the session id straight from the session manager — same id. The msg 12–13 sender id (`01a05e08-…`, UUIDv7-shaped like every cursor id) confirms pi sessions do resolve real pi ids as senders.

**Evidence:** `dist/server/create-harness.js:62` (`execution.env.PI_SESSION_ID = metadata.id`), `dist/bundle/chunks/chunk-OMWWHBTG.js` (`resolveSpawnContext` — deletes then re-sets `PI_SESSION_ID`), `dist/core/tools/bash.d.ts` sourcesContent (default `exposeSessionEnvironment: true`); msg 12/13 `sender_session` vs cursor id shapes from F2's dump.

### F9 — Both pi seams fire and inject: per user prompt, and per LLM call via transformContext [READ]

`before_agent_start` is emitted in `prompt()` for every new prompt that starts the agent loop; its returned `{message}` is appended as a `role:"custom"` message alongside the user message. The `context` event is wired as the agent's `transformContext`, invoked inside `streamAssistantResponse` — i.e., before every LLM call, including tool-loop continuations — and the handler's returned `{messages}` array replaces the array that `convertToLlm` sends to the model. The seam the complaint doubts is real and per-call.

**Evidence:** `dist/core/agent-session.js:39348-39370` region (emitBeforeAgentStart call + custom-message ingestion), `dist/core/sdk.js:231` (`transformContext: … runner.emitContext(messages)`), `dist/core/extensions/runner.js:791-816` (emitContext applies `{messages}`), `pi-agent-core/dist/agent-loop.js:179-180` (transformContext inside streamAssistantResponse, followed by convertToLlm).

### F10 — The seams demonstrably fire in live pi sessions on this machine [MEASURED]

20 cursor rows exist; 13 of them carry pi-shaped UUIDv7 ids (`01a05e…`) and were created/advanced to 13 during 19:07–19:22 today — the parallel lanes of the very task this record belongs to. Cursor creation proves the adapter spawned the delivery script and the store transaction ran in real sessions (mail was not delivered to them only because of the gate — F2).

**Evidence:** read-only `SELECT session_id, cursor_id, ts FROM cursors` on the user DB — 13 rows with ts between 19:07:39 and 19:22:42, all `cursor_id=13`, ids `01a05e*` / `01a05ddd…` (pi UUIDv7 shape).

### F11 — pi is not structurally worse per seam than claude/hermes — the shared store mechanics lose the mail; pi's lane-heavy usage maximizes exposure [INFERRED]

Claude arms SessionStart(startup|resume) + UserPromptSubmit + SessionEnd; copilot the same trio; hermes pre_llm_call + on_session_end (no start arm, by design); pi before_agent_start + context + session_shutdown — one fewer seam than claude/copilot (no start-delivery), but every harness's first delivery runs through the SAME 30-minute gate and cap in the shared store. What makes pi look worst in practice is that this machine's pi usage is parallel-lane fan-outs: many fresh session ids whose first read happens long after the sends — precisely the pattern the gate punishes (F2, F10). Reasoned from F2, F6, F9, F10 and the manifest seam map; the seam map itself is READ.

**Evidence:** `features/common/hooks/hooks-manifest.json` (three delivery hooks; claude/copilot/hermes/pi arm map; "Hermes deliberately has no arm here: its first pre_llm_call is the whole delivery"); measured gate arithmetic in F2.

### F12 — A clean shutdown deletes the cursor, so unconsumed backlog re-enters through the 30-minute gate on the next session [READ]

`session_shutdown` (fired on graceful exit, SIGHUP, and extension reload) drops the session's cursor row. A pi session that exits cleanly with unread mail leaves nothing behind: the next session has a fresh id AND no cursor, so the first-read gate applies and backlog older than 30 minutes is dropped (F6). Only a crashed/hard-killed session preserves its cursor (TTL 4 days) and would read uncapped.

**Evidence:** `message_delivery_hook.py:52` (`CLOSE_EVENTS = {"sessionend"}`), `:96-102` (`_close` → `delete_cursor`); `badger_store.py:1980-2001`; pi emission sites `dist/core/agent-session-runtime.js:106,289`, `dist/core/agent-session.js:2213`, `dist/modes/interactive/interactive-mode.js:3217,3300`.

### F13 — Whether msgs 12–13 ever reached anyone is unknowable from the persisted state [UNVERIFIED]

The two cursors at 18:19:16 (id 12) and 18:19:51 (id 13) are consistent with genuine delivery (in-window at those instants) but also with a first-read jump-past or a project-unresolved read; cursor ts records only the last read, and no per-message delivery audit exists anywhere (F15). Not checked because the evidence needed does not exist on this machine.

### F14 — The 5-second adapter spawn timeout can race the store's 5-second busy timeout under fan-out [UNVERIFIED]

`GATE_TIMEOUT_MS = 5000` kills the delivery script while SQLite's own `busy_timeout` is also 5000 ms plus 4 WAL-conversion retries — a contended store can consume the whole adapter budget, producing a killed spawn and a skipped delivery. Plausible mechanism for fan-out storms; not observed today (the 44 logged failures are in-script OperationalErrors, not kills). Would be settled by timing instrumentation on the spawn or an error reason in the log.

### F15 — No delivery audit exists anywhere on the machine [MEASURED]

`hook_audit` in the user DB holds only `grounded_feedback_hook` rows — no delivery events. The store records no "delivered message X to session Y at T" fact; only final cursor state exists. Every "was this message delivered?" question is therefore a reconstruction (F2's arithmetic), and some (F13) are impossible.

**Evidence:** read-only `SELECT … FROM hook_audit ORDER BY id DESC LIMIT 25` — all rows `grounded_feedback_hook`; no other table carries delivery history (schema dump of all 21 tables).

### F16 — Claude and copilot get one extra delivery opportunity pi lacks: session start [READ]

Claude's hooks.json fires the delivery hook on `SessionStart` with matcher `startup|resume` — mail is injected the moment a session opens or resumes, before any user input. pi's earliest seam is the first user prompt (D4: "a session that never turns consumes nothing"). Combined with F12, a pi session opened after a message was sent waits for a human to type before the gate clock stops.

**Evidence:** `/Users/arasz/RiderProjects/ai-badger/.ai-badger/hooks/hooks.json` (SessionStart entry, matcher `startup|resume`, delivery command); `features/pi/adjustments/adapter/index.ts:334-336` comment ("There is no session_start delivery — a session that never turns consumes nothing"); `hook-bridge.ts:410-418` (start-spawn deferred per D4).

### F17 — Two checkouts share one project id, so broadcasts cross project boundaries [MEASURED]

`ai-badger` and `ai-badger-code-review-entry-point` both carry project-id `024ef989-26cc-4076-a8c2-e70712b0633d`. A project broadcast to that id delivers to sessions in BOTH checkouts (opposite of a loss — cross-talk), and the cwd-walk cannot distinguish them.

**Evidence:** the four project-id file reads in F3's evidence — two distinct paths printing the same UUID.

## Ranked root causes

| # | Cause | Evidence | Impact | Covered by existing contract? |
|---|---|---|---|---|
| 1 | **30-minute first-read gate + jump-past cursor** (store design): any message whose recipient's first delivery read happens >30 min after send is silently dropped, and the cursor lands past everything older | F2, F6 | Every message to a session that doesn't read within 30 min — 3 of 4 real messages today | Yes — deliberate (L1/R5/D5); the ADR question is whether 30 min is the right window |
| 2 | **Pull-only delivery, no wake**: mail is consumed only when the session itself acts (prompt or LLM call); an idle or not-yet-started session consumes nothing, and the wait burns the gate window of cause 1 | F9, F10, F16 | Every message to an idle session; dominant for pi lanes opened after the send | Yes — deliberate (D4); the push/wake question is exactly what the ADR must decide |
| 3 | **Free-form send-side addressing vs resolved receive-side ids**: send accepts any `--project-id` string; receivers match only ADR-0025-resolved ids — msg 10 matched nothing, ever | F3 | Every message sent with a human-chosen project name — today 1 of 4 | No — send_message validates sender identity but never validates the target resolves |
| 4 | **No live-session registry**: user-DB sessions table is empty by construction (nothing writes it); 1:1 addressing to pi sessions is impractical, so everything degenerates to broadcasts, maximizing causes 1–2 | F5, F8 | Structural: shapes all real traffic into the lossiest channel | Partially — the table exists but has no writer; no discovery surface |
| 5 | **Fail-open with content-free logging**: delivery failures leave only type+file:line, unattributable to a copy or a cause; 44 failures today | F4, F15 | Every failed firing is a silently skipped delivery attempt | Partially — D31 fail-open is deliberate; the logging is insufficient for diagnosis |
| 6 | **Ephemeral pi session ids + cursor deletion on clean shutdown**: fresh id per session re-triggers the gate; backlog after a clean exit is re-gated; 1:1 mail to dead ids pruned at 4 days | F12, F6 | Amplifies cause 1 for every new/resumed session | Yes — deliberate (R6); interacts badly with cause 2 |
| 7 | **5 s spawn timeout vs 5 s store busy timeout**: under parallel fan-out the script can be killed mid-transaction-retry | F14, F7 | Rare-to-occasional under fan-out storms | No — single spawn, no retry |
| 8 | **16-cap overflow drop** on first read | F6 | Rare on this machine (13 messages total today) | Yes — deliberate (R5) |
| 9 | **D7 project-unresolved degradation to 1:1-only** — broadcast mail silently skipped that turn | F6, F13 (candidate instance at 18:19:16) | Edge; cwd-walk failures are uncommon | Yes — deliberate (D7), mail survives for later reads |
| 10 | **Shared project id across two checkouts** — broadcast cross-talk (not a loss; a misdirection) | F17 | Confined to this machine's two ai-badger checkouts | No — the id minting never checked for collisions |

## Still open

- Whether msgs 12–13 reached any session at all (F13) — needs a per-message delivery audit (a `deliveries` table or delivery rows in `hook_audit`); the current persisted state cannot answer it.
- The actual exception behind the 44 `OperationalError` failures (F4) — the log is content-free by design; settling it needs either a one-off verbose reproduction or recording the exception message for the store-open path (fix-phase work, not research).
- Whether the 5 s/5 s timeout race (F14) fires under real fan-out — needs spawn-duration telemetry.
- Why cursor `01a05e1f…` froze at 12 while a read at 18:19:16 (msg 13 in-window) took nothing — transient project-resolution failure vs cd-wander; would need the session's own transcript to settle.
- Whether hermes sessions receive bus mail on this machine at all — no hermes-shaped cursor ids were seen in the cursors table, but hermes may simply not have been used today.
- Whether the `context`-event injection persists into the session transcript or is transient to the single LLM call it was injected into (explicitly the parallel API-surface lane's scope; this record only needed the "reaches the LLM" fact, which is READ-settled in F9).
- Whether the one-sentence complaint ("pi sessions almost never get the messages") holds for claude/hermes on this machine too — today's data says the bus loses mail for every harness equally (F11); a cross-harness comparison would need claude/hermes traffic, which today's DB does not sample.
