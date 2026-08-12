# Semantica Integration — Implementation Plan

**Date:** 2026-08-12
**Status:** Plan (pre-execution)
**Review gate:** MoE review required before execution (per user requirement)

## Summary

Integrate Semantica (MIT-licensed knowledge graph MCP server, v0.6.5) into ai-badger as a common
MCP server catalog entry plus a derived Hermes integration skill. Semantica provides structured
reasoning over accumulated project knowledge — entities, relationships, causal chains, decision
provenance — complementing AiRaccoon's semantic recall.

## Files to create / modify

| File | Action | Parallel lane |
|---|---|---|
| `features/common/mcp/semantica/meta.json` | Create | Lane A |
| `features/common/mcp/semantica/server.md` | Create | Lane A |
| `features/common/mcp/semantica/tools.json` | Create | Lane A |
| `features/common/stack-mcp.json` | Modify (add entry) | Lane A (after meta.json) |
| `features/common/skills/semantica-knowledge-graph/SKILL.md` | Create | Lane B |
| `tests/test_mcp_semantica_catalog.py` | Create | Lane C |
| `tests/test_semantica_knowledge_graph_skill.py` | Create | Lane C |
| `VERSION` | Bump (patch: `0.116.3`) | Lane D |
| `docs/changelog/0.116.3-semantica-integration.md` | Create | Lane D |

---

## Section 1: MCP Server Catalog Entry (Lane A — serial: meta.json → tools.json → stack-mcp.json)

### 1.1 `features/common/mcp/semantica/meta.json`

**Pattern:** `features/common/mcp/code-review-graph/meta.json`

```json
{
  "$schema": "../../../../schemas/mcp-server.schema.json",
  "name": "semantica",
  "package": "semantica",
  "description": "Graph-native knowledge graph infrastructure: entity extraction, relationship modeling, decision intelligence with W3C PROV-O provenance, causal reasoning, and ontology governance — served over MCP stdio.",
  "homepage": "https://github.com/semantica-agi/semantica",
  "prerequisite": {
    "summary": "the semantica Python distribution, importable by the interpreter that runs the launch command",
    "check": "python3 -c 'import semantica'",
    "install": "python3 -m pip install semantica"
  }
}
```

**Acceptance criteria:**
- [ ] Validates against `schemas/mcp-server.schema.json`
- [ ] `name` matches the directory name (`semantica`)
- [ ] `prerequisite.check` exits 0 when semantica is installed, non-zero otherwise
- [ ] `prerequisite.install` is a working one-liner on a machine with pip

**Quality gate:** `python3 -m jsonschema -i features/common/mcp/semantica/meta.json schemas/mcp-server.schema.json` passes.

### 1.2 `features/common/mcp/semantica/server.md`

**Pattern:** `features/common/mcp/code-review-graph/server.md`

```markdown
<!-- semantica MCP tools -->
## MCP Tools: semantica

Semantica is the project knowledge graph. It complements AiRaccoon memory: AiRaccoon answers
"what do we know about X?"; Semantica answers "how are these things connected?", "why was this
decision made?", "what is the full causal chain?". The graph is in-memory — record decisions,
entities, and relationships as you work; they persist for the session.

Start every graph inquiry with `get_graph_summary` for orientation, then drill into specifics
with `query_decisions`, `find_precedents`, or `get_causal_chain`. Record architectural decisions
with `record_decision` — include context, rationale, and alternatives considered. Each tool's
own description covers the rest.
```

**Acceptance criteria:**
- [ ] Valid HTML comment format (matching `<!-- name MCP tools -->` header)
- [ ] Under 500 chars (agent instruction budget — code-review-graph server.md is 443 chars)
- [ ] Names the complementarity with AiRaccoon
- [ ] Gives entry-point tool guidance (`get_graph_summary`)
- [ ] Covers the primary use case (decision recording)

