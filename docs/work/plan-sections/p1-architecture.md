## A1 — Where the server lives and how it launches (ruling on D3)

**Forced choice: skill-scoped, zero-dependency, stdlib-only server; MCP descriptor carries no code; a CLI on the same module is the sanctioned fallback transport.** Layout:

```
features/common/skills/task-decomposition/scripts/
  task_graph.py          # canonical domain: model, validation, graph ops, schema emitter (pure, stdlib)
  task_graph_store.py    # persistence + root resolution (imports task_graph + vendored badger_store)
  task_graph_cli.py      # argparse transport over task_graph_store
  task_graph_mcp.py      # hand-rolled stdio JSON-RPC MCP transport over task_graph_store
  badger_store.py        # vendored copy #13 (byte-identical, test-enforced)
features/common/mcp/task-graph/{meta.json,server.md,tools.json}   # descriptor only
features/common/stack-mcp.json                                    # declaration
schemas/task-plan.schema.json                                     # repo artifact, emitted by task_graph.py
```

Declaration: `"command": "python3 .ai-badger/skills/task-decomposition/scripts/task_graph_mcp.py"` (stack-mcp schema splits on whitespace; `.mcp.json` expands `${VAR}`, `.github/mcp.json` is tracked — verified: `git check-ignore .mcp.json` → ignored, worktree has no `.mcp.json` but does have `.github/mcp.json`). `meta.json.prerequisite = {summary: "Python 3.10+ on PATH — the server is stdlib-only, nothing to install", check: "python3 -c ..."}` (every declared server must carry one or explicitly none — `tests/test_mcp_prerequisites.py:63-80`).

Why not the alternatives: (a) `features/common/mcp/<name>/scripts/` is never delivered to consumers — the semantica packet's own test says that path is "No such file or directory" in a scaffold; shipping code there needs a new delivery mechanism in `mcp_tools.py` plus its gates. (c) framework-only fails by definition — `task`/`quick-task` execute inside consumer projects. Pydantic/networkx as runtime deps are rejected (overrules D1's implementation vehicle, keeps its `Workflow` facade idea): only `python3` + a vendored stdlib store is the established consumer contract (`task_tracker.py` runs as `python3 .ai-badger/skills/task/scripts/...` today); pydantic-core cannot be vendored; a runtime that imports them dies at process start on every machine that did not install them, and `dependency_check.py` reports, never installs. `mcp` SDK is rejected for the same reason (it pulls pydantic); the protocol subset needed (initialize / tools-list / tools-call / ping / cancelled) is ~200 lines. **HYPOTHESIS:** current host clients (Claude, Copilot, pi) accept a hand-rolled server against the 2024-11/2025-06 revisions. **Counter-argument (strongest):** networkx is pure-Python, BSD, zero-transitive, and pydantic gives schema generation and validation free; if the server only ever ran framework-side, the dependency cost vanishes. **Flip condition:** the owner makes "networkx + pydantic ship to consumers" binding, or accepts an install step in `dependencies.json` plus the 8 pinned-claim-file churn (`test_dependency_honesty.py`), or a host rejects the hand-rolled loop.

Root resolution: at call time — `AI_BADGER_TRACKING_ROOT` → walk up from cwd for `.ai-badger/manifest.json` → collapse a linked worktree to its main checkout (`git worktree list --porcelain`, first entry), exactly `tracker_lib.collapse_worktree`'s rule, because task-tracking state deliberately lives in the main checkout (worktree-local DBs are empty by design, B12). Duplicated ~40 lines, pinned by an equivalence test against `tracker_lib.collapse_worktree` on a scratch worktree. The **CLI fallback is load-bearing, not a nicety**: Claude/pi worktree sessions lose `.mcp.json` (gitignored, not copied into worktrees), and the task pipeline runs in a worktree.

No new consumer dependency, no `engine/requirements.txt` entry, so the "stdlib-only except two declared dependencies" claim and its 8 pinned files stay true.

## A2 — Domain model and validation invariants

**Ruling: extend R3 §4; delete three things it carried.** Full shape (all objects `extra="forbid"` equivalent — unknown keys are rejected):

