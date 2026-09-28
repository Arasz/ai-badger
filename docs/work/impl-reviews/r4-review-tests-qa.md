All mutations reverted; final tree is clean. Here is the assessment.

---

# QA assessment — `lane-S13-integration` task-decomposition test suite

**Scope.** The 19 changed/new test files listed in the brief, plus the production files they cover. Baseline: `python3 -m pytest -q` (run here as `.venv/bin/python3`) — **475 passed in 8.0s** on the 16-file selection; 457 in ~8s on the 14 core files. No test leaves the worktree dirty (`git status --porcelain` empty after every mutation).

**Lineage check (DR1–DR13, §2 of `docs/work/2026-09-28-task-decomposition-plan.md`)** was walked clause by clause; the unpinned clauses are F7–F10.

**What this suite does well** — stated first because it is true:
- The core semantics are pinned by *literals*, not derived values: content-hash goldens (model, MCP, CLI), full per-tool CLI golden payloads, exact `waves`/`ready`/`blocked` lists, exact command `text`. Mutation testing confirms: 11/12 production mutations I applied went RED (graph waves/markers/ready/integration, hash composition, flag matrix, JEV gate boundary, status renderer, vendored copy, DDL CHECK, store no-op, `plan_create` idempotency, `tracking_root` precedence, cycle guard, `--check` drift, doc pins D1–D3).
- Witness tests are real where it matters: `test_conflict_predicate_is_what_defers_a_pair` flips the predicate and watches the checker fail; the no-subprocess guard has a mutated-copy witness; the catalog uv-missing fixture asserts the probe *was* controlled; the default-root tripwire is armed in four files.
- The integration file tests seams, not units: model→pipe→renderer→`status_report` parse, with the content hash as the cross-module oracle.

## Findings