**Quality gate:** Manual review for token budget adherence (under the 17,500 char agentDocs limit in config.json — this is one of several MCP sections that share that budget).

### 1.3 `features/common/mcp/semantica/tools.json`

**Pattern:** `features/common/mcp/code-review-graph/tools.json` + `features/common/mcp/ai-raccoon/tools.json`

**12 tools** documented in the evidence review (`2026-08-12-semantica-integration-review.md`). Below is the curated intent per tool, using the closed tag vocabulary from `features/common/mcp-tags.json`:

| Tool | Intent | Tags |
|---|---|---|
| `get_graph_summary` | Orientation entry point: graph statistics, entity/relation counts, domain overview — before any specific query. | `["read"]` |
| `extract_entities` | Named entity extraction from arbitrary text — feed in a document, conversation excerpt, or design spec and get structured entities back. | `["write", "search"]` |
| `extract_relations` | Extract triplet relations (subject-predicate-object) from text — builds the graph's edge structure from unstructured content. | `["write", "search"]` |
| `add_entity` | Manually add a knowledge graph node with properties — for facts the agent knows but that aren't in text to extract. | `["write"]` |
| `add_relationship` | Manually add an edge between two existing entities — link concepts the agent connected through reasoning. | `["write"]` |
| `record_decision` | Persist an architectural decision as a provenance-tracked node with context, rationale, alternatives, and constraints. | `["write"]` |
| `query_decisions` | Search the decision history by keyword, date range, or domain — "what did we decide about authentication?" | `["search"]` |
| `find_precedents` | Semantic precedent lookup — "has a decision like this been made before?" Returns similar past decisions ranked by relevance. | `["search", "semantic"]` |
| `get_causal_chain` | Full causal ancestry of a decision or entity — trace every "because" back to root assumptions. | `["navigation", "diagnostic"]` |
| `run_reasoning` | Forward-chaining IF/THEN rules over the graph — derive new facts, check consistency, or flag conflicts. | `["run", "batch"]` |
| `get_graph_analytics` | Centrality, community detection, and structural metrics — understand the graph's shape without reading every node. | `["diagnostic", "read"]` |
| `export_graph` | Export the current graph in RDF, JSON, or Parquet format for persistence, sharing, or external analysis. | `["write", "files"]` |

```json
{
  "$schema": "../../../../schemas/mcp-server-tools.schema.json",
  "server": "semantica",
  "tools": [
    {"name": "get_graph_summary", "intent": "Orientation entry point: graph statistics, entity/relation counts, domain overview — before any specific query.", "tags": ["read"]},
    {"name": "extract_entities", "intent": "Named entity extraction from arbitrary text — feed in a document, conversation excerpt, or design spec and get structured entities back.", "tags": ["write", "search"]},
    {"name": "extract_relations", "intent": "Extract triplet relations (subject-predicate-object) from text — builds the graph's edge structure from unstructured content.", "tags": ["write", "search"]},
    {"name": "add_entity", "intent": "Manually add a knowledge graph node with properties — for facts the agent knows but that aren't in text to extract.", "tags": ["write"]},
    {"name": "add_relationship", "intent": "Manually add an edge between two existing entities — link concepts the agent connected through reasoning.", "tags": ["write"]},
    {"name": "record_decision", "intent": "Persist an architectural decision as a provenance-tracked node with context, rationale, alternatives, and constraints.", "tags": ["write"]},
    {"name": "query_decisions", "intent": "Search the decision history by keyword, date range, or domain — 'what did we decide about authentication?'", "tags": ["search"]},
    {"name": "find_precedents", "intent": "Semantic precedent lookup — 'has a decision like this been made before?' Returns similar past decisions ranked by relevance.", "tags": ["search", "semantic"]},
    {"name": "get_causal_chain", "intent": "Full causal ancestry of a decision or entity — trace every 'because' back to root assumptions.", "tags": ["navigation", "diagnostic"]},
    {"name": "run_reasoning", "intent": "Forward-chaining IF/THEN rules over the graph — derive new facts, check consistency, or flag conflicts.", "tags": ["run", "batch"]},
    {"name": "get_graph_analytics", "intent": "Centrality, community detection, and structural metrics — understand the graph's shape without reading every node.", "tags": ["diagnostic", "read"]},
    {"name": "export_graph", "intent": "Export the current graph in RDF, JSON, or Parquet format for persistence, sharing, or external analysis.", "tags": ["write", "files"]}
  ]
}
```

