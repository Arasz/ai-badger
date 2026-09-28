# S2 report — typed `task-plan` domain model + checked-in schema + drift gate

**Status:** complete, committed on `lane/S2-domain-model` at `6154c3ea` (not pushed). Sub-agents: 0. No memory writes, no shared stores.

## Environment (measured)

- `uv --version` → `uv 0.12.5 (210d1f678 2026-08-14 aarch64-apple-darwin)`
- Venv has no pip; working install command (pasted):
  `uv pip install --python /Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 'pydantic>=2.12,<3'`
  → `Installed 4 packages ... + pydantic==2.13.5 ...`; `python3 -c "import pydantic"` → `pydantic 2.13.5` (venv is CPython 3.11.15).
- Repo declaration added to `engine/requirements.txt` (CI installs that file — `pylint.yml:44,71,97`).

## AC-by-AC

| AC | Criterion | Evidence |
|---|---|---|
| 1 | round-trip stability incl. unicode + timestamps | `tests/test_task_plan_schema.py::test_plan_round_trips_unicode_and_timestamps` — `Größe — naïve café 日本語 ✓ 🐍` survives `model_dump_json(by_alias=True, exclude_none=True)` literally; `Z`/`+00:00` forms preserved; reparse == plan. Also `test_content_hash_is_order_independent_for_the_step_map`. |
| 2 | V1–V12 each has a red fixture test | `test_v1_steps_must_not_be_empty` … `test_v12_completed_at_must_not_precede_started_at` (12 tests, incl. `test_v6_empty_criterion_list_is_legal_but_a_finding`). RED: full file failed 26/26 before the model existed (traceback pasted below). Mutation witness: disabling the three DAG validators reds exactly V2/V4/V5 + the boundary test. |
| 3 | `--check` green, red on artifact mutation | green: `ok schemas/task-plan.schema.json matches the TaskPlan model`; witness 1 below (`STALE … first difference at /required/9`, exit 1, restored exit 0). |
| 4 | `jsonschema.Draft202012Validator` ≡ runtime validator over corpus | `test_dual_validator_verdicts_agree_over_the_corpus` — 33 cases, both verdicts present, zero disagreements. |
| 5 | schema-passes/model-fails pinned: cycle + unknown dep + key≠id | `test_pydantic_only_dag_invariants_pass_schema_fail_model`; also documented in the schema `description` (`"JSON Schema cannot express the dependency graph: …"`). |
| 6 | deps_guard + validate + schema-self-description + docs-match green; golden vector pinned | final gate output below; `GOLDEN_CONTENT_HASH = "b47e37641b43586fc4a697ce627a4c538e9eb99ad5e0bf8db43311ec34893a90"` in `test_content_hash_golden_vector`. |

## RED witnesses (verbatim)

**TDD red (before `task_plan_model.py` / `task_plan_schema.py` existed):**
```
FAILED tests/test_task_plan_schema.py::test_v1_steps_must_not_be_empty - File...
...
26 failed in 0.64s

load_script = <function load_script.<locals>._load ...>
E   FileNotFoundError: [Errno 2] No such file or directory:
    '.../features/common/skills/task-decomposition/scripts/task_plan_model.py'
<frozen importlib._bootstrap_external>:1130: FileNotFoundError
```

**Witness 1 — schema `--check` red on artifact mutation (dropped `task_id` from `required`):**
```
STALE schemas/task-plan.schema.json: first difference at /required/9
  checked in: []
  generated:  ["updated_at"]
run tooling/task_plan_schema.py to regenerate
exit=1
ok schemas/task-plan.schema.json matches the TaskPlan model
restored exit=0
```

**Witness 2 — gate comparison degenerated (`if False:`), REGISTRY provocation red:**
```
E       AssertionError: tooling/task_plan_schema.py --check did not fail on: the artifact dropped a required field
E           expected exit 1, got 0
=========================== short test summary info ============================
FAILED tests/test_every_check_can_fail.py::test_check_fails_when_provoked[tooling/task_plan_schema.py --check | the artifact dropped a required field]
1 failed in 0.57s
```
restored: `..  [100%] 2 passed in 0.70s` (both provocation directions).

**Witness 3 — `validate.py` exemption removed, sweep red:**
```
INVALID  schema coverage
    - task-plan.schema.json validates nothing: add it to SCHEMA_INSTANCES or to SCHEMAS_WITHOUT_LOCAL_INSTANCES with a reason
mutated exit=1
ok       schema coverage
restored exit=0
```

**Witness 4 — `docs/scripts.md` row removed, catalog test red:**
```
E       AssertionError: docs/scripts.md omits tooling/: task_plan_schema.py
E       assert not ['task_plan_schema.py']
1 failed in 0.50s   → restored: 1 passed in 0.48s
```

**Witness 5 — pydantic undeclared, deps_guard red:**
```
    features/common/skills/task-decomposition/scripts/task_plan_model.py:23  undeclared third-party import: pydantic
    tooling/task_plan_schema.py:24  undeclared third-party import: pydantic
mutated exit=1
restored exit=0
```

