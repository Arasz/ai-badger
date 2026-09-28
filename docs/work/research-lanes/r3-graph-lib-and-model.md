# R3 — Graph/Workflow Library Selection + `TaskPlan` Model

**Scope.** Read-only research lane. No repo files were written (a `curl` scratch file under `/tmp` was removed). Interpreter: `.venv/bin/python3` = Python 3.11.15 (main checkout venv; no `pip`, no pydantic/networkx/langgraph installed) and system `python3` = 3.14.7. Repo floor = 3.10 (`pyproject.toml` `py-version="3.10"`).
**Grades.** MEASURED = I ran it or fetched the live artifact/metadata; READ = I read source/docs/metadata text; INFERRED = reasoned from evidence; UNVERIFIED = not checked this session.

## 1. "GraphLang" disambiguation

**Conclusion (confidence ~65%): the requester almost certainly means LangGraph, transposed/misremembered; ~20% pydantic-graph; ~10% the literal tiny `graphlang` package; ≤5% GML. "GraphLang" as written is not a usable base.**

- A literal `graphlang` exists on PyPI: **v0.0.1, uploaded 2024-09-10, MIT, 1 GitHub star, last pushed 2024-09-11** — a DSL for defining LLM agent graphs with dotlang-inspired syntax; `requires_dist = langgraph>=0.2.14` [MEASURED: PyPI JSON + GitHub API]. Its repo is a `.lark` grammar + parser; no typed model, no status tracking, no persistence. It is a parser sitting *on* LangGraph, not a model layer [READ: GitHub tree].
- GitHub name search returns 31 repos, none maintained: `Heidelberg-NLP/GraphLanguageModels` (an NLP paper, 77★), `Msavage314/GraphLang` (a Desmos language), a HuggingFace dataset, etc. [MEASURED: GitHub search API].
- **GML (Graph Modeling Language)** ruled out: GML is a 1990s graph *file format*, not a workflow library; its Python support is `networkx.readwrite.gml` [READ: networkx wheel, `networkx/readwrite/gml.py`]. The PyPI package literally named `gml` (v3.0.6) is an unrelated ML toolkit with 23 heavy deps (torch, tensorflow, …) [MEASURED: PyPI JSON].
- Why LangGraph is the plausible referent: it is the dominant "graph model" for LLM/agent workflows (v1.2.12, 42.4k★, MIT, Python ≥3.10) [MEASURED: PyPI + GitHub], its `StateGraph` is exactly a graph-of-steps model, and even the literal `graphlang` package is a langgraph DSL. The transposition "GraphLang" ↔ "LangGraph" is one character swap. Second candidate pydantic-graph because the requirement names pydantic as the typing layer and pydantic-graph is literally branded "Graph and state machine library" [READ: PyPI description].
- **What would change this call:** the requester's full sentence or a link. If they meant the literal DSL, it is 0.0.1/1-star code — still a no. If they meant pydantic-graph, §2/§3 explain why it is an execution engine, not a plan-state container, and still a no.

## 2. Candidate comparison (all versions/dates from live PyPI; deps = non-extra runtime transitive closure, marker-agnostic BFS — may over-count on markers)

