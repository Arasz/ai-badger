# Semantica Integration — Evidence Review

## What was checked

1. **What is Semantica?** Graph-native infrastructure for context and accountable AI. MIT licensed. Python 3.8+. Provides knowledge graph construction, decision intelligence, causal reasoning, provenance (W3C PROV-O), ontology governance, and polyglot graph storage. Ships as a single `pip install semantica` package.

2. **MCP surface**: 12 tools over stdio (`python -m semantica.mcp_server`):
   - `extract_entities` — NER on any text
   - `extract_relations` — relation/triplet extraction
   - `record_decision` — persist a decision node with full context
   - `query_decisions` — search decision history
   - `find_precedents` — semantic precedent lookup
   - `get_causal_chain` — full causal ancestry
   - `add_entity` — add a KG node
   - `add_relationship` — add a KG edge
   - `run_reasoning` — forward-chaining IF/THEN rules
   - `get_graph_analytics` — centrality, communities
   - `export_graph` — RDF/JSON/Parquet export
   - `get_graph_summary` — graph statistics

3. **Installation**: `pip install semantica` works (0.6.5). One transitive dep (gensim) fails to build on Python 3.14 but semantica core installs fine without it. `semantica doctor` confirms working graph store (in-memory), vector store (needs faiss, optional).

4. **Licensing**: MIT. Can use as tool and mention the repo, same as code-review-graph (also MIT).

5. **Usefulness next to AiRaccoon memory**:
   - AiRaccoon: hybrid semantic search over indexed files — recall, not reasoning
   - Semantica: structured knowledge graph with entities, relationships, decisions, causal chains, provenance
   - Complementary: AiRaccoon answers "what do we know about X?"; Semantica answers "how are these things connected?", "why was this decision made?", "what is the full causal chain?"
   - Primary use for ai-badger: decision tracking (record architectural decisions as structured graph nodes with causal links), entity extraction from agent conversations, reasoning over accumulated project knowledge

6. **Existing integration pattern** (code-review-graph):
   - `features/common/mcp/<name>/meta.json` — server declaration with prerequisite
   - `features/common/mcp/<name>/server.md` — agent instruction snippet (injected into CLAUDE.md/HERMES.md)
   - `features/common/mcp/<name>/tools.json` — tool intent catalog
   - `features/common/stack-mcp.json` — wires it into common stack
   - Our task adds the **skill** layer on top: a SKILL.md that tells the agent when and how to use these tools

7. **Official Claude plugin structure** (reference for our skill):
   - 17 skills in `plugins/skills/` — each a SKILL.md with YAML frontmatter
   - Skills are slash-command oriented (e.g., `/semantica:decision record <args>`)
   - Each skill wraps Python API calls to semantica context/decision modules
   - Plugin manifest: `plugin.json` with name, description, skills path

## Dogfooding results (live MCP tools testing)

Tested all 12 tools against the live MCP server (v0.6.5, Python 3.14, only core deps — no torch/transformers/gensim):

| Tool | Status | Notes |
|------|--------|-------|
| `add_entity` | WORKS | Returns `{"status":"added","id":"..."}` |
| `add_relationship` | WORKS (param names differ from schema) | Uses `source`/`target` not `source_id`/`target_id` as schema says |
| `record_decision` | WORKS | Returns UUID + status |
| `query_decisions` | WORKS (empty with fresh graph) | Stateless — returns `{"decisions":[]}` |
| `find_precedents` | WORKS (empty with fresh graph) | Stateless — returns `{"precedents":[]}` |
| `get_causal_chain` | NOT TESTED | Requires existing decision IDs |
| `get_graph_summary` | WORKS | Returns `{"node_count":0,"decision_count":0,"graph_ready":true}` |
| `get_graph_analytics` | BROKEN | `PageRank calculation failed: 'dict' object is not callable` — Python API mismatch in semantica 0.6.5 |
| `extract_entities` | DEGRADED | Returns entity labels (PERSON, ORG) but no names — needs torch/transformers for full NER |
| `extract_relations` | DEGRADED | Returns empty — needs torch/transformers for relation extraction |
| `run_reasoning` | NOT TESTED | Requires facts in the graph first |
| `export_graph` | NOT TESTED | Requires graph content |

### Key finding: MCP server is stateless per invocation

Each `python -m semantica.mcp_server` spawns a new process with a fresh in-memory graph. Entities/decisions/relationships added in one call do NOT persist to the next. This fundamentally shapes the skill design:

- **Stateless tools that work standalone**: `extract_entities`, `extract_relations` (degraded without torch), `add_entity`, `add_relationship`, `record_decision`
- **State-dependent tools that need a populated graph**: `query_decisions`, `find_precedents`, `get_causal_chain`, `get_graph_summary`, `get_graph_analytics`, `export_graph`, `run_reasoning`

**Implication for the skill**: The integration must either (a) batch graph construction + query into a single MCP call, or (b) note that persistence requires the CLI/file-backed mode. The MCP server as designed is a thin wrapper over in-memory ContextGraph — useful for one-shot extraction/recording, not for building a persistent knowledge base across sessions.

### Degraded extraction without ML deps

Without torch, transformers, and gensim (which fails to build on Python 3.14), the NER/relation extraction returns minimal labels. The skill should note this dependency and focus on the graph-structural and decision tools that work without full NLP.

## What still needs research
- Whether semantica's MCP server can be configured with a persistent backend (file, neo4j, etc.)
- Whether the `semantica init` / `semantica config` can set up persistence for the MCP server
- Whether `get_graph_analytics` is fixable (likely a simple API mismatch in the MCP server wrapper)

## Gathered evidence

All from live sources:
- GitHub repo: https://github.com/semantica-agi/semantica (MIT, README fetched)
- PyPI: semantica 0.6.5 installed and verified (`semantica doctor` pass)
- MCP tools: 12 tools discovered via `tools/list` JSON-RPC call
- Claude plugin: 17 skills, 3 agents, plugin.json + marketplace.json examined
- code-review-graph pattern: meta.json, server.md, tools.json, stack-mcp.json wiring
