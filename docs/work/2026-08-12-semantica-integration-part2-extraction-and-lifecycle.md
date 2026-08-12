# Semantica Integration Part 2: Local Extraction Options & Process Lifecycle Analysis

**Date:** 2026-08-12  
**Task:** `semantica-integration-part2`  
**Status:** COMPLETE  
**Authors:** Hermes Agent / ai-badger orchestrator  

## Executive Summary

Following the initial integration of Semantica (v0.6.5) as a common MCP server in `ai-badger` 0.116.3, this record addresses operational questions regarding local extraction options, in-memory process isolation, and cross-session persistence:

1. **What are our options for local extraction?**
2. **What does "no import" mean for us? Is the data gathered isolated to one process?**
3. **How do we persist Semantica's ephemeral graph without data loss?**
4. **Can we integrate structural info from JSON files into AiRaccoon?**

---

## 1. Local Extraction Options & Recommendations

Semantica provides two NLP-focused extraction tools: `extract_entities(text)` and `extract_relations(text)`.

### Findings & Mechanics
- **No LLM API Key Required**: Semantica's built-in extraction relies on local HuggingFace NLP models via PyTorch/Transformers (`dslim/bert-base-NER` and relation extraction pipelines), not remote LLM API calls.
- **Graceful Degradation**: If `torch` and `transformers` are not installed, `extract_entities` returns entity types without names, and `extract_relations` returns empty `[]`.

### Strategy & Tool Allocation

| Domain / Workload | Recommended Tool & Strategy | Rationale |
| :--- | :--- | :--- |
| **Natural Language Reasoning & Decisions** | **Option 2: Agent-Guided Extraction** (`add_entity` + `add_relationship` + `record_decision`) | Zero extra dependencies, instantaneous execution, 100% precise domain understanding for specs/architecture. |
| **Code Structure & AST Graphs** | **`code-review-graph` MCP Tools** (`semantic_search_nodes_tool`, `find_callers`, `find_dependents`) | Sub-second deterministic C#/TS/Python AST graph analysis. Avoids fitting code ASTs into generic NLP NER models. |
| **Bulk Unstructured Text** | **Option 1: Native Local ML Stack** (`pip install torch transformers`) | Optional fallback for large text corpora when manual agent extraction is too token-intensive. |

---

## 2. Process Lifecycle & Isolation Analysis

### Is the data gathered isolated to one process? **YES.**
- **Process Boundaries**: Semantica runs as a stdio MCP server (`python3 -m semantica.mcp_server`). The knowledge graph (NetworkX / dictionary) is stored **entirely in-memory within that single Python process**.
- **State Accumulation**: All MCP tool invocations (`add_entity`, `add_relationship`, `record_decision`) from a single connected client mutate the in-memory graph of that specific process instance.
- **Process Isolation**: Separate processes (e.g. parallel agent subagents in separate worktrees) each spawn their own `python3 -m semantica.mcp_server` process with an isolated, empty graph. There is no shared IPC or cross-process memory pool.

### What "no import" means for us
- **Export Capabilities**: Semantica v0.6.5 provides `export_graph(format="json")`, serializing the graph to JSON.
- **No Import Tool**: Semantica v0.6.5 has **NO `import_graph` or `load_graph` functionality**.
- **Consequences**: When the process terminates (on session end or IDE restart), the in-memory graph is destroyed. An exported JSON file cannot be re-loaded back into a future Semantica process.

---

## 3. Persistent Graph Strategy: Export Hook + Seed File + Watch Pattern

To prevent data loss from Semantica's ephemeral process lifecycle, we implement an **Export Hook & Watch Bridge** with AiRaccoon:

```
[Semantica MCP Server]
       │
       ▼ (export_graph via Hook / Stop / SessionEnd)
[Seeded Graph File: .ai-raccoon/semantica-graph.json]
       │
       ▼ (memory_watch_add)
[AiRaccoon Memory Server] ──► SQLite memory.db (FTS5 + Vector Chunks)
       │
       ▼ (memory_search in future sessions)
[AI Agent Context]
```

1. **Export as a Hook / Procedure**: On tool execution completion, session stop, or pre-commit, the graph is exported via `export_graph(format="json")` and saved to a seeded project file (e.g. `.ai-raccoon/semantica-graph.json`).
2. **Seed & Watch**: The project seeds `.ai-raccoon/semantica-graph.json` and registers an active watch using AiRaccoon's `memory_watch_add(project_id="...", path="<absolute-path>/semantica-graph.json")`.
3. **Automatic Synchronization**: Whenever the graph is exported and updated on disk, AiRaccoon automatically detects the change, parses the JSON file, and indexes it into AiRaccoon's persistent memory bank (`memory.db`).

---

## 4. Integrating Structural Info from JSON Files in AiRaccoon

### Can we integrate structural info from JSON files in AiRaccoon? **YES.**

AiRaccoon's memory ingestion engine (`memory_ingest_file` / `memory_watch_add`) natively processes JSON files:
- **Structural Parsing & Chunking**: AiRaccoon reads JSON key-value trees, breaks down complex node/edge arrays or entity objects, and indexes them into `memory_chunks` with section metadata.
- **FTS5 + Vector Hybrid Indexing**: Node names, entity types, relationship source/target pairs, properties, and decision rationale are all indexed into SQLite FTS5 (`nodes_fts`) and embedded for semantic retrieval.
- **Cross-Session Structural Recall**: In future sessions, even if Semantica starts with an empty graph, calling `memory_search` in AiRaccoon retrieves the exact structural relations (e.g. `"Decision D-001 -> affects -> Module X"`) and property fields directly from the indexed JSON snapshot.

---

## Verification & Quality Gates

- `tests/test_semantica_knowledge_graph_skill.py`: 21 passed (includes `code-review-graph` integration, export hook watch pattern, and structural JSON ingestion checks).
- `tests/test_scaffold_delegation_map.py`: 7 passed (fixed `semantica` in common stack assertion).
- `tooling/validate.py --all`: 0 errors.
- `pylint`: 10.00/10.
- `pytest`: 3847 passed.
