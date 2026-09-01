# ADR-0026 — pi bus delivery pushes: the adapter polls the store and wakes idle sessions

**Date:** 2026-09-01
**Status:** Accepted (2026-09-01, 0.159.0)
**Author:** Rafał Araszkiewicz (Arasz) with the aib-pi-message-bus-push-delivery MoE panel
**Extends:** ADR-0022 (the adapter is pi's whole arming surface), ADR-0024 (one vendored store; the txn is the single exactly-once owner), ADR-0025 (project resolution)
**Scope:** `features/pi/adjustments/adapter/`, `engine/badger_store.py` + vendored copies, `features/common/hooks/message_delivery_hook.py`, `features/common/skills/send-message/scripts/send_message.py`, `pi-badger-integration/publish.ts`

## Context

The complaint this task started from: "pi sessions still almost never get the
messages." Two evidence-graded research records (`docs/work/2026-09-01-*.md`)
root-caused it on the live machine:

1. **The store's 30-minute first-read gate + jump-past cursor drops backlog
   mail** — measured 3 of 4 real messages lost in one day, every harness
   equally (Lane B F2/F6).
2. **Delivery is pull-only** — mail is consumed only when the receiving session
   acts (prompt or LLM call). An idle pi session consumes nothing, and the wait
   burns the gate window (F9/F10/F16).
3. **Send-side addressing accepts unresolvable targets** — one real message was
   addressed to a project name no receiver could ever resolve (F3).
4. Content-free failure logging left 44 unattributable delivery failures the
   same day (F4/F15).

pi 0.84.4's extension API makes push possible without a daemon (Lane A,
measured): extensions run under Node 26 with stdlib `node:sqlite` (F1);
`pi.sendMessage(..., {triggerTurn: true})` wakes a fully idle session (F4);
mid-turn mail queues as steer/followUp and never interrupts (F5); timers are
sanctioned session-scoped background work started at `session_start` and
cleared at `session_shutdown` (F8); print/json modes have no idle session to
wake and a timer firing after shutdown is fatal uncaught (F7); the session id
authority is `ctx.sessionManager.getSessionId()`, never `PI_SESSION_ID` (F9,
measured divergence).

## Decisions

1. **Push = in-adapter poll + wake.** The adapter arms a poll timer at
   `session_start` (tui/rpc only, script-exists rule, default 2 s via
   `AI_BADGER_PI_BUS_POLL_SECS`, floor 0.5). Each tick runs a read-only
   **global-watermark prefilter** — one query returning `{MAX(id), COUNT(*)}`
   plus the DB file's stat identity; skip only when the fingerprint exactly
   equals the last clean probe (MAX **and** COUNT), the file identity is
   unchanged, the last spawn is younger than 60 s, and the file exists
   (`ENOENT` ⇒ skip). Anything else ⇒ spawn the Python delivery script. On a
   parseable, failure-marker-free outcome the watermark advances **to the
   tick-time capture** (never re-read post-spawn). First tick of a session
   always spawns.
2. **The Python txn stays the single exactly-once owner** (ADR-0024
   unchanged). The TS side opens the DB `readOnly`, never reads rows beyond the
   two aggregates, never classifies mail, and never advances a cursor. The txn
   now returns a delivered-batch summary `{"addressed": n, "broadcast": m}`
   (post-gate, post-cap, post-sender-exclusion), surfaced by the hook as the
   additive field `hookSpecificOutput.aiBadgerBus`; the adapter uses it only to
   choose the wake mode. A TS-side shape query was rejected as a store port in
   disguise; the bare `EXISTS(id > cursor)` alternative was rejected as
   unsound (it ignores addressing and spawn-storms on other sessions' 1:1
   mail).
3. **The hook's fail-open path is wire-distinguishable**: `guarded_main`'s
   failure response is `{"hookSpecificOutput": {"aiBadgerBus": {"error": true}}}`
   (exit 0 unchanged). A fail-open `{}` and a clean empty inbox are no longer
   confusable — without this, the poller would advance its watermark past mail
   it never delivered (review MUST M1).
