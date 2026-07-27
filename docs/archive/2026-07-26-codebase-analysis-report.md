# Codebase Analysis Report — ai-badger

> **ARCHIVED — a knowledge-graph snapshot, true of one commit.**
> Taken at **0.14.1**, commit `7d9c767`. Fifty-six commits and ~115 changed files under
> `features/ scripts/ tests/` have landed since. **Every number below is out of date**; if you
> need these metrics, regenerate the graph rather than reading them here.
>
> Verified against the code on 2026-07-27 while archiving:
>
> - The **qualitative** conclusions still hold — the test suite dominates the graph, betweenness
>   is low, the "dead code" hits on `_merge_extensions` / `wire_hooks` /
>   `assemble_instructions_doc` are mixin-dispatch false positives, and the source/scaffold split
>   is clean.
> - §2's highlighted flow **`_embed_extensions` no longer exists** — it was deleted in 0.27.0
>   ([ADR-0006](../adr/0006-one-skill-extension-mechanism.md)).
> - §6's headline "zero actual dead production code" was **contradicted later**: 0.27.0 found and
>   removed a genuinely dead mechanism this analysis did not flag.
> - Two named test nodes are gone (`test_full_lifecycle_start_subagent_finish`,
>   `test_finish_succeeds_when_state_json_updated`); several others are prefix-truncations of the
>   real names.
> - §5/§8's one actionable recommendation — "add smoke tests for `refresh.py`,
>   `detect_additions.py`, `task_tracker.py` `main()`" — was **already satisfied when written**.
>   All three `main()`s are invoked in-process by existing tests; the graph simply could not see
>   the TESTED_BY edge, which the report itself hedges about.

**Date:** 2026-07-26
**Branch:** `main`
**Commit:** `7d9c767`
**Graph nodes:** 1,097 | **Edges:** 11,229 | **Files:** 80
**Languages:** Python, JavaScript

---

## 1. Architecture Overview

13 communities detected. Dominant language is Python.

| Community | Size | Cohesion | Language |
|-----------|------|----------|----------|
| tests-write | 716 | 0.191 | python |
| scripts-session | 84 | 0.156 | python |
| scripts-mcp | 76 | 0.148 | python |
| scripts-items | 51 | 0.119 | python |
| scripts-cmd | 20 | 0.253 | python |
| scripts-cmd-index | 19 | 0.169 | python |
| hooks-find | 16 | 0.162 | python |
| scripts-read | 11 | 0.075 | javascript |
| scripts-check | 7 | 0.075 | python |
| scripts-bootstrap | 6 | 0.033 | python |
| scripts-now | 6 | 0.128 | python |
| adjustments-adjust (copilot) | 3 | 0.000 | python |
| adjustments-adjust-2 (hermes) | 2 | 0.000 | python |

**Key observations:**
- `tests-write` dominates at 716 nodes — the test suite is the largest cohesive unit.
- Cohesion is generally low (0.03–0.25), typical for a scripting framework with many small entry points.
- Zero cross-community coupling — communities are well-isolated.
- Adjustment communities are correctly split by agent type (copilot vs hermes).
- `.ai-badger/` (scaffolded copy) excluded via `.code-review-graphignore`.

---

## 2. Top Execution Flows (30 detected)

| Flow | Depth | Nodes | Criticality |
|------|-------|-------|-------------|
| main (index_build) | 2 | 4 | 0.620 |
| hasSectionMetadata (.mjs) | 1 | 2 | 0.610 |
| validateInstructionFrontmatter (.mjs) | 1 | 2 | 0.610 |
| main (mcp_index) | 1 | 2 | 0.610 |
| discover_target_sessions | 2 | 6 | 0.578 |
| resolve_own_session | 2 | 4 | 0.495 |
| validate_file | 2 | 4 | 0.495 |
| hasHeading (.mjs) | 1 | 2 | 0.490 |
| _prune_inline_extensions | 3 | 4 | 0.455 |
| _embed_extensions | 3 | 4 | 0.455 |
| main (detect/drift) | 1 | 4 | 0.435 |
| on_session_start_drift_notice | 2 | 4 | 0.433 |
| on_session_start | 1 | 4 | 0.423 |
| main (open_pr) | 2 | 13 | 0.409 |
| save_current_session | 2 | 7 | 0.406 |
| pre_llm_inject_context | 2 | 8 | 0.401 |
| __init__ (Scaffolder) | 4 | 18 | 0.390 |
| check_limit | 3 | 6 | 0.380 |
| main (scaffold) | 3 | 18 | 0.380 |