| # | file:line | rule | sev | mutation / missing clause (run?) | what it means |
|---|---|---|---|---|---|
| F1 | `features/common/skills/task-decomposition/scripts/task_graph_server.py:2-5`, `task_graph_cli.py:2-5` | T1-CST-06, T0-01 | **major** | Delete the PEP 723 header, run all server/CLI/integration tests → **59 passed** (`applied+reverted`) | The shipped launch path (`uv run --script`) is unpinned. Every test spawns with `sys.executable` + the repo venv, so a deleted/corrupted `dependencies = ["pydantic…"]` header ships silently; the plan made only the *network fetch* non-repeatable, not a static header pin. |
| F2 | `tests/conftest.py:246-256`; `~/.ai-badger/ai-badger.db` stamp=3 | T1-ISO-05/06/07, T0-06 | **major** | 4 of ~12 full-selection runs errored at teardown: *"this run appended 4 entry(ies) to the operator's real hook-error log … store schema version 3 is newer than this code knows (2)"* (`applied+reverted` on production, flake observed live) | A clean diff intermittently reddens the suite. The session fixture asserts on an operator-global log that any process on the machine appends to; the real user DB is at v3 (the documented R-D state) while installed v2 hooks still run. Plan §5 R-D requires re-verifying stamps at the wave join — this review is the join. |
| F3 | `task_graph_server.py:61-62`; `tests/test_task_graph_mcp_server.py:59-68` | T1-CST-06 | minor | Remove `prerequisite-missing` + `config-error` from the server's `ERRORS` map, run MCP+CLI+integration → **59 passed**; MCP alone → **37 passed** (`applied+reverted`) | The closed §2 error set can shrink silently. Nothing binds the test's `FROZEN_ERROR_CODES` to the server's map, and those two codes have no producing path; a uniform assertion `set(ERRORS) == FROZEN_ERROR_CODES` (plus an owner ruling to wire or drop the dead pair) closes it. |
| F4 | `tests/test_dependency_honesty.py:15-19,84-88` | T1-PRF-03 | minor | Rename `CLAUDE.md` + `.ai-badger/CLAUDE.md` away → test **passes** (`1 passed`); the loop then checks zero subjects | The net narrowed: the pre-change test required both copies to exist (`read_text`); the new `if path.is_file()` tolerates an empty subject set, and `RENDERED_COPIES` is hand-typed rather than derived from the scaffolder's render targets. Add `checked >= 1` (and derive the list, or assert the two mandated paths exist). |
| F5 | `tests/test_jev_client_vendored.py:45-54` | T1-PRF-01, T0-01 | minor | The "comparator" under test does not exist: the test byte-replaces `LOOPBACK`, asserts the bytes differ, writes a tmp file, asserts it differs from `normalized_source()` — all trivially true | The *primary* vendoring comparison is sound (my second-line mutation on the vendored copy reddened it: `3 failed`), but the stated witness proves nothing. Extract the comparator into a function and run the mutated copy through *it*, or delete the witness and rely on the real comparison. |
| F6 | `task_graph_server.py` `_now_dt`; `tests/test_task_graph_mcp_server.py:77-84`; `tests/test_task_graph_cli.py:46-53`; `engine/badger_store.py:1287` | T1-ORC-03 | minor | (a) `_now_dt` returns `datetime(2020,1,1,UTC)` → mcp+integration **44 passed**, CLI **15 passed**; (b) `updated_at` stamped constant across **27** vendored copies → **111 passed**, only the vendoring check fired (`applied+reverted`) | `freeze()` normalises every timestamp in every golden, and no test asserts a stamp is fresh, non-constant, or that `updated_at` advances on a CAS write. Consumers reading `started_at`/`updated_at` can be fed a frozen clock with no red. |
| F7 | `task_graph_server.py:191-200`; plan DR12 | T1-SCO-06 | minor | No test passes or asserts a `note` to `plan_replace`; `PlanReplaceInput` has no `note` field (`unverified (static reasoning)` for the spec reading) | DR12's "*or `plan_replace` with a note*" is neither implemented nor pinned. A test for the clause would have forced the divergence into the open; either implement+test it or pin its deliberate absence by owner ruling. |
| F8 | `tests/test_task_graph_ops.py:684`, `:555-561`; `tests/test_task_graph_mcp_server.py:793`, `:575` | T1-SCO-02 | minor | Static | Name/body mismatches: `test_blocked_is_empty_when_no_ancestor_failed_or_skipped` never asserts emptiness (only ancestry consistency); `test_step_skip_is_valid_from_pending_in_progress_and_failed` omits `failed` (covered elsewhere); `test_plan_export_returns_the_stored_document_verbatim` compares parsed JSON, so "verbatim" is semantic only; `assert step is not None` is dead code. |
| F9 | plan DR4/DR7/DR8/DR10/DR12/DR13 | T1-SCO-05/06 | minor | Static, absences grep-verified | Unpinned clauses: `task_tracker.py never reads plans` (verified true, no test); no-`Family`/no-JSON-sidecar absences; `serialized_pairs` dropped (no absence pin); DR8 "`task` requires the join for **high-effort** loops" (phrase only, no loop↔join tie); DR12 "failed/forced/blocked/join-enforcement … not enforced without the server" (sentence absent from repo and tests); DR13's machine-checkable "every non-deferred spec scenario maps to ≥1 step AC" is a keyword assertion only. |
| F10 | `task_plan_model.py:31`; `tests/test_task_plan_schema.py:182-186` | T1-STR-02 | minor | Tightening the frozen step-id pattern to `^[a-z0-9]+$` went RED only via the artifact-drift tests; no fixture exercises a *valid* id containing `.`/`_` (hypothesis: a coordinated model+regenerated-schema tightening survives) | The frozen §2 grammar has no positive cases at the boundary; add one valid `a.b_c-1`-style id round-trip. |
| F11 | `tests/test_task_graph_mcp_server.py` `McpServer.read` | T1-CST-02 | minor | Static; `pytest-timeout` is not installed | `stdout.readline()` has no deadline: a server regression that stops answering hangs a local run indefinitely (verify.sh's lane deadline covers CI only). Add a socket/thread timeout or pytest-timeout to the dev deps. |
| F12 | six files | T1-CST-02 | minor (note only, no churn now) | Static | `McpServer` is duplicated in `test_task_graph_mcp_server.py` and `test_task_graph_integration.py`; `freeze()` in server+CLI files; `_step`/`_ac`/`_evidence` builders in six. Consolidate into one `tests/mcp_harness.py` on the next touch. |

### The three suspects, with both states pasted

**M5 / F1 — PEP 723 header (survivor).**
```diff
-# /// script
-# requires-python = ">=3.10"
-# dependencies = ["pydantic>=2.12,<3"]
-# ///
```
`pytest tests/test_task_graph_mcp_server.py tests/test_task_graph_cli.py tests/test_task_graph_integration.py -q` → `59 passed in 6.46s` (rc=0). File restored by the harness; `git status` clean.

**E1 / F3 — frozen error codes (survivor).**
```diff
-    "plan-in-progress": 409, "schema-version-unsupported": 422, "prerequisite-missing": 500,
-    "config-error": 500, "store-error": 500,
+    "plan-in-progress": 409, "schema-version-unsupported": 422,
+    "store-error": 500,
```
MCP only: `37 passed in 4.33s` (rc=0). MCP+CLI+integration: `59 passed in 6.44s` (rc=0).

**T1 coordinated / F6 — timestamp oracle (survivor).**
```diff
-            (payload, now, task_id, expected_revision),
+            (payload, "2026-01-01T00:00:00+00:00", task_id, expected_revision),
```
applied to **27** tracked `badger_store.py` copies (the change the vendoring discipline mandates), then
`pytest test_badger_store_plans test_task_plan_store test_message_bus_store test_badger_store_user_families test_badger_store_vendored` → `111 passed, 1 error` — the error is the F2 session fixture, **no assertion on `updated_at` failed**. Separately, freezing the server clock to 2020: MCP+integration `44 passed`, CLI `15 passed`.

### Fixture realism and the changed store pins

- **Fixtures.** Unit fixtures are deliberately minimal toys (`{"v": 1}` payloads, 1–7 step plans) — adequate for their invariants, and the schema's drift gate is the generator deep-equality + dual-validator corpus, not fixtures. The S13 brief fixture (`tests/test_task_graph_integration.py:56-116`) is realistic: six steps, a shared file forcing a deferred wave, a join step carrying cross-step ACs, and exact `EXPECTED_WAVES`. Gaps: no multi-sink plan, blocked `step_get`, failed `ac_check`, or non-ASCII payload is exercised **over the wire** (all are covered in-process elsewhere).
- **Changed pins are honest and narrow.** `test_badger_store_user_families.py:162` keeps the deliberate double equality `stamped == "3" == str(badger_store.SCHEMA_VERSION)`; `test_message_bus_store.py:183,238` bumps the literal but its upgrade test still asserts `calls == [1]` + tables; nothing was deleted. `test_expected_skill_names.py:71` counts 47 with the derivation checked against the manifest, not just the number.

## Still open

- F2's attribution: the v3 user DB was already at 3 when I started; I did not determine which process upgraded it (other lanes on this machine were active). The **flake mechanism** is proven; the **cause of the stamp state** is not. Treat the R-D recovery as required before the join push regardless.
- F10's coordinated model+schema tightening is a hypothesis; only the artifact-drift detection was measured.
- F7's DR12 reading ("a note on `plan_replace`") is a spec interpretation — the owner ruling may have been to drop it.
- The MCP harness `readline` hang (F11) was not reproduced (it would hang the run, not redden it).

**Verdict: SOUND AFTER FIXES** — core semantics are pinned by independent literals and 15/15 behavioural mutations I applied were caught; the merge gate should not go green until F1 (launch header) and F2 (join-time R-D stamp reset / shared-log flake) are addressed.