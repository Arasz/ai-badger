## P3 — Skill integration & pipeline choreography (planning section)

Verified in this worktree: the 5-surface skill registration map and the 4-surface server map (R1 §1/§2/§5); the sentence inventory (R2 §5) and its line numbers against `features/common/skills/task/SKILL.md` (`:7,:58-59,:67-68,:142-144,:206,:212-216,:223-224,:226-231,:239-240,:257,:262,:286,:313,:364` all confirmed); `gates/skills_lint.py` rules 1–13 (body ≤500 lines, ≤5000 chars/4 proxy, `## Gotchas`, `Use when`, scope for common); `status_report.py` `PACKAGE_RE:43` / `plan_checklist():165-179` / `render():338-355` and the two pins in `tests/test_status_report.py:153,169`; the derived numerals in `docs/skills.md` recomputed live (common 47, default 45, optIn 2, catalog 48, tree 54 — so +1 default ⇒ **48/46/49/55/49**); `tests/test_docs_match_the_catalog.py` regexes; the dependency claim source `.ai-badger/config.json:6` + 7 renders (R1 §3.2); `engine/requirements.txt`/`deps_guard`/`features/common/dependencies.json`; `tests/test_memory_context_jev.py::test_j1_constants_equal_pi` (prompt constants pinned to pi goldens — `query_pipeline.py` must not be edited); no `.ai-badger/mcp/` delivery path exists, so catalog `mcp/<name>/scripts/` are **not** copied to consumers (verified: only semantica/code-review-graph external-command precedents).

Everything else is cited from R1–R4. Labels: HYPOTHESIS where I did not personally verify.

---

### C1 — the `task-decomposition` skill contract

