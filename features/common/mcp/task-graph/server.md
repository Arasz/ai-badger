<!-- task-graph MCP tools -->
## MCP Tools: task-graph

`task-graph` owns the decomposed task plan — a DAG of `step`s carrying status, acceptance
criteria and evidence, persisted beside the task tracker in the project's `tracking.db`.

Plan time: `plan_create` validates and stores the DAG; `plan_replace` revises it before
execution starts; `steps_ready` returns the dispatchable frontier and its waves. Execution:
`step_start`, `step_complete` (evidence + AC results), `step_fail`, `step_skip`, `ac_check`;
`progress_checklist` is the status view, and `plan_get`, `step_get`, `plan_export` read back.

Launched as `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_server.py`
(`uv` on PATH; the PEP 723 environment is fetched on first launch). Without a project
`.mcp.json`, the CLI twin takes the same tool names: `task_graph_cli.py <tool> --json`.
