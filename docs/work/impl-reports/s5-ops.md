# S5 implementation report — graph ops, guards, deferral waves (deterministic, no-subprocess)

> Recovered verbatim from the `d-14` delegation receipt (the lane's JSONL transcript was tee-elided
> at ~25 MB; the receipt carries the full report). Committed `783875fa` on `lane/S5-ops`, merged in
> the wave-2 join.

**S5 complete** — committed `783875fa` on `lane/S5-ops`, not pushed. Sub-agents: 0.

## AC1 — stable refusal codes + transition matrix.

Every transition guard implemented and witnessed RED first (36 rows), including
`dependencies-incomplete` (start/complete), `invalid-transition` + `allowed_transitions`
(start/complete/fail/skip, terminal states), `criteria-unmet` (unresolved + failed listed;
force-without-note), `already_complete`, `not-found`, plus the force bypass recording
`completion.forced=True` + note with AC statuses untouched. Representative red:

```
=== complete-deps-guard ===
E   AssertionError: expected refusal code 'dependencies-incomplete', got 'criteria-unmet': step 'run' has unresolved criteria ['ac1'] ...
FAILED tests/test_task_graph_ops.py::test_complete_refuses_incomplete_dependencies_first
=== force-recording ===
E   AssertionError: assert False is True
     +  where False = Completion(completed_by=None, forced=False, note='shipping with ac2 failed: ...')
FAILED tests/test_task_graph_ops.py::test_complete_force_bypass_records_forced_note_and_leaves_acs
```

RED matrix (abridged list of the 36 named rows, all RED before implementation): all-statuses-with-
allowed-transitions, start-deps-guard, not-found-guard, complete-already-complete,
complete-status-guard, complete-deps-guard, complete-criteria-guard, force-note-guard,
force-recording, fail-status-guard, skip-status-guard, satisfied-deps-set, ready-status-filter,
skipped-deps-surface, conflict-predicate-flip, waves-dep-deferral, waves-remaining-filter,
blocked-culprits, blocked-status-filter, ancestors-transitive, topological-reversal,
integration-sink-condition, integration-ok, integration-finding-kind, checklist-glyph,
checklist-order, checklist-tally, no-subprocess.

## AC2 — deferral-wave invariants + determinism.

Tests: greedy packing/order, conflict defers the later member (`[[a,c,d],[b,e]]`), deferred ready
member still in a later wave, dependent deferral, remaining-only coverage + dependency ordering,
`wave[0] ⊆ ready` + ready coverage, conflict-free waves (fixed + generated corpus). The
flipped-predicate witness is both in-suite (`test_conflict_predicate_is_what_defers_a_pair`, an
independent checker) and on the real file:

```
=== conflict-predicate-flip (real file: _conflicts → return None) ===
E   AssertionError: wave ['a', 'b', 'c', 'd', 'e'] packs 'a' and 'b' onto a shared file
    assert not ({'src/shared.py'} & {'src/shared.py'})
FAILED tests/test_task_graph_ops.py::test_no_wave_contains_a_conflicting_pair
```

Determinism: `test_waves_and_ops_are_deterministic_across_runs_and_copies` compares byte-identical
`json.dumps(..., sort_keys=True)` across two runs **and a second module copy**, plus
`test_determinism_bytes_change_when_the_order_drift` proves the comparison notices drift.
`test_guards_never_mutate_the_plan` proves purity.

## AC3 — no-subprocess property + mutation witness.

Static AST guard (`test_task_graph_source_never_reaches_a_subprocess`), a mutated-copy witness
(`test_source_guard_catches_a_mutated_copy`), and a behavioural test
(`test_check_strings_are_recorded_never_executed`: a plan whose `check` is `touch <sentinel>`
flows through every op and no sentinel appears). Temporary real-file mutation:

```
=== no-subprocess ===
E   AssertionError: assert ['import subp...bprocess.run'] == []
    Left contains 2 more items, first extra item: 'import subprocess'
FAILED tests/test_task_graph_ops.py::test_task_graph_source_never_reaches_a_subprocess
```

## AC4 — S2 model undisturbed.

`tests/test_task_plan_schema.py` green in every gate run (26 passed; 3 consecutive clean runs
before commit, plus the post-commit run).

## Rejected alternatives

1. **Transitive-closure readiness**: DR7/§2 say readiness checks direct `depends_on` only, so ready
   and `blocked` deliberately overlap when a skipped dep hides an unsatisfied ancestor; the
   pairwise-unordered property therefore runs over guard-reachable generated plans (a non-pending
   step can only depend on complete/skipped ones).
2. **Skip from pending**: P2's `step_skip` row names only `complete` as invalid, but DR7's arrow
   list is narrower — followed DR7 (`pending → in_progress` first), flagged for S7. *(Resolved
   later by the DR7 amendment: skip is valid from pending/in_progress/failed.)*
3. **`allowed_transitions` as tool names**: task_graph returns status values (`in_progress`,
   `complete/failed/skipped`, `[]`); the transport owns the `step_start`/`step_get` naming and
   terminal-read policy.
4. **Result objects**: refusals raise `TransitionRefused(code, details)` so a guard cannot be
   silently ignored.
5. **Richer checklist payload**: kept `{task_id, revision, complete, total, steps}`; S7 composes
   `next/blocked/waves/integration_ok` from the pure functions.
6. **`blocked` including terminal descendants**: restricted to remaining steps (it exists so
   dispatchable work doesn't vanish); complete descendants are tested as excluded.
7. **Private model loader key (S4 pattern)**: loads `task_plan_model` under its bare `sys.modules`
   name so the store/transport's own bare import reuses one copy; tests build via
   `graph.task_plan_model`.

## Deviations

Added `not-found` guards and `ancestors` beyond the brief (transport needs both);
`plan_quality_findings` composes the model's findings + one `integration_missing` finding
(attached to the topologically-first sink, since `PlanFinding` requires a `step_id`). Pre-commit
pylint initially blocked the commit (local `complete` shadowing, pytest fixture names, attributes
set outside `__init__`) — fixed; `pylint --rcfile=/dev/null --disable=C,R,W0611,W0613,E0401
--fail-under=9.5` on both files: **10.00/10**. Environment note: the ambient
`message_delivery_hook` (old v2 vendored store vs the v3 DB — plan risk R-D) can append to the
operator's real hook-error log mid-run and trip the conftest teardown assertion; it fired once in
five gate runs and is unrelated to these files (they open no store).

## Files changed (only the two owned)

`features/common/skills/task-decomposition/scripts/task_graph.py` (+478),
`tests/test_task_graph_ops.py` (+879). No push, no PR; committed on `lane/S5-ops` (`783875fa`) for
the orchestrator's join.
