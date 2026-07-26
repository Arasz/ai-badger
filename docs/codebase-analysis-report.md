# Codebase Analysis Report — ai-badger

**Date:** 2026-07-26
**Branch:** `task/split-python-files-domain-modules`
**Commit:** `f1ab164`
**Graph nodes:** 1,364 | **Edges:** 13,648 | **Files:** 112
**Languages:** Python, JavaScript

---

## 1. Architecture Overview

16 communities detected. Dominant language is Python across all communities.

| Community | Size | Cohesion | Language |
|-----------|------|----------|----------|
| tests-write | 637 | 0.182 | python |
| scripts-cmd | 188 | 0.146 | python |
| scripts-session | 84 | 0.156 | python |
| scripts-items | 51 | 0.119 | python |
| scripts-detect | 50 | 0.163 | python |
| scripts-cmd-now | 20 | 0.253 | python |
| scripts-cmd-utc | 20 | 0.253 | python |
| scripts-cmd-index | 18 | 0.172 | python |
| hooks-find | 16 | 0.162 | python |
| hooks-find-index | 16 | 0.162 | python |
| scripts-read | 11 | 0.075 | javascript |
| scripts-check | 7 | 0.066 | python |
| scripts-bootstrap | 6 | 0.033 | python |
| scripts-now | 6 | 0.128 | python |
| adjustments-adjust | 3 | 0.000 | python |
| adjustments-adjust-2 | 2 | 0.000 | python |

**Key observations:**
- The `tests-write` community dominates at 637 nodes — the test suite is the largest cohesive unit.
- Cohesion is generally low (0.03–0.25), typical for a scripting framework with many small entry points.
- Zero cross-community coupling detected — communities are well-isolated.
- Two adjustment communities (`adjustments-adjust`, `adjustments-adjust-2`) have zero cohesion and minimal size — candidates for merging.

---

## 2. Top Execution Flows

30 flows detected. Sorted by criticality (highest first).

| Flow | Depth | Nodes | Files | Criticality |
|------|-------|-------|-------|-------------|
| main (index_build) | 2 | 4 | 1 | 0.620 |
| hasSectionMetadata (.mjs) | 1 | 2 | 1 | 0.610 |
| validateInstructionFrontmatter (.mjs) | 1 | 2 | 1 | 0.610 |
| main (validate) | 1 | 2 | 1 | 0.610 |
| main (mcp_index) | 1 | 2 | 1 | 0.610 |
| discover_target_sessions (x2) | 2 | 6 | 1 | 0.578 |
| resolve_own_session (x2) | 2 | 4 | 1 | 0.495 |
| validate_file | 2 | 4 | 1 | 0.495 |
| hasHeading (.mjs, x2) | 1 | 2 | 1 | 0.490 |
| resume_session (x2) | 1 | 2 | 1 | 0.485 |
| dir_content_hash | 1 | 2 | 1 | 0.485 |
| main (detect/drift, x2) | 1 | 4 | 2 | 0.435 |
| on_session_start_drift_notice (x2) | 2 | 4 | 1 | 0.433 |
| on_session_start (x2) | 1 | 4 | 1 | 0.423 |
| __init__ (Scaffolder, x2) | 6-7 | 30-36 | 1 | 0.410-0.420 |
| main (scaffold, x2) | 6 | 36 | 1 | 0.410 |
| main (open_pr, x2) | 2 | 13 | 1 | 0.409 |
| save_current_session (x2) | 2 | 7 | 1 | 0.406 |

**Note:** Many flows appear in pairs because the graph tracks both `.ai-badger/` (scaffolded copy) and `features/common/` (source) as separate files.

**Key observations:**
- The `Scaffolder.__init__` and `scaffold main` flows are the deepest (6-7 levels, 30-36 nodes) — the most complex execution paths in the project.
- `index_build main` has the highest criticality (0.62) — it's the most impactful single entry point.
- Session management flows (`discover_target_sessions`, `resolve_own_session`, `save_current_session`) form a cohesive cluster.
