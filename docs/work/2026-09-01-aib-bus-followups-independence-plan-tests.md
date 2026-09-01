# Plan section — test strategy (TDD spine) — aib-bus-followups-independence

Lane: test-engineer (plan authoring MoE), 2026-09-01. Inputs: research consolidation + research-a/b/c.
Rulings are FIXED; where a ruling leaves a shape open I name the test for the recommended shape and
flag it. Method: every behaviour change below names the FAILING test written first (TDD-mandatory);
each new test lists file, name, one-line assertion shape. Line pins are worktree HEAD c7424c6f.

Standing rule for red witnesses (prove-the-check-fails): each new/amended test is shown red against
the current code, green after the change — recorded in the plan's red-witness log, one line each.

## 1. L1 — cursor lands max-over-delivered-legs (project_id=None first delivery)

No red test exists today (research-a §5): `test_deliver_without_project_id_delivers_one_to_one_only`
(tests/test_message_bus_store.py:422-436) asserts the delivered list only — no cursor assertion in
the None case.

| # | File · name · assertion shape |
|---|---|
| R1a (red) | tests/test_message_bus_store.py · `test_first_delivery_without_project_id_cursors_over_delivered_legs_only` · seed one broadcast + one 1:1; `deliver_for_session("S2", None)` returns only the 1:1; a **second** `deliver_for_session("S2", "P")` must surface the broadcast — red today because the first delivery's cursor landed at global `MAX(id)` and consumed it (engine/badger_store.py:1766-1773). |
| R1b | same file · cursor secondary observable, folded into R1a · after the None delivery, `cursor_id < broadcast_row_id` (the neighbour-field check: right delivery, wrong cursor is still the bug). |
| R1c | same file · `test_first_delivery_with_project_id_still_cursors_past_the_window` · project_id="P", zero matching rows in window, unrelated row exists → cursor still ≥ global `MAX(id)` (research-a §5 hypothesis: all legs ran ⇒ global landing is correct). Guards the fix from over-tightening. |

Negative pins that must stay green (untouched): `test_overflow_beyond_sixteen_is_dropped_and_never_redelivered`
(:545-559, `cursor_id >= newest` with project_id "P") and `test_cursorless_live_read_applies_the_gate_once`
(:492-510). Fix scope: the `row is None` branch only, `project_id is None` ⇒ `max(id of delivered rows, 0)`.

## 2. M2 — per-family containment on open (+ doctor)

**Decision — two-tier matrix, not one parametrized sweep.** Tier 1 is a parametrized neighbour sweep
whose family list is **derived from `badger_store.FAMILIES` + `_task_families` at collection time**
(derive-or-delete: a family added to the registry without containment semantics fails the sweep).
Tier 2 is per-kind-group tests carrying semantics a single parametrized shape cannot express
(refuse-on-write vs read-through vs entries-empty). A sweep alone would pin the weakest common
denominator; kind-group tests alone drift when a family is added.

**Decision — refuse-on-access reads for map/kvdoc/awm and tasks/usage/sessions.** Rationale: satisfies
D5c "condition must surface on access" most literally (research-b §3 flag 2 rules out silent
DB-only); hooks fail-open at the caller layer per D8; and it keeps
tests/test_badger_store_task_family.py:411-422 green **untouched** (research-b §4: survives iff
family-scoped reads still raise). jsonl/recent reads are already DB-only (no legacy merge to
surface); their writes refuse. File-set kinds: open succeeds, legacy reads skip, writes refuse.

Tier 2 tests (new, one per kind group; each also asserts ≥1 neighbour observable — the secondary
surface):

| Kind group | File · name · shape |
|---|---|
| map | tests/test_badger_store_session_families.py · `test_contained_map_family_surfaces_on_read_and_refuses_write` · kv_get on the contained family raises the resurrection error (upgrade pointer); kv_set to it refuses; neighbour family (e.g. dirty_sweeps) reads/writes normally. |
| kvdoc / awm | same file · `test_contained_kvdoc_family_...` / `test_contained_awm_family_...` · same shape on commit_reminder_pending / awm_state (awm via `_awm_projects` merge path). |
| jsonl/recent | same file · `test_contained_append_only_family_reads_db_and_refuses_appends` · log_rows serve DB rows; log_append raises; neighbour append-only family appends fine. |
| tasks/usage/sessions | tests/test_badger_store_task_family.py · `test_contained_task_family_refuses_reads_but_allows_neighbour_upserts` · load_tasks for the contained family raises; task_upsert to a *different* family succeeds; `tracking_transaction` skips only the contained table. |
| file-set (×5 kinds) | tests/test_badger_store.py · `test_contained_file_set_family_opens_and_refuses_writes[param-kind]` · open succeeds; kv_glob legacy reads skip the file; `_migrate_file_set` refuses; other file-set families unaffected. |

Tier 1 sweep: tests/test_badger_store_session_families.py ·
`test_resurrected_family_leaves_its_neighbours_usable[param-family]` · for each registry family:
resurrect it, then `open_user()` succeeds, a `messages` send/receive roundtrip works, and
`prune_status_lines` runs — the bus (born-in-SQLite, :633-635) is the canary neighbour.