**Ruling (forced choice):** skill name `task-decomposition`, `scope: default`, canonical dir `features/common/skills/task-decomposition/`; input = research record (+ optional `spec.json`/`.feature`); output = one validated `task-plan` recorded via the task-graph MCP `plan_build` tool, never hand-written into `tracking.db`; **D8 resolved side-by-side**: `spec.json` stays the requirements document (`create-task-spec`'s output), the `task-plan` is the executable decomposition that consumes it. **Counter:** two artifacts at the same Phase-1 injection point can disagree (spec says X, plan does Y); mitigation is traceability — the plan's steps must cover every non-deferred spec scenario, and deferred decisions arrive as constraints, never re-opened as unknowns. **Flip if:** `create-task-spec` is later declared to emit a plan manifest itself; then `spec.json` and `task-plan` merge and this skill consumes only the research record.

**Decomposition method (what the SKILL.md must state).**
- **Granularity** — one `step` = one lane: a single agent dispatch that yields a mergable change and one verifier run. Test: the step fills the `lane-dispatch-brief` slots (Task / Acceptance criteria / Files you own) without naming two independently verifiable deliverables. Split when two deliverables have independent ACs or one step needs two worktrees. Merge when a step's only content is running a gate (that is an AC) or two steps always dispatch together.
- **Actionability** — `id` (stable slug), `goal` (outcome sentence), `instructions` (files owned, approach, rejected alternative, report-back), `effort` low/medium/high (→ model tier via `model_groups.resolve`), `depends_on` (only real ordering), ≥1 `acceptance_criteria` each with a `check` that can go red. No step without a check; no AC whose comparison cannot fail (mirrors `prove-the-check-fails`).
- **Error propagation** — `failed` blocks descendants, not siblings; `step_complete` refuses while any dependency is incomplete; `force` is an orchestrator-only escape and requires evidence + note; a failed step is re-planned as a new step, never edited around; the plan is never "complete" while any AC is `unchecked`.
- **Completeness / stop rules** — stop when (1) every research finding and request point maps to ≥1 step or is explicitly recorded retired; (2) every non-deferred spec scenario is covered by ≥1 AC; (3) the DAG is non-empty, acyclic, ids unique, deps known; (4) **D6 join rule** (below) holds; (5) every step has a check. Over-decomposition guard: no "run the tests" step, no step restating another's AC.
- **D6 (forced):** the "integration package" becomes a **graph property, not a unit kind**: when the workflow has >1 sink, the plan carries a join step (`depends_on` = every sink) whose ACs are only the cross-step checks; a single-sink workflow records the sink as the integration step and adds the cross-step AC there. The uniform `Step` model stays unextended. **Counter:** a join node can be a do-nothing bookkeeping step; **flip if** P2 adds plan-level cross-step ACs to `TaskPlan` — then no join node is required and the property is asserted on the plan.
- **MoE handoff** — low effort: one `architect` agent runs the method and calls the tool; high effort: the MoE panel proposes decompositions, the synthesizer merges them into one plan and runs the tool loop. Both paths end at `plan_build`.

**Tool interaction & no-server fallback (must be explicit in the skill).**
`plan_build(plan_json)` → validate + persist + render the plan file; then `plan_get`, `waves`, `step_complete(step_id, evidence, criterion_results, force?)`, `ac_record`, `plan_progress` (names per P2 — HYPOTHESIS until frozen). If the server is not listed or `plan_build` errors: write the plan markdown yourself to `.ai-badger/task-tracking/plans/<YYYY-MM-DD>-<taskId>.md` in the frozen format (one `**S<N> …**` heading per step, one `- [ ]` per AC), say the graph is off, and never hand-write `tracking.db`. `plan_build` refuses an existing plan id unless explicitly replacing with a `note`.

**SKILL.md skeleton (skills_lint-compliant):** frontmatter `name/description ("Use when…", ≤1024)/version/author/license/platforms: [linux, macos]/scope: default/metadata.hermes.{tags,related_skills}`; body ≤500 lines with `## When to Use` / `## When NOT to Use`, `## Inputs`, `## The decomposition contract` (the five bullets above), `## Steps and the join rule`, `## Recording the plan` (tool loop + fallback), `## Gotchas`, `## Verification checklist`; three references — `references/decomposition-method.md`, `references/plan-vocabulary.md` (D7 boundary table), `references/mcp-plan-tools.md` — each mention carrying a when/before condition.

---

### C2 — sentence-accurate rewrite map (R2 §5 inventory, each line dispositioned)

| Source line | Disposition | New sentence (gist) |
|---|---|---|
| `task/SKILL.md:7` | rewrite | "…low/high effort, `task-decomposition` into a `task-plan` whose `workflow` is a DAG of steps, MoE panels…" |
| `:41-47` | **exempt** (loop spine; no package word — verified) | — |
| `:58-59` | rewrite | "Integration step: the plan carries a join step when the workflow has more than one sink; it depends on every sink and carries the cross-step tests." |
| `:67-68` | rewrite | "**plan** — run `task-decomposition`; a validated `task-plan` (`workflow` = DAG of `step`s). Every step has ACs; plan AC: all steps' ACs checked+met." |
| `:142-144` | rewrite | "name shared-file steps (serialise by adding an edge or merging) vs disjoint ones (parallel)" |
| `:206` | rewrite | "Exit: reviewed `task-plan` recorded; every step carries criteria+gate; shared-file steps serialised by an edge; join step present when >1 sink." |
| `:212-216` | rewrite | the decomposition paragraph: build via `task-decomposition`, record via `plan_build`, `depends_on` is the only order source, fallback file when the server is absent. |
| `:223-224` | rewrite | "The server derives the ready set/waves; say which steps run together" (keep "parallelism has to be designed in"). |
| `:226-231` | rewrite ("point"→"step"; keep AC+gate, `design-tests`, `archify`) | — |
| `:239-240` | rewrite | "steps sharing a file serialise (edge or merge), the rest parallelise." |
| `:257` | rewrite | "Commit and push per step". |
| `:262` | rewrite | "Entry: every step complete; all ACs checked and committed". |
| `:286` | rewrite | "steps into one change". |
| `:313` | **exempt** (state protocol unchanged) | — |
| `:364` | rewrite | "Every step's acceptance gate ran; all step ACs checked; join step carried the cross-step tests". |
| `task/extensions/github/extension.md:38` | rewrite | "as each step lands". |
| `task/extensions/claude/extension.md:49` | rewrite | "two steps disagree about a contract". |
| `task/references/tracking-visibility.md:24-30` | rewrite (owned by SK4, not SK2) | plan is server-rendered; hand-write only in no-server fallback; `**S<N>**` headings; filename contract unchanged. |
| `quick-task/SKILL.md:6,23-25,84-85,157` | **exempt** | no tracking artifact; untouched. |
| `quick-task/SKILL.md:54-56` | **+1 sentence** | "Do not call `task-decomposition` and do not create graph state — a quick-task has no plan artifact; a change needing decomposition is `task` work; escalate." |
| `status-report/SKILL.md:56` | rewrite | "Progress checklist (graph steps via `plan_progress`, plan-file fallback)". |
| `status-report/SKILL.md:81` | rewrite | source row: task-graph MCP `plan_progress` first; else `task-tracking/plans/*.md` step headings + checkbox counts (legacy `**P<N>**` still read). |
| `status_report.py:43,165-179,295-315,338-355` | rewrite (SK4) | `PACKAGE_RE` → `STEP_RE = ^\*\*([PS]\d+[^*]*)\*\*`; keys `packages/checked/total` frozen; render `[step]` vs `[package]` by prefix; loop line `:353-355` unchanged. |
| `multi-agent-communication:40` | rewrite | "Broadcast at step/join boundaries". |
| `worktree-agent-isolation/references/shared-worktree-collisions.md:3` + `SKILL.md:228` | rewrite | "parallel steps can still land in the SAME worktree"; "after a step lands". |
| `complete-project-scope-code-review` (15 hits + extensions) | **exempt + note** | one sentence in SKILL: "a review *work package* becomes a `step` when the review plan is handed to `task`." |
| `design-gate-audit:21,25,45` + ref | **exempt** | design-doc vocabulary; boundary note only. |
| `review-tests/references/plan-format.md:35`, `SKILL.md:217,241` | **exempt + mapping** | `WPn` is a source label; `decomposition-method.md` maps review rows → steps 1:1. |
| `scripts-tooling-refactor:100` + `behavior-pinning-derivation.md:9` | **exempt** | refactor batching, not the task plan. |
| `invariants/small-commits-early-draft-pr.md:3` | **exempt + note** | commit sizing ≠ plan unit ("one step = one commit" would be false). |
| `personas/delegator.md:4,24-25,41,61,64,76,81,84` | **exempt + 1 note** | "dispatch *packages* are batches of `step`s; the task-plan unit is `step`." |
| `ai-raccoon-memory/scripts/query_pipeline.py:30-90` | **exempt, no touch** | prompt bytes pinned to pi by `test_j1_constants_equal_pi`; reason recorded in `plan-vocabulary.md` + changelog. |
| `.ai-badger/skills/**` mirrors | generated | never hand-edited; re-scaffolded in SK9. |

---

### C3 — tracking + status integration

**Ruling (forced choice): MCP graph is the single source of truth; the server renders the file.** The `plans` table (D4) holds `payload`; on every successful mutation the server writes/refreshes a generated `task-tracking/plans/<YYYY-MM-DD>-<taskId>.md` (`**S<N>**` headings, one checkbox per AC, a "generated — do not edit" banner). `plan_progress` (MCP) is primary; `status_report.py` parses the generated file as fallback and keeps its exit-0/placeholder contract and the `packages/checked/total` keys; its regex learns `P|S` so legacy plans still report. **`task_tracker.py` stays the token/state tracker — confirmed:** it keeps STARTED/IN_PROGRESS/FINISHED, token usage, sessions and worktrees; it never reads `plans`, `finish` is unchanged, and the graph never owns task lifecycle. Plan-completeness is a `task`-skill check before `finish`, not a tracker exit code. **Counter:** two writers to one DB add lock contention (both use `BEGIN IMMEDIATE` + `busy_timeout`); acceptable at this scale. **Flip if:** status must show step state with the server down and the generated file proves unreliable — then read the `plans` payload directly through a vendored `tracker_lib` accessor (stdlib `sqlite3` + `json`) instead of rendering markdown, and delete the markdown layer.

`tracking-visibility.md` bullet becomes: plan built by `task-decomposition` and stored/rendered by the server; no-server fallback writes it by hand in the same shape; keep the whole-taskId filename rule, review-document exclusion, "(no plan file)" semantics, and "a brief-only plan never counts" unchanged. In-flight old `**P<N>**` plans are read, not migrated (C5).

---

### C4 — release choreography, registration surfaces, claims

**Ruling:** one version, **0.179.0** (Minor), bumped in the **first** commit that touches `features/` (release_guard compares the push diff against merge-base — INFERRED, so verify by running the lane; HYPOTHESIS if the lane only checks the final push). Order: `VERSION` + `docs/changelog/0.179.0-<slug>.md` (Minor: New features / Changes / Upgrade notes) → `changelog_index.py` → (feature steps) → `index_build.py` → `changelog_index.py` → `version_sync.py` → **re-scaffold this repo last** (`AI_BADGER_MCP_AVAILABILITY=all … --no-install --skills ''`) → `scaffold_freshness_guard`. No `BREAKING_VERSIONS`: a new default skill and an additive MCP declaration require no consumer action; a refresh delivers both. `.mcp.json.example` is hand-maintained, no gate — refresh it optionally (HYPOTHESIS: hosts launch project `.mcp.json` stdio servers with cwd = project root, so a repo-relative command works).

**Skill — 5 surfaces:** (1) `features/common/skills/task-decomposition/{SKILL.md,references/}` — SK1; (2) plugin mirror `skills/task-decomposition/**` via `sync_plugin_skills.py` — SK1 (re-run SK9); (3) self-scaffold `.ai-badger/skills/task-decomposition/**` + `.ai-badger/manifest.json` row — SK9; (4) `index.json → stacks.common.skills[]` — SK1 (generated; re-run SK9); (5) `docs/skills.md` row + `### task-decomposition` section + numerals **49 catalog / 48 common / 46 default / 2 optIn / tree 55 / These 49** — SK1.

**Server — 4 surfaces:** (1) `features/common/mcp/task-graph/{meta.json,server.md≤15 lines,tools.json}` — SK5; (2) `features/common/stack-mcp.json servers[]` — SK5; (3) `index.json → stacks.common.mcp[]` — SK5 (generated); (4) `features/common/mcp-tags.json` — **no new tags**: map tools to existing `read/write/run/batch/database/files` (flip if `mcp-index` must separate plan tools as a domain — then add a `planning` domain tag in its own vocabulary PR per ADR-0004:45). Cross-owner constraints SK5 cannot solve: server **code delivery** (catalog `mcp/<name>/scripts/` is not copied to consumers — verified; shipping it via `.ai-badger/skills/task-decomposition/scripts/` with a repo-relative command is the only precedent-breaking option) and the `declare` posture (a declared server with missing pydantic/networkx starts dead in every consumer — see critique). **Dependency claims to change:** source `.ai-badger/config.json project.summary`, then the 7 generated renders (`.ai-badger/{CLAUDE,HERMES,copilot-instructions}.md`, root `CLAUDE.md`, `HERMES.md`, `.hermes.md`, `.github/copilot-instructions.md`) via re-scaffold; plus `engine/requirements.txt` (pydantic/networkx imported under `features/`), `features/common/dependencies.json` (consumer prerequisites), `README.md:392-396`, `docs/getting-started.md:159`, `docs/authoring-a-feature.md:26`; `tests/test_dependency_honesty.py` must stay green (jsonschema named required, no `OVERCLAIM`).

---

### C5 — rollout / compat

**Ruling (forced choice): dual-read + explicit refusal, no migration.** In-flight tasks keep their `**P<N>**` plans; `status_report.py` reads both prefixes, `tracking-visibility.md` says the new format applies to plans created after rollout, and `task` continues hand-updated checkboxes for an already-running plan (no graph state for it). `plan_build` refuses an existing id unless `replace: true` with a note — the skill never silently overwrites. **Counter:** two formats coexist forever; the `[package]`/`[step]` render split makes it visible rather than invisible. **Flip if:** more than a handful of long-lived plans survive one release — then a one-shot importer (markdown → `plan_build`) lands as a tool, not a manual migration. No-server consumers degrade to today's behaviour (file plan + manual checkboxes); the skill must say so out loud, and `task` must not treat graph ops as mandatory. **Critique of P1/P2 where they constrain skill flow:** a `plans`-table + pydantic/networkx server makes graph state a hard prerequisite, so the skill needs the degraded path from day one — and if P1 ships that server to consumers, either make it run on stock `python3` (stdlib `graphlib` facade) or keep the catalog entry `declare: false`, because a declared server that dies on import is worse than an undeclared one; P2's `Step` model should carry `files` (and optional external `resources`), otherwise "shared-file steps serialise" is prose the ready-set cannot enforce and two lanes can be dispatched at one file; keep `check_ac` record-only (the caller runs the check and pastes evidence — server-side execution turns the tracker into an executor), expose `plan_progress` in status's shape (`checked/total` + step lines) and structured validation errors naming step ids, and freeze tool names before SK1/SK5 dispatch.

---

## Steps (skill-integration portion — ids local, integrator renumbers)

**Interface freeze at W0 (integrator, in every brief):** the plan-file heading format and P2's final tool names. SK1/SK4/SK5 all consume it.

**SK0 — version floor. Wave 0.**
Goal: every later commit passes `release_guard`. Instructions: `VERSION` → `0.179.0`; create `docs/changelog/0.179.0-task-decomposition-graph.md` (Minor) + `tooling/changelog_index.py`. Files: `VERSION`, `docs/changelog/0.179.0-*.md`, `docs/changelog/README.md`. Gate: `python3 tooling/changelog_index.py --check`. Effort low. AC 2: VERSION reads 0.179.0; index row present.

**SK1 — skill source + skill surfaces 1,2,4,5. Wave 1.**
Files owned: `features/common/skills/task-decomposition/{SKILL.md,references/{decomposition-method.md,plan-vocabulary.md,mcp-plan-tools.md}}`, `docs/skills.md`, `index.json`, `skills/task-decomposition/**`, `tests/test_task_decomposition_contract.py`. TDD order: write the contract test first (dir exists, `scope: default`, description starts `Use when`, references exist, the five contract sections present, join rule present), watch it red; run `tests/test_docs_match_the_catalog.py` red before the row lands; then write the skill, row/section/numerals, `index_build.py`, `sync_plugin_skills.py`. Gate: `gates/skills_lint.py && tooling/validate.py --all && .venv/bin/python3 -m pytest tests/test_task_decomposition_contract.py tests/test_docs_match_the_catalog.py tests/test_plugin_manifest.py -q && tooling/index_build.py --check && tooling/sync_plugin_skills.py --check`. Effort medium. AC 5: lint clean on N+1; contract test red→green; docs green at 49/48/46/2/55/49; index skills entry green; plugin mirror present + `--check` green. Conflicts: `docs/skills.md`/`index.json` (generated — SK5's mcp entry re-runs the generator, integrator re-runs after both).

**SK2 — task pipeline rewrite. Wave 2.**
Files: `features/common/skills/task/SKILL.md`, `task/extensions/{github,claude}/extension.md`, `features/common/skills/multi-agent-communication/SKILL.md`, `features/common/skills/worktree-agent-isolation/{SKILL.md,references/shared-worktree-collisions.md}`, `features/common/personas/delegator.md` (one boundary sentence), `features/common/skills/complete-project-scope-code-review/SKILL.md` (handoff note), `tests/test_task_pipeline_vocabulary.py`. TDD: the pin test first (forbidden: `subpackage`, `last package is the integration package`, `**P<N>**` in the task SKILL; required: `task-decomposition`, `task-plan`, `step`, `join step`), red; rewrite per the C2 table; green. Gate: `.venv/bin/python3 -m pytest tests/test_task_pipeline_vocabulary.py tests/test_skills_lint.py -q && gates/skills_lint.py`. Effort medium. AC 3: red→green; every C2 task row dispositioned in the PR body; lint green. Conflicts: none (tracking-visibility reserved for SK4).

**SK3 — quick-task boundary ruling. Wave 2.**
Files: `features/common/skills/quick-task/SKILL.md`, extend the SK2 pin test. Edit: the boundary sentence at `:54-56`; everything else exempt. Gate: the pin test + `gates/skills_lint.py`. Effort low. AC 2: boundary sentence present; test red without it.

**SK4 — status-report + tracking compatibility. Wave 1.**
Files: `features/common/skills/status-report/SKILL.md`, `status-report/scripts/status_report.py`, `features/common/skills/task/references/tracking-visibility.md` (exclusive owner), `tests/test_status_report.py`. TDD: red tests for `**S<N>**` headings, mixed P/S counts, `[step]` render, unchanged placeholders/exit-0; then `PACKAGE_RE`→`STEP_RE`, docstrings, render; then SKILL (`plan_progress` first, script fallback) + tracking-visibility bullet. Gate: `.venv/bin/python3 -m pytest tests/test_status_report.py tests/test_skills_lint.py -q && gates/skills_lint.py`. Effort medium. AC 4: new test red→green; legacy P tests untouched and green; keys/exit unchanged; SKILL + tracking-visibility carry the two-path contract.

**SK5 — MCP catalog packet + declaration. Wave 1 (needs P2 names).**
Files: `features/common/mcp/task-graph/{meta.json,server.md,tools.json}`, `features/common/stack-mcp.json`, `index.json` (generated). `meta.json` carries the real `prerequisite`; `tools.json` tags from the existing vocabulary; `declare` decided by the critique (declared only if the server starts on the prerequisite). Gate: `.venv/bin/python3 -m pytest tests/test_mcp_catalog_instructions.py tests/test_mcp_prerequisites.py tests/test_stack_mcp_servers.py tests/test_mcp_declared_servers.py -q && tooling/validate.py --all`. Effort low-medium. AC 3: schemas validate; `server.md` ≤15 lines, intents ≤200, tags closed; a scaffold fixture shows the declaration (or the unmet prerequisite) as specified. Conflicts: `index.json`.

**SK6 — dependency contract + claims. Wave 1 / same wave as the server code step (deps_guard scans `features/`).**
Files: `engine/requirements.txt`, `features/common/dependencies.json`, `.ai-badger/config.json` (summary), `README.md`, `docs/getting-started.md`, `docs/authoring-a-feature.md`, `tests/test_dependency_honesty.py` (only if the pin needs the new deps named). Gate: `.venv/bin/python3 -m pytest tests/test_dependency_honesty.py -q && gates/deps_guard.py`. Effort medium. AC 3: deps lane green with server code present; honesty test green + `OVERCLAIM` absent; the three prose files match the true count. Conflicts: `.ai-badger/config.json` vs SK9 (sequential).

**SK9 — release finish (last). Wave 3.**
Files: `VERSION` (verify), `docs/changelog/0.179.0-*.md` (final), `docs/changelog/README.md`, `.claude-plugin/{plugin.json,marketplace.json}`, `index.json`, `features/common/data/model-groups.json`, all of `.ai-badger/**` (re-scaffold). Order: changelog → `index_build.py` → `changelog_index.py` → `version_sync.py` → re-scaffold LAST → optional `.mcp.json.example`. Gate: `python3 tooling/version_sync.py --check && python3 tooling/changelog_index.py --check && python3 gates/scaffold_freshness_guard.py` + pre-push lanes `version-sync index plugin-skills docs release validate scaffold tdd`. Effort medium. AC 4: version-sync green; changelog-index green; scaffold guard green with `.ai-badger/skills/task-decomposition/` + manifest row; lane subset green locally.

---

| step id | effort | wave | files owned | gate | AC count |
|---|---|---|---|---|---|
| SK0 | low | 0 | `VERSION`, `docs/changelog/0.179.0-*.md`, `docs/changelog/README.md` | `tooling/changelog_index.py --check` | 2 |
| SK1 | medium | 1 | `features/common/skills/task-decomposition/**`, `docs/skills.md`, `index.json`, `skills/task-decomposition/**`, `tests/test_task_decomposition_contract.py` | `gates/skills_lint.py` + `validate.py --all` + docs/index/plugin tests | 5 |
| SK2 | medium | 2 | `task/SKILL.md`, `task/extensions/{github,claude}/extension.md`, `multi-agent-communication/SKILL.md`, `worktree-agent-isolation/**`, `personas/delegator.md`, `complete-project-scope-code-review/SKILL.md`, `tests/test_task_pipeline_vocabulary.py` | pin test + `gates/skills_lint.py` | 3 |
| SK3 | low | 2 | `quick-task/SKILL.md`, `tests/test_task_pipeline_vocabulary.py` | pin test + `gates/skills_lint.py` | 2 |
| SK4 | medium | 1 | `status-report/SKILL.md`, `status-report/scripts/status_report.py`, `task/references/tracking-visibility.md`, `tests/test_status_report.py` | `pytest tests/test_status_report.py` + `gates/skills_lint.py` | 4 |
| SK5 | low | 1 | `features/common/mcp/task-graph/**`, `features/common/stack-mcp.json`, `index.json` | MCP catalog tests + `validate.py --all` | 3 |
| SK6 | medium | 1 | `engine/requirements.txt`, `features/common/dependencies.json`, `.ai-badger/config.json`, `README.md`, `docs/getting-started.md`, `docs/authoring-a-feature.md`, `tests/test_dependency_honesty.py` | `gates/deps_guard.py` + `pytest tests/test_dependency_honesty.py` | 3 |
| SK9 | medium | 3 | `VERSION`, changelog, `.claude-plugin/*`, `index.json`, `model-groups.json`, `.ai-badger/**` | `version_sync.py --check` + `changelog_index.py --check` + `scaffold_freshness_guard.py` + lanes | 4 |