4. **Wake matrix** (`AI_BADGER_PI_BUS_WAKE`, default `addressed`): idle +
   addressed mail ⇒ `sendMessage({deliverAs:"followUp"}, {triggerTurn:true})` —
   the session wakes now. Idle + broadcast-only under `addressed` ⇒ consume +
   inject **without** waking (`{deliverAs:"steer", triggerTurn:false}` — the
   measured append-without-turn path: visible immediately, enters LLM context
   next turn, no token cost, nothing parked on a user prompt). Streaming mail ⇒
   steer (addressed) / followUp (broadcast under `all`), never interrupting;
   interrupting remains `ctx.abort()`'s business. Compacting ⇒ defer the tick.
   `off` ⇒ the timer is never armed at all; seams carry everything. Routing
   consults `ctx.isIdle()` as the authority with event-driven flags as hints;
   the compacting flag is timestamped and expires.
5. **The seams stay, prefilter-gated.** `before_agent_start` and the per-LLM-call
   `context` event remain the delivery path for print/json (no idle session to
   poll) and belt-and-suspenders everywhere; their spawns share the same
   prefilter and advance rules, ending the unconditional per-LLM-call spawn.
   Gating is wake-policy-independent (spawn economy, not delivery semantics).
   Timer-driven spawns get a 30 s budget (they are off the turn's critical
   path); seam spawns keep 5 s.
6. **The 30-minute first-read gate stays** (owner ruling): it is the store's
   freshness contract for sessions that never push, and push makes it moot for
   live sessions — fresh mail is read within seconds of arrival. What the gate
   still drops is backlog addressed to sessions that did not exist during the
   send; that remains the deliberate contract.
7. **Send-side validation (refuse-not-guess).** `send_message.py` refuses a
   `--project-id` that no `.ai-badger/project-id` on the machine (bounded
   depth-4 home walk, self-project resolution, or the `AI_BADGER_PROJECT_ID`
   override) carries — the same stance as sender identity. The refusal lists
   the resolvable ids. Walk-depth misses are a named residual; the escape hatch
   is documentation, not a bypass flag.
8. **Hook-error diagnosability without leaks.** `record_hook_failure` logs the
   exception message, sanitized of any payload-derived substring; fail-open
   discipline (D31) is unchanged.
9. **Cursor-wrap insurance, honestly motivated.** `messages.id` is
   AUTOINCREMENT — rowid reuse cannot occur through the store's own writes, so
   the guard is **not** justified by prune-wrap (an earlier rationale, retired).
   It is cheap insurance for DB replacement/restore states: `cursor_id >
   COALESCE(MAX(id),0)` reads as cursor-less **for that read** (gate + cap +
   leg-scoped landing re-apply). `cursor == MAX(id)` after a restore is
   indistinguishable from caught-up without an epoch — recorded residual, not
   "self-heals".
10. **Canonical flow restored.** pi-badger-integration's adapter had drifted
    behind ai-badger's vendored copy (the 0.156–0.157.1 bus work never flowed
    back; its mirrored tests were already red). P0 reverse-synced it; the
    forward canonical flow (pbi → ai-badger via `publish.ts --ai-badger`)
    resumes, with `bus-prefilter.ts` and `bus-store.ts` added to the exact-set
    `ADAPTER_FILES`.

### Rejected alternatives

- **Bus daemon** (external process driving RPC): a long-lived machine service,
  cross-platform service management, a second trust surface; priced high-effort
  against the timer's low. NO-DAEMON owner ruling.
- **TS port of the delivery transaction**: two implementations of the
  exactly-once txn drift exactly where correctness lives; the spawn cost it
  removes is already bounded by the prefilter.
- **WAL watcher / fs.watch on the DB**: sidecars commit on every hook write
  machine-wide (markers, audit, telemetry), an unbounded callback rate that
  still needs the txn; loses to one indexed aggregate per 2 s tick.
- **Cron-fired fresh sessions (pi-cron)**: each fire is a new process; it
  cannot reach an existing idle session. Right carrier for a future "wake
  sessions that don't exist yet" decision.
- **session_start delivery** (claude-parity): ruled out at 0.156.0 (D4) and
  useless for print/json where `session_start` fires at stdin EOF; the poll
  supersedes its purpose.
