# Plan proposal — API engineer lane: aib-pi-message-bus-push-delivery (technical design)

**Date:** 2026-09-01 · **Lane:** one of three parallel plan proposals, to be consolidated into plan rev 1 · **Planning only; no code, no git mutations.**

**Ground truth read:** Lane A `docs/work/2026-09-01-pi-push-api-surface.md` (F1–F14); Lane B `docs/work/2026-09-01-pi-bus-delivery-root-cause.md` (F1–F17); code: `features/pi/adjustments/adapter/{index.ts,hook-bridge.ts}`, `.ai-badger/skills/send-message/scripts/{send_message.py,message_delivery_hook.py,badger_store.py}`, `features/common/hooks/`, `features/pi/adjustments/adjust_hooks.py`, `tooling/sync_plugin_skills.py`, `engine/badger_lib.py`, `pi-badger-integration/publish.ts`, tests under `features/pi/tests/` and `tests/`.

All line references to `badger_store.py` are the worktree's vendored skill copy (byte-identical to `features/common/hooks/badger_store.py` and `features/common/skills/send-message/scripts/badger_store.py` — verified 2026-09-01).

---

## 0. Design at a glance

```
timer tick (tui/rpc only, AI_BADGER_PI_BUS_POLL_SECS, default 2s)
  └─ bus-prefilter (pure state machine)
       ├─ L0  SELECT COALESCE(MAX(id),0) FROM messages      ─┐
       ├─ L1  stat(dbPath) → inode identity                  │ node:sqlite readOnly
       ├─ L2  SELECT cursor_id FROM cursors WHERE session_id=?│ + fs.stat —
       └─ L3  probe rows (exact txn predicate mirror)        ─┘ never writes
            └─ classify (1:1 / project / broadcast) × wake policy
              ├─ nothing wake-eligible → record watermark, SKIP (no spawn)
              └─ wake-eligible mail → spawn python delivery txn (the ONLY txn)
                   └─ pi.sendMessage(mailDocument, {deliverAs, triggerTurn}) per wake matrix
seams (before_agent_start, context): same prefilter as a spawn-decorator; router untouched
send_message.py: refuse a --project-id that no receiver's resolver can produce
```

Invariant kept everywhere: **the Python store is the single transaction owner.** The TS side opens the user DB `readOnly` and can provably not write (readOnly connections cannot write). Every consume is `deliver_for_session`'s one `BEGIN IMMEDIATE` (badger_store.py:1886–1951).

---

## 1. Watermark design

### 1.1 What is remembered

Per **pi session instance** (keyed by `resolveSessionId(ctx, env)` — session-manager authority, never `PI_SESSION_ID` env alone, Lane A F9), held in a closure inside the adapter factory:

| field | meaning |
|---|---|
| `watermark: number \| null` | `MAX(messages.id)` at the last **clean negative probe** for this session; `null` = unknown (force probe) |
| `dbIdentity: {dev, ino} \| null` | the user DB file's identity at last probe (from `fs.statSync`) |
| `compacting: boolean` | set by `session_before_compact`, cleared by `session_compact` / `session_compact_failed` |
| `failStreak: number` | consecutive failed spawns (drives notice latch + backoff) |

Nothing is persisted. Process death, `/new`, `/resume`, `/fork`, `/clone` all go through the disarm/re-arm cycle (§4.3) and lose it — which is safe, because a lost watermark only means "probe once more".

### 1.2 The exact cheap queries (all read-only, one `node:sqlite` connection)

```sql
-- L0, per tick: nothing new globally? (PK reverse seek, O(1))
SELECT COALESCE(MAX(id), 0) FROM messages;

-- L1, per tick: this session's cursor (fresh EVERY tick — never cached)
SELECT cursor_id FROM cursors WHERE session_id = :sid;

-- L2 probe, cursor exists (live read): exact mirror of _read_addressed's predicate
SELECT id, target_session, target_project, sender_session, ts
FROM messages
WHERE id > :cursor_id
  AND sender_session <> :sid                              -- R2 exclusion
  AND (target_session = :sid OR target_session IS NULL)   -- 1:1 ∪ (project ∪ broadcast) shapes
ORDER BY id ASC
LIMIT 16;

-- L2 probe, cursor-less (fresh/resumed session): adds the 30-min gate, INCLUSIVE
--   (python: ts >= cutoff, badger_store.py:1912 — inclusive comparison mirrored)
--   ... AND ts >= :cutoff
```

