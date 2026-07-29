<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Reach for the code-review-graph MCP tools before
Grep/Glob/Read** — they cost fewer tokens and return structural context (callers,
dependents, test coverage) that file scanning cannot. Fall back to Grep/Glob/Read only
where the graph doesn't reach.

Entry points: `semantic_search_nodes_tool` to locate code, `query_graph_tool` to trace
callers/callees/imports/tests, `detect_changes_tool` for review, `get_impact_radius_tool`
for blast radius, `get_architecture_overview_tool` for structure. Each tool's own
description covers the rest; the graph auto-updates on file change.
