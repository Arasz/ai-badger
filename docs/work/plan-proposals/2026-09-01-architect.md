# Plan proposal — STRUCTURE lane (architect) — aib-pi-message-bus-push-delivery

**Date:** 2026-09-01 · **Lane:** plan-expert (architecture), one of three parallel plan proposals
**Inputs:** `docs/work/2026-09-01-pi-push-api-surface.md` (Lane A, cited F1–F14),
`docs/work/2026-09-01-pi-bus-delivery-root-cause.md` (Lane B, cited F1–F17 + ranked causes),
adapter `features/pi/adjustments/adapter/{index.ts,hook-bridge.ts}` (worktree tip = 0.157.2,
post-#464 defer seams), `.ai-badger/skills/send-message/scripts/{send_message.py,message_delivery_hook.py,badger_store.py}`,
`features/common/hooks/hooks-manifest.json`, ADR-0022/0024/0025 + `docs/adr/README.md`,
`pi-badger-integration/publish.ts` (canonical-source flow).
**Scope:** structure only — package decomposition, ADR-0026 skeleton, risk register, sequencing.
Planning only; no code, no ADR file, no memory writes.

---

## 0. The shape being planned (one paragraph, decisions pre-made by owner — not re-litigated)

The pi adapter (user-scope extension, canonical in pi-badger-integration) gains an **in-adapter
poll loop**: a timer armed at `session_start` (tui/rpc modes only), cleared at
`session_shutdown`, every callback stale-ctx-guarded (Lane A F7: unguarded is fatal). Each
tick runs a **sound read-only watermark prefilter** in TS (`node:sqlite`, per-tick read-only
open — Lane A F1): "any messages row this session's cursor has not passed?" No → tick done,
zero spawns. Yes → spawn the existing Python delivery script (the sole exactly-once
transaction owner, ADR-0024) and inject what it returns via `pi.sendMessage`, waking idle
sessions on addressed mail per `AI_BADGER_PI_BUS_WAKE=off|addressed|all` (default
`addressed`); machine broadcasts queue without waking. The 30-minute first-read gate stays
(store freshness contract; ADR documents push making it moot for live sessions). Send-side:
`send_message.py` refuses `--project-id` targets that resolve to no project id on the machine
(refuse-not-guess, the sender-identity stance). No daemon, no TS transaction port. Poll
default 2s, `AI_BADGER_PI_BUS_POLL_SECS`.

Two structural facts discovered during grounding that shape everything below:

- **The seam work this builds on has already landed.** 0.157.1 (#464) delivered P4 pi defer
  (router = `before_agent_start` + per-turn `context` seam, session_start delivery deleted)
  and the leg-scoped cursor. The worktree tip already wires both seams + `session_shutdown`
  (adapter index.ts:338–402). Lane A F13's "sequence after P4" concern is already satisfied.
- **pbi is drifted behind ai-badger.** pbi's adapter (316/406 lines, no delivery router, no
  `context` seam) predates 0.156–0.157.1; ai-badger's vendored copy (419/593 lines) is ahead.
  `bun publish.ts --check` fails today (byte-differ). The canonical-flow invariant
  (pbi canonical ⇄ ai-badger vendored byte-equal, exact-set `ADAPTER_FILES`) is broken and
  every adapter edit made on top of a drifted pair deepens the skew. Healing is package P0,
  first and serialising.

---

## 1. Packages and subpackages

Mergable units, each independently reviewable. P0 → P3 are serial on the adapter files;
P1 and P2 are disjoint from the adapter and from each other; P5 (integration) is last.

| Pkg | Title | Files owned | Runs |
|---|---|---|---|
| **P0** | pbi canonical heal (reverse-sync) | pbi: `features/pi/adjustments/adapter/*` (4 files), mirrored adapter tests | first, serial |
| **P1** | Send-side target validation | `.ai-badger/skills/send-message/scripts/send_message.py`, `tests/test_send_message_skill.py` | parallel with P0/P2 |
| **P2** | Store delivery summary + cursor-wrap guard (Python) | `engine/badger_store.py` + vendored copies (manifest), `.ai-badger/skills/send-message/scripts/{badger_store.py,message_delivery_hook.py}`, `schemas/message.schema.json` (if per-doc shape), `tests/test_message_bus_store.py`, `tests/test_message_delivery_hook.py` | parallel with P0/P1 |
| **P3** | Adapter poll/wake state machine (TS) | `features/pi/adjustments/adapter/{index.ts,hook-bridge.ts}` + ai-badger pi tests; pbi mirrored tests | after P0; against P2's pinned contract |
| **P4** | ADR-0026 + docs | `docs/adr/0026-*.md`, send-message SKILL.md, changelog | parallel, finalised in P5 |
| **P5** | Integration (LAST) | cross-package: both repos' suites, `publish.ts --check`, live wake measurement, race drill | serial, last |

File-ownership rule: the adapter's two TS files are edited **only** in P3 (after P0's heal);
store/hook Python **only** in P2; `send_message.py` **only** in P1. No two packages share a
file; the only serialisation edges are P0→P3 (same files, canonical-direction safety) and
P2→P5 (P3 codes against P2's response contract, which this plan pins below).

### P0 — pbi canonical heal (reverse-sync) — *serial, first*

Bring pbi main up to the ai-badger 0.157.2 delivery state so the byte-equality contract is
restored **before** any new adapter work, then keep the canonical direction (pbi → ai-badger
via `publish.ts --ai-badger`) honest at the end.

Steps: diff the full delivery-related lagging set (adapter dir: `index.ts`, `hook-bridge.ts`,
`package.json`, `.ai-badger-capability-resources-discover`; plus any `send-message` skill
and `.ai-badger/hooks/` mirrors the den-refresh at 8340699 already covered — verify, don't
assume); copy ai-badger's 0.157.2 state into pbi as one reverse-sync commit; update pbi's
mirrored adapter tests (tests/adapter/) to the router shape; `bun publish.ts` to user scope.

**Acceptance criteria (checkable):**
- `bun publish.ts --check` exits 0 on pbi main (byte-equal, exact-set, no extras).
- pbi `bun test` and `bunx tsc --noEmit -p .` pass.
- `diff -r features/pi/adjustments/adapter/ ~/.pi/agent/extensions/ai-badger/` → identical.
- ai-badger `pytest tests/test_pi_adjustments.py tests/test_framework_copies.py` still green
  (the vendored copy is untouched by P0; the check proves the heal didn't desync it).

**Quality gate:** pbi `bun test && bun run check` + ai-badger framework-copies test run.

### P1 — Send-side target validation (`send_message.py`) — *parallel with P0/P2*

`--project-id` targets that resolve to no project id on the machine are refused (exit 1, the
`_refused` voice, nothing written) — root cause 3 (Lane B F3: msg 10 addressed to a string
no receiver could ever match). Machine-wide truth = collect every `.ai-badger/project-id`
value in a depth-budgeted home walk (Lane B used depth ≤ 4 and found all four live ids);
keep the helper **inside `send_message.py`** (skill-local), not `badger_store.py` — the
store is vendored ~12× under ADR-0024 and a machine-wide scan is a sender-side concern, not
store semantics. The refusal message lists the resolvable ids it did find (the msg-10
failure mode becomes self-diagnosing). Walk-depth budget documented; deeper-than-budget
repos are a named residual (ADR-0025 ids are minted at scaffold; the walk is the only
registry — root cause 4 stands, out of scope).

**Acceptance criteria:** unresolvable `--project-id` → refusal naming near-matches, nothing
written; resolvable id → sent; broadcast (no target) and 1:1 (`--session-id`) paths
byte-identical in behaviour to today; `--sender-project` explicitly out of scope (open
question); walk-depth budget documented in the SKILL.

**Quality gate:** red-first tests in `tests/test_send_message_skill.py` (fixture tree with
planted `project-id` files: refuse / accept / no-target unaffected), then the full file.

### P2 — Store delivery summary + cursor-wrap guard (Python) — *parallel with P0/P1*

Two changes, both owned by the store because both are delivery semantics (ADR-0024: one
implementation of the txn):

- **P2.1 Wake-summary contract.** The wake decision (addressed vs broadcast-only batch)
  must be made by the exactly-once transaction — a TS-side shape query would duplicate the
  three-shape + R2 + cursor read predicate in TS, i.e. a store port in disguise (rejected,
  see ADR §2). Pin the contract here so P3 can code against it: `deliver_for_session` gains
  a summary of what the transaction delivered, surfaced by `message_delivery_hook.py` as an
  **additive** response field (e.g. `hookSpecificOutput.aiBadgerBus = {addressed: n,
  broadcast: m}`; harnesses that ignore it are unaffected — today's `{}`-empty and
  `additionalContext` shapes unchanged). Proposed carrier: batch-level counts computed in
  the txn (rows already carry `target_session`/`target_project`); the per-document
  `target`-field + schema change is the named alternative — api-engineer lane rules, either
  way the summary is computed inside the txn, never re-derived in TS.
- **P2.2 Cursor-wrap guard.** `deliver_for_session` reads purely `id > cursor`; SQLite
  reuses rowids after a full-table prune, and the 4-day prune CAN empty `messages` while a
  poll-refreshed cursor stays fresh (our own 2 s ticks upsert `cursors.ts` on empty reads).
  A post-wrap id ≤ cursor is then silently unreadable — by the store, not just by the TS
  prefilter. Guard inside the same BEGIN IMMEDIATE: `cursor_id > COALESCE(MAX(id),0)` ⇒
  reset the cursor to 0 (treat as pruned/replaced state; the gate re-applies on that read).
  This makes wrap self-healing at the txn and gives the TS prefilter a sound "fire when
  wrapped" rule (§3 R2).

**Acceptance criteria:** summary field present on mail-bearing responses and absent/empty on
`{}`; per-leg counts verified against the three shapes; wrap scenario (cursor > MAX(id))
self-heals in one txn and a red-first test pins it; all vendored store copies re-synced
byte-equal via the manifest (copy-skew test green); response without mail stays `{}`.

**Quality gate:** `pytest tests/test_message_bus_store.py tests/test_message_delivery_hook.py
tests/test_send_message_skill.py` + the vendored byte-equality suite
(`tests/test_copy_skew.py` / `test_framework_copies.py`).

### P3 — Adapter poll/wake state machine (TS) — *serialises on P0; codes against P2's contract*

Structure chosen to keep `publish.ts`'s exact-set `ADAPTER_FILES` untouched (no third file →
no canonical file-set contract change, no `adjust_hooks.py` churn):

- **Pure logic → `hook-bridge.ts`** (stays I/O-free, matching its header contract): the poll
  decision function — wake policy from `AI_BADGER_PI_BUS_WAKE` (`off|addressed|all`, default
  `addressed`), poll interval from `AI_BADGER_PI_BUS_POLL_SECS` (default 2), mode gating
  (tui/rpc arm; print/json never), in-flight skip, tick-schedule arithmetic — pure, therefore
  unit-testable in both repos.
- **I/O → `index.ts`**: `session_start` arms the timer (clearing any prior timer first —
  `/new`, `/resume`, `/fork` re-fire it, Lane A F10); `session_shutdown` clears it; every
  timer callback runs inside the stale-ctx guard (try/catch; measured fatal otherwise, F7)
  and checks a session-live flag before touching `pi.sendMessage`. The prefilter is one
  `node:sqlite` read-only **per-tick** open (never a held handle — DB replacement must be
  seen, §3 R2) running the pinned sound predicate:
  `EXISTS(SELECT 1 FROM messages WHERE id > (SELECT COALESCE(cursor_id,0) FROM cursors WHERE session_id=?))`
  or cursor-row absent/wrapped → poll. Any prefilter error fails OPEN (spawn anyway — sound
  direction: never silent when unsure). On poll fire: the existing `runDelivery` spawn; on
  mail, `pi.sendMessage` with `triggerTurn` per wake policy (addressed mail present → wake;
  broadcast-only → `deliverAs: "nextTurn"/"steer"`, never wake); an in-flight-delivery flag
  prevents spawn storms.
- **Seams stay, now prefilter-gated.** `before_agent_start`/`context` keep their roles
  (print/json have no timer — F7 — so the seams remain their only delivery path, and they
  stay belt-and-suspenders in tui/rpc), but each seam spawn is gated by the same prefilter,
  removing the unconditional per-LLM-call spawn cost (Lane A "Still open": per-LLM-call poll
  cost unmeasured — this answers it structurally). Poll-driven spawns get a timeout budget
  larger than `GATE_TIMEOUT_MS` (they are off the turn's critical path; the 5s/5s race, §3
  R5, does not apply to them the way it does to seam spawns).

**Acceptance criteria (checkable):**
- rpc-mode scripted probe (Lane A F4 probe shape): idle session wakes on a 1:1 send within
  `poll + wake` latency, zero stdin commands; broadcast-only mail queues without waking.
- `AI_BADGER_PI_BUS_WAKE=off`: no `triggerTurn` ever; `=all`: broadcast wakes.
- print/json: no timer armed (no `session_start`-armed timer observable), seam delivery
  unchanged; stale-ctx probe (timer firing after `session_shutdown`, F7's exact shape) is
  caught and non-fatal.
- Prefilter silence: no spawn when `EXISTS` is false (spawn-count assertion in tests);
  prefilter error → spawn anyway.
- At most one in-flight delivery per session; timer and seams never double-inject (§3 R6).

**Quality gate:** ai-badger `pytest tests/test_pi_adjustments.py` (+ new poll/wake unit
file), pbi `bun test` mirrored suite, `bunx tsc --noEmit -p .` in pbi; scripted rpc probe +
stale-ctx probe as committed integration artifacts.

### P4 — ADR-0026 + docs — *parallel; finalised at P5*

ADR-0026 skeleton → full text (§2 below); send-message SKILL.md gains the wake/poll env
contract and the target-validation refusal; no hooks-manifest changes (ADR-0022: the
adapter is pi's whole arming surface — the timer arms nothing new in any manifest);
`docs/work/` plan + changelog. Drafted parallel, cannot merge before P3/P2 final shapes.

### P5 — Integration package (LAST) — *serial; nothing merges after it*

Cross-package proof, in order: full ai-badger pytest suite + pbi `bun test`; vendored-copy
manifest byte-equality across all copies; `bun publish.ts --check` green (pbi canonical ⇄
ai-badger vendored ⇄ user scope, all three byte-equal); **live wake measurement** — the one
load-bearing unmeasured claim (Lane A F6/F14): a pty-driven TUI probe upgrading F6 from
INFERRED to MEASURED, plus the rpc measurement (send 1:1 → wake latency ≤ poll+spawn+turn;
broadcast → no wake, next-turn delivery); the compaction-race probe (wake during a forced
`/compact`); timer-vs-seam double-delivery drill under fan-out; print/json regression (pull
seams still deliver); `AI_BADGER_PI_BUS_POLL_SECS`/`WAKE` knob matrix. Measurement results
fold into ADR-0026's open-questions section (TUI wake upgrade, compaction verdict).

---

## 2. ADR-0026 skeleton — `docs/adr/0026-pi-bus-push-delivery.md`

> Kebeb-case imperative title suggestion: **"0026-pi-bus-delivery-pushes-with-an-in-adapter-poll.md"**.
> Status: Proposed (date of PR). In the same PR as the change (ADR README convention).
> Extends: ADR-0022 (adapter = whole arming surface), ADR-0024 (store; one txn owner), ADR-0025
> (project resolution). Supersedes nothing; narrows the D4 "no session_start delivery" ruling of
> the delivered tasks by adding a new path beside it.

### Context (cite the measured record, don't restate it)

- **Root causes (Lane B, ranked):** (1) the 30-minute first-read gate + jump-past cursor
  dropped 3 of 4 real messages today (F2, F6); (2) pull-only delivery — an idle session
  consumes nothing and the wait burns the gate window (F9, F10, F16 — dominant for pi's
  lane-heavy usage); (3) send-side accepts unresolvable targets — msg 10 was undeliverable
  by construction (F3); (5) fail-open with content-free logging left 44 unattributable
  failures (F4, F15). The gate stays (owner freshness ruling); push makes it moot for live
  sessions — the ADR says exactly that and why the gate is nonetheless kept.
- **API surface (Lane A, measured on pi 0.84.4):** `pi.sendMessage(..., {triggerTurn:true})`
  wakes an idle rpc session with no stdin input (F4, measured; TUI same code path, inferred
  F6, measured in this task's integration package); mid-turn injection queues
  (steer/followUp), never interrupts (F5); the runtime is Node 26.8.1 and `node:sqlite`
  works in-process while `bun:sqlite` does not (F1) — the prefilter needs no subprocess and
  no native deps; timers are sanctioned session-scoped background work, deferred to
  `session_start`, cleaned in `session_shutdown` (F8); print/json have no idle session to
  wake and `session_start` is deferred until stdin EOF (F7); a timer firing after
  `session_shutdown` hits a stale ctx that is **fatal** uncaught (F7) — every callback
  guards; session id authority is `ctx.sessionManager.getSessionId()`, never
  `PI_SESSION_ID` (F9); fork/new/resume re-fire the lifecycle and are the re-arm points
  (F10).

### Decision(s)

1. **Push = in-adapter poll + wake.** The adapter arms a poll timer at `session_start`
   (tui/rpc only), clears it at `session_shutdown`, and each tick runs a sound read-only
   prefilter (`node:sqlite`, per-tick open, fail-open to "poll") before spawning the
   existing Python delivery script — the only exactly-once transaction owner (ADR-0024
   unchanged). Mail returns through the existing Claude-shaped response, now with an
   additive batch summary (target-shape counts) computed inside the txn; the adapter injects
   via `pi.sendMessage`, waking idle sessions (`triggerTurn`) on addressed mail only, by
   default. Env: `AI_BADGER_PI_BUS_WAKE=off|addressed|all` (default `addressed`),
   `AI_BADGER_PI_BUS_POLL_SECS` (default 2).
2. **The gate stays; push makes it moot for live sessions.** The 30-minute first-read window
   remains the store's freshness contract for sessions that never push (print/json, other
   harnesses). Push changes who reads, not what the store guarantees.
3. **Send-side validation (refuse-not-guess).** `send_message.py` refuses `--project-id`
   targets resolving to no machine project id — the same stance as sender identity.
4. **The seams stay, prefilter-gated.** `before_agent_start`/`context` remain the delivery
   path for print/json (no idle session to poll) and as a fallback everywhere; their spawns
   become prefilter-gated, ending the per-LLM-call spawn cost. The timer is the sole *push*
   initiator; both paths share the one exactly-once txn, so cross-path races cost a
   serialized empty read, never a duplicate.

### Rejected alternatives (each with the reason it loses)

- **Bus daemon** (external process driving RPC prompt/steer): needs a long-lived machine
  service (owner: NO-DAEMON), cross-platform service management, and a second trust surface;
  the measured matrix (Lane A) prices it high-effort vs the timer's low. Loses.
- **TS port of the delivery transaction** (deliver from TS, drop the spawn): violates
  ADR-0024's one-implementation-of-the-txn; dual implementations drift exactly where
  exactly-once lives; the spawn cost it removes is already bounded by the prefilter. Loses.
- **WAL watcher / fs.watch on the DB**: WAL sidecars commit on every hook write
  machine-wide (markers, audit, telemetry — not just messages), so the callback rate is
  unbounded and row semantics still require the txn; loses to a 2s poll costing one index
  seek.
- **Cron-fired fresh sessions (pi-cron carrier)**: each fire is a *new* process; it cannot
  reach an existing idle session (Lane A F12). Right carrier for a future "wake sessions
  that don't exist yet" decision, wrong for live delivery.
- **session_start delivery** (claude-parity arm): already ruled out (D4, 0.156.0) — a
  session that never turns consumes nothing; in print/json `session_start` fires only at
  stdin EOF (F7), so it would not help headless anyway; and the gate would still drop
  >30 min mail. The poll supersedes its purpose for live sessions. Loses.
- **TS-side shape query for the wake policy** (deciding addressed-vs-broadcast in TS):
  duplicates the read predicate (three shapes + R2 + cursor semantics) in a second language
  — the store port in disguise. The txn that consumed the mail reports the summary. Loses.
- *(Standing, not re-litigated: per-hook manifest pi entries — ADR-0022.)*

### Consequences

**Positive.** Idle tui/rpc sessions receive mail within poll-interval + wake latency instead
of never; the gate stops consuming mail on this machine's dominant pattern (parallel pi
lanes); per-LLM-call delivery cost drops to one index seek; send-side mis-addressing fails
loudly at send time.
**Negative / accepted.** New TS↔store schema coupling (the prefilter's SQL knows
`messages`/`cursors`) — compensated by a contract test pinning the SQL to the real DDL. New
runtime coupling to pi's Node runtime (`node:sqlite`; a bun switch degrades fail-open to
unconditional ticks — logged, not fatal). The cursor-wrap hole must be fixed for the
prefilter to be sound (P2.2) — a latent store bug this task retires. Wake-on-`all` spends
tokens per broadcast per live session — default is `addressed`. Mail consumed by the txn but
lost to a failed injection (wake throws, e.g. mid-compaction) is a named residual, same
shape as today's seam injection.
**Neutral.** Machine broadcasts queue without waking; poll wakes do not preempt in-flight
turns (pi queues steer/followUp, F5); nothing survives process exit (F8) — mail persists in
the store, which is the point.

### Open questions (the ADR records them; this task's integration package settles two)

1. TUI wake: measured or still inferred? (integration probe upgrades F6.)
2. Wake during auto-compaction: unmeasured (F14); probe + design note.
3. json-mode long-held stdin sessions: can `session_start` fire on first line? (out of
   scope; recorded.)
4. Should the seams' own spawns be retired entirely once push proves out? Kept
   belt-and-suspenders now; revisit after one release of telemetry.
5. Delivery audit (a `deliveries` fact — Lane B F15): explicitly out of scope here;
   successor task.

---

## 3. Risk register (top risks, mitigations, owner of the mitigation)

| # | Risk | Evidence | Mitigation (owning package) |
|---|---|---|---|
| R1 | **Stale-ctx crash** — a timer callback firing after `session_shutdown` throws synchronously and is fatal (measured, F7) | Lane A F7 | Every timer callback wrapped; timer cleared first thing in `session_shutdown`; session-live flag checked before any `sendMessage`; re-arm idempotent on `session_start` re-fires (F10). Proven by a probe that replays F7's exact shape (P3, integration re-run P5) |
| R2 | **Watermark soundness vs DB replacement/prune**: (a) a held-open sqlite handle reads a deleted inode after a recovery-runbook delete; (b) rowid reuse after a full 4-day prune wraps ids below a fresh cursor — and our own 2s ticks keep cursor `ts` fresh forever, *manufacturing* the hole; the store's `id > cursor` read is equally blind to wrap | Lane B F6 (4-day prune, cursors included); ADR-0024 recovery runbook deletes the DB | Per-tick read-only open (no held handle); prefilter fires on cursor-row absent **or** `MAX(id) < cursor` (wrap detected → poll); P2.2's in-txn reset makes the store itself wrap-safe; prefilter errors fail open to "poll". Soundness tests: replace the DB file under a live ticker; wrap the id space on a scratch DB (R2→P2, prefilter→P3) |
| R3 | **Wake cost on `all`** — every machine broadcast wakes every live session; token spend scales with broadcast × sessions | Owner knob exists; Lane A F4 shows each wake is a full agent run | Default `addressed`; wake emits a notice naming the trigger; SKILL.md prices the knob; no rate-limit in v1 (recorded as open) |
| R4 | **pbi sync skew** — canonical/vendor/user three-way equality broken today (pbi behind 0.157.x); any parallel edit deepens it; a missed vendored re-land is this framework's recorded failure mode (0.157.0 join-repair: 15/16 missed) | publish.ts exact-set contract; git log; state.json | P0 heals first and serialises the adapter; P5 ends on `bun publish.ts --check` exit 0 across all three locations; adapter file-set kept stable (no third file) so `ADAPTER_FILES` is untouched |
| R5 | **5s/5s spawn-vs-busy-timeout race** — adapter kill at 5000 ms vs store `busy_timeout` 5000 + WAL retries (F14) | Lane B F14, adapter `GATE_TIMEOUT_MS` | Poll spawns are off the turn's critical path → larger timeout budget for timer-driven spawns; prefilter removes most spawns; seam spawns keep 5s (they gate a turn). Timer-vs-store contention asserted in the integration drill |
| R6 | **Double-delivery races, timer vs seams** — tick and `before_agent_start`/`context` both spawn for one session | BEGIN IMMEDIATE serializes (R3: exactly-one-injects, same final cursor) | Exactly-once holds at the store by construction; adapter adds an in-flight skip flag; inject paths stay disjoint (timer → `sendMessage`, seams → their return channels). Integration drill: interleaved timer + prompt seams, assert at-most-once per message |
| R7 | **`node:sqlite` / runtime coupling**: pi 0.84.4 runs Node (F1); a future pi on bun breaks `node:sqlite` import | Lane A F1 | Import guarded; prefilter failure degrades to unconditional ticks (fail-open, D31); contract test pins the prefilter SQL against the store DDL so schema drift fails a test, not a session |
| R8 | **Consume-then-lose injection failure** — the txn advances the cursor, then `sendMessage` throws (compaction race, F14-unchecked) → mail consumed but not injected | Lane A F14 (unchecked), F5 | Same residual as today's seams (accepted by D31 direction); guard + notice; integration probe measures the compaction shape; if it throws, mail is re-readable only if the txn is made inject-aware — recorded as an ADR open question, not silently accepted |
| R9 | **Validation false-refuses** deep repos (walk depth budget) or a not-yet-backfilled fleet (ADR-0025 id-less repos resolve to None) | ADR-0025 consequences; state.json carried item (den-refresh backfill) | Depth budget documented; refusal message lists discovered ids and names the backfill path; coordinate the one-shot machine den-refresh before relying on validation |

**Most likely to actually bite:** R8's compaction race (with R2's wrap hole a close second) —
a poll timer *will* fire during a long compaction on a real session, pi's behavior there is
unmeasured (F14), and the failure shape is silent mail loss right after the store did its
exactly-once job. The integration package must run that probe, not just the happy wake.

