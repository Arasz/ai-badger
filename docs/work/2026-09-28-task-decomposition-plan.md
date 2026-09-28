# Plan — task-decomposition skill + DAG task-plan model + task-graph MCP server

Task `aib-task-decomposition-workflow-graph-mcp` · 2026-09-28 · **Plan rev 2.1** (owner gate passed;
rev 2 + plan-review
MUST/SHOULD folded from `docs/work/plan-reviews/r{1,2,3}-*.md`; rev 1 sections in
`docs/work/plan-sections/p{1,2,3}-*.md` remain authoritative detail where not restated).
Unit of work is **step**. Last step is the **join/integration step** (DR8). Owner-decidable items
Q1–Q3 are answered in §6 before dispatch.

## 1. Decisions

| # | Ruling | Notes / overrules |
|---|---|---|
| DR1 | **Stack: Python 3.10+, pydantic (typing + `model_json_schema()`), stdlib `graphlib` + thin `Workflow` facade.** networkx a one-module swap behind the facade (flip: longest-path/transitive-reduction need or owner ruling). | USER summary settles pydantic; graphlib per P2-B3. |
| DR2 | **Hand-rolled stdio JSON-RPC server** (NDJSON; initialize/ping/tools-list/tools-call; protocol versions 2024-11-05/2025-03-26/2025-06-18), **PEP 723 `uv run --script` launch** (`dependencies = ["pydantic>=2.12,<3"]`), prerequisite `uv`. MCP SDK rejected (15 direct deps). Flip (R-A): a host rejects our protocol shape → adopt `mcp` 2.x behind the same handlers. | P2-B3 + R1-F6/R3-F3. |
| DR3 | **Server code in `features/common/skills/task-decomposition/scripts/`**; `features/common/mcp/task-graph/` packet is descriptor-only; `stack-mcp.json` command = `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_server.py`, `declare: true` + Claude `agentOverrides` (`${CLAUDE_PROJECT_DIR}`). **Declared regardless of unmet prerequisite; the scaffold note carries the prerequisite** (exact note content pinned in S8's fixtures). **CLI ships**: `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_cli.py <tool-name> --json` (same PEP 723 header), 12 verbs = the 12 tool names. | R1-F6, R3-F9, R3-F15, R2-F7. |
| DR4 | **`plans` table in `tracking.db`**: `SCHEMA_VERSION` 2→3 + `UPGRADE_HOOKS[2]` (`_BUS_DDL` pattern), accessors in `engine/badger_store.py`; re-vendor **every file matched by `_VENDORED_GLOBS`** (`features/**`+`skills/**`, 23 today) + the new skill copy — count-free wording, `.ai-badger/**` copies regenerate at re-scaffold. CAS on integer `revision`; `content_hash` (DR5) gives idempotent create/replace. No JSON sidecar. **No `Family` entry** (born-in-SQLite; no legacy import path — P1-A3 over P2-S2). | R1-F4, R2, N3. |
| DR5 | **12-tool surface** (names frozen §2) with per-mutation `expected_revision` CAS — one server-side `BEGIN IMMEDIATE` read-modify-write per mutation. `content_hash` = SHA-256 over canonical JSON (`sort_keys=True, separators=(",",":")`) of the authored content: `task_id, task_description_ref, research_ref, task_context, loop, source_refs`, and per step `id, goal, instructions, effort, level, model, persona, depends_on, files, resources` + AC `id, statement, check` — **excluding** `revision, created_at, updated_at, $schema` and all runtime state (status/timestamps/completion/evidence). One golden known-answer vector pinned in S7. | P2-B1 + R2-F4. |
| DR6 | **Model**: key is `task_id` (`plan_id` deleted everywhere — R1-F1). `TaskPlan{schema_version(1), task_id, task_description_ref, research_ref?, task_context, loop(low|high), source_refs[], $schema?(alias, excluded from hash), workflow{steps}, revision, created_at, updated_at}`. `Step{id, goal, instructions, effort(low|medium|high), level?, model?, persona?, depends_on, acceptance_criteria, files[], resources[], status, started_at?, completed_at?, completion?}`. `AcceptanceCriterion{id, statement, check?, status, evidence[]}` single AC source. `Completion{completed_by?, forced, note?, evidence[]}`. Invariants V1–V12 (P1-A2) enforced at build **and** load. Module paths frozen: `task_plan_model.py` (model+emitter), `task_graph.py` (ops). | R1-F1/F7, R2-F21, R3-F12. |
| DR7 | **Transitions**: `pending → in_progress → {complete, failed, skipped}`, `failed → in_progress` retry, complete/skipped terminal. `ready` = pending/failed with all deps ∈ {complete, **skipped**} (skipped satisfies; `skipped_deps[]` surfaced). **Waves use the deferral model** (R2-F3 ruling): greedy packing in (topological, id) order; a `files∩`/`resources∩` pair defers the later member to a later wave; `wave[0]` is the ready prefix admitted by tie-order+conflict rule; every ready member appears in some wave; no wave contains a conflicting pair. `serialized_pairs` output is dropped (deferral makes it redundant). `blocked` = failed/skipped-ancestor descendants. Server never runs `check` (record-only evidence). | P1-A4 + P2-B1 + R2-F3. |
| DR8 | **Integration (D6): a join step is a real `Step`** depending on every other sink, carrying the cross-step ACs; `integration_sink(plan)` derived; `progress_checklist` and `plan_get(include:"state")` surface `integration_ok`; `task` requires the join for high-effort loops. (`plan_state` does not exist — R1-F5/R3-F6.) | P3-C1 + P1-A2. |
| DR9 | **Jev advisory is skill-side** (`jev_choice.py` + vendored `openrouter_client.py` copy in the skill's `scripts/`) — **the server is offline by contract; `steps_ready` has NO advisory parameter** (frozen §2); the skill post-processes `steps_ready` output with hints. Polarity frozen: **absent or not `"1"` = off**; `AI_BADGER_JEV=1` master, `AI_BADGER_JEV_TIER/WAVES=1` per capability; loopback test seam `AI_BADGER_JEV_TEST_OPENROUTER_BASE`. Fail-safe: tier proposes **upgrade only** (`choice=="high"` ∧ conf ≥ 0.6), never demotes, never overrides `level`/`model`; wave hints can only **add** serialization (failure/`serialize`/conf < 0.7 → serialize). `Budget` port lives in `jev_choice.py`; the vendored client copy differs by exactly one line (`TEST_BASE_ENV`), test-enforced. Prompt literals live in the test fixtures (never parsed from docs at runtime). Caps (`PAIR_CAP=10`, `STATE_CHAR_CAP=32000`, chunking) owned by S4 with ACs. **[Q2 pending: default-off vs on]** | R1-F11, R2-F5/F11/F16/F19, R3-F2. |
| DR10 | **Progress**: `progress_checklist` primary — its `format:"text"` output **is** the status section verbatim; `status_report.py` file-parsing is the fallback; `packages/checked/total` keys frozen; `STEP_RE = ^\*\*([PS]\d+[^*]*)\*\*`; renderer `mkdir -p` the plans dir on first render; render/parse round-trip tested. `task_tracker.py` never reads `plans`. | R2-F8, R3-F7, N1. |
| DR11 | **Vocabulary blast radius: scoped rename + explicit exemptions** per P3-C2 dispositions (`query_pipeline.py` untouched — prompt bytes pinned to pi goldens; delegator persona / complete-project-scope / design-gate-audit / review-tests / scripts-tooling-refactor get boundary notes). Sections' stale tool names normalise: `plan_build→plan_create`, `plan_progress→progress_checklist`, `ac_record→ac_check`, `plan_state→progress_checklist`+`plan_get`, `plan_id` does not exist. | R1-F5. |
| DR12 | **Compat: dual-read + explicit refusal, no migration.** In-flight `**P<N>**` plans keep reporting. **No plan row → legacy file + manual checkboxes; `task` never calls `plan_create` over an in-flight task** (pinned sentence + test row). `plan_create` refuses existing `task_id` unless content-identical (idempotent) or `plan_replace` with a note. Degraded manual semantics: checkbox states map to AC status; failed/forced/blocked/join-enforcement are documented as "not enforced without the server". | R3-F8. |
| DR13 | **`spec.json` relationship (D8): side-by-side.** `create-task-spec`'s `spec.json` stays the requirements artifact; `task-plan` is the executable decomposition that consumes it. Coverage rule: every non-deferred spec scenario maps to ≥1 step AC. **[Q1 pending: quick-task]** | R3-F4/F11. |

## 2. Interface freeze (every lane brief quotes this)

- **Tools (12, exact):** `plan_create, plan_replace, plan_get, plan_export, step_get, step_start,
  step_complete, step_fail, step_skip, ac_check, steps_ready, progress_checklist`.
  `PlanRef = {task_id}`; `plan_id` absent from all I/O. `plan_create(task_id, task_description_ref,
  steps[], task_context?, research_ref?, loop, source_refs?)`. All other I/O = P2-B1 shapes with
  `plan_id` removed and `steps_ready(PlanRef, waves?=true)` **without** `advisory`/`openWorldHint`.
- **Error codes (closed):** `invalid-arguments, not-found, already-exists, conflict,
  invalid-transition, dependencies-incomplete, criteria-unmet, plan-in-progress,
  schema-version-unsupported, prerequisite-missing, config-error, store-error`.
- **CLI:** `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_cli.py
  <tool-name> --json <args>`; 12 verbs; payloads equal the tool payloads (goldens frozen per tool).
- **Plan file:** `.ai-badger/task-tracking/plans/<YYYY-MM-DD>-<taskId>.md` (dir auto-created),
  `**S<N> …**` heading per step, one `- [ ]` per AC, generated-banner; `tracking-visibility.md`
  filename/review-exclusion rules unchanged.
- **Root resolution (frozen precedence, R1-F2):** `CLAUDE_PROJECT_DIR` → `project_above(cwd)`
  (marker `.ai-badger/config.json`, worktree collapsed) → `project_above(script_dir, stop=$HOME)`;
  then set `AI_BADGER_TRACKING_ROOT=<resolved>/.ai-badger/task-tracking` before opening the
  vendored store (the `tracker_lib.py:468` pattern). S6 pins the FULL precedence against
  `tracker_lib.resolve_project_root` on a scratch worktree.
- **Idempotency hash:** DR5's `content_hash` normal form + one golden vector.
- **Model ids/patterns:** step `^[a-z0-9][a-z0-9._-]*$`, task `^[a-z0-9][a-z0-9-]*$`.
- **Schema artifact:** `schemas/task-plan.schema.json` (Draft 2020-12, repo `$id`), generated by
  `tooling/task_plan_schema.py` (`--check` deep-equality; wired into `lane_validate`;
  `test_every_check_can_fail` REGISTRY row). Generated schema declares `properties.$schema`
  (R1-F7). `tooling/validate.py` `SCHEMAS_WITHOUT_LOCAL_INSTANCES` gains the entry + reason;
  `docs/scripts.md` gains the tooling row (R1-F3).
- **Env:** `AI_BADGER_TRACKING_ROOT`, `AI_BADGER_JEV*`, `OPENROUTER_API_KEY` (never logged).
- **Interpreters:** every gate string uses `.venv/bin/python3` (or the verify.sh lane); tests use
  `load_script` for script modules and `sys.executable` for server spawns (R2-F9/F22).

## 3. Steps

TDD everywhere (failing test first, RED output pasted); **every** guard gets a red witness (the Do
list is the witness list — R2-F13), including the no-subprocess guard (temporary mutation).
**Every test and subprocess that opens the tracking store sets `AI_BADGER_TRACKING_ROOT` to
`tmp_path`** (R1-F8) and one AC asserts no test path reaches `_default_badger_root()`.
Race tests use a **scheduled interleave** (second connection holds `BEGIN IMMEDIATE` while the first
attempts its CAS) — never timing (R2-F14).

**S1 — version floor** (low, wave 0).
Goal: every later push passes `version-sync`. Do: `VERSION`→`0.179.0`; `docs/changelog/0.179.0-task-decomposition-graph.md` (Minor: New features/Changes/Upgrade notes — upgrade note carries R-D's den-refresh warning); `tooling/changelog_index.py`; run `tooling/version_sync.py` (write) + **one self-scaffold with the guard's remediation `--skills` list (config-derived; NEVER `--skills ''`)** and commit the stamps (R2-F1).
Files: `VERSION`, `docs/changelog/0.179.0-*.md`, `docs/changelog/README.md`, stamp files (`.claude-plugin/*`, `index.json`, `model-groups.json`, `.ai-badger/**` stamps).
AC: (1) `VERSION` = 0.179.0, `changelog_index.py --check` + `version_sync.py --check` green; (2) changelog Minor headings + upgrade note present. Gate: both `--check`s.

**S2 — domain model + schema artifact + sync gate** (high, wave 0).
Goal: typed plan model, checked-in schema, drift gate that can fail. Do: install `pydantic>=2.12,<3` into the repo venv (measure & record the working command — `.venv` has no pip; e.g. `uv pip install --python .venv/bin/python3 …`) and `uv --version` recorded (R2-F9). TDD `tests/test_task_plan_schema.py` (round-trip incl. unicode/timestamps; per-invariant red fixtures V1–V12; emitter deep-equality vs checked-in; `Draft202012Validator` ≡ runtime validator over corpus; schema-passes/model-fails for cycle + unknown-dep + key≠id; mutated-fixture failures; `$schema` alias accepted + excluded from hash). Then `task_plan_model.py`, `task_graph.py` stub (ops land in S5), `tooling/task_plan_schema.py`, regenerate `schemas/task-plan.schema.json`, `engine/requirements.txt` += pydantic, `tooling/validate.py` schemas entry, `docs/scripts.md` row, verify.sh `lane_validate` line, `test_every_check_can_fail.py` REGISTRY row (break it on purpose — red witness), `tests/test_schema_self_description.py` green in the gate.
Files: `features/common/skills/task-decomposition/scripts/task_plan_model.py`, `schemas/task-plan.schema.json`, `tooling/task_plan_schema.py`, `tooling/validate.py`, `docs/scripts.md`, `tests/test_task_plan_schema.py`, `tests/test_every_check_can_fail.py`, `engine/requirements.txt`, `.lefthook/pre-push/verify.sh`.
AC: (1) round-trip stable; (2) V1–V12 red fixtures; (3) `--check` green and red on artifact mutation (witness); (4) dual-validator equivalence; (5) schema/model boundary pinned; (6) `gates/deps_guard.py` + `tooling/validate.py --all` + `tests/test_docs_match_the_catalog.py` + `tests/test_schema_self_description.py` green. Gate: `.venv/bin/python3 -m pytest tests/test_task_plan_schema.py tests/test_every_check_can_fail.py tests/test_schema_self_description.py -q && tooling/task_plan_schema.py --check && gates/deps_guard.py && tooling/validate.py --all`.

**S3 — `plans` store** (medium, wave 0).
Goal: persistence with CAS; every `_VENDORED_GLOBS` copy byte-identical. Do: TDD `tests/test_badger_store_plans.py` (fresh→table+stamp 3; v2→hook; newer stamp fails closed; CAS matrix incl. **scheduled** two-connection interleave → one winner; `created_at` preserved; payload byte-preserved; `json_valid` CHECK rejects garbage; `schema-version-unsupported` path is S6/S7's, not here). Then `engine/badger_store.py` (`_PLANS_DDL`, `UPGRADE_HOOKS[2]`, `plan_row/plan_upsert`); re-vendor every `_VENDORED_GLOBS` file + the skill copy.
Files: `engine/badger_store.py` + all `badger_store.py` under `features/**`/`skills/**`, `tests/test_badger_store_plans.py`.
AC: (1) lifecycle/upgrade/fail-closed green; (2) CAS matrix green (scheduled interleave); (3) `vendored_copies_report()` empty + vendored test green; (4) red witness: mutate the **imported** module's CHECK constraint, scoped run of `tests/test_badger_store_plans.py` flips exactly the garbage-payload test (R2-F20). Gate: `.venv/bin/python3 -m pytest tests/test_badger_store_plans.py tests/test_badger_store_vendored.py -q`.

**S4 — Jev advisory module (skill-side)** (medium, wave 0; disjoint files).
Goal: fail-closed `choice` client + decision prompts, advisory-only. Do: TDD `tests/test_jev_choice_parser.py` (valid; NaN confidence; missing winner probability; impossible winner; out-of-range probabilities; string-number; malformed body; garbage never raises) + `tests/test_jev_client_vendored.py` (byte-compare minus exactly the `TEST_BASE_ENV` line; Budget lives in `jev_choice.py` — expected diff stated) + **fail-safe direction witnesses** (R2-F5: `medium`/`low`/conf<0.6 → no proposal; `serialize`/failure → serialized pair; `share-wave` conf<0.7 → serialize). Prompt literals carried in the fixtures (never parsed from docs — R2-F19). Then `openrouter_client.py` vendored copy, `jev_choice.py` (prompts = fixture literals; gates per DR9; caps `PAIR_CAP=10`/`STATE_CHAR_CAP=32000`/chunking with ACs). Flags off → zero network (poisoned stub asserts it).
Files: `features/common/skills/task-decomposition/scripts/{openrouter_client.py,jev_choice.py}`, `tests/test_jev_choice_parser.py`, `tests/test_jev_client_vendored.py`.
AC: (1) parser matrix + 2 RED witnesses; (2) vendoring equivalence + red on a second changed line; (3) flags-off zero-network; (4) prompt-literal fixture pin; (5) fail-safe directions with red witnesses; (6) caps/chunking behaviour tested. Gate: `.venv/bin/python3 -m pytest tests/test_jev_choice_parser.py tests/test_jev_client_vendored.py -q`.

**S5 — graph ops** (high, wave 1; after S2 — module interface).
Goal: DR7 semantics in `task_graph.py`. Do: TDD `tests/test_task_graph_ops.py` — ready-set correctness + pairwise-unordered property; **deferral-model waves** (wave[0] = admitted ready prefix; every ready member in some wave; no conflicting pair in a wave; red witness flipping the conflict predicate); guard matrix (`dependencies-incomplete`, `criteria-unmet`, `already_complete`, `invalid-transition`+`allowed_transitions`, force bypass records `forced`+note & leaves AC statuses); skipped-dep readiness + `skipped_deps[]`; failed-ancestor `blocked`; `integration_sink` true/false/multi-sink; checklist order/glyphs/tallies; **no-subprocess guard with mutation witness**; every guard in this list gets a red witness (R2-F13).
Files: `features/common/skills/task-decomposition/scripts/task_graph.py`, `tests/test_task_graph_ops.py`.
AC: the list above, each with RED where marked; deterministic waves across runs. Gate: `.venv/bin/python3 -m pytest tests/test_task_graph_ops.py -q`.

**S6 — persistence glue + root resolution** (medium, wave 1; after S2+S3).
Goal: store-backed plan service with the frozen root precedence. Do: TDD `tests/test_task_plan_store.py` (save→load round-trip; `update_step` atomic RMW with **scheduled interleave** → one `conflict`; **full root-precedence pin** vs `tracker_lib.resolve_project_root` incl. collapse on a scratch worktree (R1-F2); `AI_BADGER_TRACKING_ROOT` wins; missing store/table → actionable refusal; **`schema-version-unsupported` raised before pydantic, row untouched** (R2-F10)). Then `task_plan_store.py`.
Files: `features/common/skills/task-decomposition/scripts/task_plan_store.py`, `tests/test_task_plan_store.py`.
AC: (1) round-trip + CAS green; (2) root-precedence pin green + red when the rule changes; (3) refusal + unsupported-version messages name remediation and leave the row untouched. Gate: `.venv/bin/python3 -m pytest tests/test_task_plan_store.py -q`.

**S7 — MCP server + CLI transports** (high, wave 2; after S5+S6).
Goal: 12 tools over stdio JSON-RPC + equivalent CLI. Do: TDD `tests/test_task_graph_mcp_server.py` + `tests/test_task_graph_cli.py` (protocol matrix over real pipes; 12-tool contract per the frozen I/O **fixture** (R1-F1) incl. error codes + `isError`; malformed line → error response + server alive (witness); stdout protocol-only (witness); idempotency incl. `created:false`/`replaced:false`/stale-revision-replaced-false rows and the **golden content_hash vector** (DR5); `plan-in-progress` refusal matrix (R2-F10); `schema-version-unsupported` pre-validation; **render/parse round-trip** — the server-rendered plan file parsed by `status_report.plan_checklist()` (R2-F8); CLI≡MCP equality as an extra check on top of **one golden payload literal per tool** (R2-F17); `load_script`/`sys.executable` conventions). Register `task_graph_server.py --check` in `test_every_check_can_fail` REGISTRY with a hermetic provocation (R2-F6). Then `task_graph_server.py` + `task_graph_cli.py`.
Files: `features/common/skills/task-decomposition/scripts/{task_graph_server.py,task_graph_cli.py}`, `tests/test_task_graph_mcp_server.py`, `tests/test_task_graph_cli.py`, `tests/test_every_check_can_fail.py`.
AC: (1) protocol matrix green; (2) frozen-contract fixture green (12 tools, no `plan_id`, no `advisory`); (3) survival + stdout-purity witnesses; (4) idempotency + golden hash vector; (5) render/parse round-trip; (6) CLI goldens + equality; (7) REGISTRY provocation red→green; (8) one-time **manual MEASURED** `uv run --script … --check` in a clean env (pasted; not a repeatable gate — R2-F18). Gate: `.venv/bin/python3 -m pytest tests/test_task_graph_mcp_server.py tests/test_task_graph_cli.py tests/test_every_check_can_fail.py -q`.

**S8 — MCP catalog packet + declaration** (low, wave 2; disjoint).
Goal: registration so scaffolds wire the server. Do: TDD `tests/test_mcp_task_graph_catalog.py` first. Then `features/common/mcp/task-graph/{meta.json,server.md≤15 lines,tools.json}` (prerequisite per DR3), `features/common/stack-mcp.json` entry, regenerate `index.json`. **Two fixtures** (R2-F7): `uv` resolvable → `.mcp.json`/`.github/mcp.json` entry present; unresolvable → the declaration is still written and the scaffold note carries the exact pinned prerequisite text.
Files: `features/common/mcp/task-graph/**`, `features/common/stack-mcp.json`, `index.json`, `tests/test_mcp_task_graph_catalog.py`.
AC: (1) `validate.py --all` + `index_build.py --check` green; (2) catalog rules green (≤15 lines, intents ≤200, tags closed, prerequisite declared); (3) both fixtures green with exact expected texts. Gate: `.venv/bin/python3 -m pytest tests/test_mcp_task_graph_catalog.py tests/test_mcp_prerequisites.py tests/test_stack_mcp_servers.py -q && tooling/validate.py --all`.

**S9 — `task-decomposition` skill source + first re-scaffold** (medium, wave 3a).
Goal: the skill ships, is machine-checked, and its self-scaffold mirror lands. Do: TDD `tests/test_task_decomposition_contract.py` (dir + `scope: default` + `Use when` description + **the five decomposition rule names** (granularity, actionability, error-propagation, completeness, stop-rules) + join rule + enumerated section headings + references with when-conditions + the degraded-path and CLI command lines); `tests/test_docs_match_the_catalog.py` red first. Then SKILL.md (≤500 lines, `## Gotchas`), `references/{decomposition-method.md,plan-vocabulary.md,mcp-plan-tools.md}` (method per P3-C1; vocabulary = P3-C2 dispositions + DR11 normalisation table + `query_pipeline.py` pin reason; tools reference names all 12 frozen tools + the exact CLI command + DR12 degraded path with R-B's honest wording (R3-F14)); `docs/skills.md` row/section/numerols (recompute at run time). Then `index_build.py`, `sync_plugin_skills.py`, and the **self-scaffold with the config-derived `--skills` list** — AC asserts `.ai-badger/skills/task-decomposition/SKILL.md` appears in the diff (R3-F1).
Files: `features/common/skills/task-decomposition/**`, `docs/skills.md`, `index.json`, `skills/task-decomposition/**`, `tests/test_task_decomposition_contract.py`, `.ai-badger/**` (scaffold output).
AC: (1) contract test red→green (RED pasted) incl. the five rule names; (2) `gates/skills_lint.py` + `validate.py --all` green; (3) docs numerals green at the recomputed set; (4) plugin mirror + `sync_plugin_skills.py --check` green; (5) `index_build.py --check` green (after S8's entry — S9 depends on S8); (6) re-scaffold diff contains the new mirror + manifest row; `scaffold_freshness_guard` green. Gate: the above command set.

**S10 — task/quick-task pipeline rewrite + vocabulary pins** (medium, wave 3b; serial after S9 — shared `.ai-badger/**` via re-scaffold; `[Q1]` decides the quick-task sentence).
Goal: P3-C2 rewrite map applied with per-row test assertions. Do: TDD `tests/test_task_pipeline_vocabulary.py` — **one required new sentence per rewritten C2 row** (R2-F12) across `task/SKILL.md`, both `task/extensions/*`, `multi-agent-communication`, `worktree-agent-isolation` (SKILL+ref), `personas/delegator.md` note, `complete-project-scope-code-review` note, `quick-task`; forbidden strings (`subpackage`, `last package is the integration package`, `**P<N>**` in task SKILL, stale tool names `plan_build`/`plan_progress`/`ac_record`/`plan_state`) + required 12 frozen names present (R1-F5); **loop/effort disambiguation rows** (R3-F10): `task/SKILL.md:44,134,166,169,366` + Model-tier contract reworded to "task `loop` (low|high) vs step `effort` (low|medium|high) → model tier". Then rewrite per the disposition table + DR12's "no plan row → legacy file" sentence.
Files: listed skill files + `tests/test_task_pipeline_vocabulary.py`.
AC: (1) pin test red→green (RED pasted) covering every row; (2) every C2 row + R3-F10 lines dispositioned in the report; (3) `gates/skills_lint.py` green catalog-wide. Gate: `.venv/bin/python3 -m pytest tests/test_task_pipeline_vocabulary.py tests/test_skills_lint.py -q && gates/skills_lint.py`.

**S11 — status-report + tracking compatibility** (medium, wave 3b; parallel with S10 — disjoint files).
Goal: progress reads graph first, legacy second. Do: TDD `tests/test_status_report.py` additions (red: `**S<N>**` headings, mixed P/S counts, `[step]` render, unchanged placeholders/exit-0/keys, **hand-written fallback fixture parses+renders** (R3-F8)). Then `status_report.py` (`STEP_RE`, render split), `status-report/SKILL.md:56,81` (**frozen mapping (R3-F7): `progress_checklist format:"text"` is the section verbatim; script output is the fallback** — pinned against a fixture), `task/references/tracking-visibility.md:24-30` (server-rendered plan, `**S<N>**`, fallback rules).
Files: `features/common/skills/status-report/{SKILL.md,scripts/status_report.py}`, `features/common/skills/task/references/tracking-visibility.md`, `tests/test_status_report.py`.
AC: (1) new tests red→green (RED pasted); (2) legacy P tests green; (3) keys/exit-0 unchanged (asserted); (4) SKILL mapping pinned against the fixture. Gate: `.venv/bin/python3 -m pytest tests/test_status_report.py -q && gates/skills_lint.py`.

**S12 — dependency declarations + honest claims** (medium, wave 3b; parallel).
Goal: every dependency claim true. Do: `features/common/dependencies.json` += `uv` (system; feature `task-decomposition`; note: PEP 723 fetches `pydantic>=2.12,<3` into uv's cache; the server does not use the project venv); `README.md:392-396`, `docs/getting-started.md:159`, `docs/authoring-a-feature.md:26`, `.ai-badger/config.json project.summary`; extend `tests/test_dependency_honesty.py` if the pin needs it (`OVERCLAIM` guard stays green).
Files: `features/common/dependencies.json`, `README.md`, `docs/getting-started.md`, `docs/authoring-a-feature.md`, `.ai-badger/config.json`, `tests/test_dependency_honesty.py`.
AC: (1) `gates/deps_guard.py` green; (2) honesty test green, no OVERCLAIM; (3) prose + summary state the true posture. Gate: `gates/deps_guard.py && .venv/bin/python3 -m pytest tests/test_dependency_honesty.py -q`.

**S13 — JOIN: cross-step integration + release finish** (high, wave 4; `depends_on`: S1–S12).
Goal: prove the assembled whole on the merged tree and ship. Do (TDD): `tests/test_task_graph_integration.py` FIRST (red) — decompose a fixture brief → `plan_create` → wave/deferral dispatch simulation → `step_start`/`ac_check`/`step_complete` chain → `progress_checklist` (text section) → render/parse round-trip through `status_report.plan_checklist()` → `plan_replace` `plan-in-progress` refusal mid-execution → export schema-valid under **both** validators → degraded-path fixture (no server: hand-written plan file reports). Then green on the merged tree; **host smoke (manual, MEASURED — R3-F3)**: launch under Claude Code and pi (Copilot if available), `initialize`/`tools/list`/one `tools/call`, pasted; on protocol-shape failure apply R-A's flip, on launch-path failure apply P2-B3's shim flip; if unautomatable, recorded as an owner-performed acceptance check. Then the combined gate set (`validate.py --all`, `index_build.py --check`, `sync_plugin_skills.py --check`, `task_plan_schema.py --check`, `version_sync.py --check`, `changelog_index.py --check`, `release_guard`, `docs_guard`, `scaffold_freshness_guard`); release finish (changelog final → `index_build` → `changelog_index` → `version_sync` → **re-scaffold with the config-derived list** for stamps + S12's summary render); optional `.mcp.json.example` refresh; join review of every merged seam (S2→S5 module, S8→S9 index, S9→S10→S11→S12 scaffold output). **Push the branch; CI is the pass condition for the full suite** (R2-F15) — local runs the touched surface once; one documented local full run only if CI is dead.
Files: `tests/test_task_graph_integration.py`, `docs/changelog/**`, `.claude-plugin/*`, `index.json`, `features/common/data/model-groups.json`, `.ai-badger/**`.
AC: (1) integration test red→green (RED pasted) incl. render/parse + degraded fixture; (2) host smoke recorded (MEASURED or owner-performed); (3) all gates green, output pasted; (4) CI green on the pushed head (reported) or documented local full run; (5) re-scaffold diff clean except stamps/summary + the new skill. Gate: the gate set + `.venv/bin/python3 -m pytest tests/test_task_graph_integration.py -q`.

## 4. Execution model & parallelism (folds R2-F1/R3-F1)

- **Lanes are isolated**: each implementation lane gets its own git worktree + `lane/<step-id>`
  branch off the task branch and its own workspace id; TDD; per-lane briefs carry the interface freeze.
- **The orchestrator owns the joins**: at each wave end, merge lane branches into the task branch
  (join review on the merged result), **re-scaffold + regenerate `index.json`/stamps in the merge
  commit** (only the orchestrator touches `.ai-badger/**`, which removes every re-scaffold
  collision between parallel lanes), then push the task branch (CI gate) before the next wave.
  The re-scaffold always uses the config-derived `--skills` list (guard remediation form) —
  `--skills ''` would re-deliver the stale manifest set and is forbidden (R3-F1).
- **Push-green invariant**: every push of the task branch carries committed stamps + scaffold
  mirror, so `version-sync`/`scaffold` lanes are green at push time (R2-F1). Mid-wave lane-branch
  pushes (if any) may use the printed `VERIFY_SKIP=scaffold,version-sync` form and must say so.
- Waves: 0 = S1‖S2‖S3‖S4 (disjoint) → 1 = S5 (after S2) ‖ S6 (after S2+S3) → 2 = S7 (after
  S5+S6) ‖ S8 → 3 = S9 (after S8) → then S10‖S11‖S12 (S10 after S9) → 4 = S13 (join).
- Effort→tier: S2/S5/S7/S13 high (architect/code-reviewer lanes per `delegation.md`); rest medium
  (api-engineer/test-engineer lanes); S1/S8 low. Explicit `model` never passed — `level` via registry.

## 5. Risks (folds R1-F9/F10)

R-A host rejects the hand-rolled loop → DR2 flip (`mcp` SDK behind same handlers).
R-B first `uv run --script` needs network on a cold cache **for both server and CLI**; warm cache
or the hand-written file path afterwards (R3-F14).
R-C vendoring misses a copy → `vendored_copies_report()` + vendored test.
R-D **v3 `tracking.db` is unreadable by every pre-0.179 vendored copy** (task lifecycle hooks,
statusline, tracker CLIs) — changelog Upgrade note: *run den-refresh before the next task
command*; no test or step opens the repo's real tracking root (tmp-pinned) and the orchestrator's
own tracker calls run on the main checkout's v2 code until the release lands.
R-E plan-file/graph drift → generated banner + graph single-source.
R-F host cwd=project-root HYPOTHESIS (P2-B3) → S13 host smoke; flip = `~/.local/bin/task-graph`
shim + bare command + `availability.command`.

| step | effort | wave | gate | ACs |
|---|---|---|---|---|
| S1 | low | 0 | changelog_index + version_sync `--check` | 2 |
| S2 | high | 0 | schema `--check` + pytest + deps_guard + validate | 6 |
| S3 | medium | 0 | pytest store + vendored | 4 |
| S4 | medium | 0 | pytest jev | 6 |
| S5 | high | 1 | pytest ops (witness list) | 2 |
| S6 | medium | 1 | pytest store glue | 3 |
| S7 | high | 2 | pytest mcp+cli (+ manual uv/host smokes) | 8 |
| S8 | low | 2 | catalog pytest + validate | 3 |
| S9 | medium | 3a | contract pytest + skills_lint + index/plugin + scaffold | 6 |
| S10 | medium | 3b | pin pytest + skills_lint | 3 |
| S11 | medium | 3b | status pytest + skills_lint | 4 |
| S12 | medium | 3b | deps_guard + honesty pytest | 3 |
| S13 | high | 4 (join) | integration pytest + all gates + CI + release ritual | 5 |

Plan AC: every step's ACs checked and met; S13's join ACs met on the merged tree.

## 6. Owner gate — CLOSED 2026-09-28T16:39Z (owner-gate-review, 4/4 APPROVE)

Rulings (`docs/work/2026-09-28-task-decomposition-owner-gate-feedback.md`, storageKey
`refinement:aib-task-decomposition-workflow-graph-mcp:owner-gate:v1`, answered 4/4, no open items):

- **D1 (was Q1) APPROVE** — quick-task stays decomposition-free; S10's boundary sentence + pin test stands.
- **D2 (was Q2) APPROVE** — Jev ships as default-off advisory (upgrade-only ≥0.6, serialize-safe
  hints); deterministic logic is the source of truth (DR9 as written).
- **D3 (was Q3) APPROVE** — pydantic via `uv run --script` (prerequisite `uv`) + stdlib `graphlib`
  (networkx remains the one-module swap) (DR1–DR3 as written).
- **O1 APPROVE** — the live MCP host smoke is an owner-performed acceptance check if the lanes
  cannot automate it (S13 AC(2) as written).