**Key observations:**
- `index_build main` has the highest criticality (0.62) — the most impactful entry point.
- `Scaffolder.__init__` and `scaffold main` are the deepest flows (4 levels, 18 nodes).
- Extension processing (`_prune_inline_extensions`, `_embed_extensions`) forms a cohesive flow cluster.
- Session management flows are well-structured at depth 2.

---

## 3. Hub Nodes (Top 15 by Total Degree)

| Node | Kind | File | Total |
|------|------|------|-------|
| `_load` | Function | tests/test_tracker_lib.py | 103 |
| `_config` | Function | tests/test_scaffold.py | 87 |
| `_run` | Function | tests/test_task_tracker.py | 84 |
| `_scaf` | Function | tests/test_stack_mcp_servers.py | 77 |
| `tt` | Function | tests/test_task_tracker.py | 77 |
| `_config` | Function | tests/test_stack_mcp_servers.py | 73 |
| test_refresh_re_scaffolds_hermes_agent_files | Test | tests/test_den_refresh.py | 61 |
| test_full_lifecycle_start_subagent_finish_grade | Test | tests/test_task_tracker.py | 52 |
| test_refresh_preserves_seed_once_files | Test | tests/test_den_refresh.py | 49 |
| test_refresh_detects_drift_and_re_scaffolds | Test | tests/test_den_refresh.py | 45 |
| `main` | Function | den-refresh/scripts/refresh.py | 44 |
| `_make_fake_root` | Function | tests/test_index_build.py | 43 |
| test_refresh_updates_framework_version | Test | tests/test_den_refresh.py | 41 |
| test_scaffold_reset_seed_files_flag | Test | tests/test_scaffold.py | 41 |
| `main` | Function | feed-badger/scripts/detect_additions.py | 38 |

ALL top hubs are test helpers — xUnit fixtures aggregate assertions, giving high degree. The highest non-test hub is `refresh.py::main` (degree 44).

---

## 4. Bridge Nodes (Top 10 by Betweenness Centrality)

| Node | Kind | File | Betweenness |
|------|------|------|-------------|
| `_load` | Function | tests/test_tracker_lib.py | 0.0340 |
| `tt` | Function | tests/test_task_tracker.py | 0.0102 |
| test_run_skips_when_lock_already_held | Test | tests/test_resume_cron.py | 0.0083 |
| `_validate` | Function | tests/test_mcp_servers_schema.py | 0.0063 |
| test_code_review_checklist_roundtrip | Test | tests/test_scaffold.py | 0.0054 |
| test_extension_marker_routing | Test | tests/test_scaffold.py | 0.0051 |
| test_instance_without_schema_or_kind | Test | tests/test_validate.py | 0.0049 |
| test_find_root_raises_when_no_ancestor | Test | tests/test_badger_lib.py | 0.0049 |
| test_finish_succeeds_when_state_json_updated | Test | tests/test_task_tracker.py | 0.0047 |
| test_full_lifecycle_start_subagent_finish | Test | tests/test_task_tracker.py | 0.0044 |

Betweenness values are very low (max 0.034) — no critical chokepoints. Good redundancy.

---

## 5. Knowledge Gaps (33 total)

**Summary:** 9 isolated nodes, 1 thin community, 20 untested hotspots, 3 single-file communities.

