# Test Strategy proposal — aib-pi-message-bus-push-delivery (test-engineer lane)

**Repo:** ai-badger, worktree `.ai-badger/worktrees/aib-pi-message-bus-push-delivery`, branch tip `3fbc6010`.
**Basis:** Lane A `docs/work/2026-09-01-pi-push-api-surface.md` (F1–F14, MEASURED/READ/INFERRED marked), Lane B `docs/work/2026-09-01-pi-bus-delivery-root-cause.md` (F1–F17), owner decisions as given in the task brief. Every existing-suite claim below was verified in this worktree this session; nothing assumed from memory.
**Scope:** plan only. One file written (this one); no code, no test files, no git mutations.

---

## 0. Verified pre-flight facts (re-run as step-0 acceptance before implementing)

| Fact | Evidence |
|---|---|
| pytest runner: `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest -q` from the worktree; **5159 tests collected, collect alone ≈ 63 s** | run this session |
| The four core bus/regression suites are fast: `test_message_delivery_hook.py + test_message_bus_store.py + test_badger_store_vendored.py + test_pi_hook_arm_coverage_contract.py` → **77 passed in 3.09 s** | run this session |
| bun 1.4.0 (features/pi runner) **supports `node:sqlite`** — `DatabaseSync` create/insert/select verified in-process | `bun -e` probe this session; production pi runs Node 26.8.1 (Lane A F1), so the adapter's import target is valid on both runners |
| `bun test features/pi` today: `adapter-entry.test.ts`, `away-mode.test.ts`, `hook-bridge.test.ts`; `adapter-entry.test.ts` loads the real default export against a fake `pi` (registered-handler map + notify sink) | read `features/pi/tests/*.test.ts` |
| Existing adapter delivery seams: `before_agent_start` + `context` (both route as `UserPromptSubmit`) and `session_shutdown` (as `SessionEnd`); no `session_start` registration exists today; `GATE_TIMEOUT_MS = 5000` | `features/pi/adjustments/adapter/index.ts:244–415`, `hook-bridge.ts:274–470` |
| `resolveSessionId(ctx, process.env)` = `ctx.sessionManager.getSessionId()` first, `PI_SESSION_ID` env fallback, empty string last — and Lane A F9 **measured** env ≠ manager id inside one process | `hook-bridge.ts:313–341`; Lane A F9 |
| Store exactly-once authority: `deliver_for_session` runs read + cursor upsert in one `BEGIN IMMEDIATE`; test hooks `AI_BADGER_TEST_HOLD(_ARMED)` exist for deterministic cross-process races | `.ai-badger/hooks/badger_store.py:1886–1951`; `tests/test_message_bus_integration.py:215` |
| Existing exactly-once-across-processes test to extend: `test_two_hook_processes_race_one_unread_message_exactly_once` (tests/test_message_bus_integration.py:215) | read |
| Send-side refusal precedent to model on: `test_ambiguous_project_is_refused_with_candidates`, `test_missing_sender_project_is_refused_no_row_no_traceback`; send-side vendored byte-equality exists at `test_send_message_skill.py:448` | read |
| `record_hook_failure` writes **type + file:line only** ("an exception message can quote scanned input"), rotated at 1 MB; `guarded_main` calls it, prints `{}`, returns 0 | `features/common/hooks/message_delivery_hook.py:145–178` |
| Vendored-copy gates that must stay green: `test_badger_store_vendored.py` (4 landed copies, ADR-0024/D16), `test_message_bus_manifest.py:55–58` (`CANONICAL_HOOK` vs `SKILL_COPY`), `test_send_message_skill.py:448` | read |
| hooks-arm contract test regexes `pi\.on\(...)` out of `adapter/index.ts` and asserts ≥ 1 subscription plus manifest-family correspondence — adding `pi.on("session_start")` does not break it, but it is the file that catches adapter-event drift | `tests/test_pi_hook_arm_coverage_contract.py` |
| Live-probe feasibility: Lane A's F4 wake probe (`sleep 45 | pi --mode rpc --no-session -e <ext>` + python timestamped reader) and F7 stale-ctx probe both ran under `/private/tmp`; `AI_BADGER_USER_ROOT` env-redirect is an established, tested seam (`tests/test_message_bus_integration.py` `USER_ROOT_ENV`) | Lane A F4/F7; read |