DB open: `new DatabaseSync(dbPath, { readOnly: true })` (Node 26.8.1 per Lane A F1; feature-detect the `node:sqlite` import — see §3.4), plus `db.exec("PRAGMA busy_timeout = 250")`. WAL readers never block on the writer's `BEGIN IMMEDIATE`, so a probe cannot collide with a delivery txn.

The project leg's precision needs the resolved project id; TS mirrors the resolver (§1.4). When the mirror cannot resolve (walk error, unreadable file) → treated as UNKNOWN → spawn (fail-open).

### 1.3 Tick flow (pure decision in `bus-prefilter.ts`, I/O in `bus-store.ts`)

```
tick(sid):
  if delivery script absent            → return SILENT_SKIP        (Rule 7 scenario 2, no I/O at all)
  if inFlight                          → return SILENT_SKIP        (a spawn can run 5s; ticks are 2s)
  stat(dbPath):
    ENOENT                             → watermk=null; return SILENT_SKIP  (no file ⇒ no rows; next tick re-stats)
    identity ≠ dbIdentity              → dbIdentity=stat; watermk=null     (DB replaced: forced probe)
    stat error                         → return SPAWN               (UNKNOWN, fail-open)
  maxId = SELECT COALESCE(MAX(id),0) FROM messages
  if watermk !== null AND maxId === watermk
                                       → return SILENT_SKIP        (nothing written since last clean negative)
  cursorId, rows = L1, L2
  classified = classify(rows, {sid, pid})                           (pure; §2 classes)
  if no row is wake-eligible under policy
                                       → watermk = maxId; return SILENT_SKIP
  else                                 → return SPAWN             (watermark deliberately left stale;
                                                                   next tick re-probes; after the txn
                                                                   advances the cursor the probe goes
                                                                   negative and the watermark re-arms)
  any error above                      → watermk=null; return SPAWN (fail-open, D31)
```

Two properties make the equality test the whole game: (a) writes to `messages` are **inserts only** (send path, badger_store.py:1868–1884) plus the prune's low-end `DELETE` — every insert raises `MAX(id)`, every prune lowers or keeps it; (b) the skip test is **exact equality**, never `≤`, so a replaced/fresh DB (lower `MAX(id)`) can never produce a skip.

### 1.4 Path and resolver mirrors (exact names from source)

