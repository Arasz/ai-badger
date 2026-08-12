# Implementation Plan: Semantica Export Hook & AiRaccoon Watch Bridge

**Date:** 2026-08-12  
**Task:** `semantica-integration-part2`  
**Status:** DRAFT (Pending MoE Plan Review)  
**Authors:** Hermes Agent / ai-badger orchestrator  

## 1. Overview & Architectural Goals

As established in ADR-0019, Semantica's in-memory graph process is session-scoped and lacks an `import_graph` mechanism. To guarantee **zero data loss** across sessions, we implement an **Export Hook & Watch Bridge** connecting Semantica to AiRaccoon:

1. **Seeded Graph File**: Seed an initial `.ai-raccoon/semantica-graph.json` during project scaffolding.
2. **Export Hook**: A python hook script `export_semantica_graph.py` triggered on session stop / pre-commit / post-tool that executes `export_graph(format="json")` via Semantica stdio or client, writing the JSON snapshot to `.ai-raccoon/semantica-graph.json`.
3. **AiRaccoon Watch Registration**: Register `.ai-raccoon/semantica-graph.json` with `memory_watch_add`, triggering automatic FTS5 and vector re-indexing into AiRaccoon's persistent `memory.db`.
4. **Tool Allocation**:
   - **Natural Language & Decisions**: Option 2 (Agent-Guided Extraction via `add_entity` & `add_relationship`).
   - **Code Structure**: `code-review-graph` MCP tools (`semantic_search_nodes_tool`, `find_callers`, `find_dependents`).

---

## 2. Work Packages & Component Breakdown

### Work Package A: Seed File & Scaffolding Template
- Create `.ai-raccoon/semantica-graph.json` template containing `{ "nodes": [], "edges": [], "decisions": [] }`.
- Update `features/common/skills/semantica-knowledge-graph/` and `features/common/scaffolding.json` to seed this file into project root on scaffold.

### Work Package B: Export Hook Script (`export_semantica_graph.py`)
- Create `features/common/skills/semantica-knowledge-graph/scripts/export_semantica_graph.py`.
- Functionality:
  - Connects to running Semantica stdio or checks local graph export buffer.
  - Safe write (atomic tempfile write + rename) to `.ai-raccoon/semantica-graph.json`.
  - Non-blocking error handling: if Semantica process is not running or graph is empty, gracefully exits 0 without blocking git/session hooks.

### Work Package C: AiRaccoon Watch Integration
- Add automatic watch registration for `.ai-raccoon/semantica-graph.json` in `skills/ai-raccoon-memory/`.
- Ensure AiRaccoon's `memory_watch_add` adds `.ai-raccoon/semantica-graph.json` to `watches.json`.

### Work Package D: TDD Test Suite (`tests/test_semantica_export_hook.py`)
- Test seed file existence and valid JSON schema.
- Test `export_semantica_graph.py` execution (atomic write, graceful fallback when process unattached).
- Test AiRaccoon watch registration and structural JSON chunking verification.
- Sensitivity checks proving every assertion can fail.

---

## 3. MoE Review Requirements

Before implementing code changes, this plan will be subjected to a 2-lane MoE review:
1. **Architect Lane**: Review process boundaries, hook execution overhead, atomic file writes, error handling, and ADR-0019 alignment.
2. **Test Engineer Lane**: Review TDD testability, RED-GREEN witnessing, sensitivity test coverage, and gate chain compliance (`validate.py --all`, `pylint`, `pytest`).