**Acceptance criteria:**
- [ ] Validates against `schemas/mcp-server-tools.schema.json`
- [ ] All 12 tools present with unique names
- [ ] All tags are drawn from the closed vocabulary in `features/common/mcp-tags.json`
- [ ] Every `intent` is ≤ 200 chars (schema limit)
- [ ] Tools are listed in workflow order: orientation → extraction → manual addition → decision → search → reasoning → analytics → export

**Quality gate:** `python3 -m jsonschema -i features/common/mcp/semantica/tools.json schemas/mcp-server-tools.schema.json` passes.

### 1.4 `features/common/stack-mcp.json` — Add semantica entry

**Pattern:** Existing entries in the file (code-review-graph, hermes, ai-raccoon).

Add after the ai-raccoon entry:

```json
    {
      "name": "semantica",
      "command": "python3 -m semantica.mcp_server",
      "declare": true,
      "availability": {
        "command": "python3"
      }
    }
```

**Design rationale:**
- `declare: true` — ai-badger writes the launch config. Semantica is always local (pip install), never a remote endpoint, so ai-badger can declare it.
- `availability.command: "python3"` — Python 3.8+ is a universal prerequisite for ai-badger itself; this gate is handled by the meta.json prerequisite chain. Python3 is always available on ai-badger hosts, so this gate is always satisfied. We don't gate on `semantica` itself because the prerequisite in meta.json documents what's needed; the availability gate here ensures the interpreter exists before writing launch config.
- No `agentOverrides` — the same `python3 -m semantica.mcp_server` command works for all agents (Claude Code, Hermes, Copilot).
- No `env` — Semantica's in-memory graph store needs no environment variables. If a future version requires an API key for LLM-backed extraction, that's documented in the prerequisite and set by the user, not ai-badger.

**Acceptance criteria:**
- [ ] Validates against `schemas/stack-mcp.schema.json`
- [ ] Entry appears after `ai-raccoon` in the `servers` array
- [ ] `command` launches semantica's MCP server when invoked in a shell with semantica installed
- [ ] `index_build.py --check` passes (the new `features/common/mcp/semantica/` dir is picked up by the mcp discovery rule)

**Quality gate:** `python3 tooling/index_build.py --check` passes with the full change set.

---

## Section 2: Integration Skill (Lane B — parallel with Lane A)

### 2.1 `features/common/skills/semantica-knowledge-graph/SKILL.md`

**Pattern:** `features/common/skills/ai-raccoon-memory/SKILL.md`

The skill follows the same structure: YAML frontmatter, "When NOT to Use" guard, numbered workflow sections with specific tool calls, gotchas, and a verification checklist.

**Frontmatter:**

```yaml
---
name: semantica-knowledge-graph
description: >-
  Use when reasoning over structured project knowledge — record decisions with provenance,
  trace causal chains, extract entities from conversations, or run graph analytics.
  Complements AiRaccoon memory (recall) with structured reasoning (connections and causality).
version: 0.1.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [knowledge-graph, decision-tracking, causal-reasoning, provenance]
    related_skills: [ai-raccoon-memory, mcp-index, hermes-mcp-setup]
---
```

**Skill body outline:**

1. **When NOT to Use** — A one-off lookup "is this connected to that?" — use `memory_search` (AiRaccoon); no decision was made and no entity needs extraction → skip the graph ceremony. The graph is in-memory per session; don't record trivia.