- **TS-side classification for the wake policy** (addressed-vs-broadcast in
  TS): duplicates the three-shape + R2 + cursor read predicate in a second
  language. The txn that consumed the mail reports the summary.

## Consequences

**Positive.** Idle tui/rpc pi sessions receive mail within poll-interval + spawn
latency instead of never; the gate stops consuming mail on this machine's
dominant pattern (parallel pi lane fan-outs); per-LLM-call delivery cost drops
to one indexed aggregate; send-side mis-addressing fails loudly with
self-diagnosing refusals; the 44-failures-a-day class becomes diagnosable.

**Negative / accepted residuals.**
- **Consume-then-lose window**: the txn consumes mail before `sendMessage`
  runs; if injection throws (e.g. a compaction interleave), the mail is
  consumed but not injected — the store has no un-consume API. Mitigated by the
  stale-ctx generation guard and a `nextTurn` compensation retry; the residual
  window is sub-millisecond on a live ctx.
- **Compaction event-ordering gap**: pi's `sendCustomMessage` bypasses
  `prompt()`'s compaction guard; the adapter avoids the window via the
  timestamped compacting flag, but an event-ordering sliver remains (same tick
  granularity as the flag).
- **Host tolerance of additive `hookSpecificOutput` keys** is named residual,
  owner-accepted (no existing test proves claude/copilot/hermes ignore unknown
  keys; the genuinely pinned parts — clean-empty `{}`, the 4-key render
  document — are covered).
- **In-flight tick across shutdown** can serialize after cursor cleanup and
  recreate a cursor row for the dead session (4-day TTL litter); the
  recreated read takes the gate path — same shape as a fresh session's first
  read.
- **Un-refreshed hook copies have no failure marker on the advance side.**
  C10's routing fallback makes an old hook copy wake, but its fail-open net
  prints a bare `{}` — no marker — so a persistent hook failure there advances
  the watermark every max-skip-staleness window and stalls silently until
  den-refresh refreshes the copy. Bounded retries, no notice; den-refresh is
  the coordination, alongside the project-id backfill note.
- **Same-inode restore with coincidentally equal MAX+COUNT** can equality-skip;
  vanishingly improbable, bounded by the 60 s max-skip-staleness.
- **Wake on `all`** spends a turn per broadcast per live session; default is
  `addressed`; no rate limit in v1 (recorded open question).
- **New TS↔store schema coupling** (the probe names `messages`): pinned by a
  contract test running the probe against a store-created DB; a bun runtime
  switch degrades fail-open to unconditional ticks (logged, not fatal).
- **Send-validation false refusals** beyond the depth-4 walk budget;
  documented escape hatch.
- **"Read-only" is precise about sidecars**: the probe never writes the
  database file (a write attempt through the connection throws, pinned), but a
  read-only open can create transient `-wal`/`-shm` wal-index sidecars beside
  it; SQLite recovers cleanly and the next writer's clean close removes them.

**Neutral.** Machine broadcasts queue without waking; polls do not preempt
in-flight turns; nothing survives process exit (F8) — mail persists in the
store, which is the point.

## Open questions

1. **TUI wake** — inferred from the shared code path + production precedent
   (subagent extension ships the identical `sendMessage`/`triggerTurn` shape);
   the integration package's pty probe (L6) is conditional with a 2-attempt
   flake budget.
2. **Wake during auto-compaction** — probe planned; the design defers ticks in
   the window either way.
3. **Seams' retirement** — once push telemetry shows the seams' spawns are
   pure overhead in tui/rpc, should they be retired there (keeping print/json
   on seams)? Revisit after one release.
4. **Delivery audit** — a `deliveries` fact so "was message X delivered?" is
   answerable from the store (Lane B F15). Successor task.
5. **Live-session registry** — the user-DB sessions table has no writer; 1:1
   addressing to pi sessions remains impractical, so traffic still
   degenerates to broadcasts. Successor task.
6. **pi-cron as the carrier for waking sessions that don't exist yet**; and
   **cross-harness push** (claude/hermes/copilot have no in-process timer
   surface) — future decisions, likely per-host.