**TDD discipline for this task (binding):** every gate below is written RED-first against the untouched tree, the RED output pasted into a red-witness log (pattern: `docs/work/2026-08-31-scaffold-freshness-guard-red-witnesses.md`), and only then implemented. Existing test files are append-only while a phase is being implemented; production code stays untouched during each RED step.

---

## 1. Test list per package

### Package A — adapter push module (TS) · layer: bun unit (`features/pi/tests/`), one live probe gate

New module (plan lane names it; hereafter `bus-push.ts`) beside `hook-bridge.ts`, kept dependency-injectable so bun can drive every decision without a live pi. One structural requirement the plan must honor for this strategy to work: **mode detection, the clock, the sendMessage call, and the spawn are injected**; the module exports pure decision functions for everything else.

| # | Test (RED-first candidate named as the criterion it demands) | Layer | Acceptance gate (and the mutation that must kill it) |
|---|---|---|---|
| A1 | `wake-mode env parses to the owner matrix` — `AI_BADGER_PI_BUS_WAKE` accepts `off\|addressed\|all`, defaults to `addressed`, and an unknown value degrades to the default with a notice | bun unit | absent var → `addressed`; `off` → no poll, no wake; `all` → broadcast mail may wake; `garbage` → default. Mutation: default flipped to `all` → red |
| A2 | `poll-interval env parses with a sane floor` — `AI_BADGER_PI_BUS_POLL_SECS`, default 2; `0`, negative, non-numeric → default (never a hot loop). Fixture realism: assert the non-default value is the one used, not just that the default works | bun unit | set 5 → parsed 5; set `banana`/`0` → 2. Mutation: `Number(x) \|\| 2` replaced by `2` → red on the 5 case |
| A3 | **watermark soundness — false negatives are the only intolerable failure.** One property test walking the intersection matrix of §2 row 6: rows-past-watermark → spawn; no rows → skip; `MAX(id) < watermark` (DB replaced/pruned) → spawn; empty table with stale watermark → spawn; **any sqlite/contained-family error → spawn and never throw out of the poll tick**. The watermark may only advance on a parseable delivery-script stdout (`{}` included), never on spawn error/timeout | bun unit (in-memory `node:sqlite`, measured working under bun 1.4.0) | Mutation: replace the error branch with `return false` (fail closed) → the contained-family case goes red — exactly the production failure shape of Lane B F4's silent mail loss. Mutation: advance watermark on timeout → the re-fire case goes red |
| A4 | `timer arms tui/rpc only` — the arm decision is a pure function of injected mode signals; print/json modes (Lane A F7: `session_start` deferred to stdin EOF there) never arm | bun unit | fake mode=json → no timer; rpc/tui → timer. Mutation: gate deleted → red |
| A5 | `timer lifecycle: armed at session_start, cleared at session_shutdown, idempotent, rebind-safe` — double shutdown harmless; after a `/fork`-style rebind (shutdown → session_start, Lane A F10) the poller polls the **new** session id's watermark, never the old | bun unit (fake timers) | Mutation: clear removed → the post-shutdown fire case (A6's fixture) red; rebind keeps old id → red on the rebind case |
| A6 | `stale-ctx is caught, not fatal` — a `sendMessage` that throws the pi stale-ctx error after disposal is caught, converted to a notice, and the timer callback completes (Lane A F7 measured this as process-fatal uncaught) | bun unit | fake pi whose sendMessage throws the exact stale message → callback resolves, notice emitted, no unhandled rejection. Mutation: try/catch removed → red |
| A7 | `session identity for the push path is the session manager's` — watermark key and wake targeting use `ctx.sessionManager.getSessionId()`; **no `PI_SESSION_ID` env fallback on the wake path** (Lane A F9 measured divergence). The pull seams' existing fallback semantics must NOT change (regression pin §4) | bun unit | fake ctx where manager id ≠ env id → payload keys on manager id. Mutation: fall back to env → red |
| A8 | `wake routing matches the owner matrix` — idle + addressed mail → one `sendMessage(triggerTurn: true)`; streaming + addressed → `deliverAs` steer/followUp, never a second triggerTurn; broadcast mail under `addressed` → **no sendMessage at all** (mail waits for the pull seams); under `all` → broadcast wakes too | bun unit | fake pi recording sendMessage calls. Mutation: broadcast wakes under default → red |
| A9 | `seam + timer cannot double-deliver to the LLM` — pinned at two layers: (i) bun: the timer path's consumption flows through the same router outcome channel so the watermark advances on any parseable outcome; (ii) the real exactly-once authority stays the python txn (D1 below). The TS layer's obligation is only "never advance the watermark on error" + "never suppress a spawn on uncertainty" | bun unit + pytest (D1) | (i) spawn errors → watermark unchanged → red if hoisted; (ii) D1 |