2. **Decision-recording workflow** — When making an architectural decision:
   - `record_decision(decision_text, context="...", rationale="...", alternatives=["..."], constraints=["..."])` — persist with full provenance
   - `add_entity` for key concepts the decision references (if not auto-extracted)
   - `add_relationship` to link decision to affected components
   - Cite the decision in commit messages / PR descriptions for traceability

3. **Entity extraction workflow** — When analyzing a conversation, document, or spec:
   - `extract_entities(text)` → structured entity list
   - `extract_relations(text)` → triplet relations
   - `get_graph_summary()` → verify the graph reflects the extraction
   - `get_graph_analytics()` → check centrality to find key entities

4. **Decision archaeology workflow** — When asking "why did we do this?":
   - `query_decisions(query="keyword", domain="...")` → find relevant decisions
   - `get_causal_chain(entity_or_decision_id)` → trace full ancestry
   - `find_precedents(query="...")` → has this pattern appeared before?

5. **Reasoning workflow** — When deriving new facts or checking consistency:
   - `run_reasoning(rules=[...], target="...")` → forward-chain inference
   - `export_graph(format="json")` → save for cross-session persistence

6. **Escalation by result**:
   - Graph is empty → `get_graph_summary` returns zero nodes; start with entity extraction or decision recording
   - No precedent found → record the decision now so it becomes a precedent for the next inquiry
   - Causal chain incomplete → add missing intermediate entities/relationships, then re-query

7. **Gotchas**:
   - The graph store is **in-memory** — decisions and entities do not survive a session restart. Export the graph (`export_graph`) before ending a session if persistence matters.
   - Entity extraction may require an LLM provider; check `semantica doctor` if extraction tools return errors.
   - `record_decision` expects structured fields — don't just paste raw text.
   - The graph is session-scoped; cross-project sharing is via export, not a shared server.

8. **AiRaccoon complementarity**:
   - AiRaccoon: "what do we know?" (semantic recall) → `memory_search`
   - Semantica: "how are things connected?" (structured reasoning) → `get_graph_summary` → `query_decisions`
   - Use both: search AiRaccoon for context first, then trace relationships in Semantica
   - Write durable facts to AiRaccoon (`memory_write`); decisions and causal chains go to Semantica

9. **Verification Checklist**:
   - [ ] `get_graph_summary` returns node/edge counts reflecting the session's activity
   - [ ] At least one decision was recorded with `record_decision` and is findable via `query_decisions`
   - [ ] `get_causal_chain` traces back to the root for at least one decision
   - [ ] `export_graph` produces valid JSON when persistence is needed
   - [ ] AiRaccoon `memory_search` and Semantica `query_decisions` return complementary, non-overlapping results

**Acceptance criteria:**
- [ ] YAML frontmatter is valid and `scope: default` ensures auto-inclusion via DEFAULT_SKILLS
- [ ] "When NOT to Use" guard prevents overuse
- [ ] Each workflow names specific MCP tool calls with argument guidance
- [ ] Complementarity with AiRaccoon is clearly explained
- [ ] Gotchas cover the in-memory limitation and LLM provider requirement
- [ ] Verification checklist has testable items
- [ ] Under 120 lines (ai-raccoon-memory is 80 lines; Semantica has fewer tools so should be comparable)
- [ ] `metadata.hermes.tags` and `related_skills` are populated

**Quality gate:** Manual review against the ai-raccoon-memory SKILL.md structure. The `scope: default` ensures the `index_build.py --check` gate picks it up automatically.

---

## Section 3: Testing (Lane C — parallel with Lane A+B; final integration test serial after both)

### 3.1 Catalog validation tests (`tests/test_mcp_semantica_catalog.py`)

**TDD approach:** Write the test RED first (before creating the catalog files), then write the catalog files to make it GREEN.