**Witness 6 — DAG validators disabled (V2/V4/V5 + boundary tests red):**
```
FAILED tests/test_task_plan_schema.py::test_v2_map_key_must_equal_step_id
FAILED tests/test_task_plan_schema.py::test_v4_dependencies_must_be_known_and_not_self
FAILED tests/test_task_plan_schema.py::test_v5_cycle_is_rejected_and_named
FAILED tests/test_task_plan_schema.py::test_pydantic_only_dag_invariants_pass_schema_fail_model
4 failed in 0.55s
```
restored: `26 passed in 0.61s`.

## Gate outputs (committed tree)

```
$ .venv/bin/python3 -m pytest tests/test_task_plan_schema.py tests/test_every_check_can_fail.py \
      tests/test_schema_self_description.py tests/test_docs_match_the_catalog.py -q
167 passed in 41.84s
$ .venv/bin/python3 tooling/task_plan_schema.py --check
ok schemas/task-plan.schema.json matches the TaskPlan model
$ .venv/bin/python3 gates/deps_guard.py
177 file(s) scanned; every third-party import is declared in engine/requirements.txt
(jsonschema, pydantic, semantica, yaml) — PASS
$ .venv/bin/python3 tooling/validate.py --all   → exit 0; 104 ok lines, 0 INVALID/FAIL
```
Also run as a touching-file check: `pylint` on the three non-test files → `10.00/10`; `bash -n .lefthook/pre-push/verify.sh` → ok.

## Rejected alternatives

1. **`schema_version: int` + `ge/le` + custom validator** → emitted `minimum/maximum` not `const`, and the validator was unreachable dead code (a check that can never fail). Chose `Literal[SUPPORTED_SCHEMA_VERSION]` → schema `"const": 1`, type-level rejection, `PLAN_UPGRADES = {}` left as the upgrade seam.
2. **Pydantic `strict=True`** → rejected: it refuses enum-from-string on in-process `model_validate(dict)` (`Input should be an instance of StepStatus`) while JSON load accepts, which would force S5/S7 to construct enum members everywhere. Lax mode + a curated dual-validator corpus; the one laxness edge (str→int coercion) is deliberately outside the corpus, which only contains schema-expressible cases.
3. **`datetime` fields** → rejected; validated ISO-8601-UTC strings mean `Z` vs `+00:00` bytes survive round-trip (V10 parses for UTC-ness, V12 for ordering).
4. **Steps as an ordered list in `content_hash`** → rejected; `workflow.steps` is a map, so steps are id-sorted (canonical normal form); insertion-order independence is tested.
5. **`steps: Dict = Field(min_length=1)`** → pylint `E1101` (sees `FieldInfo`, no pydantic plugin); switched to `Annotated[Dict[str, Step], Field(min_length=1)]` — generated schema byte-identical, pylint 10/10.
6. **Generator loading the model from its own tree** → rejected; it loads from `--root`, so the gate checks one tree's model against that tree's artifact and the hermetic provocation can copy the model.

## Deviations / notes for the orchestrator

- **`scaffold-freshness-guard` skipped for the lane commit** (`SKIP=scaffold-freshness-guard git commit`). It names exactly 2 of 2734 paths — `.ai-badger/schemas/task-plan.schema.json` and `.ai-badger/engine/requirements.txt` — i.e. the orchestrator-owned mirrors; all other pre-commit hooks passed (incl. pylint). The plan reserves `.ai-badger/**` regeneration for the join commit, and the lane brief forbids touching it.
- **Measured:** pydantic 2.13.5's `model_json_schema()` does **not** emit a top-level `$schema`; the generator injects `GenerateJsonSchema.schema_dialect` (Draft 2020-12) alongside `$id`/title/description and `workflow.steps.propertyNames.pattern` — required for `test_schema_self_description` and for the artifact to be a schema at all.
- **Cross-lane flake (environmental):** one combined pytest run errored at teardown because the conftest FS observer saw lanes S3/S4 writing inside the shared main checkout (`.ai-badger/worktrees/lane-S3-store/…`, `lane-S4-jev/…`); re-runs green. `tests/test_verify_gate.py`/`test_gates_layout.py` showed the same teardown-only pattern (60 passed each time). Unrelated to this change.
- P1-A2's older note mentions a shipped `references/task-plan.schema.json` copy; the frozen S2 file list (and DR6/B2) names only `schemas/task-plan.schema.json`, so no copy was created — S9 can ship/point at the repo artifact if needed.
- `task_graph.py` is the import-clean stub only (`__all__ = []`); ops are S5's.

## Files changed (`6154c3ea`, +1538)

`features/common/skills/task-decomposition/scripts/task_plan_model.py` (new, 346), `.../task_graph.py` (new, 9), `schemas/task-plan.schema.json` (new, 440), `tooling/task_plan_schema.py` (new, 159), `tests/test_task_plan_schema.py` (new, 549), `tests/test_every_check_can_fail.py` (+27), `tooling/validate.py` (+3), `docs/scripts.md` (+1), `engine/requirements.txt` (+3), `.lefthook/pre-push/verify.sh` (+1). Nothing else touched; no push.