Amended existing tests:
- tests/test_badger_store_session_families.py:597-619 `test_resurrected_legacy_file_fails_closed` →
  renamed `test_resurrected_legacy_file_is_contained_per_family`: both raises (:609-612, :616-619)
  become open-succeeds; add the per-family assertions above.
- tests/test_badger_store.py:347-361 `test_resurrected_legacy_map_file_fails_closed` →
  `test_resurrected_legacy_map_file_is_contained_on_tracking`: `open_tracking()` succeeds;
  marker_state accessor raises; tasks/statusline unaffected.
- Untouched pin: tests/test_badger_store_task_family.py:411-422 (see refusal decision).
- Untouched pin: tests/test_p4_integration.py:310-345 — a restored `*.migrated.*` file reads as
  legacy, not resurrection; a doctor repair must not break this (rename preserves mtime).

Doctor: tests per verb land with the verb's home decision; minimum shape
`test_doctor_status_reports_each_resurrected_family_without_creating_or_migrating` (mirrors the
`prune --status` read-only pattern, engine/badger_store.py:2060-2094).

## 3. D2 — resolver off the raccoon bank

Fixture conversion (bank → in-repo `.ai-badger/` id file; helper `_make_project(dir, id)`):

- tests/test_project_registry.py: tests 1-10 convert (containment/override logic on directory
  fixtures); tests 11-13 (`test_raccoon_reader_*`, :234, :252, :271) **delete with the surface**.
  Test 8 (`test_env_override_wins_without_consulting_the_registry`, :182) converts to a
  throwing-walker fake: override set ⇒ no filesystem walk at all.
- tests/test_send_message_skill.py:382 `test_sender_project_resolves_from_the_raccoon_registry` →
  `test_sender_project_resolves_from_the_scaffolded_ai_badger_dir`.
- tests/test_message_bus_manifest.py: `_register_bank` (:140-150) + env redirects (:33, :68) →
  scaffolded-project fixture (the hook walks from payload cwd).
- tests/test_message_bus_hermes.py:345 `test_unresolved_project_delivers_one_to_one_only` →
  mechanism becomes "no `.ai-badger` found upward" (same 1:1 fail-open shape, kept);
  :362 `test_ambiguous_project_delivers_one_to_one_only` → mechanism becomes nested-`.ai-badger`
  refusal caught by the wiring (same 1:1 fail-open shape, kept).