Test cases:
1. `test_meta_json_validates_against_schema` — Load `meta.json`, validate against `mcp-server.schema.json`
2. `test_tools_json_validates_against_schema` — Load `tools.json`, validate against `mcp-server-tools.schema.json`
3. `test_all_12_tools_present` — `tools.json` has exactly 12 tool entries
4. `test_tool_names_are_unique` — No duplicate tool names
5. `test_tool_tags_are_from_closed_vocabulary` — Every tag in `tools.json` exists in `mcp-tags.json`
6. `test_tool_intents_under_200_chars` — Every `intent` string ≤ 200 chars
7. `test_server_md_exists_and_under_500_chars` — `server.md` exists and is under the token budget
8. `test_server_md_starts_with_comment_header` — `server.md` begins with `<!-- semantica MCP tools -->`
9. `test_stack_mcp_includes_semantica` — `stack-mcp.json` servers array contains `{"name": "semantica"}`
10. `test_semantica_entry_has_required_fields` — entry has `name`, `command`, `declare: true`
11. `test_index_build_discovers_semantica_mcp` — Running `index_build.py` includes semantica in the mcp feature under the common stack
12. `test_index_build_discovers_semantica_skill` — Running `index_build.py` includes `semantica-knowledge-graph` in the skills feature

**Acceptance criteria:**
- [ ] All 12 tests pass (GREEN)
- [ ] RED-GREEN cycle demonstrated: test file committed first, failures witnessed, then catalog files committed
- [ ] Tests run in under 2 seconds (no network, no heavy imports — all JSON schema validation is local)
- [ ] Tests use `jsonschema` for validation (already a required dependency in `engine/requirements.txt`)

**Quality gate:** `python3 -m pytest tests/test_mcp_semantica_catalog.py -q` passes.

### 3.2 Skill structure tests (`tests/test_semantica_knowledge_graph_skill.py`)

Test cases:
1. `test_skill_md_exists` — `SKILL.md` file exists
2. `test_skill_md_has_valid_yaml_frontmatter` — Parse frontmatter, check required fields
3. `test_skill_scope_is_default` — `scope: default` for auto-inclusion
4. `test_skill_has_when_not_to_use_section` — Contains "When NOT to Use" heading
5. `test_skill_has_workflow_sections` — Contains at least 3 numbered workflow sections
6. `test_skill_has_gotchas_section` — Contains gotchas
7. `test_skill_has_verification_checklist` — Contains verification checklist with checkboxes
8. `test_skill_references_specific_tools` — Contains at least 6 of the 12 semantica tool names
9. `test_skill_mentions_ai_raccoon_complementarity` — Mentions AiRaccoon and explains the distinction
10. `test_skill_under_120_lines` — Total line count ≤ 120

**Acceptance criteria:**
- [ ] All 10 tests pass
- [ ] RED-GREEN cycle demonstrated

**Quality gate:** `python3 -m pytest tests/test_semantica_knowledge_graph_skill.py -q` passes.

### 3.3 Integration gate (serial, after Lane A + Lane B merge)

After both lanes merge, run the full build:
- `python3 tooling/index_build.py --check` — confirms index.json is fresh and valid
- `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')` — no new lint warnings
- `python3 -m pytest -q` — full test suite passes

---

## Section 4: VERSION + Changelog (Lane D — last, serial after everything else merges)

### 4.1 Version bump

- `VERSION`: `0.116.2` → `0.116.3` (patch bump: new feature, no breaking changes)

### 4.2 Changelog

`docs/changelog/0.116.3-semantica-integration.md`:

