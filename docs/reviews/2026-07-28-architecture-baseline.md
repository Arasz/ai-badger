# Architecture baseline — 0.36.2, before Wave 6 and ADR-0011 phase 2

**Measured:** 2026-07-28 · **Commit:** `9a9cded` · **Tag:** `ai-badger--v0.36.2`
**Tool:** `code-review-graph`, **full rebuild** (not incremental — see §5)

Captured so the two refactors in flight can be judged by measurement instead of impression.
Neither is merged at this commit: Wave 6 (`refactor/scaffold-collaborators`) and ADR-0011 phase 2
(`refactor/engine-tooling-split`) are still on branches. **Phase 1 (`gates/`) *is* included** —
it shipped in 0.36.2.

## 1. Graph totals

| Metric | Value |
|---|---|
| Files parsed | 158 |
| Nodes | 2,587 |
| Edges | 24,603 |
| Communities | 11 |
| Flows | 109 |
| Cross-community edges | **0** |
| Architecture warnings | **0** |

## 2. Communities

| Community | Size | Cohesion |
|---|---:|---:|
| `tests-fake` | 1,680 | 0.2461 |
| `scripts-root` | 436 | 0.1821 |
| `scripts-root-skill` | 82 | 0.1413 |
| `hooks-root` | 78 | 0.2226 |
| **`gates-check`** | **52** | **0.2022** |
| `scripts-cmd` | 33 | 0.2424 |
| `js-model` | 27 | 0.4252 |
| `pre-push-lane` | 17 | 0.1111 |
| `adjustments-adjust` | 7 | 0.0583 |
| `adjustments-adjust-prune` | 5 | 0.1250 |
| `adjustments-adjust-shared` | 5 | 0.0909 |

**`gates-check` already exists as its own community** — phase 1 is visible structurally, not just
as a directory rename. That is the first piece of evidence that the ADR-0011 split does what it
claims.

## 3. Largest production classes — Wave 6's target

| Lines | Node |
|---:|---|
| **555** | **`Scaffolder`** (`features/common/skills/welcome-ai-badger/scripts/scaffold.py:307`) |
| 342 | `McpToolsMixin` |
| 169 | `ExtensionsMixin` |
| 148 | `HookWiringMixin` |
| 122 | `AgentFilesMixin` |
| 121 | `TemplateRenderingMixin` |
| 92 | `StatusLineWiringMixin` |

`Scaffolder` is the **largest class in the codebase**, and its file is the largest production
file at 922 lines. The six `*Mixin` classes sum to 994 lines that are not independently
constructible.

## 4. Hub nodes — where coupling actually concentrates

**All twelve highest-degree nodes are test helpers.** Not one is production code.

| Degree | Node |
|---:|---|
| 148 | `_config` (`tests/scaffold_helpers.py`) |
| 109 | `_load` (`tests/test_tracker_lib.py`) |
| 86 | `_make_project` (`tests/test_learned_skills_sync.py`) |
| 85 | `_scaf` (`tests/test_stack_mcp_servers.py`) |
| 84 | `_run` (`tests/test_task_tracker.py`) |

This is the 103 direct `Scaffolder(...)` constructions across 23 test files, showing up as graph
degree. It is the strongest argument for Wave 6's E1 constraint — **zero test changes** while
introducing `ScaffoldContext` — because the test fixtures, not the production code, are what a
careless refactor would break.

It is also a caution about reading these numbers: production coupling in this repo is *low*, and
the graph's hub metric is dominated by test scaffolding. Wave 6 should not be expected to move
the hub table much.

## 5. Reproducing this

A **full rebuild is required**; an incremental update reports 175 files and 2,855 nodes because
stale generated-mirror entries (`.claude/skills/…`, `.ai-badger/skills/…`) linger and
double-count `Scaffolder`, `McpToolsMixin` and friends. Comparing an incremental snapshot against
a full one would manufacture an improvement that did not happen.

```
build_or_update_graph_tool(full_rebuild=True, postprocess="full")
list_graph_stats_tool()
get_architecture_overview_tool(detail_level="minimal")
find_large_functions_tool(min_lines=80, file_path_pattern="features/")
get_hub_nodes_tool(top_n=12)
```

## 6. What improvement should look like

Predictions recorded **before** the results, so they can be wrong.

### Wave 6 — mixins → collaborators

- [ ] `Scaffolder` drops well below 555 lines; it should become a constructor plus delegations
- [ ] **Zero classes named `*Mixin` remain**
- [ ] A new `ScaffoldContext` class appears, small (~36 lines at E1)
- [ ] Six collaborator classes, each independently constructible
- [ ] `scripts-root-skill` / `scripts-root` cohesion should **rise**, since collaborators
      cluster by concern rather than sharing one `self`
- [ ] Hub table: **little movement expected** — it is test-dominated (§4)

**Honest risk:** total line count will likely *increase*. Explicit construction and delegation
cost lines that `self` hid. Line count is not the metric; independent constructibility and
cohesion are.

### ADR-0011 phase 2 — `engine/` + `tooling/`

- [ ] `scripts-root` (436) splits into distinct `engine`- and `tooling`-flavoured communities
- [ ] Cross-community edges stay at **0**, or every new one is explainable
- [ ] Community count rises from 11
- [ ] No production node gains hub-scale degree

## 7. Caveats

- **Embeddings: 0 nodes.** Semantic search is unavailable; everything here is structural.
- Communities come from the Leiden algorithm and are **not stable under unrelated edits** —
  compare sizes and cohesion, not community IDs.
- `tests-fake` (1,680 of 2,587 nodes) dominates every aggregate. Read production numbers on their
  own, not as a share of the total.
- Cohesion values here are low in absolute terms (0.06–0.43). Treat them as a relative
  before/after signal for this repo, not as an industry-benchmarked score.
