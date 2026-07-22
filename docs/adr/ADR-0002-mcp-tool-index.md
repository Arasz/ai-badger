# ADR-0002: MCP Tool Index with Tag + Intent Semantic Matching

**Date:** 2026-07-22
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent
**Supersedes:** None

## Context

MCP servers expose 40+ tools per server (Rider has 42, Playwright 24, dotnet-sdk 12). All tool definitions are injected into the LLM's system prompt every turn. This causes two problems:

1. **Prompt bloat:** Tool definitions consume thousands of tokens that are wasted on most turns (a database query doesn't need to see `browser_navigate`)
2. **Tool selection errors:** The agent sometimes picks the wrong tool from a set of near-duplicates (e.g., `search_text` vs `search_in_files_by_text` vs `search_symbol`)

ai-badger already has a `pre_llm_call` hook (`ai_badger_hooks.py`) that injects framework context. We can extend this hook to also inject targeted tool recommendations, reducing the cognitive load on the agent.

## Decision

We will build an **MCP Tool Index** — a YAML file (`.ai-badger/mcp-tools.yaml`) that maps every MCP server tool to:

1. **Tags** — category labels from a closed taxonomy (e.g., `[dotnet, build, csharp]`, `[diagnostic]`, `[database, sql]`)
2. **Intent** — a one-sentence description of what the tool accomplishes, used for semantic disambiguation between tools that share the same tags

The index feeds into the `pre_llm_call` hook, which extracts domain keywords from the user's message and injects a compact hint listing the top-5 relevant tools.

### DD-1: Tags + Intent as the compound index key

Both are required. Tags enable categorical filtering; intent disambiguates tools that share the same tags. Multiple tools from different MCP servers can share the same intent.

### DD-2: Closed tag taxonomy

Tags come from a curated set in `features/common/mcp-tags.json`:

| Category | Tags |
|---|---|
| Language | `csharp`, `typescript`, `javascript`, `python`, `sql`, `css`, `html` |
| Action | `navigation`, `diagnostic`, `build`, `run`, `refactoring`, `search`, `read`, `write`, `terminal` |
| Domain | `database`, `tracing`, `opentelemetry`, `browser`, `dotnet`, `semantic`, `files` |
| Meta | `batch`, `slow`, `unsafe` |

New tags are added via PR to `mcp-tags.json`.

### DD-3: YAML format over JSON

The index is hand-editable. Agents and humans co-author it: `mcp-index init` auto-tags ~60% of tools by name heuristics, then the user (or agent) curates the rest with `mcp-index tag <tool> <tags...>`.

### DD-4: `mcp-index` as an operational skill

The index is managed by a new operational skill (`skills/mcp-index/`) with a Python script that provides `init`, `update`, `validate`, `tag`, `intent`, and `list` commands. This mirrors the existing `welcome-ai-badger`/`den-refresh` pattern.

### DD-5: `pre_llm_call` hook integration (not prompt filtering)

Hermes does not currently support filtering which MCP tools are injected into the system prompt. Instead, the `pre_llm_call` hook injects a context hint listing the top-5 relevant tools. The agent still sees all tools but is steered toward the right ones.

**Future:** If Hermes adds support for tool-level filtering in the system prompt, the index can be used directly to prune the tool list, yielding substantial token savings.

### DD-6: Dogfood first on job-search-ai-assistant

The index was hand-authored for all 42 Rider MCP tools and validated with a 16-query semantic matching spike (100% accuracy with keyword + intent overlap). A full 10-query agent-level dogfood suite will be run after the feature ships.

## Alternatives Considered

### A) Per-server index files

Rejected. A single `.ai-badger/mcp-tools.yaml` is simpler to load, validate, and version-control. Per-server files would require multiple file reads and cross-referencing.

### B) Embedding-based semantic matching

Rejected for v1. Keyword extraction + tag intersection + intent word overlap achieves 100% accuracy on the 16-query spike suite with zero external dependencies. Embedding-based matching could be added as a v2 optimization if keyword matching proves insufficient for complex queries.

### C) Cron-only approach (no hooks)

Rejected. The hook provides real-time tool recommendations during the agent's decision loop. A cron-only approach (periodic index validation) is complementary but doesn't solve the tool-selection problem mid-turn.

### D) Free-form tags (no taxonomy)

Rejected. A closed taxonomy enables validation (`mcp-index validate` catches unknown tags) and ensures consistent filtering across projects. Free-form tags would drift and become unusable for automated recommendations.

## Consequences

### Positive

- **Reduced tool-selection errors:** The agent gets a ranked shortlist instead of scanning 40+ tool definitions
- **Faster tool discovery:** `mcp-index list --tag diagnostic` surfaces all diagnostic tools across all MCP servers
- **Index portability:** The YAML file is committed to the project repo and shared across all agents (Hermes, Claude, Copilot)
- **Observability:** The `post_tool_observer` hook logs index hit/miss metrics

### Negative

- **Maintenance burden:** The index must be updated (`mcp-index update`) after adding/removing MCP servers
- **Initial curation cost:** `mcp-index init` auto-tags ~60% of tools; the remaining ~40% need manual curation with `mcp-index tag`
- **No prompt-level tool filtering yet:** The agent still receives all tool definitions in the system prompt until Hermes adds support for tool-level filtering

### Migration

1. Run `mcp-index init` in any ai-badger scaffolded project to create the index
2. Curate tools tagged as `general` with `mcp-index tag`
3. Install the updated `ai_badger_hooks.py` plugin
4. The `pre_llm_call` hook automatically picks up the index on next session start

## References

- Phase 0 spike results: `job-search-ai-assistant/.hermes/plans/2026-07-22-mcp-tool-index.md`
- Phase 0 spike script: `job-search-ai-assistant/scripts/spike_mcp_match.py`
- Hand-authored index: `job-search-ai-assistant/.ai-badger/mcp-tools.yaml`
