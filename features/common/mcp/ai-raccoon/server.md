<!-- ai-raccoon MCP tools -->
## MCP Tools: ai-raccoon

AiRaccoon is the project memory server. Search memory FIRST — before web search, code search,
or asking the user — with memory_search (project_id, scope=all) and 2-3 query formulations.
Entries carry source paths; a decisive hit is evidence, so cite it. Escalate by result: a partial
hit → one targeted external search; no hit → search externally, then write the finding back with
memory_write (include the source path).

Every call passes project_id. Plain writes land in committed project memory; active workspaces
isolate in-progress notes (consolidate on finish); promote durable cross-project facts with
memory_share — shared entries are curated and never swept. Keep the docs directory searchable:
check memory_watch_status, then memory_watch_add (project_id + absolute path) when no watch
exists. One-time CLI setup: `ai-raccoon watch scope add` / `ai-raccoon watch enable`.
The common declaration is conditional: ai-badger emits it only when `ai-raccoon` resolves on PATH.