| Candidate | License | Runtime transitive deps | Py floor | Maturity | DAG expression / node state / readiness / JSON | Dep discipline |
|---|---|---|---|---|---|---|
| **networkx 3.7** (2026-09-21); 3.4.2 last for 3.10 | BSD-3-Clause | **0** (plain install; `default` extra pulls numpy/scipy only if asked) | 3.4.2: ≥3.10; 3.5–3.6: ≥3.11; 3.7: ≥3.12, ≠3.14.1 | 17.3k★, long-maintained algorithm library | `DiGraph`; attrs per node; `is_directed_acyclic_graph`/`find_cycle`; `topological_generations`, `predecessors`; `node_link_data`/`node_link_graph` JSON; `ancestors`/`descendants`, `dag_longest_path` | **Survives.** One pure-Python dep, zero transitives; version-aware pin needed for 3.10 |
| **stdlib graphlib** (PSF-2.0) | stdlib | 0 | ≥3.9 | stdlib, "Functionality to operate with graph-like structures" | No graph container; `TopologicalSorter.prepare/get_ready/done`; `CycleError`; no node/edge retrieval; no serialization; readiness is the library's whole purpose | **Wins.** Zero deps |
| **langgraph 1.2.12** (2026-09-21) | MIT | **≈39** incl. langchain-core, langsmith, httpx/requests, orjson/ormsgpack/zstandard | ≥3.10 | 42.4k★ | Execution engine: `StateGraph(State)` code-defined, `.compile()`, `.invoke`; nodes are callables; readiness implicit in scheduler; persistence is checkpointer+`thread_id` (`InMemorySaver`/`SqliteSaver`), not a task-plan document | **Fails.** langchain-core + telemetry + binary JSON codecs for a local stdio tracker |
| **pydantic-graph 2.51.0** (2026-09-25) | MIT | **9** (anyio, logfire-api, pydantic chain) | ≥3.10 | part of pydantic-ai (20.2k★) | Typed graph/FSM: nodes are classes whose `run` return type declares edges; `GraphBuilder.add_edge/build(validate_graph_structure=True)`, `Fork`/`Join`; mermaid render; **persistence removed in 2.x** (existed through 1.0.0: `persistence/file.py`) | Weak fit: engine + anyio/logfire-api, and no persistence in current release |
| **transitions 0.9.3** (2025-07-02) | MIT | 1 (`six`) | — | 6.6k★ | Finite state machine (states/events), **not a DAG**; no topological readiness, no graph JSON | Survives weight, fails shape |
| **dspy 3.4.0** (2026-09-25) | MIT | 12+(openai, litellm, requests, …) | ≥3.10, <3.15 | 38.4k★ | Dynamic module pipelines, not a declarative DAG model | Fails |
| literal **graphlang 0.0.1** (2024-09-10) | MIT | pulls langgraph | ≥3.8 | 1★, abandoned | Parser/DSL only | Fails |

**What each expresses, concretely** [READ: wheels of pydantic-graph 2.51, langgraph 1.2.12, networkx 3.4.2/3.7; MEASURED: graphlib on 3.11.15]:
- `graphlib.TopologicalSorter`: `prepare()` first (else `ValueError`); `get_ready()` returns the current parallel frontier; `done(n)` advances; `CycleError.args == ('nodes are in a cycle', ['A','B','A'])`. Restoring a partial state requires replaying the completed frontier (measured working).
- networkx: all needed DAG functions present in both 3.4.2 and 3.7; `node_link_data`/`node_link_graph` present in both.
- pydantic-graph 2.51 wheel contains **zero files and zero source mentions of "persistence"**; 1.0.0 and earlier shipped `pydantic_graph/persistence/{file,in_mem}.py`.

## 3. Recommendation (forced choice)

**Use networkx as the graph base, behind a thin `Workflow` facade, with pydantic as the model/serialization layer and stdlib `graphlib` as an allowed no-dependency fallback.**

Rationale: the requirement set is graph-shaped — build, validate DAG, retrieve nodes/edges, derive the parallel frontier, order a checklist. networkx provides all of it as a mature, pure-Python, BSD-3 library with **zero transitive runtime deps**, and the used surface is small enough (`DiGraph`, `is_directed_acyclic_graph`, `find_cycle`, `predecessors`, `topological_generations`, `ancestors/descendants`) to be isolated in one module. Version-aware resolution keeps the 3.10 floor: declare `networkx>=3.4.2` — pip selects 3.4.2 on 3.10, 3.6.x on 3.11, 3.7 on 3.12+/3.13 (not 3.14.1) [MEASURED: PyPI `requires_python`].

**Runner-up: stdlib `graphlib` + pure-pydantic adjacency.** Strongest counter-argument against the recommendation, stated plainly: *networkx buys almost nothing this feature needs.* Cycle detection, topological order, and the ready frontier are exactly `graphlib`'s remit, and node/edge retrieval, status, progress, and JSON round-trip are pydantic-dict operations either way. Adding networkx to an MCP server that ai-badger ships means declaring another prerequisite on every machine that launches it — the repo's own ADR-0024 chose stdlib `sqlite3` over third-party stores for precisely this reason ("no dependency is added for hooks, skills, or scaffolded projects" [READ: `docs/adr/0024-sqlite-runtime-store.md`]).

