<!-- ai-raccoon MCP tools -->
## MCP Tools: ai-raccoon

AiRaccoon is the project memory server. Search memory FIRST — before web search, code search, or
asking the user — with `query` (projectId, scope=all) and 2-3 query formulations. Entries
carry source paths, so a decisive hit is evidence: cite it. Escalate by result — a partial hit gets
one targeted external search; no hit means search externally, then write the finding back with
`add_memory` including the source path.

Every call passes projectId. Plain writes land in committed project memory; active workspaces
isolate in-progress notes and consolidate on finish; `share_memory` promotes durable cross-project
facts. Keep the docs directory searchable: check `get_watch_status`, then `add_watch`
(projectId + absolute path) when no watch exists.
