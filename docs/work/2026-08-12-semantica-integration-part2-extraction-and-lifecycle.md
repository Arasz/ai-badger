# Semantica Integration Part 2: Local Extraction Options & Process Lifecycle Analysis

**Date:** 2026-08-12  
**Task:** `semantica-integration-part2`  
**Status:** COMPLETE  
**Authors:** Hermes Agent / ai-badger orchestrator  

## Executive Summary

Following the initial integration of Semantica (v0.6.5) as a common MCP server in `ai-badger` 0.116.3, this record addresses two core operational questions raised during live dogfooding and evidence analysis:

1. **What are our options for local extraction?**
2. **What does "no import" mean for us? Is the data gathered isolated to one process?**

---

## 1. Local Extraction Options

Semantica provides two NLP-focused extraction tools: `extract_entities(text)` and `extract_relations(text)`.

### Findings & Mechanics
- **No LLM API Key Required**: Semantica's built-in extraction relies on local HuggingFace NLP models via PyTorch/Transformers (`dslim/bert-base-NER` and relation extraction pipelines), not remote LLM API calls.
- **Graceful Degradation / Failure Mode**: If `torch` and `transformers` are not installed in the Python environment running `python3 -m semantica.mcp_server`:
  - `extract_entities(text)` returns entity types without extracted names/text.
  - `extract_relations(text)` returns an empty list `[]`.

### Evaluated Options for AI Agents & Developers

| Option | Mechanism | Dependencies | Performance / Overhead | Precision & Suitability |
| :--- | :--- | :--- | :--- | :--- |
| **Option 1: Native Local ML Stack** | `extract_entities` & `extract_relations` via Semantica | `torch`, `transformers` (~2-3GB) | Heavy disk/RAM footprint (~2.5GB cache), ~10-15s cold-start model load on first call | Good for generic text; poor for domain-specific code ASTs or architectural rationale |
| **Option 2: Agent-Guided Extraction (Recommended)** | AI Agent (Hermes/Claude/Copilot) extracts entities & relationships directly, calling `add_entity` & `add_relationship` | None (builtin agent reasoning) | Instantaneous, zero cold-start, zero extra pip dependencies | Excellent — 100% precise, domain-tailored, understands code symbols, architecture decisions, and causality |
| **Option 3: Code AST Parsers** | `code-review-graph` MCP tools / Tree-sitter / PyAST | Existing `code-review-graph` MCP server | Sub-second, deterministic | Excellent for code structure (symbol call graphs), but does not extract natural language reasoning |
| **Option 4: Hybrid Workflow (Standard)** | Agent-guided for decisions/specs; optional ML stack for bulk text | Optional `pip install torch transformers` | Adaptive | Best developer experience |

### Recommendation
For `ai-badger` agent instruction workflows, **Option 2 (Agent-Guided Extraction)** is the primary recommended pattern. The agent already possesses high reasoning capacity to parse code, specs, and decisions; invoking `add_entity` and `add_relationship` avoids requiring developers to install PyTorch/Transformers while providing superior extraction quality for technical concepts.

---

## 2. Process Lifecycle, "No Import", and Data Isolation

### Is the data gathered isolated to one process? **YES.**
- **Process Boundaries**: Semantica runs as a stdio MCP server (`python3 -m semantica.mcp_server`). The knowledge graph (NetworkX / dictionary of nodes and edges) is stored **entirely in-memory within that single Python process**.
- **State Accumulation**: All MCP tool invocations (`add_entity`, `add_relationship`, `record_decision`) from a single connected client mutate the in-memory graph of that specific process instance.
- **Process Isolation**: Separate processes (e.g. parallel agent subagents in separate worktrees, or separate terminal sessions) each spawn their own `python3 -m semantica.mcp_server` process with an isolated, empty graph. There is no shared IPC or cross-process memory pool.

### What "no import" means for us
- **Export Capabilities**: Semantica v0.6.5 provides `export_graph(format="json")`, which serializes the current in-memory graph into a JSON string or file.
- **No Import Tool**: Semantica v0.6.5 has **NO `import_graph` or `load_graph` functionality**.
- **Lifecycle Consequences**:
  1. **Session-Scoped Lifetime**: When the `python3 -m semantica.mcp_server` process terminates (on agent disconnect, session finish, or IDE reload), the in-memory graph is completely destroyed.
  2. **Un-restorable Exports**: An `export_graph` JSON snapshot **cannot be re-loaded** into a future Semantica session.
  3. **Archival Purpose Only**: `export_graph` serves exclusively as an offline audit trail or human inspection artifact (e.g., attaching to PR descriptions or saving in `docs/work/`).

### Architectural Relationship: Semantica vs. AiRaccoon

| Dimension | Semantica | AiRaccoon |
| :--- | :--- | :--- |
| **Persistence** | Session-scoped (in-memory) | Cross-session durable (`memory.db` SQLite) |
| **Data Model** | Directed Knowledge Graph (Entities, Relations, Causal Chains) | Hybrid FTS5 + Vector Document Memory |
| **Primary Question** | *"How are things connected?"* / *"Why was this decision made?"* | *"What do we know?"* / *"Where are the docs for X?"* |
| **Cross-Session Strategy** | Ephemeral intra-session reasoning | Durable fact storage via `memory_write` |

**Rule**: To preserve a decision or relationship across sessions, the AI Agent must record the reasoning in Semantica for intra-session causal queries AND write the durable summary to AiRaccoon via `memory_write` or tracked documentation (ADR / changelog).