**Pick the runner-up instead iff** any of: (a) the owner treats "the plan server must run on a stock python3 with no install step" as binding (ai-badger mcp-server catalog convention: prerequisites are documented, never installed [READ: `schemas/mcp-server.schema.json`]); or (b) after implementation the only graph calls used are `prepare/get_ready/done` and a one-line predecessor-complete predicate. In that world networkx is dead weight. Given the requester explicitly permits declared new deps and pydantic is already accepted, I recommend networkx now and keep the facade small so a later downgrade to graphlib is a one-module change.

**Explicitly rejected:** LangGraph and pydantic-graph are **execution engines** — they run node callables. This MCP server tracks plan state while the agent executes steps and reports evidence; a long-lived stdio server must not be the executor, and neither library exposes "mark a data-defined step complete with evidence" as a first-class operation. LangGraph's checkpointer is thread-scoped runtime state with a different lifecycle than a durable plan document, and it costs ≈39 transitive packages including langchain-core and langsmith telemetry [MEASURED: PyPI transitive walk]. pydantic-graph's current release has no persistence at all and a dynamic, data-defined DAG fights its class-and-return-type edge model. Both remain useful only as prior art for the typed model sketch.

## 4. Draft pydantic model sketch

```python
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, model_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Effort(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class StepStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    complete = "complete"
    failed = "failed"
    skipped = "skipped"


class CriterionStatus(str, Enum):
    unchecked = "unchecked"
    passed = "passed"
    failed = "failed"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["command", "test", "artifact", "review", "note"]
    summary: str = Field(min_length=1)
    ref: str | None = None                  # path / URL / sha256
    recorded_at: datetime = Field(default_factory=_now)


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    statement: str                          # the AC itself
    check: str | None = None                # command/procedure, if executable
    status: CriterionStatus = CriterionStatus.unchecked
    evidence: list[Evidence] = Field(default_factory=list)


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed_by: str | None = None         # session/agent id
    evidence: list[Evidence]
    criterion_results: dict[str, CriterionStatus]   # AC id -> outcome
    note: str | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    goal: str = Field(min_length=1)          # target / acceptance target
    instructions: str = Field(min_length=1)  # how to do it
    effort: Effort                           # drives model selection
    depends_on: list[str] = Field(default_factory=list)   # incoming edges
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    status: StepStatus = StepStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    completion: Completion | None = None


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: dict[str, Step]                    # keyed by step id, insertion-ordered

    def edges(self) -> list[tuple[str, str]]:
        return [(dep, sid) for sid, s in self.steps.items() for dep in s.depends_on]

    def to_networkx(self) -> nx.DiGraph:
        g = nx.DiGraph()
        g.add_nodes_from(self.steps)
        g.add_edges_from(self.edges())
        return g

    @model_validator(mode="after")
    def _valid_dag(self) -> "Workflow":
        if not self.steps:
            raise ValueError("workflow must contain at least one step")
        ids = set(self.steps)
        for sid, step in self.steps.items():
            if step.id != sid:
                raise ValueError(f"step key {sid!r} != step.id {step.id!r}")
            if sid in step.depends_on:
                raise ValueError(f"step {sid!r} depends on itself")
            unknown = sorted(set(step.depends_on) - ids)
            if unknown:
                raise ValueError(f"step {sid!r} depends on unknown steps: {unknown}")
        g = self.to_networkx()
        if not nx.is_directed_acyclic_graph(g):
            raise ValueError(f"workflow is not a DAG; cycle: {nx.find_cycle(g)}")
        return self


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    task_description_ref: str                 # path/URI of the full task description
    task_context: str = ""                    # short human-readable context
    workflow: Workflow
    revision: int = 0                         # optimistic concurrency token (see §6)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ---- JSON-schema generation hook (pydantic v2) -------------------------------
# TaskPlan.model_json_schema() defaults: by_alias=True,
# ref_template='#/$defs/{model}', mode='validation' [READ: pydantic 2.13.5 source].
# It emits {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': {...}}
# because GenerateJsonSchema.schema_dialect is 2020-12 [READ: pydantic/json_schema.py].
SCHEMA = TaskPlan.model_json_schema()         # -> schemas/task-plan.schema.json (checked in)
PLAN = TaskPlan.model_validate_json(payload)  # load: validators run -> corrupted input fails closed
payload = PLAN.model_dump_json()              # persist: this exact text is the stored document
```