### Isolated Nodes
All are test fixtures (`_FakeSubprocess.__init__`, `fake_popen`, etc.) or `__init__` methods — no production code isolation.

### Thin Communities
- `adjustments-adjust-2` (2 members) — hermes adjustments, correctly separated from copilot by domain.

### Single-File Communities
- `scripts-check` (7 nodes) — den-refresh/refresh.py
- `scripts-cmd-index` (19 nodes) — mcp-index/mcp_index.py
- `scripts-now` (6 nodes) — prompt-markers/user_prompt_hook.py

### Untested Hotspots (top 10 of 20)
| Function | Degree | Note |
|----------|--------|------|
| `main` (den-refresh) | 44 | CLI entry point |
| `main` (feed-badger) | 38 | CLI entry point |
| `build_index` | 37 | CLI entry point |
| `main` (task_tracker) | 35 | CLI entry point |
| `main` (drift) | 35 | CLI entry point |
| `wire_hooks` | 35 | Mixin method |
| `_auto_tags` | 34 | MCP index helper |
| `main` (awm_gate) | 33 | CLI entry point |
| `cmd_start` | 33 | CLI subcommand |
| `Scaffolder.run` | 33 | Core entry point |

Most are `main()` entry points tested via integration/subprocess — the graph can't trace TESTED_BY edges for those.

---

## 6. Dead Code Analysis (20 symbols)

**All 20 are false positives.** Categorization:

| Category | Count | Explanation |
|----------|-------|-------------|
| Mixin methods (welcome-ai-badger) | 14 | `_merge_extensions`, `wire_hooks`, `assemble_instructions_doc`, etc. — called via mixin inheritance by Scaffolder |
| Dynamic dispatch adjustments | 5 | `adjust()` functions called at runtime via `importlib.util` |
| Hook entry points | 2 | `register()`, `post_tool_call()` — called by agent runtime |
| Test fixture | 1 | `conftest.py::_load` — pytest autouse |

**Conclusion:** Zero actual dead production code. The `.ai-badger/` exclusion eliminated 49 scaffold-duplication false positives (71% reduction from prior report).

---

## 7. Review Questions

### High Priority
1. `_load` (test_tracker_lib.py) — critical bridge node (betweenness 0.034). Adequately documented?
2. `tt` (test_task_tracker.py) — critical bridge (betweenness 0.010). Documented?
3. `test_run_skips_when_lock_already_held` — critical bridge. Documented?

### Medium Priority
4. `tt` — 77 connections, no direct test coverage. Risk?
5. `main` (den-refresh) — 44 connections, no direct test coverage.

### Low Priority
6. `adjustments-adjust-2` — 2 members. Already correctly split by domain (hermes vs copilot).

---

## 8. Recommendations

### Immediate Actions
1. **No dead code to remove.** All 20 flags are false positives.
2. **Add smoke tests for `main()` entry points** — `refresh.py`, `detect_additions.py`, `task_tracker.py` are high-degree untested hotspots.

### Architectural Health
- **Excellent isolation.** Zero cross-community coupling.
- **No critical chokepoints.** Betweenness values are very low.
- **Good test coverage.** Test community (716 nodes) is the largest and most cohesive.
- **Clean source/scaffold separation.** `.ai-badger/` excluded from analysis.

### Applied Cleanup (this session)
1. **Created `.code-review-graphignore`** — excludes `.ai-badger/` scaffolded copy. Reduced dead-code false positives by 71% (69 → 20).
2. **Created `features/README-adjustments.md`** — documents the dynamic dispatch pattern for agent-specific adjustments.
3. **Full graph rebuild** — 85 files, 1,097 nodes, 11,351 edges, 13 communities (was 112/1,364/13,648/16).

---

*Report generated by code-review-graph MCP tools on 2026-07-26.*
*Graph: 1,097 nodes, 11,229 edges, 80 files, 13 communities.*
