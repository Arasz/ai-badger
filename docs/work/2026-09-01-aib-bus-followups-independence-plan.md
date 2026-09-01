# Plan — aib-bus-followups-independence (rev 2, post plan-review)

**Date:** 2026-09-01 · **Effort:** high · **PR:** #463 (draft) · **Branch:** `task/aib-bus-followups-independence`
**Reviews:** api-engineer (d-190), qa (d-189), code-reviewer (d-188) — all **DISPATCH-READY-WITH-CHANGES**; every MUST below is folded. Appendices (plan-architect/-tests/-harness) are the authoring record; **this file governs** where they contradict it (walk policy, arm-env name, containment wording).
**Owner rulings (confirmed 2026-09-01):** dedicated `.ai-badger/project-id` file · uuid4 minted in `scaffold.py run()` pre-config-write · id-absent → None (fail-open) · **nearest `.ai-badger` wins**, `ProjectIdAmbiguous` retires.
**Gates:** `python3 -m pytest -q` · `python3 tooling/index_build.py --check` · `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')` · `bun test features/pi && bun test tests/js/` · `python3 tooling/sync_plugin_skills.py --check`.

## Re-land procedure (every store commit — P1, P2, P3)

Byte-copy canonical `engine/badger_store.py` over all `VENDORED_PATHS` destinations (16), run `python3 tooling/sync_plugin_skills.py` (skills/ mirrors), then hand-copy the **11 ungated `.ai-badger/` mirror copies** (engine, hooks, skills/*/scripts — no gate covers these; use a checklist, api-review S2); gate = `tests/test_badger_store_vendored.py` report `[]` + `sync_plugin_skills.py --check`. Code + copies + amended tests in ONE commit (c7424c6f precedent).

## P1 — Store containment + doctor (M2) — serial store lane, 1st — subagent (test-engineer)

`_open` records **per-family** unavailable state (NOT per-table — two families share table `"statusline"`, tracker_lib.py:425-433; containment keyed by family keeps the delegate neighbour usable, review M2); accessors of a contained family raise the resurrection error (upgrade pointer). **Refuse-on-access for every non-store kind, including file-set kv_glob legacy reads** (`_legacy_rows` :889 raises today — "skip" would silently downgrade a raising path, reviewer M1). Neighbours exactly as today. New `doctor` verb in `badger_store.py main()` (`--user` default, `--project PATH`), read-only `prune --status` pattern; `doctor --status` names family/stamp/mtime **+ a content diff for map families** (the actual incident shape: newer file vs DB rows, reviewer S3); `doctor --repair` re-imports additive kinds idempotently, inspect-only for map/kvdoc/awm. den-refresh runs `doctor --status` as a pre-flight — the wiring lands IN P1, not deferred (reviewer S4).

Red-first: rename both fail-closed tests (session_families:597-619, test_badger_store.py:347-361) to contained-open shapes; tier-1 parametrized neighbour sweep **derived from `badger_store.FAMILIES` + `badger_store.USER_FAMILIES` + `tracker_lib._task_families()`, skipping `legacy_path is None` store families (messages/cursors) — ~21 families** (qa M3; note `_task_families` lives in tracker_lib, not badger_store); tier-2 per-kind-group tests (map, kvdoc/awm, jsonl/recent, tasks/usage/sessions, file-set ×5) each with a neighbour observable; **NEW: `test_contained_statusline_sibling_keeps_its_delegate_neighbour`** (contained statusline family ⇒ the other statusline family still reads/writes, reviewer M2); untouched pins: task_family:411-422, test_p4_integration.py:310-345.

ACs: per-kind-group contained-open + refuse-on-read + refuse-on-write + neighbour-normal; statusline sibling pair asserted; `doctor --status` non-mutating with map-family diff; `doctor --repair` additive re-import; vendored report empty.
Gate: full pytest + pylint + vendored gate + `sync_plugin_skills.py --check`.

## P2 — Resolver independence + mint + backfill + L1 (D2/L1) — serial store lane, 2nd — subagent (test-engineer)

Resolver walks up to the nearest `.ai-badger`, reads `.ai-badger/project-id`; `AI_BADGER_PROJECT_ID` wins; id absent → None; **`ProjectIdAmbiguous` retires — and its callers are part of this package** (reviewer M3): `features/common/hooks/message_delivery_hook.py:76-83`, `features/common/skills/send-message/scripts/message_delivery_hook.py` (hook copy), `features/common/skills/send-message/scripts/send_message.py:148-151` — ambiguity branches become nearest-wins/None semantics. Scaffold mints uuid4 pre-config-write (scaffold.py:740-742, both copies); den-refresh backfills between `check_prerequisites` (:191-199) and `re_scaffold` (:213-230). L1: `row is None` + `project_id is None` branch lands cursor at max-over-delivered-legs (:1766-1773); global MAX(id) when all legs ran.

**Full conversion inventory — scoped by fixture symbol, every bank site** (api M1 + qa M1 + reviewer M4): `tests/test_project_registry.py` (tests 1-10 convert; 11-13 delete with the surface); `tests/test_send_message_skill.py:382`; `tests/test_message_bus_manifest.py` (:33, :68, :140-150, :405-417); `tests/test_message_bus_hermes.py` (:345 mechanism → "no `.ai-badger` found upward ⇒ None"; **:330 third bank test**; **:362 → nearest-wins nested mechanism** — the ambiguity scenario it pinned no longer exists, reviewer M5); `tests/test_message_delivery_hook.py` (`_register_bank` :106-115 + **11 call sites**); **`tests/test_message_bus_integration.py` `_register_bank` (:97) incl. the flagship exactly-once E2E — its tmp repo gets a scaffolded `.ai-badger/project-id`** (resolves "bus-proj", :196/:221/:243); **`tests/js/pi_message_bus_adapter.test.mjs` E2E fixtures get a project-id file** (the real-script legs resolve cwd). The Rule 8 owner-map repoint (integration sweep :625-632) lands IN P2's commit.

Red-first: R1a/R1b/R1c — **R1a seeds the 1:1 BEFORE the broadcast** (seeding-order trap: broadcast-after-1:1 is the only order that proves the cursor didn't sweep it; a broadcast seeded first would sit below any MAX landing, reviewer S1); R3a nearest-wins (worktree case); R3c id-absent; R3d sibling walk mutation-killer; R3b dropped; override-wins via throwing-walker fake.
ACs: R1a green with cursor below the broadcast id; overflow :545-559 + gate-once :492-510 green; nearest-wins/sibling/id-absent/override green; mint preserved across re-scaffold; backfill resolves; raccoon symbols gone incl. all callers compiling (assertion test); E2E race green on the new id fixture.
Gate: full pytest + vendored gate + `sync_plugin_skills.py --check` + `bun test tests/js/pi_message_bus_adapter.test.mjs`.

## P3 — Arm-env hold gate (D3) — serial store lane, 3rd — in-orchestrator (store commit: full re-land ceremony)

`_hold_at` env branch gated on **`AI_BADGER_TEST_HOLD_ARMED`**; `_TEST_HOLDS` ungated; seam-prefix check survives. `_child_env` sets both; store arming test :852-865 sets both; strip lists gain the arm env: integration :75/:194, manifest :83/:411, hook :85/:671; NEW leak witness `test_a_leaked_hold_env_without_the_arm_env_does_not_park`; E2E parks and releases through the vendored copy; shipped-pair identity :419 green.
Gate: bus-store + integration suites, then full pytest.

## P4 — pi defer (D4) — subagent (api-engineer) — **dispatch AFTER the store lane** (order adjustment: P2 converts the JS E2E fixtures P4's amendments live in — starting P4 pre-P2 would double-edit that file)

Remove `sessionStart` from the router interface entirely (single caller, compile-enforced); delete `pendingStart`, held-consume branch, `pi.on("session_start")` wiring, `"session_start"` from the event map; `beforeAgentStart` = one unconditional `liveTurn`; docstring rewritten; absent-script silent-empty + away/payload gates preserved.
Red-first: five adapter amendments (:97/:137/:193/:266/:293) + NEW never-turned-session-consumes-nothing (no spawn, no cursor row, mail intact); `test_pi_hook_arm_coverage_contract.py` :237/:262 → two-event shape, :90-236 untouched.
Gate: `bun test tests/js/pi_message_bus_adapter.test.mjs && bun test features/pi && bunx tsc --noEmit -p features/pi` + pytest pi/integration files.

## P5 — Hermes defer (D4) — subagent (test-engineer) — **dispatch AFTER P2** (owns the re-timing of P2's converted hermes tests, api M3)

Drop `_bus_pending` + `on_session_start_message_delivery`; `_bus_turn_context` = live-read-only injected via the `pre_llm_call` return channel (first call consumes-and-injects); `on_session_end` keeps cursor deletion; manifest hermes session-start arm removed; register() trims the delivery hook (drift notice stays).
Red-first: first-`pre_llm_call` consume-and-inject (context contains mail, cursor row once, turn 2 live-only); NEW never-reaches-`pre_llm_call`-consumes-nothing (no cursor row, no stash leak); close-event pin untouched; P2's converted :345/:362 shapes re-timed in P5's commit.
Amended pins: :90-91, :169-172, :182+, :299/:404/:409/:442, manifest :171-200/:374/:386; `test_hermes_plugin_payloads.py` green.
Gate: `python3 -m pytest -q tests/test_message_bus_hermes.py tests/test_message_bus_manifest.py` then full.

## P6 — Docs (D5/D6) — in-orchestrator — parallel from now

Changelog 0.156.0: P5–P8 Copilot `sessionEnd` residual-risk clause; P3 machine-local trust-boundary lines; P4 consistency amendment (hold sentence names both envs); **P2 consumer-impact: fleet transition — id-less repos deliver 1:1/env-only until den-refresh backfills (reviewer S5)**. SKILL.md "Sender identity is mandatory" paragraph in the features/ catalog → `sync_plugin_skills.py` → re-land `.ai-badger/skills/send-message/` mirror same-commit; SKILL.full.md paragraph for the registry change (resolver reads `.ai-badger/project-id`). D9/L7 dropped as moot.
Gate: `sync_plugin_skills.py --check` + `tests/test_sync_plugin_skills.py` + changelog/skill lint tests.

## P7 — Copilot `if -f` guard (D7) — subagent (api-engineer) — parallel from now

`_guarded(cmd, script_rel)` copied shape (single existence branch, systemMessage-on-skip kept); `_rewrite_command` → `(cmd, script_rel)`; shape (b) uses in-scope `rel_path`; balance pins :210/:384 and artifact E2E :555-565 stay green; ~10 pins amended; NEW `test_guarded_command_skips_cleanly_when_the_script_is_absent`.
Gate: `python3 -m pytest -q tests/test_adjust_hooks_copilot.py`.

## P8 — Integration (last, no production edits) — in-orchestrator

New `test_project_id_lifecycle.py` (scaffold `--target/--root` → mint → resolve; strip id → refresh `--root/--target` backfill → resolve; env override wins — no `$AI_BADGER` needed, api-verified); new `test_containment_bus_coexistence.py`; E2E race re-run with the arm gate through the vendored copy; spec-mirror reconciliation (sc.1 timing; Rule 8 titles + mutation-flag repoint verified done in P2); VERSION bump + new changelog entry (P6 drafts).
Full gate sweep.

## Order of operations (rev 2)

1. **Now, parallel:** P1 (subagent, own worktree) · P7 (subagent, own worktree) · P6 (in-orchestrator).
2. P1 merges → **P2** (subagent) merges → **P3** (in-orchestrator).
3. **P4** and **P5** dispatch after the store lane lands (JS E2E + hermes re-timing seams), in own worktrees, merge in either order.
4. **P8** last on the integrated branch; then Phase 4 quality gate.

## Red-witness log (honest shape, qa M4)

Two row types, per test: **RED-FIRST** (red against shipped code today — R1a, containment tier-2, doctor, leak witness, guard-absent no-op) and **PIN/GUARD** (green-before by construction — R1c, amended :852, strip-list edits, pi :97/:193 — validated by a NAMED MUTATION instead, e.g. revert the containment guard ⇒ tier-1 sweep red; omit one strip entry ⇒ child parks; strip the guard from one row ⇒ :209/:411 red). Each lane merge names its verifier (the lane agent records; the orchestrator re-runs the named mutations at join).

## Risk register

| # | Risk | Mitigation |
|---|---|---|
| R1 | Missed copy among ~33 across three serial re-lands | checklist procedure above + vendored gate + `sync --check` per store commit |
| R2 | Containment degrades to silent DB-only reads (D5c) | refuse-on-access EVERYWHERE incl. file-set reads (reviewer M1); per-family not per-table (M2); task-family pin green unamended |
| R3 | P2 conversion inventory misses a bank site | fixture-symbol sweep (grep `_register_bank|RACCOON_BANK_ENV|ingest.scope`) at P2 start + full-pytest gate |
| R4 | Worktree sessions resolve to the worktree project (correct); stale ids on repo copies | per-directory mint at scaffold/refresh; changelog consumer note (P6/S5) |
| R5 | Strip-list omission leaks hold/arm env; inert holds stall the E2E | six-constraint checklist + leak witness + P8 re-run |
| R6 | Copilot guard breaks quoted balance or artifact E2E | balance pins unamended as tripwires; `bash -c` E2E in P7 gate |
| R7 | Resolver rewrite breaks send CLI sender resolution | send CLI tests converted in P2, same fail-open contract |
| R8 | L1 seeding order masks the bug | R1a seeds 1:1 before broadcast (S1) |