Sequencing: A1/A2 → A3 → A4/A5/A6 → A7 → A8/A9. No mocking needed below A3 (pure functions); A3 mocks only the DB handle; A5–A8 mock pi + spawn. One failing test at a time; RED output pasted per gate.

### Package B — send-side validation + hook-error logging (pytest)

| # | Test | Layer | Acceptance gate |
|---|---|---|---|
| B1 | `send refuses an unresolvable target project id` (Lane B F3's exact shape: the literal name `job-search-ai-assistant` style id that no project-id file carries) — refusal exit, **no row** in the store. Fixture: monkeypatched home (conftest `_home_off_limits` precedent) with planted `.ai-badger/project-id` files | pytest (`tests/test_send_message_skill.py`, append-only) | Mutation: delete the validation → red. Pattern: modeled on `test_ambiguous_project_is_refused_with_candidates` |
| B2 | `send still accepts resolvable and explicit ids` — target id that a planted project-id file carries → row lands; the `AI_BADGER_PROJECT_ID`-style override path (if the plan keeps one for targets) → row lands. Non-degenerate: at least two planted projects, assert the *right* one matched | pytest | Mutation: validation inverted (accepts nothing) → B2 red while B1 stays green — the pair is the pin |
| B3 | `the unresolvable-id refusal names the closest candidates` — refusal message lists resolvable ids (same UX contract as `test_ambiguous_project_is_refused_with_candidates`) and never echoes message content | pytest | Mutation: refusal message emptied → red |
| B4 | **`hook-errors.log gains the exception message without leaking mail content`** (Lane B F4: 44 content-free `OperationalError at badger_store.py:959` lines are undiagnosable; the current docstring's own reason is that a message can quote scanned input). Two tests: (i) a planted `sqlite3.OperationalError("no such table: messages")` now yields the exception text in the log line; (ii) a crafted exception whose `str()` embeds a sentinel taken from the stdin payload → the sentinel must NOT appear in the log or stderr (sanitize by removing payload-derived substrings, or whitelist exception classes whose messages cannot carry content — plan lane picks; the gate is the property, not the mechanism) | pytest (`tests/test_message_delivery_hook.py`, append-only) | (i) mutation: log format reverted to type+location → red; (ii) mutation: raw `str(exc)` written → red on the sentinel case. Both must keep `test_every_termination_path_emits_parseable_json_and_exits_zero` green |
| B5 | `guarded_main still fails open` — the new logging cannot reintroduce a crash path: any exception in the logging itself still prints `{}` and exits 0 (extends the existing termination-path test with a logging-forced-OSError case) | pytest | Mutation: log write made throwing → red |

### Package C — canonical repair + vendor sync (pytest + one scripted deployment check)

Reading note for the consolidator: "pbi canonical repair" is read here as *repair the canonical framework copies (features/common/hooks/, features/common/skills/send-message/scripts/) so every vendored/scaffold/deployed copy — including the pi-badger-integration checkout's scaffold measured md5-identical in Lane B F1 — is refreshed from them*. The test surface below is identical under either reading of "pbi".

| # | Test | Layer | Acceptance gate |
|---|---|---|---|
| C1 | Existing byte-equality gates stay green after the sync (these ARE the vendor-sync gate — no new test needed unless a copy point is added): `test_badger_store_vendored.py` (ADR-0024/D16, 4 landed copies), `test_message_bus_manifest.py` canonical-vs-skill-copy, `test_send_message_skill.py:448` | pytest | Each already fails on skew by design (docstrings name the mutations); step-0 re-run is the acceptance |
| C2 | **Gap found — pin it if the plan touches the scaffold copy:** no test in this repo compares `features/common/hooks/message_delivery_hook.py` to the scaffolded `.ai-badger/hooks/` copy in the same tree (Lane B F1's four-project md5 equality was a *manual* measurement). If the plan repairs canonical files that are also scaffold-delivered, add one manifest-style byte-equality test (edit a landed copy → red) to `test_message_bus_manifest.py` | pytest | New copy-point lands in the manifest-style check; a drifted scaffold copy is red within CI, not only on a human's md5 run |
| C3 | Deployed-copy equality (`~/.pi/agent/extensions/ai-badger/` + the four scaffolded projects) is **not CI-runnable** — it is a scripted post-install check in the integration package (md5/diff against the repaired canonical), the same measurement Lane B F1 used, re-run as the final step of D's live package | live/manual script | md5 equality across all deployed copies, or an explicit den-refresh task recorded as pending |

### Package D — integration

| # | Test | Layer | Acceptance gate |
|---|---|---|---|
| D1 | `timer-spawn and seam-spawn race one unread message exactly once` — extends `test_two_hook_processes_race_one_unread_message_exactly_once` to two *simultaneous* spawns of the delivery hook modeling a timer firing while a seam spawn is in flight (the `AI_BADGER_TEST_HOLD(_ARMED)` hooks make the race deterministic) | pytest, SERIAL, LAST (integration package) | Exactly one child returns the message; both finish at the same cursor. Mutation: hoist the unread read before `BEGIN IMMEDIATE` → red (the existing test's proven mutation) |
| D2 | Wiring sweep: the adapter's new `pi.on("session_start")` registration + push-module wiring are covered by the bun suite (A4–A8); `test_pi_hook_arm_coverage_contract.py` re-run unmodified is the cross-file drift gate | pytest | Stays green; §4 pin |
| D3 | **Live probes — the integration package's merge gate.** L1–L6 below, run as one serial package on this machine, not in CI | live pi | §3 |

---

## 2. Scenario matrix (each row must be covered somewhere; owner column names the owning layer)

| # | Scenario | Owner | Where / how |
|---|---|---|---|
| 1 | Idle-wake in rpc (Lane A F4's measured pattern: zero stdin commands, `agent_start` fires, mail in context) | live probe L1 | §3 probe design |
| 2 | Streaming steer (mail mid-turn queues as steer/followUp; never interrupts; delivered before the run settles — Lane A F5) | live probe L2 + bun A8 (routing decision) | bun pins the routing choice; live probe proves pi honors it |
| 3 | Broadcast does not wake under default `addressed` (mail waits for the next pull seam) | live probe L3 + bun A8 | both halves of the negative |
| 4 | `AI_BADGER_PI_BUS_WAKE=off` → no timer, no spawn, no wake; mail survives for pull | live probe L4 + bun A1 | cursor row absent in seeded DB is the deterministic observable |
| 5 | Poll-interval env parsing (2 s default; garbage/0 → default) | bun A2 (CI) | env parsing is pure |
| 6 | Watermark soundness edges: **prune** (rows deleted under watermark), **DB replaced** (fresh DB, ids restart — `MAX(id) < watermark`), **contained-family/sqlite error** — all three must resolve to "maybe mail → spawn"; never to silence | bun A3 (CI, in-memory DB) | property test; fail-closed mutation is the red witness |
| 7 | Stale-ctx guarded, not crashing (Lane A F7 measured process-fatal shape) | bun A6 (CI) + live probe L5 | both the caught-exception unit and the real exit-code probe |
| 8 | Timer cleared at `session_shutdown`; rebind after fork/new polls the new session id (Lane A F10) | bun A5 (CI, fake timers) + L5 exit-clean assertion | |
| 9 | Seam + timer no-double-delivery (exactly-once) — python txn sole owner; TS watermark advisory, never advances on error | pytest D1 (CI, serial) + bun A9(i) | process-level race, deterministic via store hold hooks |
| 10 | Send refuses unresolvable project id (Lane B F3, cause #3) | pytest B1/B3 (CI) | |
| 11 | Send still accepts resolvable ids + explicit ids | pytest B2 (CI) | |
| 12 | Hook-error log gains the exception message without leaking mail content (Lane B F4, cause #5) | pytest B4/B5 (CI) | two-direction property (diagnosable AND non-leaking) |
| 13 | Vendored byte-equality after the repair (ADR-0024) | pytest C1/C2 (CI) + C3 scripted check | |
| 14 | Session-id authority: push path keys on `getSessionId()`, not `PI_SESSION_ID` (Lane A F9 measured divergence) | bun A7 (CI) | |

**Coverage claim to enforce at plan-review:** rows 1–4 and 7 are the ones that can only be *proven* live; rows 5, 6, 8–14 are fully CI-provable and must not be deferred to live probes.

---

## 3. CI vs live — which gates the merge

**CI (must be green before any live probe runs):** `python3 -m pytest -q` (repo .venv), `bun test features/pi`, `bunx tsc --noEmit -p features/pi`, `python3 -m pylint` (non-test py), `python3 tooling/index_build.py --check` — the config.json commands. All of §2 rows 5–6, 8–14 gate here. Cost: suite ≈ minutes on this machine (collect alone 63 s); the new bun + pytest tests add seconds, not minutes.

**Live probes — the integration package's merge gate.** Reuse Lane A's rpc-probe pattern verbatim: a throwaway TS probe extension is NOT needed — the real adapter from this worktree is loaded via `-e <worktree>/features/pi/adjustments/adapter/index.ts`, driven by a python timestamped stdin-writer/stdout-reader, with the user store redirected via `AI_BADGER_USER_ROOT` to a seeded temp DB (the same env-redirect the pytest fixtures use) so the real `~/.ai-badger/ai-badger.db` is never touched. Probes run serially, one pi spawn each.

| Probe | Design | Mandatory? | Cost / flakiness controls |
|---|---|---|---|
| **L1 idle-wake (rpc)** | Seed temp DB with a 1:1 message for the session (session id discovered from the probe's first logged `session_info`/`session_start` event, or the probe writes its `getSessionId()` to a file the sender polls). Launch `pi --mode rpc --no-session -e <adapter>`; no stdin commands after startup. PASS = `agent_start` (with the custom mail message in context) within `poll + spawn + model` budget, with **zero prompt commands written to stdin** | **Yes — this is the feature** | 60 s ceiling; assert on event order (agent_start with no prompt), never wall-clock; seeded DB env-redirect; one retry on infrastructure failure (spawn failure ≠ feature failure) |
| **L2 streaming steer** | Start a turn whose duration is deterministic (prompt the model to call a sleeping tool). Send a message mid-stream. PASS = message enters context before the run settles (steer semantics), and no second concurrent agent loop starts | Yes | The sleeping tool makes the window wide (≥ 10 s); observation window generous; assertion on ordering not timing |
| **L3 broadcast-not-waking** | `AI_BADGER_PI_BUS_WAKE=addressed` (default); seed only a broadcast; wait 3 poll intervals. PASS = no `agent_start`, no cursor movement from the timer; then a stdin prompt arrives → broadcast delivered via the existing pull seam | Yes | Negative probe: absence-of-event assertions need the full window, hence bounded by design |
| **L4 wake=off** | `AI_BADGER_PI_BUS_WAKE=off`; seed mail; wait window. PASS = no spawn (no cursor row in the seeded DB), no wake, mail survives | Yes | Cursor absence in the redirected DB is deterministic |
| **L5 shutdown/timer-clear** | rpc session with mail seeded but wake blocked; close stdin promptly (shutdown before the timer fires, the Lane A F7 fatal shape). PASS = process exits **without** the Node uncaught-exception footer, exit code clean, ≤ 1 delivery spawn total | Yes — this is the regression Lane A measured as fatal | Same probe shell as L1; deterministic |
| **L6 TUI wake (pty)** | `script -q /dev/null pi -e <adapter>` + seeded send; PASS = wake observed in the pty transcript. Upgrades Lane A F6 from INFERRED to MEASURED | **Conditional** — required if the plan arms timers in TUI (owner decision says tui/rpc). Abort criteria: if the pty harness proves nondeterministic in 2 attempts, downgrade to documented residual (§5) with owner acceptance | pty automation is the flakiest surface in this whole strategy; timebox it |

**Merge gate:** CI green **and** L1, L2, L3, L4, L5 green. L6 per its conditional rule. C3's deployed-copy check is a post-merge den-refresh concern, not a merge gate (recorded, not blocking).

---

## 4. Regression risks to pin (must-not-change list)

| Risk | Pin | Where |
|---|---|---|
| **P4's router behavior must not change semantics.** The push work touches the same delivery section of `adapter/index.ts` that the sibling P4 plan (bus-followups-independence) reworks — sequence per Lane A F13. Until then: `before_agent_start` injects via the result-message seam, `context` appends mail between LLM calls, `session_shutdown` is cursor cleanup — the existing bun delivery tests must pass **unmodified** (append-only rule), and the delivery-script routing (`UserPromptSubmit`/`SessionEnd` vocabulary, `PI_DELIVERY_EVENT_MAP`) must not drift | hook-bridge.test.ts (existing, unmodified) + the arm-contract test |
| **`test_pi_hook_arm_coverage_contract.py` stays green** — it regexes `pi.on(...)` out of `index.ts`; adding `session_start` is compatible, but its ≥1-subscription and manifest-family checks are the drift gate if the push module restructures the adapter | re-run per phase |
| **ADR-0024 vendored byte-equality stays green** after the C sync — `test_badger_store_vendored.py`'s 4 landed copies + `test_message_bus_manifest.py` + `test_send_message_skill.py:448` | CI, every phase |
| **Pull-seam `resolveSessionId` fallback must not change** — A7 tightens only the push path; the existing env-fallback semantics for the pull seams are pinned by existing hook-bridge tests | bun suite |
| **The 30-minute first-read gate is unchanged** (owner decision) — no new test needed; the existing gate tests (`test_session_start_injects_recent_history_and_gates_the_ancient` etc.) are the pin and must stay green untouched | pytest |
| **Fail-open discipline** — delivery failures never break the turn (D31); the push module's timer callback inherits it (A3/A6 pins) | bun A3/A6 |

---

## 5. What will NOT be tested (residual risk, with the named accepter)

| Not tested | Why | Residual accepted by |
|---|---|---|
| TUI wake (L6) **if** the pty probe proves flaky in 2 attempts | pty automation flakiness; the code path is shared with the measured rpc wake (Lane A F4/F6) | **Owner**, at plan consolidation — recorded as a documented residual, not silently dropped |
| Windows parity | ADR-0024 already excludes Windows-specific tests by owner decision; Lane A ran macOS-only | Owner (precedent: ADR-0024 scope) |
| Wake arriving during auto-compaction (Lane A F14's unchecked race — `sendCustomMessage` bypasses `prompt()`'s compaction guard) | No deterministic way found to force compaction in a probe without mocking pi internals; if the plan lane adds a design note, a live probe *may* be added, not gated | Owner; the stale-ctx guard (A6) bounds the blast radius |
| Two `triggerTurn` sends in quick succession while the first run settles (Lane A F14 #2) | pi-internal queue semantics, not our code; observed once live in L1's retry window if cheap | Owner |
| json-mode long-lived stdin sessions (Lane A still-open) | Owner decision confines the timer to tui/rpc; json print-mode is prompt-bounded by design | Owner |
| Per-LLM-call/timer poll cost on the real user DB; the 5 s/5 s spawn-vs-busy-timeout race (Lane B F14) | Performance envelope, no gate exists; the TS prefilter exists precisely to avoid per-call spawns — a perf note in the ADR, not a test | Owner (noted in ADR-0026) |
| A delivery-audit table (Lane B F15) | Out of scope unless the plan adds one; if added, it earns its own tests then | Owner |
| Cross-machine / cross-fleet delivery semantics | The unresolvable-id refusal (B1) is precisely the machine-local contract; cross-machine is out of scope | Owner |
| Real-DB performance of the `node:sqlite` prefilter against the 3.4 MB user DB | The prefilter is one indexed `MAX(id)`-class query per tick; measured cost asserted only if the plan sets a budget | Owner |

---

## 6. The five tests I would run first (RED-first order)

1. **B1** — `send refuses an unresolvable target project id` (pytest; fastest RED, pins Lane B cause #3, zero new machinery).
2. **B4** — `hook-errors.log gains the exception message without leaking mail content` (pytest; pins cause #5's diagnosability with the leak guard in the same pair).
3. **A1+A2** — wake-mode and poll-interval env parsing (bun; the push module's decision core, no DB needed).
4. **A3** — watermark soundness property test (the false-negative-is-intolerable gate; in-memory `node:sqlite`, measured working under bun).
5. **A5+A6** — timer lifecycle: clear at `session_shutdown` + stale-ctx caught (pins the one process-fatal shape Lane A measured).

Then D1 (process-race exactly-once), then the live package L1–L5.

---

## 7. Proposal summary for the consolidator

- **Open decisions this lane flags for the plan rev:** (1) the mode-detection mechanism for "tui/rpc only" must be injectable for bun tests — plan lane names it; (2) whether the wake path uses the strict `getSessionId()`-only identity (A7) — recommended yes, but it diverges from the pull seams' env fallback and should be a recorded decision; (3) whether Package C's "pbi" scope includes extending `VENDORED_PATHS`-style manifests to the delivery hook's scaffold copies (C2) — recommended yes, one test; (4) whether `wake=off` also disables the poll timer entirely (assumed yes here; A1's gate text assumes it).
- **Merge gate summary:** CI (pytest + bun + tsc + pylint + index_build) green, every new gate RED-pasted first, then live package L1–L5 green on this machine. L6 conditional. Regression pins §4 re-run at every phase boundary.
