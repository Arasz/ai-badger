# Research record — task-decomposition skill + DAG task-plan model + task-graph MCP server

Task: `aib-task-decomposition-workflow-graph-mcp` · Date: 2026-09-28 · Branch: `task/aib-task-decomposition-workflow-graph-mcp` (base `f40d8240`)

Method: four parallel read-only research lanes, consolidated here per `multi-lane-report-assembly`.
Authoritative full summaries (verbatim, untruncated) — the appendices to this record:

| Lane | File | Grade labels used |
|---|---|---|
| R1 integration surface | `docs/work/research-lanes/r1-integration-surface.md` | READ/HYPOTHESIS |
| R2 task-pipeline seams | `docs/work/research-lanes/r2-task-pipeline-seams.md` | READ/HYPOTHESIS |
| R3 graph lib + model | `docs/work/research-lanes/r3-graph-lib-and-model.md` | MEASURED/READ/INFERRED/UNVERIFIED |
| R4 Jev decisions | `docs/work/research-lanes/r4-jev-decisions.md` | MEASURED/READ/INFERRED/UNVERIFIED |

Findings below are lifted from those summaries; everything unverified is labelled. Nothing here is
from memory — where a claim came from an earlier run (e.g. the Jev latency numbers) the grade of
the original applies and is re-cited.

## 0. Request coverage — every point of the request, and what is guess vs. researched