- `TaskPlan`: `schema_version` (const 1, fail-closed forward compat), `task_id` (the store key — R3's separate `plan_id` is deleted: one plan per task in v1, and two keys for one identity is a drift source), `task_description_ref` (required; path/URI of the issue/spec/markdown plan — the request's "reference to full description"), `research_ref` (optional; the analyze/research record the decomposition consumed — provenance for the Phase 1→2 pipe), `task_context` (short human line), `loop` (`low|high` — which task loop gates QA/MoE steps; distinct from step effort), `revision` (int ≥ 0, server-owned), `created_at`/`updated_at` (ISO-8601 UTC), `workflow`.
- `Workflow.steps`: map keyed by step id (duplicate ids must be unrepresentable), ≥1 step.
- `Step`: `id`, `goal`, `instructions`, `effort` (`low|medium|high`, required), `depends_on`, `acceptance_criteria`, `status`, `started_at?`, `completed_at?`, `completion?`, `level?`, `model?`, `persona?`. `level`/`model` exist only to compose with the existing delegation precedence (A5) — without them a step cannot express "medium derivation, high tier". `persona` is optional because `personaRouting` is config-owned and re-deriving it from prose is exactly the failure the plan format should prevent. `started_at`/`completed_at` are the transition record; `completion` is the close-out.
- `AcceptanceCriterion`: `id`, `statement`, `check?` (the run that proves it — the plan-format quality gate), `status` (`unchecked|passed|failed`), `evidence[]`. R3's `Completion.criterion_results` duplicate is **deleted** — AC status is the single source; completion carries only `completed_by?`, `forced` (bool), `note?`, `evidence[]`.
- `Evidence`: `kind` (`command|test|artifact|review|note`), `summary`, `ref?`, `recorded_at`.

Invariants (rejection at build **and** load; corrupt rows fail closed with an actionable message, never crash):
V1 steps non-empty. V2 map key == `step.id`. V3 id patterns (`step ^[a-z0-9][a-z0-9._-]*$`, `task_id ^[a-z0-9][a-z0-9-]*$`). V4 `depends_on` all known, no self-loop. V5 acyclic, error names the cycle. V6 AC ids unique within a step; empty AC lists are *structurally* legal but a plan-quality finding (`step_without_acs`). V7 unknown keys rejected at every level. V8 enums closed (all five listed above + `loop`). V9 `schema_version == 1`, `revision ≥ 0`. V10 timestamps ISO-8601 UTC. V11 completion consistency: `status == complete ⇒ completed_at`; any un-passed AC at rest ⇒ `completion.forced` true and a non-empty `note` (force stays visible); `in_progress ⇒ started_at`. V12 `completed_at ≥ started_at` when both present.

**D6 ruling: "the last package is the integration package" maps to a derived join, never a stored field.** `integration_sink(plan)` = a step whose ancestor set is every other step. Structural validation must **not** reject its absence (drafts, low-effort plans); `plan_state` returns `integration_ok` plus the finding, and the task skill requires it for the high-effort loop. No `integration_step_id` field — derivable, so not stored.

## A3 — Persistence (ruling on D4)

**Ruling: `plans` table in `tracking.db` via the Family/DDL/UPGRADE_HOOKS path; CAS on an integer revision; no JSON-file fallback.** Born in SQLite like the message-bus tables: `SCHEMA_VERSION = 3`, `UPGRADE_HOOKS[2] = _upgrade_v2_to_v3` with `_PLANS_DDL` (idempotent `CREATE TABLE IF NOT EXISTS`), and no `Family` entry (born-in-SQLite tables are not registered — `messages`/`cursors` set that precedent).

```sql
plans(task_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      CHECK (json_valid(payload)), CHECK (revision >= 0));
CREATE INDEX IF NOT EXISTS idx_plans_updated_at ON plans(updated_at);
```

Store accessors (in `engine/badger_store.py`, then re-vendored): `plan_get(task_id) → row|None`; `plan_put(task_id, payload, expected_revision=None) → revision` (INSERT when absent; `UPDATE ... WHERE task_id=? AND revision=?` when present; 0 rows → `PlanConflict`; `created_at` preserved, `revision`/`updated_at` server-stamped); `plan_payload(task_id)`. Whole-document JSON column per ADR-0024 decision 11 (access pattern is whole-document, like `token_usage.subagents`).

Concurrency: every mutation runs read→validate→mutate→CAS inside one `BEGIN IMMEDIATE` (the store already opens WAL, `busy_timeout=5000`, `synchronous=NORMAL`), so `step_update` is atomic and a competing `task_tracker` writer or a second server blocks cleanly. No `plan_events` table in v1 (completion evidence and timestamps are the transition record); revisit when a consumer needs queryable history.

