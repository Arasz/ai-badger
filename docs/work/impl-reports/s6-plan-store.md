# S6 implementation report — store-backed plan service + frozen root resolution

> Recovered verbatim from the `d-15` delegation receipt (the lane's JSONL transcript was tee-elided
> at ~25 MB; the receipt carries the full report). Committed `c7c5ec03` on `lane/S6-plan-store`,
> merged in the wave-3 join.

**Status: done. Commit `c7c5ec03` on `lane/S6-plan-store`, tree clean, not pushed. Sub-agents: 0.**

## AC-by-AC evidence

**AC1 — round-trip + atomic RMW with scheduled interleave (both outcomes asserted).**
`save`→`load` preserves statuses/evidence/revision/`created_at`, and `canonical_payload(loaded)`
equals the stored bytes (`test_save_load_round_trip_preserves_runtime_state_and_payload_bytes`,
incl. unicode evidence). The interleave is fully scheduled: A and B each read rev 0, B holds
`BEGIN IMMEDIATE` across its own read→stamp→CAS→commit, then A's
`update_step(expected_revision=0)` is refused. Both outcomes asserted — winner's `revision == 1` +
`in_progress` + payload; loser's `code == "conflict"`, `current_revision == 1`, row byte-unchanged
from the winner (`test_scheduled_interleave_leaves_one_winner_and_one_conflict`). The lock-hold
path mirrors S3's deterministic blocker
(`test_held_write_lock_refuses_the_rmw_cleanly_then_lands_after_release`), and a `None`-returning
mutation writes nothing (`test_update_step_no_op_mutation_writes_nothing`).

**AC2 — `schema-version-unsupported` pre-validation, row untouched, no-hook row.**
v2 row containing no valid document at all →
`{code:"schema-version-unsupported", found:2, supported:[1], remediation:"upgrade ai-badger, or re-create the plan with this version"}`
(exact dict), row byte-identical after both load and mutation
(`test_newer_schema_version_refuses_before_pydantic_and_leaves_the_row`). v0 with
`PLAN_UPGRADES == {}` → same refusal, `found:0`, doc-level `decode_plan` too
(`test_version_below_the_floor_with_no_upgrade_hook_refuses`); found 7 mutation path too. The
bypass witness below proves the gate precedes pydantic.

**AC3 — root-precedence pin + RED witness.**
`test_root_precedence_pins_tracker_lib_on_a_scratch_worktree` builds a real `git worktree add`
into `tmp_path` (committed marker), then compares `resolve_project_root` input-for-input across 4
cases (`CLAUDE_PROJECT_DIR`, cwd walk collapsed, script-dir walk from the linked worktree,
`parents[3]` fallback), plus `project_above` and `collapse_worktree` agreement and `tracking_root`
env-wins. `test_explicit_tracking_root_wins_over_project_resolution` and
`test_resolved_root_lands_the_store_under_the_resolved_project` pin the open-time behavior.

**AC4 — actionable refusals.**
Missing `plans` table → `store-error` naming "den-refresh … task pipeline" on both load and save;
un-hosting tracking root (a file in the path) → same actionable refusal instead of
`NotADirectoryError`.

**AC5 — tripwire armed + witnessed.**
Autouse fixture patches `plan_store.badger_store._default_badger_root` to raise; every test pins
`AI_BADGER_TRACKING_ROOT=tmp_path`; `test_the_default_root_tripwire_is_armed` unsets the env and
proves the tripwire fires.

## RED witnesses (verbatim)

1. **RED-first (module missing):** `16 errors in 0.62s` — every fixture raised
   `FileNotFoundError: … task_plan_store.py`.
2. **Root rule change (collapse removed):** exactly the pin test:
   `AssertionError: precedence diverged … assert PosixPath('…/linked worktree') == PosixPath('…/main checkout')`
   → `1 failed`.
3. **Schema gate bypassed:** `3 failed` — all three gate tests got pydantic
   `ValidationError: … Field required` instead of `SchemaVersionUnsupported`, proving pre-pydantic.
4. **No-op treated as a write:** `assert 1 == 0` — a `None` mutation bumped revision.
5. **Refusal mapping removed:** raw `sqlite3.OperationalError: no such table: plans` and
   `NotADirectoryError: [Errno 20] …` tracebacks — both refusal tests failed.
6. **Tripwire:** the armed test passes; S3's own witness already proves the unarmed path leaks.

## Rejected alternatives

- **Importing `tracker_lib` for root resolution** — another skill's module with import-time path
  constants/session registry; the skill must ship self-contained into consumer repos; the rules
  are pinned by equivalence test instead.
- **`badger_lib.run_git` for the worktree probe** — consumer repos have no framework checkout; a
  standalone `git_env` copy is the repo convention (scanned by `test_git_invocation.py` — ran it:
  **25 passed**).
- **`BEGIN IMMEDIATE` for reads** — single SELECTs; a write lock would serialize
  `plan_get`/`steps_ready` behind writers.
- **Hand-rolled `json.dumps` payload** — `model_dump_json(by_alias=True, exclude_none=True)` is the
  model's own canonical serializer and round-trips byte-identically; a second serialization
  surface was rejected.
- **Wrapping pydantic `ValidationError` into a new code** — `invalid-arguments` envelope mapping
  belongs to S7; only the pre-validation version refusal is S6's.
- **Writing the mutated step without re-validating** — the brief demands read→validate→mutate→CAS;
  the mutated document is `model_validate`d so V11/V12 still fire.
- **A public multi-call `plan_transaction()`** — no S6 consumer needs it; `save_plan`/`update_step`
  accept a caller-owned store for composition (the seam the interleave test uses).

## Files changed

`features/common/skills/task-decomposition/scripts/task_plan_store.py` (449 lines),
`tests/test_task_plan_store.py` (535 lines). Nothing else — VERSION/docs/changelog/index.json/
`.ai-badger/**` untouched; frozen modules untouched.

## Gate

```
37 passed in 0.92s        # 16 new + test_badger_store_plans (17) + test_badger_store_vendored (4)
pylint task_plan_store.py: 10.00/10
```

## Deviations

1. **Ambient R-D condition** (operator-side, pre-existing): the pi extension's installed pre-S3
   hook copies (`~/.pi/agent/extensions/ai-badger` → 0.178.0, schema 2) fail every ~1 s against
   `~/.ai-badger/ai-badger.db` stamped 3, so conftest's session teardown hook-error check
   intermittently reports `37 passed, 1 error`. Proven not mine: pre-existing
   `tests/test_badger_store_plans.py` alone reproduces it; clean gate runs reproduce 4/5. Fix is
   operator-side `den-refresh`; broadcast on the project bus (#1530). *(Root-caused and fixed at
   the 0.179.0 fix wave: the plans DDL is now gated to the tracking store — see ADR-0032.)*
2. Ran `pylint` + `tests/test_git_invocation.py` as extra checks because the new module adds a
   scanned `git_env` copy — both green.
3. `model_dump(..., warnings=False)` on the two pre-write dump sites: input models may come from
   unvalidated `model_copy`; the service re-validates immediately, so serializer warnings about
   the pre-validation snapshot are noise.
4. Three guards beyond the literal list, each tested because S7 consumes them: no-op mutation
   writes nothing, CAS-on-absent is `not-found` (never a silent insert at 0), unknown step is
   `not-found`.