| # | Request point | Status | Where settled |
|---|---|---|---|
| 1 | New skill `task-decomposition`, used by `task` and `quick-task` | RESEARCHED (exact 5-surface registration map) | R1 §1, §5 |
| 2 | After research/analyze, pipe results to `task-decomposition` → decomposed task (steps) | RESEARCHED (slot found: task Phase 1 injection `task/SKILL.md:176-180` + Phase 2 `:210-216`, R2 §4) | R2 §4, §6 |
| 3 | Replace packages/subpackages with `step` (simplification) | RESEARCHED (164 line-hits/64 files census; [P] planning hits separated from [S] software-package hits that must NOT change) | R2 §1 |
| 4 | JSON schema for the types; pydantic for typing | RESEARCHED (pydantic `model_json_schema()` → Draft 2020-12, matches repo's existing `jsonschema.Draft202012Validator` use) | R3 §4 |
| 5 | `task-plan` type: task context, id, reference to full description + more; `workflow` field = directed graph of `step`s | RESEARCHED (draft model with `extra="forbid"`, key==id validator, DAG validation) | R3 §4 |
| 6 | `step` = effort (→ model), instructions, goal, acceptance criteria | RESEARCHED (draft `Step`; effort enum low/medium/high per `.ai-badger/delegation.md:42-47`) | R3 §4 |
| 7 | Use an existing graph lib — "research GraphLang model" | RESEARCHED: "GraphLang" disambiguated — most plausibly **LangGraph** (INFERRED, ~65%), literal `graphlang` PyPI package exists but is 0.0.1/1★ abandoned DSL on top of LangGraph (MEASURED). LangGraph itself **rejected** as an execution engine (≈39 transitive deps incl. langchain-core/langsmith) | R3 §1–§3 |
| 8 | `task` skill: steps move into the graph | RESEARCHED (sentence inventory with line numbers for the rewrite) | R2 §5 |
| 9 | Graph build/retrieve/mark-complete/AC-check/transitions done by code behind a small local-only stdio MCP server | RESEARCHED (operation mapping table; MCP registration map; **open**: where server code lives — see D3) | R3 §5, R1 §2 |
| 10 | Choices (model use, parallel-able) via "JAV" with correctly defined prompt | RESEARCHED: "JAV" = **Jev** (`typesafe/jev-1.13`, OpenRouter `/api/alpha/decisions`) — confirmed against `.ai-badger/state.json:3` + `docs/work/2026-09-28-jev-decision-points.md`; prompts designed; **forced judgments: both choices are better decided deterministically, Jev kept as an advisory layer** (see D2) | R4 §2–§4 |
| 11 | Other skills adjusted; progress-update MCP tool (graph state → checklist) for status-report | RESEARCHED (seam: `status_report.py:165-179,295-315,338-355`; script is stdlib-only and cannot itself call MCP → the caller invokes the tool, script keeps file fallback) | R2 §3, §6 |

Nothing in the request is left as pure guess. Residual hypotheses are carried inside the
decisions table (§3) and the lane files.

## 1. Load-bearing findings (by lane)

**R1 — integration surface.** A new skill needs 5 coordinated surfaces: `features/common/skills/<name>/`
(canonical; frontmatter rule set incl. `scope: default|optIn`, skills_lint rules 1–13), the plugin
mirror `skills/<name>/` (`tooling/sync_plugin_skills.py`), the self-scaffold mirror
`.ai-badger/skills/<name>/` (re-scaffold, `gates/scaffold_freshness_guard.py`), `index.json`
(`tooling/index_build.py`), and `docs/skills.md` (row + 5 derived numerals, `tests/test_docs_match_the_catalog.py`).
A new MCP server needs `features/common/mcp/<name>/{meta.json,server.md≤15 lines,tools.json}`,
a `stack-mcp.json` `servers[]` entry, an `index.json` mcp entry, and optionally new
`mcp-tags.json` tags. Dependency contract: `engine/requirements.txt` (enforced by
`gates/deps_guard.py` AST walk) for framework-side imports; `features/common/dependencies.json`
for consumer prerequisites (reported, never auto-installed); ADR-0024 vendoring for code that
must run inside consumers. "Stdlib-only except two declared dependencies" is pinned verbatim in
8 files incl. `tests/test_dependency_honesty.py` and becomes false with any new dep (R1 §3.2).
Release ritual: VERSION → changelog file + `changelog_index.py` → `version_sync.py` →
re-scaffold last → `release_guard`/`docs_guard`/`scaffold_freshness_guard`. Correction to our
premise: the vendored-verbatim discipline is **ADR-0024** (extends ADR-0009); gate name
`skills-shape` does not exist — the real gate is `gates/skills_lint.py`.

**R2 — seams.** Package/subpackage planning vocabulary lives in `task/SKILL.md` (13 hits:
`:7,58-59,67-68,206,212-216,257,364` + plan-point sentences `:142-144,223-231,239-240,262,286,313`),
`task/references/tracking-visibility.md:24-30` (the `**P<N>**` plan-file format),
`task/extensions/{github,claude}/extension.md`, `status-report` (SKILL + `status_report.py`
`PACKAGE_RE` `:43`, `plan_checklist()` `:165-179`, render `:338-355`, pinned by
`tests/test_status_report.py:153,169`), `complete-project-scope-code-review` (15 hits),
`multi-agent-communication:40`, `design-gate-audit`, `review-tests/references/plan-format.md:33-38`,
`scripts-tooling-refactor`, `personas/delegator.md`, and the embedded delegator contract in
`ai-raccoon-memory/scripts/query_pipeline.py:30-90` (different pipeline — decide explicitly).
`quick-task/SKILL.md` has **zero** package vocabulary; its touch points are the minimal-plan rule
(`:54-56`) and "no tracking artifacts" (`:157`). Task-state contract to coexist with (not break):
task_tracker verbs/exit codes (`task_tracker.py:4-23`), STARTED/IN_PROGRESS/FINISHED transitions,
`tracking.db` store discipline (one write lock, `task_upsert` never INSERT OR REPLACE, newer
`schema_version` fails closed, `engine/badger_store.py` vendored byte-identical per skill). A
graph table belongs in the Family/DDL/UPGRADE_HOOKS path **plus re-vendoring**. `status-notes.json`
has no code readers (hand-edited); `state.json` is read only for `next` and mtime.

**R3 — graph lib + model.** Forced choice: **networkx** (`>=3.4.2`, BSD-3, zero transitive deps,
version-aware for the 3.10 floor) behind a thin `Workflow` facade, **pydantic** as the model/
serialization layer, persistence as a JSON document in the existing SQLite store (ADR-0024
`plans` table, `revision` CAS, `BEGIN IMMEDIATE`) — with **stdlib `graphlib.TopologicalSorter`**
as the zero-dependency fallback if "no new third-party runtime dep on consumer machines" is made
binding (the strongest counter-argument, stated in R3 §3). LangGraph and pydantic-graph explicitly
**rejected** as execution engines, wrong shape for a data-defined plan-state tracker (pydantic-graph
2.x even removed persistence — MEASURED on the wheel). The parallel frontier is derivable: the
DAG-ready set is pairwise unordered by construction; `topological_generations` gives display waves;
`dag_longest_path` is available for effort-weighted critical path. Draft pydantic model
(`TaskPlan`/`Workflow`/`Step`/`AcceptanceCriterion`/`Evidence`/`Completion`, `extra="forbid"`,
key==id validator, cycle/self-loop/unknown-dep rejection at build AND load) is in R3 §4 and was
**not executed** (UNVERIFIED until pytest runs it).

**R4 — Jev.** Jev = `typesafe/jev-1.13`, structured-decision model on `POST
https://openrouter.ai/api/alpha/decisions` (`{model, state, questions}`), direct HTTPS with
`OPENROUTER_API_KEY`, no proxy (MEASURED 9 live calls). The repo's port (`query_pipeline.py` +
`openrouter_client.py` + `memory_context.py`, stdlib-only, prompt/wire bytes pinned to pi's by
`tests/test_memory_context_jev.py`) implements **only** `score` questions; the `choice` primitive
(winner + probabilities + confidence, ≤255 options) is missing in Python and its parser
(`dr-client.ts:214-276`) is the one new piece to port. Fail-closed parsing, no-raise contract,
3×15 s attempts, no sleep/Retry-After, budget child timers — all documented at R4 §1.5–1.7.
Cost/latency: 0.47–0.89 s and ~$2e-5–$9e-5 per call (MEASURED in the cited records).
**Forced judgments:** (a) step→tier should be the deterministic `effort`/`level` →
`model_groups.resolve` mapping, Jev kept only as an advisory upgrade proposer for steps with no
declared tier (pi measured Jev tier misclassification at 0.84 confidence); (b) wave membership
should be derived from the DAG + the worktree-isolation rule, Jev unnecessary — the missing fact
is *external* resource conflict which only the plan can declare. Both prompts are designed and
ready in R4 §3–4 if the owner wants the calls anyway.