| what | Python (authority) | TS mirror |
|---|---|---|
| user DB path | `user_db_path()` badger_store.py:388 — `AI_BADGER_USER_ROOT` set and non-blank ⇒ `Path(env)/"ai-badger.db"`; else `Path.home()/.ai-badger/ai-badger.db` (where `Path.home()` = `_DEFAULT_HOME = Path.home()`, :136) | `process.env.AI_BADGER_USER_ROOT` ⇒ `path.resolve(ctx.cwd, env, "ai-badger.db")` when relative (Python resolves `Path(env)` against the spawned process's cwd, and the adapter spawns with `cwd: ctx.cwd` — index.ts runDelivery), else `path.join(os.homedir(), ".ai-badger", "ai-badger.db")` (both read `$HOME` on POSIX) |
| project id | `resolve_project_id()` badger_store.py:2048 — `AI_BADGER_PROJECT_ID` wins; else nearest ancestor `.ai-badger/project-id` (nearest `.ai-badger` dir **stops** the walk; blank/absent = unset) | same env first; else `fs.realpathSync(path.resolve(cwd))` walk upward — mirroring `_real_path` (:2038) and `_nearest_project_id_file` (:2013) incl. the stop-at-nearest rule |
| gate cutoff format | `(now − 30min).isoformat()` UTC, micro-second precision, `+00:00` suffix; comparison is SQL string `ts >= :cutoff` | pure helper `isoCutoffUtc(date)` emitting Python's exact shape (`2026-09-01T19:07:39.123456+00:00`); **never** `toISOString()` whose `Z` suffix and ms precision break the string ordering at the boundary |

The spawn inherits `...process.env`, so `AI_BADGER_USER_ROOT` and `AI_BADGER_PROJECT_ID` are identical on both sides by construction; the mirrors only make the *prefilter's* view agree with the *txn's* view in the same process.

### 1.5 Soundness argument — "prefilter says nothing ⇒ the python txn would return empty"

Stated invariant: the tick may skip **only** on (i) exact-watermark equality, or (ii) a clean probe whose predicate is literally the txn's read predicate (same three D3 shapes, same R2 exclusion, same gate cutoff for the cursor-less case) evaluated on a fresh read of the same file identity. Errors never produce a skip (they spawn, §3.3). Hazard by hazard:

1. **Concurrent sends mid-check.** Each SELECT is its own WAL read snapshot. A send commits before the probe's snapshot ⇒ the probe sees it. It commits after ⇒ it has id > the watermark we are about to store, and the **next** tick's fresh `MAX(id)` differs from the stored watermark ⇒ probe. The watermark is only ever written *after* a negative probe and compared against a *fresh* `MAX(id)`, so no interleave hides a committed row. A send committing *during* the spawned txn is inside `BEGIN IMMEDIATE` — the store's own atomicity (R3).
2. **4-day prune** (`open_user` → `prune_expired` on every open, badger_store.py:2139–2151, hour-throttled): deletes only rows with `ts < now−4d` — the low-id end (id order = ts order; inserts serialize under `BEGIN IMMEDIATE`). A deleted row is undeliverable for the txn and invisible to the probe *symmetrically*: cursor-less probes exclude it via the 30-min `ts` gate, cursor-ful probes exclude it because everything above a cursor is younger than 4 days (the cursor itself is pruned at the same age, reverting that session to the gate path — mirrored). A boundary-inverted row can at worst cause a false-positive spawn. **No false negative.**
3. **DB replaced/deleted (fresh DB, lower max id):** `statSync` dev/ino changes ⇒ watermark discarded and one forced probe. Exact-equality (never `≤`) closes the "restored backup with coincidentally equal MAX(id)" case only together with the identity check; an in-place same-inode restore is still safe because any data change moves `MAX(id)` off the watermark and forces a probe whose predicate runs on exactly the data the txn will see. A *deleted* file (`ENOENT`) skips soundly (no file ⇒ no rows) and re-probes the moment a sender recreates it.
4. **Contained-family refusals** (`_refuse_contained_table`, badger_store.py:865): scoped to families whose legacy file reappeared. `messages` and `cursors` are born-in-SQLite families with **no legacy path** (badger_store.py:642–643), so they can never be contained, and `deliver_for_session`/`delete_cursor` touch nothing else — asserted by `tests/test_containment_bus_coexistence.py` ("send/deliver run normally while containment is live"). The raw-SQL probe is unaffected by any family state. Residual: probe flags mail, spawn dies on an *unrelated* store error ⇒ error notice (D31), turn/session unaffected.
5. **DB path resolution:** mirrored per §1.4. Both sides derive the same file from the same env under the same cwd; the TS probe and the Python txn cannot disagree about *which* file they read. A relative `AI_BADGER_USER_ROOT` resolves against `ctx.cwd` on both sides (the spawn's cwd).
6. **Cutoff mirror:** TS's cutoff instant is read at tick time, Python's at txn time (later) ⇒ Python's 30-min window is always a **subset** of the TS window ⇒ the prefilter can only over-flag (false-positive spawn ⇒ the gate drops the row and the txn returns empty), never under-flag — except on a backward wall-clock step, where the worst case is one delayed wake by one poll interval; the ungated seams still deliver (§1.7).
7. **Where it cannot be made sound → spawn.** Probe/store errors, stat errors, resolver-walk failures, an empty/unresolvable session id (`""`), and any `node:sqlite` unavailability (feature-detect at import; older runtimes) all classify UNKNOWN ⇒ **spawn unconditionally**, which is exactly today's seam behavior. The prefilter degrades to a pass-through decorator, silently — the existsSync silent-unwired rule (Rule 7 scenario 2) keeps holding; the bus simply behaves as it does today.

Statement of the one deliberate scoping: under `AI_BADGER_PI_BUS_WAKE=addressed` (default) the tick **does not spawn on broadcast-only mail** — the txn *would* return those rows, so the literal "txn returns empty" claim is narrowed to: *the txn returns empty, or returns only mail the wake policy defers to the existing seams.* Deferred broadcast mail is not lost: the store keeps it (no cursor movement) and the next seam read delivers it (today's path). Under `all`, the claim holds unmodified.

### 1.6 Cost

Per tick per session: 1 `stat` + 3 indexed reads (multi-index OR per D6, same plan shape as `_read_addressed`). Sub-millisecond on the observed 3.4 MB DB. This replaces today's per-LLM-call python spawn (~50–100 ms process start) at the `context` seam with a sub-ms probe that spawns only when mail may exist.

---

## 2. Wake matrix

### 2.1 Classification (pure, in `bus-prefilter.ts`)

Rows are classified against `{sid, pid}` (pid = mirrored resolver output; `null` ⇒ project class cannot exist for us, matching the txn's D7 1:1-only leg):

| class | predicate (subset of the probe rows) |
|---|---|
| `direct` (1:1) | `target_session === sid` |
| `project` | `target_session === null && pid !== null && target_project === pid` |
| `broadcast` | `target_session === null && target_project === null` |

Mixed mail: the **policy gates the spawn, not the payload**. If any wake-eligible row exists, the txn runs and its full returned document is injected — a broadcast rides along as a passenger of a justified wake rather than being dropped.

### 2.2 The matrix

`WAKE = AI_BADGER_PI_BUS_WAKE` (`off` < `addressed` < `all`; default `addressed`). Session state: **idle** = `ctx.isIdle()` (types.d.ts ExtensionContext.isIdle) and not compacting; **streaming** = a run is between `agent_start` and `agent_end` (tracked in index.ts; `isIdle()` is the cross-check); **compacting** = `session_before_compact` … `session_compact`/`session_compact_failed`.

| state ↓ \ class → | direct (1:1) | project | broadcast |
|---|---|---|---|
| **idle** | WAKE — `pi.sendMessage({customType:"ai-badger", content, display:true}, { deliverAs:"followUp", triggerTurn:true })` — the measured idle-wake branch (Lane A F4) in the subagent-proven shape (F11) | same as 1:1 | `off`/`addressed`: DEFER — no spawn, no send; mail waits for the next seam. `all`: same call as 1:1 |
| **streaming** | `sendMessage(…, { deliverAs:"steer" })` — no `triggerTurn`; lands after the current turn's tool calls, before the next LLM call (F5) | same as 1:1 | `off`/`addressed`: DEFER · `all`: `deliverAs:"followUp"` (natural stop) |
| **compacting** | DEFER (skip tick; re-probe next tick) | DEFER | DEFER |

- `off`: the timer is **never armed** (no probe, no wake). Seams keep running, prefilter-gated as usual (§4.2). All mail classes are pull-only — today's behavior.
- `addressed` (default): 1:1 + project wake; broadcast queues in the store (owner decision) and is delivered by the seams on the next natural read — or as a passenger of a later justified wake.
- `all`: broadcast additionally wakes (idle) or follows up (streaming).
- `nextTurn` is deliberately **unused**: idle mail can turn *now* (`followUp`+`triggerTurn`), streaming mail has a sooner queue (`steer`/`followUp`); `nextTurn` would park consumed mail on a future *user* prompt, a strictly worse and riskier holding state.
- `off|addressed|all` values are read once per session at arm time; any other value ⇒ one warning notice and the default (never a crash), same voice as the existing env parsing (`awayFromEnv`).

### 2.2 The compaction-window race (Lane A F14-3) — handled, not accepted

`sendCustomMessage`'s `triggerTurn` path bypasses `prompt()`'s compaction guard (`agent-session.js:836–838`), so a wake landing mid-compaction is untested upstream. The design **avoids** the window: `session_before_compact` sets `compacting=true`; `session_compact` / `session_compact_failed` clear it; the timer defers every tick while set. Mail stays in the store (the probe is side-effect-free), so deferral costs nothing. Residual, documented: an event-ordering gap between pi deciding to compact and the `before_compact` emission reaching the adapter — same tick granularity as the flag itself; and `steer`/`followUp` sends issued in that gap take pi's unguarded path. Accepted because closing it fully requires a pi-side lock this adapter cannot own; the next tick heals any misfire.

### 2.3 Consumption-then-loss window (the one true residual)

The timer's txn consumes mail *before* `sendMessage` runs. If `sendMessage` throws after the txn committed, the mail is consumed but not injected — the store has no un-consume API, so this window cannot be closed from the adapter. Mitigations, in order: (a) generation-token staleness check before spawning (§3.2); (b) on a non-stale throw (e.g. run aborted between classify and send), one compensation retry with `deliverAs:"nextTurn"` (no turn, rides the next prompt); (c) on a stale-ctx throw, drop silently — the session is gone, and a successor session has its own cursor. The residual window is sub-millisecond on a live ctx and the F7 shutdown race is closed by the generation token except at the exact teardown interleave. Documented as accepted in the ADR.

---

## 3. Module shape

Follows the existing discipline: **`hook-bridge.ts` stays pure; new pure logic goes in a new pure module; all I/O is isolated in one injectable port; index.ts only wires.** No test files inside the adapter directory (it is vendored wholesale to user scope — see §6); tests live in `features/pi/tests/`.

### 3.1 New files

**`features/pi/adjustments/adapter/bus-prefilter.ts`** — PURE, zero `node:*` imports (the hook-bridge rule: no I/O in anything under test):
- `type WakePolicy = "off" | "addressed" | "all"`; `wakePolicyFromEnv(env)` (default `addressed`, warn-once sentinel for invalid), `pollSecsFromEnv(env)` (default 2, floor 0.5, warn-once on invalid).
- `isoCutoffUtc(now: Date, gateMinutes = 30): string` — the Python-format mirror (§1.4); a unit test pins it against the literal `_GATE_WINDOW = timedelta(minutes=30)` line read from the vendored `badger_store.py` (a fork↔canonical-style drift tripwire for the constant).
- `classify(rows, {sid, pid})` → per-row classes (§2.1).
- `decideTick(state, probe, policy): { action: "skip" | "spawn"; reason?; nextState }` — the §1.3 flow minus I/O; watermark equality, identity reset, gate-cutoff comparison, classification and policy all live here.
- `wakeFor(state, cls, policy): { deliverAs, triggerTurn } | null` — the §2 matrix.

**`features/pi/adjustments/adapter/bus-store.ts`** — the I/O port, every function throwing on failure (caller converts):
- `userDbPath(env, cwd)` — §1.4 mirror; `statIdentity(dbPath)` → `{dev, ino} | "missing"`; `openProbeDb(dbPath)` — `node:sqlite` `DatabaseSync` `readOnly:true` + `busy_timeout=250`, feature-detecting the import (failure ⇒ `probeAvailable=false`).
- `maxMessageId(db)`, `cursorFor(db, sid)`, `probeRows(db, {sid, pid, cutoff})` — the §1.2 SQL.
- `resolveProjectMirror(env, cwd)` — `AI_BADGER_PROJECT_ID` override, else the realpath'd nearest-`.ai-badger/project-id` walk with the stop rule (§1.4).

### 3.2 Timer lifecycle wiring (index.ts, inside the default-export factory — F8 sanctioned)

- **Arm** in `pi.on("session_start")`, **only when**: delivery script exists (`existsSync` — the silent-unwired rule; no timer, no DB I/O otherwise), `ctx.mode` is `"tui" | "rpc"` (owner MODES decision; `ExtensionMode = "tui"|"rpc"|"json"|"print"`, types.d.ts:208 — print/json have no persistent idle session, Lane A F7), and `WAKE !== "off"`. `setInterval(tick, pollMs)` + `.unref()` (pi exits via `process.exit` on every path — Lane A F8 — so an unref'd tick never delays exit; RPC's idle loop keeps the process alive so the timer still fires).
- **Disarm** in the existing `session_shutdown` handler (idempotent `clearInterval`, before the router's cursor-cleanup spawn), and clear per-session state.
- **Guard** every timer callback: a `generation` counter incremented at `session_shutdown`; the callback captures it, re-checks it after every `await`, and wraps *everything* in try/catch — an uncaught throw inside a timer callback is fatal (Lane A F7, measured). A `spawnInFlight` boolean prevents tick overlap (a spawn can run 5 s; ticks are 2 s).
- **Wake** uses `pi.sendMessage` (the `ExtensionAPI` surface, as measured in Lane A F4) with the mail document from the spawned script's `additionalContext` (same rendered document the seams inject — one rendering, one schema).
- Compaction and streaming flags: `session_before_compact`/`session_compact`/`session_compact_failed` and `agent_start`/`agent_end` handlers — two boolean writes each, no I/O.

### 3.3 Error taxonomy (per D31; silent-unwired rule preserved)

| failure | behavior |
|---|---|
| delivery script absent | timer not armed; seams keep the existing `existsSync → {kind:"empty"}` silent no-op (index.ts runDelivery) — **unchanged** |
| `node:sqlite` unavailable / probe DB error / stat error | UNKNOWN ⇒ **spawn** (fail-open, D31): the seams and timer behave exactly as today; the prefilter never claims "empty" on error |
| spawn error on the timer path | one **notice-latch**: first failure of a consecutive-failure streak notifies (`ai-badger: message delivery tick failed — …`), continuations are silent, any success or seam firing resets. Prevents 2 s-period notice spam without making failures invisible |
| stale-ctx throw in a timer callback | caught, silent (session is being torn down; a notice has no UI left), never fatal |
| probe says nothing | silent skip — the *normal* path, not an error |
| delivery success via timer | silent inject; no chatter per tick |

---

## 4. Interaction with the existing seams

### 4.1 No double delivery — proof

Every consumption path — timer wake, `before_agent_start`, `context`, any harness's hook — funnels into the *same* script and the *same* `deliver_for_session` transaction: one `BEGIN IMMEDIATE` reads the cursor, reads addressed rows, and upserts the cursor atomically (badger_store.py:1886–1951; Lane B F6/R3: two racing hooks serialize, exactly one injects, both finish at the same cursor). The prefilter opens the DB `readOnly` and executes only SELECTs — it cannot advance, reset, or create cursors, so it cannot open a second delivery path; it only decides whether a spawn happens. A timer spawn racing a seam spawn serializes on the write lock; the loser reads the advanced cursor and returns `{}`. Injection duplication is impossible because each injection's content is the return value of exactly one txn. **Store exactly-once serialises; TS never writes.**

### 4.2 Seam gating — yes, behind the same prefilter, and why that is safe

Both existing seams (`before_agent_start` unconditional live read; per-LLM-call `context` live read — hook-bridge.ts `createDeliveryRouter`) become: `spawn = prefilter says maybe → runDelivery`, wired as a decorator **around** the existing spawn closure so the router and its tests stay untouched. Safe because:
- A prefilter negative is sound w.r.t. "the txn returns mail" (§1.5) — skipping spawns only when the txn would have returned nothing (or only policy-deferred broadcast rows, which remain in the store for the next read).
- A prefilter error is fail-open ⇒ spawn ⇒ today's behavior byte-for-byte.
- It is *strictly better* for the 30-minute gate: today every cursor-less session burns the first-read gate (cursor lands at global `MAX(id)`) on its very first prompt even with an empty inbox (Lane B cause 1). Gated, the burn happens only when in-window, wake-eligible mail actually exists — or at a turn whose probe is positive. The deliverable set is unchanged; the *discarding* of gate-dropped overflow is deferred and can only help.
- `session_shutdown`'s cursor-cleanup spawn stays **ungated** — cleanup is not mail.

### 4.3 Session-id rebind (`/new`, `/resume`, `/fork`, `/clone`)

Lane A F10: the id changes on all four; compaction and `/tree` moves do not. The pi lifecycle already mirrors rebinds as `session_shutdown(reason)` → `session_start` (Lane A F8/F10), so:
- `session_shutdown`: disarm timer, drop the per-session state (watermark/flags — a fresh id must never inherit a skip), generation++, and the *existing* router call drops the store cursor (F12, unchanged).
- `session_start`: re-arm fresh ⇒ first tick always probes (watermark `null`). `/resume` keeps the same id but the cursor was just deleted ⇒ the prefilter takes the cursor-less gate path, mirrored. `/fork`//`clone` mint new ids ⇒ fresh state; the parent's cursor is untouched.
- Compaction: no rebind; the compaction flag handles it (§2.2).
- Empty session id (`resolveSessionId` last resort, hook-bridge.ts): the timer skips silently (nothing is addressable); seam behavior is unchanged (the script refuses with its ValueError → D31 notice, as today).

---

## 5. `send_message.py` validation fix

**Where.** In `main()` after sender identity is established and **before** `open_user()` (cheap-first ordering; the refusal writes nothing, per the `_refused` voice). Fires only when the project half will actually be *stored*: `if args.project_id and not args.session_id` — the stored shape drops the project half when a session id is present (write-normalisation, send_message.py `main`/store `send_message`), so validating it would refuse legitimate 1:1 sends.

**How "resolves" is defined.** The delivery receiver matches rows with `target_project = resolve_project_id(receiver_cwd)` (ADR-0025 walk). The sender cannot enumerate receiver cwds, so "resolves" is defined as: *the value is producible by the same resolver for at least one real project on this machine* — concretely, the target passes iff any of:
1. `badger_store.resolve_project_id(sender_cwd) == target` (self-project broadcasts — the common agent case, zero I/O), or
2. `os.environ.get("AI_BADGER_PROJECT_ID", "").strip() == target` (the resolver's own explicit-override leg — the same env the delivery resolver honors first, badger_store.py:2052–2055), or
3. `target` is the stripped content of some `.ai-badger/project-id` file found by a bounded walk of `badger_store._DEFAULT_HOME` to depth ≤ 4 (pruning `Library`, `node_modules`, `.git`, `.cache`, `*.migrated.json`-style dot-dirs) — the machine-view approximation of the receiver universe, the same method Lane B F3 used to prove msg 10 undeliverable. Scanning the store's `_DEFAULT_HOME` (not `Path.home()`) is deliberate: the suite's `$HOME` redirect composes, and it is the store's own home authority.

Definition 3 is an approximation, stated as such: a scaffolded project outside the scan bound (another volume, a deeper tree) false-refuses. The escape hatch is documentation, not code — no bypass flag in this task; revisit only if a real caller appears.

**Exact error shape** (the one voice, D7): `stderr: send refused: --project-id 'job-search-ai-assistant' does not resolve to any project on this machine — no .ai-badger/project-id carries it (ADR-0025); use a minted id or omit --project-id for a machine broadcast`, exit 1, no row.

**Why existing callers cannot break.**
- Humans/cron passing *valid minted ids*: their id is in the sender's own resolution or in the scan ⇒ unchanged behavior, unchanged exit 0.
- Callers passing the msg-10 pattern (a project *name*): previously a silently-unreceivable row; now a clean refusal with the fix's guidance. That is the intended change; cron sees the existing non-zero+stderr contract it already handles for identity refusals.
- `--session-id` sends and dual-flag sends: untouched (validation skipped when the half is dropped).
- Tests: `tests/test_send_message_skill.py` sends `--project-id proj-target` from unscaffolded cwds (e.g. `test_project_broadcast_send_lands_a_project_row`, :171–183) — those tests get the mechanical update: `_make_project(tmp_path, "proj-target")` beside the redirected user root (the file already has the helper, :108) so leg 3 finds it; the `--session-id`-wins test (:196–210) needs nothing (dropped half). The `badger_store is None` refusal and all identity refusals are untouched.

---

## 6. pbi sync — canonical↔vendored mechanics

**Baseline drift found (heal step 0).** `pi-badger-integration/features/pi/adjustments/adapter/` (the fork, canonical per `publish.ts`'s header) **lacks the entire delivery section** (`runDelivery`, router, `parseDeliveryStdout`, payload map) that this worktree's adapter carries — the worktree is ahead. Today's three copies: fork (behind) ↔ `~/.pi/agent/extensions/ai-badger/` ↔ worktree `features/pi/adjustments/adapter/` (ahead, this task's base). Also verified byte-identical today: `features/common/skills/send-message/scripts/*` ↔ `.ai-badger/skills/send-message/scripts/*` ↔ `features/common/hooks/{message_delivery_hook,badger_store}.py` ↔ `.ai-badger/hooks/*`.

**Direction for this task (inverted, and that is the point to record):** for adapter TS, ai-badger (worktree, ahead) → fork (canonical), *then* fork → user scope; for the Python send-side, `features/common/skills/…` (canonical) → plugin `skills/` → self-scaffold. After the inverted pull, the normal `publish.ts` direction resumes.

**Steps.**
1. **Adapter TS.** Implement `bus-prefilter.ts`, `bus-store.ts`, and the index.ts timer/seam changes **in the worktree first** (tests live here: `features/pi/tests/`, `bun test features/pi`, `bunx tsc --noEmit -p features/pi`). When the code settles: copy `adapter/{index.ts,hook-bridge.ts,bus-prefilter.ts,bus-store.ts}` (byte-identical, package.json unchanged) into `pi-badger-integration/features/pi/adjustments/adapter/`; add both new filenames to `ADAPTER_FILES` in `pi-badger-integration/publish.ts` (exact-set contract: an unlisted canonical file fails `--check` at user scope; `adjust_hooks.py` needs no change — its copy contract ships any `.ts`, adjust_hooks.py:48–53). In the fork: `bun publish.ts` (installs user scope) and `bun publish.ts --ai-badger <worktree path>` to prove the reverse direction is now a no-op diff.
2. **Python send-side.** Edit canonical `features/common/skills/send-message/scripts/send_message.py` (+ the targeting tests above). Then `python3 tooling/sync_plugin_skills.py` (heals the plugin copy `skills/send-message/scripts/send_message.py`; the tree copy includes `scripts/`, excludes only test artefacts — `engine/badger_lib.py` SKILL_EXCLUDE_PATTERNS), and refresh this repo's self-scaffold copy `.ai-badger/skills/send-message/scripts/send_message.py` via den-refresh/re-scaffold (byte-identical requirement). `badger_store.py` and `message_delivery_hook.py` are **untouched** by this task — delivery semantics stay put, so `features/common/hooks/` copies don't move. Other scaffolded projects receive the new send script on their next den-refresh (out of scope; note only).
3. **What `--check` must see.** `python3 tooling/sync_plugin_skills.py --check` → exit 0 (every shipped skill copy, incl. `send-message/scripts/send_message.py`, byte-equal to `features/`). `bun publish.ts --check` → exit 0 with three-way byte-identity: fork canonical ↔ `~/.pi/agent/extensions/ai-badger/` ↔ ai-badger `features/pi/adjustments/adapter/`; exact file set = `{index.ts, hook-bridge.ts, bus-prefilter.ts, bus-store.ts, package.json, .ai-badger-capability-resources-discover}` at both targets (missing/extra/byte-differing all fail; `node_modules` exempt); `git status --porcelain features/pi/adjustments/adapter` in ai-badger shows exactly the two new files + the two edited ones.

**Sequencing risk (Lane A F13).** P4 on `task/aib-bus-followups-independence` rewrites the same delivery section. This worktree already carries the P4-shaped router, so this design slots into it additively (decorator + new files + session events — minimal conflict surface), but the branches must be sequenced: land this task after that branch's adapter section merges, or rebase its file ownership deliberately before editing.

---

## 7. Version / config surface

| variable | status | validation |
|---|---|---|
| `AI_BADGER_PI_BUS_WAKE` | **new** | `off\|addressed\|all`, default `addressed`; any other value ⇒ one warning notice + default; read once per session at arm time (mirrors `AI_BADGER_PI_AWAY`'s read-once contract) |
| `AI_BADGER_PI_BUS_POLL_SECS` | **new** | finite number ≥ 0.5, default `2`; invalid ⇒ one warning notice + default; clamped, never fatal |
| `AI_BADGER_USER_ROOT` | existing (badger_store.py:128) — **mirrored, not new** | TS resolves the probe DB exactly per §1.4; relative values resolve against `ctx.cwd` (the python spawn's cwd) |
| `AI_BADGER_PROJECT_ID` | existing (badger_store.py:2047) — **mirrored, not new** | read by the TS classification mirror and inherited by the spawn, so both sides resolve identically |
| `AI_BADGER_PI_AWAY` | existing | untouched |
| `config.json` | **no change** | nothing new is scaffolded; the two new env vars are read from the environment only |

No new files under `.ai-badger/`, no schema change, no store migration: the bus tables, gate, cap, cursor legs and retention stay exactly as the store defines them (GATE owner decision honored — `_GATE_WINDOW` untouched).

---

## 8. Test plan sketch (what the consolidated plan should carry)

- `features/pi/tests/bus-prefilter.test.ts` (pure): watermark equality/reset, identity change, gate-cutoff mirror pinned to the literal `_GATE_WINDOW` source line, classification, full wake matrix × policies, env parsing, tick-flow branches including error→spawn.
- `features/pi/tests/bus-store.test.ts` (real tmp DBs via `node:sqlite`): cursor-less gate mirror, cursor leg, own-row exclusion, prune interaction, `AI_BADGER_USER_ROOT` relative/absolute, project-id walk incl. symlink + stop-at-nearest, readOnly enforcement (a write attempt must fail).
- `features/pi/tests/adapter-entry.test.ts` additions: arm/disarm per mode (`ctx.mode`), stale-ctx catch (no process death), notice latch, unwired-project silence, seam gating through the decorator.
- Python: updated targeting tests (§5) + one refusal-voice test.

## 9. Residuals accepted (for the ADR's honesty section)

TUI wake itself rests on F6's inference + F11's production shape (no pty probe in this lane); the compaction event-ordering gap (§2.2); the txn→`sendMessage` gap and its nextTurn compensation (§2.3); one delayed wake after a backward clock step (§1.5-6); the scan-bound false-refusal class (§5). None blocks the design; each is named where it is incurred.
