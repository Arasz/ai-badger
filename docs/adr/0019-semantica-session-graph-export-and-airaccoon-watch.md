# ADR-0019 — Semantica session-scoped graph export, AiRaccoon watch bridge, and extraction strategy

**Date:** 2026-08-12  
**Status:** Accepted (2026-08-12, 0.116.3) — **owner-guided**  
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent  
**Scope:** `features/common/mcp/semantica/`, `features/common/skills/semantica-knowledge-graph/`, `docs/work/`, `AiRaccoon memory bridge`  

## Context

In ai-badger 0.116.3, Semantica (MIT, v0.6.5) was integrated as a common MCP server alongside AiRaccoon and code-review-graph. Live dogfooding and MoE analysis revealed key operational facts:
1. **In-Memory Ephemeral Lifecycle**: Semantica runs as a single-process stdio MCP server (`python3 -m semantica.mcp_server`). All nodes, relationships, decisions, and causal chains accumulate in-memory within a single running process. On process exit (session stop, IDE restart, agent disconnect), the graph is completely destroyed.
2. **No Import Mechanism**: While Semantica provides `export_graph(format="json")`, Semantica v0.6.5 has **NO `import_graph` or `load_graph` API**. Exported JSON snapshots cannot be re-loaded into future Semantica sessions.
3. **Extraction Options & Dependencies**: Semantica's native `extract_entities` and `extract_relations` rely on local PyTorch/Transformers NLP models (no remote LLM API keys needed). Without `torch` and `transformers` installed, extraction degrades to empty or unnamed entity/relation lists.
4. **Data Loss Risk**: Relying on Semantica alone causes all architectural reasoning, entity graphs, and causal decision chains to disappear when the agent session finishes.

## Decision

We adopt three structural decisions to govern Semantica's lifecycle, extraction strategy, and persistence:

### 1. Extraction Strategy: Option 2 (Agent-Guided) + `code-review-graph`
- **Natural Language Reasoning, Specs & Architecture Decisions**: Use **Option 2 (Agent-Guided Extraction)** via `add_entity`, `add_relationship`, and `record_decision`. The AI Agent already possesses high reasoning capacity; this avoids requiring PyTorch/Transformers (~2.5GB dependencies) while providing 100% precise domain understanding.
- **Code Symbol Graphs & Call Hierarchies**: Use `code-review-graph` MCP tools (`semantic_search_nodes_tool`, `find_callers`, `find_dependents`). Avoid fitting deterministic code symbol graphs into generic NLP NER models.
- **Bulk Unstructured Text**: Option 1 (`extract_entities` via local `torch` + `transformers`) remains an optional fallback for token-intensive raw document parsing.

### 2. Lifecycle & Persistence: Export Hook + Seed File + Watch Bridge
To prevent data loss without hand-rolled graph import logic:
1. **Export as Hook/Procedure**: On tool completion, session stop, or pre-commit, the agent exports the Semantica graph via `export_graph(format="json")` and writes it to a seeded project file (`.ai-raccoon/semantica-graph.json`).
2. **Seeded Watch**: The project seeds `.ai-raccoon/semantica-graph.json` and registers an active watch with AiRaccoon via `memory_watch_add(project_id, path)`.
3. **Automatic Synchronization**: Whenever the graph JSON file is exported and updated on disk, AiRaccoon automatically detects the change, parses the JSON node/edge structure, and indexes it into AiRaccoon's persistent SQLite memory bank (`memory.db`).

### 3. Structural JSON Ingestion in AiRaccoon
- **Ingestion Capabilities**: AiRaccoon natively parses JSON files into structured key-value chunks, indexing node names, entity types, relationship source/target pairs, and decision outcomes into `memory_chunks` and FTS5 (`nodes_fts`).
- **Cross-Session Structural Recall**: In future sessions (even when Semantica's process starts empty), `memory_search` in AiRaccoon retrieves both textual decision rationale and exact structural graph relations from the indexed JSON snapshot.

## Consequences

- **Zero Data Loss**: Session-scoped knowledge graph data is captured on export and permanently indexed in AiRaccoon memory.
- **Zero Heavy Dependencies Required**: Developers do not need PyTorch or HuggingFace transformers for routine agent coding sessions.
- **Clear Tool Allocation**: Semantica handles active intra-session decision causality; `code-review-graph` handles code symbols; AiRaccoon handles cross-session durable memory recall.