```markdown
# 0.116.3 — Semantica MCP Server + Integration Skill

## Added

- **MCP server catalog entry for Semantica** (`features/common/mcp/semantica/`)
  - 12 curated tools with intents: entity extraction, relationship modeling, decision
    provenance (W3C PROV-O), causal reasoning, graph analytics, and export
  - Wired into the common stack (`features/common/stack-mcp.json`) with
    `python3 -m semantica.mcp_server` as the launch command
  - Prerequisite: `pip install semantica` (MIT-licensed, v0.6.5+)

- **Integration skill** (`features/common/skills/semantica-knowledge-graph/SKILL.md`)
  - Teaches the agent when and how to use Semantica's 12 MCP tools
  - Decision-recording, entity extraction, causal archaeology, and reasoning workflows
  - Complementarity guide: AiRaccoon (semantic recall) vs Semantica (structured reasoning)
  - `scope: default` for automatic inclusion in new scaffolds

## Changed

- `features/common/stack-mcp.json` — added semantica to the common server list
```

**Acceptance criteria:**
- [ ] `VERSION` reads `0.116.3`
- [ ] Changelog file exists at `docs/changelog/0.116.3-semantica-integration.md`
- [ ] Changelog follows the existing format (checked against another changelog entry)
- [ ] `docs/changelog/README.md` updated if this is a new format convention (check — likely not needed)

**Quality gate:** Git diff shows only the expected files changed. `VERSION` is bumped.

---

## Section 5: Integration Order & Parallelism

```
                    ┌─────────────────────┐
                    │  Plan + MoE Review   │ ← GATE (this document)
                    └─────────┬────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
     ┌────────────────┐ ┌──────────┐ ┌──────────────┐
     │  Lane A:       │ │ Lane B:  │ │ Lane C:      │
     │  Catalog Entry │ │ Skill    │ │ Tests (TDD)  │
     │                │ │ SKILL.md │ │              │
     │ meta.json      │ │          │ │ catalog +    │
     │   ↓            │ │          │ │ skill tests  │
     │ tools.json     │ │          │ │              │
     │   ↓            │ │          │ │ (can write   │
     │ server.md      │ │          │ │ tests before │
     │   ↓            │ │          │ │ files exist) │
     │ stack-mcp.json │ │          │ │              │
     └───────┬────────┘ └────┬─────┘ └──────┬───────┘
             │               │              │
             └───────────────┼──────────────┘
                             ▼
                  ┌─────────────────────┐
                  │  Integration Gate   │
                  │  index_build --check│
                  │  pytest -q          │
                  │  pylint             │
                  └─────────┬───────────┘
                            ▼
                  ┌─────────────────────┐
                  │  Lane D:            │
                  │  VERSION + Changelog│
                  └─────────┬───────────┘
                            ▼
                  ┌─────────────────────┐
                  │  Dogfooding         │
                  │  (see Section 6)    │
                  └─────────────────────┘
```

**What can run in parallel:**
- Lane A (catalog entry) and Lane B (skill) are fully independent — they touch different files with no shared dependency
- Lane C (tests) can begin RED as soon as the schemas are understood — write tests against the expected file structure before creating the files, then run them GREEN after Lanes A and B deliver

**What must serialize:**
- `tools.json` after `meta.json` within Lane A (the `server` field in tools.json references the server name, but both files are in the same directory and written together)
- `stack-mcp.json` edit after `meta.json` exists (the `name` field references the catalog directory, and `index_build.py` checks it)
- Integration gate after all three lanes merge
- Lane D (version + changelog) after integration gate passes
- Dogfooding after Lane D

---

## Section 6: Dogfooding Plan

After the integration is complete (all tests pass, index_build succeeds, version bumped):

### 6.1 Setup
1. Ensure Semantica is installed: `pip install semantica` (already verified working in the evidence review)
2. Run `semantica doctor` to confirm graph store health
3. Re-scaffold the worktree with the new catalog: `welcome-ai-badger` (or scaffold.py equivalent)
4. Verify the `semantica-knowledge-graph` skill appears in the agent's available skills list

### 6.2 Dogfooding scenarios

#### Scenario 1: Decision recording
- In a coding session, make an architectural decision (e.g., "we'll use SQLite for caching")
- The agent should invoke `record_decision` with context, rationale, and alternatives
- Verify: `query_decisions("SQLite caching")` returns the decision

