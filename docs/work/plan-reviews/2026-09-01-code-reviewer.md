# Adversarial plan review — aib-pi-message-bus-push-delivery (rev 1) — code-reviewer lane

**Date:** 2026-09-01 · **Scope:** correctness only — C1–C8 rulings, P2 store changes, P3 adapter state machine, P0/P5 process. Read-only lane; this file is the only artifact.
**Method:** two passes (unaided read for logic; mechanical scan for silent-failure shapes) against the plan, the three lane proposals, both evidence records, the worktree adapter (`index.ts`, `hook-bridge.ts`), and the vendored store/hook scripts. pi claims re-verified against installed 0.84.4 source.

---

## MUST findings (plan must not proceed as written)

### M1 — C1's advance rule treats the hook's failure-shaped `{}` as a clean empty read and silences the poller

The consolidated advance rule (C1 + test-engineer A3/A9: "the watermark may only advance on a parseable delivery-script stdout (`{}` included)") is unsound, because the delivery hook's fail-open net produces a **parseable `{}` with exit 0 on internal failure** — indistinguishable on stdout from a genuine empty inbox:

- `message_delivery_hook.py:165–180` (`guarded_main`): any exception from `main()` → `record_hook_failure(...)` → `print("{}")` → exit 0.
- Failure sources on this exact path: `badger_store.open_user()` raising (connect/PRAGMA/schema on a locked or corrupt DB — the same class as Lane B F4's **44 real `OperationalError` failures today**) and `deliver_for_session` raising mid-txn (`badger_store.py:1886–1951`). In both, the cursor has **not** moved and the mail **is still there**.
- Under C1, the tick then advances the watermark to tick-time `MAX(id)` — which includes the undelivered rows' ids. Every subsequent tick sees exact `MAX(id)` equality → **skip**. The mail sits until *any unrelated send anywhere on the machine* moves `MAX(id)`. For an idle session this reintroduces, silently, exactly the "delayed until other traffic" failure this task exists to fix — and it is *worse than today's seams*, which retry unconditionally on every turn. The notice-latch never fires (the spawn did not error; `parseDeliveryStdout("{}")` is `kind:"empty"`), so nothing is observable except the stall.

**Fix:** P2 must make the failure path distinguishable on the wire: on the `guarded_main` failure path, print an additive marker (e.g. `{"hookSpecificOutput": {"aiBadgerBus": {"error": true}}}` — keep it inside `hookSpecificOutput`; hosts act only on documented keys and ignore unknown ones). Clean-empty stays `{}`. P3's rule becomes: advance the watermark only on parseable outcomes **without** the failure marker; a failure-marked outcome leaves the watermark stale → next tick re-spawns (retry-until-success, notice-latched per the existing taxonomy). AC additions: failure-marked `{}` does not advance the watermark; the "empty `{}` response stays `{}`" AC is reworded to "clean-empty stays `{}`".

### M2 — C1's equality-skip strands already-addressed mail when deliverability changes without a new row (D7 leg-scoped cursor × mid-session project resolution change)

The C1 soundness claim — "mail-for-me implies a row; a row moves MAX(id)" — is false for the store's actual cursor semantics. Deliverability is not a function of rows alone:

- Cursor-less first read with an unresolved project (D7): the txn delivers the 1:1 leg only and lands the cursor at the **1:1-leg max** `M1`, not global MAX (`badger_store.py:1927–1933`). Project/broadcast rows with `M1 < id ≤ MAX(id)` remain parked above the cursor, deliverable **as soon as the project resolves**.
- Project resolution is re-evaluated **per read** (`message_delivery_hook.py:70–78` → `resolve_project_id`, `badger_store.py:2030–2043`), and it can change mid-session: (a) the den-refresh backfill this very plan schedules *creates* `.ai-badger/project-id` files under live sessions; (b) `_read_project_id_file` returns `None` on a transient `OSError` (`:2036–2038`) and heals on the next read.
- After such a change the txn **would** deliver the parked rows, but `MAX(id)` is unchanged → exact equality → the timer *and* the now-prefilter-gated seams skip until the next machine-wide send. Today's ungated seams retry the resolution on every LLM call — gating **removes an existing recovery path** (a regression vs the status quo for this scenario, not just an accepted imperfection).

**Fix (cheap, keeps C1's no-mirror stance):** add a **max-skip-staleness** to the tick decision: on exact equality, skip only if the last spawn (any outcome) is younger than N seconds (30–60); otherwise spawn. Bounds the strand to N at a worst case of ~1 spawn/min/session — negligible against the per-LLM-call spawns being removed. Do **not** fix via summary flags ("don't advance when degraded"): un-scaffolded cwds are *permanently* D7-degraded, so that reading degenerates to unconditional ticking — the prefilter would be void exactly where mail is commonest. If the owner prefers, the alternative is demoting the claim: ADR-0026 must then state the strand as an accepted residual instead of asserting soundness.

### M3 — The watermark's advance *value* is unpinned; the natural reading (fresh post-spawn MAX re-read) has a missed-row race

C1 specifies *when* the watermark may advance but not *to what*. The post-spawn re-read reading is racy: senders block on the write lock while the delivery txn holds `BEGIN IMMEDIATE` (busy_timeout 5000), then commit in the window between the txn's commit and a post-spawn `MAX(id)` refresh. A fresh re-read there **includes** the new row → watermark equals it → equality-skip strands a row that is `id > cursor` and will never be re-read by any txn. Window is milliseconds but correlates with contention (long txns are exactly what blocks senders).

**Fix:** pin in P3: the watermark advances to the **tick-time `MAX(id)` captured before the spawn**, never re-read afterwards. Soundness then holds: any row committed after the tick's read has `id > watermark` → next tick's `MAX(id)` differs → spawn. Cost: one harmless empty spawn per post-tick send (over-approximation, the accepted direction).

---

## SHOULD findings

### S1 — P2.2's motivating scenario is impossible under the current schema; C4/P4 would record a false "latent store bug" in the ADR

`messages.id` is `INTEGER PRIMARY KEY AUTOINCREMENT` (`badger_store.py:57–58`, all vendored copies byte-equal). SQLite never reuses rowids for an AUTOINCREMENT table within the file's lifetime — `sqlite_sequence` survives full `DELETE`s — so "rowid reuse after a full prune + tick-refreshed cursor ts → `id > cursor` silently skips reused ids" (C4, architect P2.2) **cannot occur**: after a full prune the next id continues *above* every existing cursor and `id > cursor` keeps delivering. `cursor_id > COALESCE(MAX(id),0)` is reachable only transiently (emptied table before the next insert) or by DB replacement/surgery — and in both the guard changes no delivery outcome (post-restore AUTOINCREMENT ids still sit above restored cursors). The guard itself is harmless, but: (a) C4 justifies store surgery on the four-harness exactly-once txn with a false premise; (b) the "red-first pin" can only pass by constructing `cursor > MAX` surgically — a test that documents a scenario nature cannot produce; (c) ADR-0026 would enshrine "a latent store bug this task retires" as a false fact. **Fix:** correct the rationale in C4/P4; either drop P2.2 (smaller diff on the shared txn) or keep it as explicitly-cheap insurance with the honest test. If kept, also pin the reset's semantics: "treat the session as cursor-less **for this read** (30-min gate + 16-cap + leg-scoped landing re-apply)" — the one-line "reset cursor to 0" read as a plain reset followed by the existing-cursor path would re-read the whole table uncapped and duplicate-inject old mail.

### S2 — Missing-summary fallback unpinned (user-scope adapter vs per-project hook copies)

The adapter is user-scope (one copy, updated by P0/P3); the delivery hook is per-project vendored (4+ scaffolded copies refreshed only by den-refresh — P2 re-syncs only ai-badger's own copies). On un-refreshed projects the timer's spawns hit an **old hook that never emits `aiBadgerBus`**, and the wake routing has no summary. The plan never defines this fallback. **Fix:** pin "additionalContext present + summary absent ⇒ treat as addressed (`followUp` + `triggerTurn:true`)" — fail-open toward waking, which never loses mail and makes the headline feature work machine-wide on day one; `{}` + absent ⇒ empty. Record the den-refresh coordination for hook copies alongside the existing P5 project-id backfill note.

### S3 — Flag lattice has no cross-check and no stuck-flag recovery; a missed event pair silently degrades or kills push

The consolidated P3 trusts the `agent_start`/`agent_end` and `session_before_compact`/`session_compact(_failed)` pairs. A missed `agent_end` (abort path) leaves `streaming=true`; a missed compact-close leaves `compacting=true` → ticks defer **forever** (push silently dead for the process, seams gated too if the compacting defer lives in the shared prefilter). And a stuck streaming flag on an actually-idle session routes addressed mail to `{deliverAs:"steer"}` with no `triggerTurn` → `sendCustomMessage` falls to `_appendCustomMessage` (`agent-session.js:1124–1131`) — appended, **no wake**: the parked-mail hole C3 closed reopens silently. **Fix:** routing consults `ctx.isIdle()` (authoritative, `types.d.ts:232`; the api-engineer lane designed exactly this cross-check and consolidation dropped it) with the flags as hints; timestamp the compacting flag and expire it (e.g. 10 min) or clear it on `agent_start`.

### S4 — P0 heals pbi, but no package step re-syncs pbi after P3 — the merge gate cannot pass as scheduled

P0 copies the 0.157.2 state into pbi; P3 then edits the adapter **only in the ai-badger worktree**. At merge, `bun publish.ts --check` (pbi canonical ↔ user scope ↔ ai-badger vendored, exact-set `ADAPTER_FILES`, verified at `pi-badger-integration/publish.ts:59–64` = `{index.ts, hook-bridge.ts, package.json, .ai-badger-capability-resources-discover}`) fails until pbi receives the P3 state, the two new `ADAPTER_FILES` entries, and mirrored-test updates. A gate without a step = an improvised rescue at merge time. **Fix:** give P3 (or P5) the explicit final reverse-sync step (copy settled adapter incl. the two new files → pbi; append both names to `ADAPTER_FILES`; update pbi mirrored tests; run `--check`).

### S5 — The timer-spawn timeout budget was dropped in consolidation

The architect's R5 mitigation — timer spawns are off the turn's critical path, so they get a budget **larger than `GATE_TIMEOUT_MS=5000`**, which races the store's `busy_timeout=5000` + 4 WAL retries (Lane B F14 / root cause 7) — is absent from the consolidated P3, whose timer path reuses `runDelivery`'s 5 s spawn (`index.ts:18, 262–266`). Under fan-out the timer spawn dies mid-txn. **Fix:** restore the larger timer-spawn budget in P3 text; seam spawns keep 5 s (they gate a turn).

### S6 — L3 is trivially green if the timer is dead; L5's spawn count has no named observation mechanism

L3's pass criteria (no `agent_start`, no cursor movement) are equally satisfied by "timer never armed / prefilter never spawns" — the probe cannot distinguish correct-skipping from broken-arming. L5 asserts "≤ 1 delivery spawn total" but cursor-row deltas are unobservable post-`delete_cursor`, and no counting mechanism is named. **Fix:** L3 gains an in-probe positive control (after the broadcast window, send one *addressed* message to the same session and assert the wake + cursor movement — one probe then proves armed-and-skipping). L5 names its mechanism (e.g. substitute a counting wrapper for the project hook script in the temp cwd — the adapter spawns `<cwd>/.ai-badger/hooks/message_delivery_hook.py`, so the substitution is trivial).

---

## NOTE findings

### N1 — C3 verified sound against pi 0.84.4 source (the task's named falsification target fails to falsify)

`sendCustomMessage` (`agent-session.js:1099–1124`): idle + `{deliverAs:"steer", triggerTurn:false}` — not `nextTurn`; branch 2 needs `isStreaming`; branch 3 needs truthy `triggerTurn`; branch 4 needs `isStreaming` — falls to the final else → `_appendCustomMessage` (`:1126–1131`): pushed to `agent.state.messages` (LLM context next turn), persisted via `sessionManager.appendCustomMessageEntry` (display honored), `message_start`/`message_end` emitted. **No throw.** The "deliverAs required while streaming" throw lives in `prompt()` (`:861–862`) and `sendUserMessage` (`:1152–1187`) — surfaces `sendCustomMessage` never routes through. The call is correct as written. Residual (already accepted in C3) confirmed: consume-then-lose if the session dies before its next turn.

### N2 — Containment refusals cannot produce the task's "`{}` from a CONTAINED-family refusal" scenario

`messages`/`cursors` are not containment families at all (`USER_FAMILIES` holds only `awm_state`/`awm_decisions`; born-in-SQLite, no legacy path — `badger_store.py:550+`; `_check_resurrections` skips `legacy_path IS NULL`). `_refuse_contained_table` can never fire on the delivery path. The failure-shaped-`{}` hazard is real but comes from store-open/in-txn errors — see M1, which owns it.

### N3 — Same-inode restore with coincidentally-equal MAX(id) can equality-skip

The architect's "any data change moves MAX(id) off the watermark" is false for an in-place restore (`cp backup.db live.db` keeps dev/ino) whose restored content shares the watermark's `MAX(id)` but differs elsewhere (e.g. a lower cursor → rows above it undelivered, txn would deliver, prefilter skips). Cheap hardening: fold `COUNT(*)` into the tick fingerprint (same query, one more aggregate) — a restore matching both COUNT and MAX on the same inode is vanishingly improbable. With AUTOINCREMENT (S1) there is no prune-side wrap, so restore is the *only* remaining same-MAX channel; worth one ADR sentence either way.

### N4 — Pin the seam decorator's state ownership and the wake=off seam-gating question

(a) The plan says the seams are gated "by the same prefilter" but never states whether a seam firing **participates in the same watermark advance rule**. If it advances (A9(i) implies it does), M1's marker rule must apply there too, and the advance value pin (M3) covers it; if it doesn't, seam spawns leave the watermark stale — harmless over-approximation. Pin one. (b) C7 says wake=off leaves "seams carry everything as today" while P3 gates the seams unconditionally of wake mode — the two readings differ observably (spawn counts under off). Pin: gating is spawn economy, independent of wake → stays on under `off` (recommended; it also answers Lane A's unmeasured per-LLM-call cost), and C7's wording is amended.

### N5 — Small bounded races worth one ADR sentence each

(i) An in-flight tick's spawn across `session_shutdown` serializes after the cleanup's `delete_cursor` and **recreates the cursor row** for the dead session (4-day TTL litter); the post-spawn generation check (spec'd) bounds the send side, not the spawn side. (ii) The recreated read takes the *gate* path (cursor-less), so in-flight mail older than 30 min is gate-dropped on that interleave — same shape as today's fresh-session first read. (iii) bun tests: the AC "existing bun delivery tests pass UNMODIFIED" now runs the real adapter, whose prefilter stats/opens the **real** user DB per arm/tick — P3 must wire the injected I/O port (C5) in tests so the suite never touches `~/.ai-badger/ai-badger.db` nor spawns the real hook.

### N6 — P2 summary shape: verified safe by construction, pin the one collision class

Riding inside `hookSpecificOutput` (not top-level) is the right call: Claude Code acts only on documented `hookSpecificOutput` keys for UserPromptSubmit and ignores unknown ones; copilot/hermes read named keys only. The one class to pin with a test: the marker/summary must never occupy a key the hosts act on (`decision`, `continue`, `stopReason`, `suppressOutput`) — a one-line assertion in `test_message_delivery_hook.py`.

---

## Verdict

**REQUEST-CHANGES.**

C1 is the load-bearing synthesis no lane designed, and two of its three rules are unsound as written: the advance rule conflates the hook's fail-open `{}` with a clean read (M1 — reintroduces silent mail stalls, worse than the seams it replaces), and the equality-skip strands deliverable mail when deliverability changes without a new row (M2 — a genuine under-approximation). The advance *value* is unpinned and one natural reading has a missed-row race (M3). All three are fixable with small, plan-level amendments (additive failure marker in P2; tick-time value pin + max-skip-staleness in P3); with those landed, plus the S1 rationale correction before ADR-0026 records a false bug, the design is sound — C3's injection call verifies clean against pi 0.84.4 source, the store exactly-once ownership survives the prefilter, and the seam-gating decorator inherits soundness from a repaired C1.