Modeling notes: the wire format is `dict[str, Step]` because duplicate ids must not exist; the authored JSON schema refines it with `patternProperties`/`propertyNames` so keys match the id pattern; the `key == step.id` validator catches hand-edits. `effort → model` is a pure lookup (`EFFORT_MODELS`) sourced from `.ai-badger/delegation.md`, not stored. All enums serialize as strings, so the JSON schema is self-describing for any consumer.

## 5. Operation mapping (chosen: networkx behind `Workflow`)

| Operation | Implementation sketch | Notes |
|---|---|---|
| build / reject invalid graph | `TaskPlan.model_validate*` → `Workflow._valid_dag`: empty check, key==id, self-loop, unknown-dependency, then `nx.is_directed_acyclic_graph` + `nx.find_cycle` | Rejection at build **and** every load; pydantic wraps failures as `ValidationError`. Unknown deps are caught before networkx sees the graph |
| retrieve nodes/edges/state | `plan.workflow.steps[id]`; `workflow.edges()`; `workflow.to_networkx()`; `g.predecessors(sid)`/`g.successors(sid)`; `nx.ancestors(g, sid)`/`descendants` for dependency closure | No copying: node state is the pydantic `Step`; the nx view is derived per call (plans are tens of nodes) |
| mark complete (with evidence) | `step.status = COMPLETE; step.completed_at = _now(); step.completion = Completion(evidence=..., criterion_results=...)`; `plan.revision += 1`; persist (§6); return `ready_steps(plan)` | Guard: refuse if any `depends_on` is not complete (`force` escape hatch), refuse if already complete |
| check AC | `AcceptanceCriterion.check` holds the command/procedure; the caller (agent) supplies `CriterionStatus` + evidence; optionally the server runs `subprocess.run(check, timeout=60)` and records stdout hash as evidence — stdlib, no graph lib | Gating policy: complete requires a result for every AC unless `force=True` |
| transitions + ready set | `ready = [sid for sid, s in steps.items() if s.status in (PENDING, FAILED) and all(steps[d].status is COMPLETE for d in g.predecessors(sid))]` | **Parallel derivation:** every member of `ready` is pairwise unordered by construction (an incomplete ancestor blocks its descendant; a complete ancestor leaves the frontier), so `ready` *is* the parallel frontier. Independent alternative: rebuild `graphlib.TopologicalSorter({sid: set(s.depends_on)})`, replay completed frontier, then `get_ready()` [MEASURED on 3.11]. `nx.topological_generations` gives parallel waves for display; `nx.dag_longest_path` is available if effort-weighted critical path is ever wanted |
| progress checklist | `nx.topological_sort(g)` order; mark `x`/`~`/` `/`!`/`-` per status; per step tally `passed/total` AC; header `complete/total` | Stable for a fixed steps ordering |

## 6. Persistence design

**Recommendation: store the plan as a JSON document in the existing SQLite runtime store — a new `plans` table in `.ai-badger/task-tracking/tracking.db` — not a new file format.** This follows the repo's accepted ADR-0024: project runtime state lives in that DB, opened with `journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, one `BEGIN IMMEDIATE` transaction, root resolved at call time from `AI_BADGER_TRACKING_ROOT` (never import time), and `meta(schema_version)` failing closed on a newer database [READ: `docs/adr/0024-sqlite-runtime-store.md`, `skills/task/scripts/badger_store.py`]. ADR-0024 decision 11 directly prescribes the shape: "normal columns for what is queried, JSON columns for payloads".