#### Scenario 2: Causal archaeology
- With at least 2 recorded decisions where one depends on another
- Ask the agent: "why did we pick SQLite for caching?"
- The agent should use `get_causal_chain` to trace the full ancestry
- Verify: the causal chain includes the root decision and all intermediate steps

#### Scenario 3: Entity extraction from conversation
- Provide a paragraph describing system components and their relationships
- The agent should use `extract_entities` and `extract_relations`
- Verify: `get_graph_summary` shows the extracted entities and relations

#### Scenario 4: Complementarity with AiRaccoon
- Ask a question that benefits from both: "what do we know about our auth system and what decisions shaped it?"
- The agent should use `memory_search` (AiRaccoon) for recall + `query_decisions` (Semantica) for decisions
- Verify: both tools return complementary results

#### Scenario 5: Graph persistence across sessions
- Export the graph: `export_graph(format="json")`
- Note: In-memory limitation means the exported artifact is the session's deliverable
- Verify: the exported JSON is valid and contains all recorded decisions and entities

### 6.3 Dogfooding success criteria
- [ ] All 5 scenarios exercised successfully
- [ ] Agent correctly chooses Semantica tools over AiRaccoon tools for decision/causal queries
- [ ] Agent correctly chooses AiRaccoon tools over Semantica for recall queries
- [ ] No tool-call errors (wrong arguments, missing fields)
- [ ] Agent cites decisions from Semantica in its reasoning
- [ ] `get_graph_summary` shows cumulative growth over the session

---

## Section 7: Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Semantica's MCP tools change signature between versions | Low | Medium | Pin to `semantica>=0.6.5,<0.7` in prerequisite docs; the tools.json intents are our interpretation — real signature comes from the server at runtime |
| In-memory graph store limits utility | High | Medium | Clearly document in the skill (gotchas section); recommend `export_graph` for persistence; if demand emerges, investigate file-backed storage |
| LLM-backed extraction tools (entities, relations) need API keys | Medium | Low | Document in prerequisite; the manual `add_entity`/`add_relationship` tools work without LLM |
| Skill is too long for agent context budget | Low | Medium | Target under 120 lines (comparable to ai-raccoon-memory's 80 lines); the server.md snippet is under 500 chars |
| `index_build.py` doesn't pick up the new catalog entry | Low | Low | The mcp discovery rule (`_mcp_items`) picks up any dir under `features/*/mcp/` with a `meta.json` — zero config needed |
| Semantica transitively depends on gensim which fails on Python 3.14 | Medium | Low | Evidence review confirms semantica core works without gensim; document this in the prerequisite if it becomes a support issue |

---

## Section 8: Acceptance Criteria Summary

### Must have (blockers for merge):
- [x] Plan documented (this file) ✅
- [ ] MoE review of plan completed and approved
- [ ] All 12 catalog tests pass (Lane C — tests/test_mcp_semantica_catalog.py)
- [ ] All 10 skill structure tests pass (Lane C — tests/test_semantica_knowledge_graph_skill.py)
- [ ] `index_build.py --check` passes
- [ ] `python3 -m pytest -q` passes (full suite)
- [ ] `python3 -m pylint` passes (no new warnings)
- [ ] VERSION bumped to 0.116.3
- [ ] Changelog entry created
- [ ] TDD RED-GREEN cycle witnessed for both test files

### Should have (stretch):
- [ ] Dogfooding all 5 scenarios
- [ ] At least one dogfooding session where the agent correctly chooses between Semantica and AiRaccoon
- [ ] Graph export round-trip: record → export → verify JSON structure

### Nice to have (future):
- [ ] File-backed graph persistence (not in v0.116.3 scope)
- [ ] Cross-project graph sharing (not in v0.116.3 scope)
- [ ] Pre-built Reasoning Rules library for common ai-badger use cases