New behaviour tests (rule 8's Gherkin text unchanged — D2 changes owning tests only, constraint 4):

| # | File · name · shape |
|---|---|
| R3a | tests/test_project_registry.py · `test_nearest_ai_badger_dir_wins_on_the_upward_walk` · nested dirs: inner `.ai-badger` (id "inner") inside outer (id "outer"), cwd = inner ⇒ "inner" — the worktree-inside-repo live case (this session's own cwd). |
| R3b | same file · `test_ancestor_ai_badger_conflict_refuses_per_owner_ruling` · owner ruling "nested-`.ai-badger` ambiguity refuses" vs R3a's nearest-wins are in tension on the worktree case; the plan must settle walk policy before R3a/R3b are authored — both shapes named so either ruling has its red test (refuse ⇒ raise carrying sorted candidates; nearest-wins ⇒ R3a alone, refusal retired). Flagged owner-level. |
| R3c | same file · `test_ai_badger_dir_without_an_id_resolves_to_none` · `.ai-badger/` present, no id ⇒ None (env-only delivery) — recommended: fail-open, a permanent fleet state (constraint 6), consistent with the D7 contract; flagged owner-level (refuse is the alternative). |
| R3d | same file · `test_sibling_ai_badger_dir_never_claims_a_sibling_cwd` · walk from cwd never returns a sibling directory's id (the naive-walk mutation's killer, heir to the old sibling test :3). |

## 4. D3 — arm-env gate on the env hold (six constraints → tests/edits)

| Constraint (research-c §3) | Test or edit |
|---|---|
| 1. `_child_env` sets the arm env | EDIT tests/test_message_bus_integration.py:197; witness = the E2E itself (arm missing ⇒ no child parks ⇒ `_wait_for_parked_transaction` fails at :249). The E2E must still park and release — unchanged. |
| 2. store-level env-arming test sets both | AMEND tests/test_message_bus_store.py:852 `test_env_gated_hold_blocks_until_the_release_file_exists`: sets HOLD + arm env; assertion shape unchanged (blocks until release; seam prefix still required — constraint 6 folded in: wrong-prefix spec parks nothing). |
| 3. strip lists add the arm env | EDITS: test_message_bus_integration.py:75, :194; test_message_bus_manifest.py:83, :411; test_message_delivery_hook.py:85, :671. NEW test `test_a_leaked_hold_env_without_the_arm_env_does_not_park` (test_message_bus_store.py): child env carries HOLD but not the arm env ⇒ delivery completes immediately — proves the gate bites, not just that the E2E was re-armed. |
| 4. `_TEST_HOLDS` stays ungated | No edit; the in-process seam tests remain untouched regression pins (production never registers callbacks, badger_store.py:91-92). |
| 5. Gate lands in engine AND vendored copy | Covered mechanically by tests/test_badger_store_vendored.py:25-27 (`report == []`) after same-commit re-landing; the E2E exercises the vendored copy (research-c §3); test_adjust_hooks_copilot.py:419 shipped-pair identity untouched. |
| 6. `spec.startswith(f"{seam}:")` survives | Folded into the amended :852 test (prefix mismatch ⇒ no park, arm env present). |

## 5. D4 — defer start-spawn (pi + Hermes)

Pi amends (tests/js/pi_message_bus_adapter.test.mjs):

| Line · today's title | Amended shape |
|---|---|
| :97 "router hands the start-delivered mail to the first turn exactly once, then goes live" | → "the router live-reads and injects on the first turn": no sessionStart arm; `seen == ["UserPromptSubmit"]` only; first `beforeAgentStart` injects the live read; later turns continue live. |
| :137 "router falls through to the live read when the start delivery was empty or errored" | fall-through branch deleted → "an empty first live read injects nothing and later turns still deliver" (empty ≠ broken; the property survives the deleted branch). |
| :193 (shutdown) | amended to the pendingStart-free router: shutdown drains nothing, no error. |
| :266 E2E "session_start payload delivers seeded mail…" | re-timed: the beforeAgentStart-shaped payload delivers on the **first turn** through the real script; cursor-advance and close-event legs unchanged. |
| :293 empty-inbox E2E | retitled to the deferred event; `{}` → no injection unchanged. |

New pi test: `a session that never reaches the first turn consumes nothing` — session_start fires,
no beforeAgentStart: no spawn, no store hit, **no cursor row**, mail still deliverable afterwards
(the L4 loss shape, now impossible). Hermes (tests/test_message_bus_hermes.py): the start-delivery
tests amend to first-`pre_llm_call` consume-and-inject (context contains the mail, cursor row
exists, turn 2 is a live read only); NEW `test_session_that_never_reaches_pre_llm_call_consumes_
nothing` — after start: no cursor row, no `_bus_pending` entry (no stash leak), mail intact.
Untouched pin: the close-event cursor-deletion test (`on_session_end` keeps `delete_cursor`).
Untouched pin: :345/:362 fail-open shapes (mechanism-only conversion, §3).

## 6. D7 — Copilot `if -f` guard

Amend (research-c §4's ~10 pins; every one re-asserts the guarded form: `if [ -f "$CLAUDE_PROJECT_DIR/<path>" ]; then … elif [ -f "<path>" ]…`):
exact-equality :209 (drift row) and :411-412 (three delivery rows) → assert the bash string contains
the guard and the **script path carried alongside the rewrite** (shape (a) requirement); tail-extraction
pins :58-59, :99-101, :143-145, :171-172, :253-257, :292-295, :383-385 → guarded string each.

- Untouched pins that MUST keep passing: `bash.count('"') % 2 == 0` (:210, :384) — the guard adds
  quoted paths, so balance is the real regression risk; artifact E2E :562 (guarded string under
  `bash -c`, shipped file exists ⇒ still passes, :413-414).
- New: `test_guarded_command_skips_cleanly_when_the_script_is_absent` — `bash -c` a generated guarded
  row with the script removed ⇒ exit 0, skipped systemMessage emitted (the guard's no-op behaviour).

## 7. Mutation-style honesty checks carried (QA-gate precedent)

1. Every new/amended test witnessed red-before/green-after in the plan's red-witness log (esp. R1a,
   which is red against shipped MAX(id) today).
2. Containment: temporarily revert the per-family guard ⇒ tier-1 sweep AND both amended fail-closed
   tests must go red — proves they test containment, not the fixture.
3. Arm-env leak test (§4.3) doubles as the mutation witness for the strip lists: omit one strip
   entry in a scratch run ⇒ a child must park.
4. R3d sibling test kills the naive "any `.ai-badger` below root" walk, heir to the sibling pin.
5. Guard: strip the guard from one generated row ⇒ :209/:411 amendments go red.

## 8. Integration gates (cross-package, run after each phase lands)

1. `python3 -m pytest -q` — full suite green; pre-existing failures triaged, not absorbed.
2. Vendored byte-equality: tests/test_badger_store_vendored.py report `[]` after every
   engine/badger_store.py change (L1, M2, D2, D3 all touch it) — ~33 copies re-landed same-commit
   + `python3 tooling/sync_plugin_skills.py`.
3. JS suite: `node --test tests/js/` (pi adapter + hook-bridge).
4. Build gate: `python3 tooling/index_build.py --check`; lint: pylint over non-test python.
5. E2E exactly-once race parks AND releases through the **vendored** copy (constraint 5).
6. Spec mirror: tests/test_message_bus_integration.py:466-501 reconciled to the amended `.feature`
   (Rule 7 sc.1 timing wording changes; Rule 8 titles untouched); Rule 8 mutation flags :576, :579-581
   repointed to the D2 owning tests.
7. Copilot artifact E2E under `bash -c` with the guard present.
8. Hermes plugin tests (vendored-store load path) green.
