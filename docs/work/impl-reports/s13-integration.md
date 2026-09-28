# S13 test half — report

## Verdict
Green on the committed tree. Commit `132bfdcf` on `lane/S13-integration` (not pushed). Sub-agents: 0. Test files changed: 1. Production files changed: 0 — no seam defect surfaced.

## AC-by-AC

**(1) Six scenarios green in one module, each scenario a named test** — `tests/test_task_graph_integration.py`, 7 tests (6 scenarios + `test_the_default_root_tripwire_is_armed`):

| # | Test | Seam proven |
|---|---|---|
| 1 | `test_scenario_1_decompose_and_create_match_the_model_hash` | `TaskPlan` model → wire args → store → server hash; exact create shape, `waves == [["s1"],["s2","s3","s5"],["s4"],["s6"]]`, `ready == [s1,s2]`, `integration_sink == "s6"` |
| 2 | `test_scenario_2_waves_deferral_retry_and_skip_advance_the_frontier` | deferral split of the `files∩` pair (s1/s2 both ready, different waves), wave-0 completion → frontier advances, `step_fail` propagation + `step_start` retry, DR7 pending-skip, skipped-dep surfaced in `skipped_deps`/`blocked`, final markers `["x","x","x","x","-","x"]` |
| 3 | `test_scenario_3_text_and_rendered_file_agree_with_status_report` | exact `progress_checklist format:"text"` section (glyphs `x ~ ! ␣ - ␣`, 1/6) → server-rendered file → independent `status_report.plan_checklist()` agreement (headings, `checked == passed ACs`, `total == all ACs`) |
| 4 | `test_scenario_4_replace_refuses_mid_execution_then_bumps_pending` | `plan_replace` → `plan-in-progress` with `blocking_steps` for in_progress **and** complete; pending-only replace → `replaced:true`, revision 0→1, same waves |
| 5 | `test_scenario_5_export_validates_under_both_validators` | `plan_export` document passes `Draft202012Validator(checked-in schema)` **and** `TaskPlan.model_validate`; hash survives round-trip; three corruptions refused by **both** |
| 6 | `test_scenario_6_handwritten_plan_reports_without_a_server_row` | DR12 degraded: banner + `**S<N> …**` + checkboxes, no `tracking.db`; parser reports `packages` 2, `checked 1`, `total 3` |

**(2) Mutation witness** — pasted below.

**(3) Seam defects found** — none. Two reds occurred on the first run and both were this test file's own bugs, fixed in the test (none of them justified touching an owning module):
- `_complete_step` assumed a pending step; scenario 4's `step_start` on an already-in_progress step replays `changed:false`. Red: `assert False is True` on `started["changed"]`. Fix: accept the in_progress replay.
- Scenario 2 asserted 6/6 complete, but the scenario intentionally retires s5, so complete is 5/6. Red: `assert 5 == 6`. Fix: assert 5/6 with `-` marker.

**(4) Feature-set confirmation pass** — `211 passed in 6.95s`.

## Mutation witness (verbatim)

**Witness A — renderer emits `**P<N>**`.** Temporary edit in `task_graph_server.py`: `f"**S{index} — …"` → `f"**P{index} — …"`.

```
>       assert [(int(number), goal, status) for number, goal, status in headings] == [
            (index, row["goal"], row["status"])
            for index, row in enumerate(payload["steps"], start=1)]
E       AssertionError: assert [] == [(1, 'model t...', 'pending')]
E         Right contains 6 more items, first extra item: (1, 'model the reminder', 'complete')
...
FAILED tests/test_task_graph_integration.py::test_scenario_3_text_and_rendered_file_agree_with_status_report
1 failed in 1.11s
```

**Witness B (bonus) — `_conflicts` always returns `None`** (deferral edge ignored):

```
E   AssertionError: assert [['s1', 's2']...'s4'], ['s6']] == [['s1'], ['s2...'s4'], ['s6']]
      At index 0 diff: ['s1', 's2'] != ['s1']
tests/test_task_graph_integration.py:374  (scenario 1, create waves)
tests/test_task_graph_integration.py:394  (scenario 2, frontier waves)
tests/test_task_graph_integration.py:571  (scenario 4, replaced waves)
3 failed, 4 passed in 1.48s
```

Both mutations reverted with `git checkout --`; restored state:

```
.......                                                                  [100%]
7 passed in 1.52s
```

## Files changed
- `tests/test_task_graph_integration.py` (new, ~640 lines) — the deliverable.
- Narrowly-fixed modules: **none**.
Tree after commit: clean. Nothing else touched (VERSION, `docs/changelog/`, `.ai-badger/**`, `index.json` untouched).

## Gate outputs
- `HOME=$(mktemp -d) .venv/bin/python3 -m pytest tests/test_task_graph_integration.py -q` → `7 passed in 1.51s`
- Feature set (integration + mcp_server + cli + plan_schema + graph_ops + plan_store + badger_store_plans + status_report) → `211 passed in 6.95s`
- Commit hook also ran green: `version-sync, index-build, changelog-index, plugin-skills-sync, docs-guard, deps-guard, shipped-paths-guard, scaffold-freshness-guard, rules-index-regen, pylint` — all `Passed`.

## Deviations / notes
- **Store root shape:** `AI_BADGER_TRACKING_ROOT=tmp_path/.ai-badger/task-tracking` rather than the brief's literal `tmp_path/task-tracking`, so the same `tmp_path` is a valid project root for `status_report.plan_checklist()` (which resolves `target/.ai-badger/task-tracking/plans`). All store access is still `tmp_path`-pinned, and the autouse tripwire arms `badger_store._default_badger_root`.
- **Model→wire projection:** create args are built from the validated `TaskPlan` object (`_create_args`), so scenario 1's `content_hash` equality is the seam proof that the model, store and server agree on authored content.
- No network, no Jev module touched; no test imports `openrouter_client`/`jev_choice`.