## 2. Corrected premises (do not propagate the old beliefs)

- ADR for vendoring is **0024**, not 0009 (R1 §0).
- Gate `skills-shape` does not exist; it is `gates/skills_lint.py`, 13 rules (R1 §0).
- "Jev uses the medium tier" is false — the *planner* uses medium; Jev's model id is fixed
  (`typesafe/jev-1.13`) with no tier (R4 §1.3).
- `skills-source.json`/`skills.json` are for **external marketplace** skills only — internal
  catalog skills register via directory + `index.json` (R1 §1.1).
- `.mcp.json.example` is hand-maintained dev convenience; no gate reads it (R1 §2.3).

## 3. Open decisions for the plan (with research-nudged defaults)

| # | Decision | Options | Research-nudged default | Grade |
|---|---|---|---|---|
| D1 | Graph base | networkx / stdlib graphlib / LangGraph / pydantic-graph | networkx `>=3.4.2` behind thin facade; graphlib is a one-module swap if D3 lands the server on stock python3 | INFERRED (from MEASURED dep data) |
| D2 | Jev role | (i) primary decision maker as requested; (ii) advisory layer behind a flag over deterministic derivation; (iii) drop | (ii) — honours "we could use JAV with correctly defined prompt" while the safe direction stays deterministic; both prompts from R4 ship as the advisory implementation | INFERRED |
| D3 | Where the server lives + dependency posture | (a) `features/common/mcp/task-graph/scripts/` shipped to consumers (prereqs: pydantic, networkx, MCP stack); (b) skill-scoped `features/common/skills/task-decomposition/scripts/`; (c) framework-only (runs where `engine/requirements.txt` is installed) | (a) or (b) with deps declared in `features/common/dependencies.json` + summary-claim updates in all 8 pinned files — **the plan must pick and justify**; MC SDK vs hand-rolled stdlib JSON-RPC loop is part of this decision | UNVERIFIED (no precedent: all 5 existing servers are external commands) |
| D4 | Graph state storage | `plans` table in `tracking.db` (Family/DDL/UPGRADE_HOOKS + re-vendoring) / JSON files beside it | `plans` table per ADR-0024 decision 11; JSON-snapshot fallback documented as degraded mode | READ |
| D5 | `status-report` progress path | MCP checklist tool primary + `status_report.py` file fallback (stdlib-only script cannot call MCP) | yes — tool primary, keep `packages/checked/total` keys and exit-0/placeholder contract; plan-file parsing becomes the fallback | READ |
| D6 | Integration-step semantics in the new model | final `step` node depending on all leaves / cross-step ACs on the plan / DAG join node | plan must define; "last package is the integration package" maps to something in the graph model or is explicitly retired | UNVERIFIED |
| D7 | Vocabulary blast radius | rename everything to `step` / rename task+quick-task+status-report only, leave `complete-project-scope-code-review`, `query_pipeline.py` embedded delegator, `personas/delegator.md` explicitly exempt | scoped rename + explicit exemptions recorded in the skill, per R2 §1a/[P\*] | INFERRED |
| D8 | `task-plan` vs `create-task-spec` `spec.json` | plan replaces manifest / plan consumes it / side-by-side | side-by-side at the same Phase 1 injection point (R2 §4): spec stays requirements, plan becomes the executable decomposition | INFERRED |

## 4. What the plan must answer (Phase 2 brief seeds)

1. The `task-decomposition` skill contract: input (analyze/research record + optional `spec.json`),
   output (a `task-plan` document validated against the checked-in JSON schema), and the
   stop/decomposition rules (granularity, actionability, error propagation, completeness — from
   the request's context material).
2. The exact MCP tool surface: build, get/retrieve, mark-complete (evidence + AC results),
   check-AC, ready/waves (transitions), progress→checklist, plus plan load/save — with typed
   inputs/outputs and failure semantics.
3. Sentence-accurate rewrite of `task/SKILL.md`, `quick-task/SKILL.md`, `status-report` (per R2 §5
   inventory) and what happens to `tracking-visibility.md`'s `**P<N>**` plan format.
4. Test strategy (red-first per repo tdd_guard; every new gate must have a failure provocation —
   `tests/test_every_check_can_fail.py`), the release choreography (0.179.0), and the docs/claim
   updates (8 pinned dependency-claim files).
5. How waves/parallel dispatch and `lane-dispatch-brief` fields map onto `step` fields
   (goal/instructions/AC/effort ↔ Task/How-to-work/Acceptance-criteria/Sub-agents).