Re-vendoring is mechanical but mandatory in the same change: all 12 existing copies plus copy #13 must be byte-identical, `test_badger_store_vendored.py` globs `features/**` and `skills/**` (not `.ai-badger/**`) and fails otherwise. Consequence to state in the changelog: old copies opening a v3 DB fail closed by design with the den-refresh pointer (ADR-0024 decision 4), so consumer refresh must carry all copies together. **Counter-argument:** a separate `plan-graph.db` avoids coupling schema versions to the task family. **Flip:** if two independent schema upgrade cadences are actually required; today a separate DB contradicts ADR-0024 decision 1 and buys nothing.

## A4 — Transition semantics, guards, waves, progress

**Ruling: an explicit five-state machine; the server performs atomic read-modify-write; no server-side command execution.** States `pending → in_progress → {complete, failed, skipped}`; `failed → in_progress` (retry) allowed; `skipped` terminal; `complete` terminal (no reopen without a structural edit through `plan_put`).

- `ready(plan) = {pending|failed : every dep complete}`. Members are pairwise unordered by construction (the DAG-ready set *is* the parallel frontier); `in_progress` members block their successors and are excluded.
- `waves(plan)` = Kahn generations over the **remaining** steps (pending/in_progress/failed): generation 0 == `ready` exactly. Deterministic ordering (declaration order within a generation). Waves are display/dispatch advisory, recomputed on every call — never stored.
- `blocked(plan)` = steps with a failed/skipped ancestor (derived; shown so nothing silently disappears).
- `step_update` guards: `start` requires `ready` and status ∈ {pending, failed}; `complete` requires all deps complete **and** every AC `passed`, unless `force=true` with a non-empty note (unresolved ACs stay unresolved and the step renders as forced — V11). Refusals are stable codes: `unknown_step`, `invalid_transition`, `dependency_incomplete`, `ac_unresolved`, `already_complete`, `plan_missing`, `revision_conflict`, `invalid_plan`.
- AC checking: the caller records results and evidence; **the server never runs `check`** — the executing agent's approval/sandbox flow owns gate execution. **Counter:** auto-running `check` captures exact output. **Flip:** owner asks the server to own gate execution, at which point subprocess policy/timeout/sandbox becomes a first-class design.
- Progress checklist (derived, never stored): topological order; glyphs `[ ]/~[x]/!/-`; per-step `acs_passed/acs_total`; header complete/total steps; forced steps visible via their AC tally. Output keeps the keys `status_report.py` already consumes (`plan_file`, `matched`, `packages`, `checked`, `total`) plus graph-native fields (`task_id`, `revision`, `waves`, `ready`, `blocked`, `integration_ok`); P3 decides whether to keep the legacy keys.
- No `resources`/exclusivity field in v1: with per-lane worktrees, DAG-derived waves are the honest frontier, and R4 found no fixture set for anything finer. **Counter:** external shared resources (ports, services, a shared test DB) have no representation. **Flip:** an observed wave collision on a shared external resource — then add one optional field and a greedy resource-aware wave pass.

## A5 — `effort` → model tier, and the Jev layer (ruling on D2)

**Exact precedence (declaration → resolution):**

1. `step.model` (explicit pin) wins outright — no registry read.
2. else `step.level` → `model_groups.resolve(level=step.level)` (`.ai-badger/skills/task/scripts/model_groups.py`).
3. else `effort` maps to level **identically** (`low→low`, `medium→medium`, `high→high`) → `model_groups.resolve(level=effort)`. The identity is not a covert second knob: `delegation.md`'s three levels ("derived / spec-determined / transformation") *are* the step-effort semantics, so a separate default tier would be one decision with two names. `level` exists only as an explicit override (e.g. a security-sensitive medium-effort step that still needs adversarial reading).
4. else (no registry resolvable) → `None` = inherit session/parent default.

Resolution stays in the **dispatch path**, not the server: the server returns `effort`/`level`/`model` verbatim plus `tier_input = level or effort`; there is no vendored second copy of `model_groups.py` and no duplicate precedence logic. The server never reads `model-groups.json`.