- **Format.** `plans(plan_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)`; `payload = plan.model_dump_json()`, validated against `schemas/task-plan.schema.json` (Draft 2020-12, generated from `model_json_schema()`) on write **and** read. JSON Schema authoring/validation already exists: `badger_lib.validate` uses `jsonschema.Draft202012Validator` [READ: `engine/badger_lib.py`]. SQLite on Python 3.11.15 here is 3.53.1 with JSON1 (`json_valid`, `json_extract` verified) [MEASURED]; stdlib-only, no new dependency for storage.
- **Atomicity.** A SQLite transaction, not temp-file rename: `UPDATE plans SET revision=revision+1, payload=?, updated_at=? WHERE plan_id=? AND revision=?`. Zero rows updated = CAS conflict → reload and retry once, else return a conflict error. Multi-process-safe: several stdio servers on the same repo block on `BEGIN IMMEDIATE` for at most `busy_timeout` and then get a clean "database is locked".
- **Server lifecycle.** Long-lived: cache the loaded `TaskPlan` by `(plan_id, revision)`; re-read the row when a write's CAS fails or on explicit `reload`. Short-lived: one `SELECT payload` → `TaskPlan.model_validate_json`. Either way the database is the sole authority — no in-memory-only state, so restart survival is inherent.
- **Migration.** Bump `badger_store.SCHEMA_VERSION` (currently 2) and add the DDL to `UPGRADE_HOOKS` (the bus tables landed exactly this way) [READ: `badger_store.py`]; the store already rolls DDL back on failure.
- **Fallback (only if the server must ship without the store module).** Atomic JSON snapshot per plan (`.ai-badger/task-tracking/plans/<task_id>.json`): write temp in the same directory, `fsync`, `os.replace` — the pattern already used by `tracker_lib.save_json` [READ: lines 396–404] — plus a CAS `revision` and a `.write.lock` flock. ADR-0024 supersedes this for runtime state; treat it as a degraded mode, not the primary.
- **Optional history.** Completion is append-only in meaning; if evidence history must be queryable, add a `plan_events(ts, plan_id, event_payload)` table following the log-table + 60-day-prune convention rather than growing the payload.

## Open questions / risks

1. **Where the server runs decides the dependency question.** If the plan MCP server is shipped to scaffolded projects (catalog entry + launch config, prerequisites never auto-installed [READ: `schemas/mcp-server.schema.json`]), pydantic *and* networkx become user-visible prerequisites — the flip condition in §3. If it runs in the plugin host where `engine/requirements.txt` is installed, declaring them there is routine. Confirm before implementation.
2. pydantic is a compiled dependency (`pydantic-core` ships binary wheels only; latest 2.49.0 requires ≥3.10) [MEASURED: PyPI JSON] — it narrows exotic-platform support; mark INFERRED that this is acceptable given the requester already chose pydantic.
3. The model sketch was not executed (pydantic absent and the lane is read-only) — validate it under pytest first; pydantic claims here are READ, not MEASURED.
4. AC execution policy (server runs `check` vs. agent reports outcomes) is unstated; the model supports both.
5. Checklist tie-ordering is topological, not dependency-depth-stable — INFERRED sufficient; adjust only if a display bug is observed.

## Recommendation

Base the DAG task-workflow model on **networkx** behind a thin `Workflow` facade — pure-Python, BSD-3, zero transitive runtime deps, version-pinned as `networkx>=3.4.2` to hold the Python 3.10 floor — with **pydantic** as the typed/serialization layer (the requester's given choice) and the repo's existing **SQLite runtime store** (ADR-0024) as the persistence layer, storing the pydantic JSON document in a `plans` table behind a revision CAS; if the owner makes "no new third-party runtime dependency for the plan server" binding, fall back to **stdlib `graphlib.TopologicalSorter`**, which satisfies every required operation at zero dependency cost, and the "GraphLang" in the request most plausibly means **LangGraph**, which should be explicitly rejected as an execution engine that is the wrong shape for this state-tracking MCP server.