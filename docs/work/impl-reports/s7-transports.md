# S7 implementation report — MCP server + CLI transports (12-tool frozen contract)

> Recovered verbatim from the `d-16` delegation receipt (the lane's JSONL transcript was tee-elided
> at ~25 MB; the receipt carries the full report). Committed `b3937668` on `lane/S7-transports`,
> merged in the wave-3 join.

**S7 complete** — commit `b3937668` on `lane/S7-transports` (not pushed), tree clean, 0 sub-agents.

## AC-by-AC evidence

**AC(1) protocol matrix** — `tests/test_task_graph_mcp_server.py`, 37 tests over real subprocess
pipes (`sys.executable` runs the script). Negotiation matrix (`2024-11-05/2025-03-26/2025-06-18`
echoed; `1999-01-01` and missing → `2025-06-18`; `serverInfo.version` == VERSION file). Survival
witness: `{not json at all` → `-32700`, then `ping` → `{}`. Purity witness: every stdout line
parses as `jsonrpc:2.0`; `parse error` appears on stderr only. Unknown method `-32601`; unknown
tool `-32602`; notification no-ops.

**AC(2) frozen contract** — names exact in frozen order; `json.dumps(tools)` contains **no
`plan_id`, no `advisory`** (two descriptions reworded to keep the word off the wire); every
inputSchema `additionalProperties:false` with `task_id`; annotations exactly
`{readOnlyHint, idempotentHint, openWorldHint:false}`; only `step_start` is `idempotentHint:false`
(pinned as the deliberate P2-B1 exception). Every observed error is asserted ∈ the 12-code closed
set with the §2 status analogue.

**AC(3) idempotency + hash + plan-in-progress** — `plan_create` two identical calls →
`created:true` then `created:false`, revision 0, hash == S2 `GOLDEN_CONTENT_HASH` `b47e3764…3a90`.
`plan_replace` identical content with `expected_revision:99` → `replaced:false`, revision 0.
Replays: start/complete/fail/skip/ac_check all `changed:false` with no revision bump (evidence keys
drop `recorded_at`). Replace matrix: pending-only and skipped-only succeed; in_progress/complete/
failed → `plan-in-progress` with `blocking_steps`.

**AC(4) render round-trip** — after create→ac_check→complete→skip, one file
`plans/<YYYY-MM-DD>-aib-demo-task.md`; an independent parser in the test matches 2
`**S<N> — goal (status)**` headings in topological order and `[x]/[ ]` box counts/glyphs to the
state.

**AC(5) CLI goldens + equality** — `tests/test_task_graph_cli.py`: one full golden literal for each
of the 12 tools (timestamps normalised to `<ts>`), plus 13 CLI≡MCP pair comparisons. CLI exit
0/1/2 = ok/tool-error/usage.

**AC(6) REGISTRY provocation red→green** — verbatim red when the check was deliberately disabled:
```
AssertionError: features/common/skills/task-decomposition/scripts/task_graph_server.py --check
  did not fail on: the checked-in task-plan schema dropped a required field
  expected exit 1, got 0
FAILED ... 1 failed, 3 passed, 84 deselected
```
Same red for the missing-schema row (`return 0` substituted), then restored: `4 passed`. Full meta
discovery/coverage tests: `7 passed`.

**AC(7) uv smoke MEASURED** — cold cache:
```
Downloading pydantic-core (1.8MiB)
Installed 5 packages in 4ms
ok …/schemas/task-plan.schema.json matches the TaskPlan model
```
plus the uv CLI end-to-end (`plan_create` + `progress_checklist` payloads printed).

## RED witnesses
Initial run before implementation: `39 failed, 13 errors` —
`can't open file '…/task_graph_server.py': [Errno 2] No such file or directory`. Both permanent
fixes have red witnesses above/pasted during development.

## Rejected alternatives
- **Split server across modules** → one file keeps the §2 contract in one place;
  `# pylint: disable=too-many-lines` with reason (precedent `badger_store.py`), pylint 10.00/10
  under the repo rc and the pre-commit rc.
- **`update_step` for every mutation** → guards/ready need the whole plan; used a server-owned
  `BEGIN IMMEDIATE` + `save_plan(..., store=store)` (the store documents caller-owned
  transactions), one read→validate→mutate→CAS per mutation.
- **Persist `run_id`** → frozen `Step` has no run field; accepted, validated, documented as not
  persisted (deviation).
- **`idempotentHint:true` for all writes** → P2-B1 says a start after failure is a new attempt;
  pinned `step_start` as the sole false.
- **Render date = `updated_at`** → `created_at[:10]` keeps one stable plan file per task; render
  failures log to stderr rather than turning a committed write into an error.

## Gates
- Lane tests: `52 passed`; meta subset: `7 passed`; `--check` clean/mutated/missing all correct.
- Brief gate **as written**: `166 passed, 1 error`. The one error is the session-teardown fixture
  `_real_hook_errors_are_surfaced` — not a test. Cause proven environmental (R-D): real
  `~/.ai-badger/ai-badger.db` is v3 while main-checkout v2 hooks keep failing against it; **3 new
  log lines appeared during 40 s of pure idle**, and `pytest -k consumer_journey` (untouched tests,
  none of my rows) reproduces it.
- Same gate with the shared-log noise isolated (`HOME=$(mktemp -d)`): **`166 passed in 41.95s`**,
  including `tests/test_task_plan_schema.py` untouched.
- `pylint` (repo rc, pre-commit rc), `gates/deps_guard.py` (PASS), all pre-commit guards PASS.

## Files changed
`features/common/skills/task-decomposition/scripts/task_graph_server.py` (+1298),
`task_graph_cli.py` (+76), `tests/test_task_graph_mcp_server.py` (+1017),
`tests/test_task_graph_cli.py` (+417), `tests/test_every_check_can_fail.py` (+34, REGISTRY rows +
constant). Nothing outside these — VERSION/docs/.ai-badger/index.json untouched.

**Flag for the wave join:** the real user-DB v3 / v2-hook mismatch (R-D) makes the meta gate's
teardown red for any sufficiently long local run in the shared environment; orchestrator
re-verification at the join is the documented recovery point. *(Root-caused and fixed at the
0.179.0 fix wave — the plans DDL is gated to the tracking store; see ADR-0032.)*