**D2 ruling: Jev is an advisory proposer only, flag-gated off by default, and it lives in the skill scripts — never in the local-only server.** `AI_BADGER_PLAN_JEV=1` runs the ported `choice` call at plan time over the step set; it may propose **upgrades only** (confidence ≥ 0.6), never demotes, never writes the plan; results land as plan-review notes. The server stays offline by contract. **Counter (strongest):** the owner explicitly asked for Jev, and the port is small. **Flip:** an eval fixture set showing Jev's tier choice beating the effort rubric on a meaningful share of disagreements, or an owner instruction to ship it on by default. Step E8 is therefore marked cuttable at plan review; if cut, R4's prompts ship as a reference document owned by P3.

## Critique — P2's MCP API contract, as it constrains this architecture

Keep the surface at **four tools** (`plan_put`, `plan_get`, `step_update`, `plan_state`): every mutation must be one server-side read-modify-write so the CAS/revision guard actually protects concurrent writers; a per-AC `check_ac` verb, per-edge verbs, or a client-supplied revision on `step_update` would force client-side read-modify-write and silently reintroduce lost updates. Validation failures from `plan_put` must be structured findings (invariant id + path), not JSON-RPC internal errors; refuse-don't-repair. Tool outputs must be domain objects, not the storage payload; stable error codes come from A4. A `propose_tier` tool would duplicate the resolver — keep tier resolution out of the server. `tools.json` tags must come from the closed vocabulary (`read`, `write`, `run`, `diagnostic` fit).

## Critique — P3's skill integration, as it constrains this architecture