---

## 4. Sequencing vs the in-flight framework

**Already landed (prerequisites in place — this worktree branched on them):**
- 0.157.1 / #464: P4 pi defer seams (the router this task extends), leg-scoped cursor (the
  first-read semantics the gate keeps), P9 send-side identity. No rebase needed; P0's heal
  presupposes this state.
- ADR-0025 project-id walk (send-side validation resolves against it).

**Must land before this task's merge:**
- Nothing in code. One machine op: the recorded den-refresh backfill of
  `.ai-badger/project-id` on existing repos (state.json "next" item 3) should run before the
  owner relies on P2's validation — an id-less repo makes every `--project-id` send refuse.

**Intersects (fold, don't fork):** state.json's optional hardening item "pi per-call spawn
cooldown" — the poll loop needs exactly one cooldown/skip mechanism; fold it into P3's
in-flight flag rather than shipping two mechanisms.

**Must land after this task (explicitly out of scope; name them so they don't ride along):**
- **Delivery audit** (`deliveries` fact or `hook_audit` delivery rows) — root cause 5's real
  fix and the only way "was it delivered?" becomes answerable (F13/F15). Follow-up task.
- **The 44 OperationalError diagnosis** — P2 touches the hook's failure path; keep the
  content-free discipline, but a verbose-repro env knob is a candidate rider only if the
  owner pulls it; otherwise follow-up.
- **pi-cron as the "wake sessions that don't exist yet" carrier** (Lane A F12) — future ADR;
  deliberately not here.
- **Cross-harness push** (claude/hermes/copilot have no in-process timer surface) — future
  decision, likely per-host; pi-only for now, and the ADR should say so.
- ADR-0024's queued `subagents` child-table revisit: this task's P2 deliberately avoids
  needing query verbs (batch summary, not per-row SQL), so that trigger stays unpulled.

---

## 5. Proposal in one sentence

Heal pbi first (P0), then three disjoint parallel lanes — send-side refusal (P1), store
summary + wrap guard (P2), adapter poll/wake (P3) with ADR/docs (P4) — closing with an
integration package (P5) whose headline run is the live wake measurement and the
compaction-race probe, with `publish.ts --check` byte-equality as the merge gate.