P3 must bless the **CLI fallback** in the `task-decomposition`/`task` text, because the Claude and pi worktree sessions have no `.mcp.json` (measured: gitignored, absent here; only Copilot's tracked `.github/mcp.json` survives) and the entire task pipeline executes inside a worktree — an MCP-only flow dies exactly where it is used. Progress must stay single-sourced: once a plan exists, the graph is the truth and `status_report.py` stays stdlib, exit-0, file-fallback (its caller invokes the tool or CLI; the script cannot). The `**P<N>**` plan file remains the *human* plan and must not stay a second machine-readable progress counter. `quick-task` creates no plan artifacts and escalates past six bullets. P3's `SKILL.md` + registration surfaces gate E6/E7 (the directory must exist with a SKILL.md before `index_build`/scaffold freshness can see it).

## Proposed steps

All steps are TDD-ordered: failing test first, red witness for every new guard, then green. Waves share files only where named.

**E1** — domain model, validation, schema emitter. `task_graph.py` (new), `schemas/task-plan.schema.json` (emitted + checked in), `references/task-plan.schema.json` (shipped copy, pinned equal), `tests/test_task_graph_model.py`. ACs: (1) round-trip stability; (2) each V1–V12 invariant has a red fixture test; (3) emitter output byte-equals the checked-in schema; (4) `jsonschema.Draft202012Validator` verdicts equal the runtime validator over the fixture corpus; (5) cycle-guard red witness recorded (disable check → exactly the cycle test fails). **High**, wave 0.

**E2** — graph ops. `task_graph.py` (same file as E1 → serialized), `tests/test_task_graph_ops.py`. ACs: (1) ready set correctness + pairwise-unordered property; (2) waves == Kahn generations with `ready == wave[0]`, deterministic; (3) `start`/`complete` guard matrix incl. `dependency_incomplete`, `ac_unresolved`, `already_complete`; (4) force bypass records `forced` + note and leaves AC statuses untouched; (5) `integration_sink` true/false/single-step; (6) checklist order/glyphs/tallies; (7) no subprocess in the module (check strings never executed). **High**, wave 1.

**E3** — store: `plans` DDL + SCHEMA_VERSION 3 + hooks + accessors. `engine/badger_store.py`, all 12 existing copies + new copy in the decomposition skill, `tests/test_badger_store_plans.py`. ACs: (1) fresh DB → table + stamp 3; v2 DB → hook upgrade; newer stamp still fails closed; (2) CAS: stale `expected_revision` → `PlanConflict`, no row mutation; revision increments; `created_at` preserved; (3) payload byte-preserved on read; `json_valid` CHECK rejects garbage; (4) two-process concurrent CAS leaves exactly one winner; (5) `vendored_copies_report()` empty. **Medium**, wave 0.

**E4** — persistence glue + root resolution. `task_graph_store.py` (new), `tests/test_task_graph_store.py`. ACs: (1) save→load round-trip preserves statuses/evidence/revision; (2) `update_step` atomic RMW — interleaved writers produce one conflict, no lost update; (3) worktree collapse equivalence with `tracker_lib.collapse_worktree` on a scratch worktree, env override wins; (4) missing store/table → actionable refusal. **Medium**, wave 1.

**E5** — transports. `task_graph_cli.py`, `task_graph_mcp.py` (new), `tests/test_task_graph_cli.py`, `tests/test_task_graph_mcp.py`. ACs: (1) initialize/tools-list/tools-call over real pipes; (2) four tools; stable error codes as `isError`; (3) malformed line → error response, server stays alive (red witness on the handler); (4) CLI and MCP produce identical payloads for the same call; (5) stdout is protocol-only, logs on stderr. **Medium**, wave 2.

**E6** — catalog registration. `features/common/mcp/task-graph/{meta.json,server.md,tools.json}`, `features/common/stack-mcp.json`, regenerated `index.json`; `tests/test_mcp_task_graph_catalog.py`. ACs: (1) `tooling/validate.py --all`; (2) `tooling/index_build.py --check`; (3) `server.md` ≤15 lines, tags closed, prerequisite recorded; (4) scratch scaffold writes the entry into `.mcp.json`/`.github/mcp.json`. **Low**, wave 3 (shares catalog/index files with P3).

**E7** — release. `VERSION` → `docs/changelog/0.179.0-*.md` → `changelog_index.py` → `version_sync.py` → re-scaffold last. ACs: (1) `version_sync.py --check`, `changelog_index.py --check`, `release_guard`, `docs_guard`, `scaffold_freshness_guard` pass; (2) `.ai-badger/skills/task-decomposition/` ships scripts + byte-equal store; (3) plugin mirror synced. **Low**, wave 4, serial (touches every generated file).

**E8** — Jev advisory (**cuttable**). `features/common/skills/task-decomposition/scripts/jev_choice.py`, `tests/test_jev_choice.py`. ACs: (1) fail-closed `choice` parser port (unknown choice → None, missing confidence → 0, clamp, never raises); (2) flag off → zero network, resolution unchanged; (3) loopback test seam; key never logged; (4) payload pinned to R4 §3. **Medium**, wave 0; cut if the review accepts A5's recommendation.

| step id | effort | wave | files owned | gate | AC count |
|---|---|---|---|---|---|
| E1 | high | 0 | `features/common/skills/task-decomposition/scripts/task_graph.py`; `schemas/task-plan.schema.json`; skill `references/task-plan.schema.json`; `tests/test_task_graph_model.py` | `pytest tests/test_task_graph_model.py -q` + schema-byte check | 5 |
| E3 | medium | 0 | `engine/badger_store.py` + 12 copies + skill copy; `tests/test_badger_store_plans.py` | `pytest tests/test_badger_store_plans.py tests/test_badger_store_vendored.py -q` | 5 |
| E8 | medium | 0 (cuttable) | skill `scripts/jev_choice.py`; `tests/test_jev_choice.py` | `pytest tests/test_jev_choice.py -q` | 4 |
| E2 | high | 1 | `task_graph.py` (serialized after E1); `tests/test_task_graph_ops.py` | `pytest tests/test_task_graph_ops.py -q` + guard red witness | 7 |
| E4 | medium | 1 | skill `scripts/task_graph_store.py`; `tests/test_task_graph_store.py` | `pytest tests/test_task_graph_store.py -q` | 4 |
| E5 | medium | 2 | skill `scripts/task_graph_cli.py`, `scripts/task_graph_mcp.py`; `tests/test_task_graph_cli.py`, `tests/test_task_graph_mcp.py` | `pytest tests/test_task_graph_cli.py tests/test_task_graph_mcp.py -q` | 5 |
| E6 | low | 3 | `features/common/mcp/task-graph/{meta.json,server.md,tools.json}`; `features/common/stack-mcp.json`; `index.json`; `tests/test_mcp_task_graph_catalog.py` | `python3 tooling/validate.py --all && python3 tooling/index_build.py --check` | 4 |
| E7 | low | 4 (serial last) | `VERSION`; `docs/changelog/0.179.0-*.md`; `docs/changelog/README.md`; `index.json`; plugin/marketplace JSON; `model-groups.json`; `.ai-badger/**` re-scaffold | `version_sync.py --check && changelog_index.py --check && gates/release_guard.py && gates/docs_guard.py && gates/scaffold_freshness_guard.py` | 3 |