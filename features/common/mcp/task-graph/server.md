<!-- task-graph MCP tools -->
## MCP Tools: task-graph

`task-graph` owns the decomposed task plan — a DAG of `step`s carrying status, acceptance criteria and evidence, persisted beside the task tracker in the project's `tracking.db`.

Plan time: `plan_create` validates and stores the DAG; `plan_replace` revises it before
execution starts; `steps_ready` returns the dispatchable frontier and its waves. Execution:
`step_start`, `step_complete` (evidence + AC results), `step_fail`, `step_skip`, `ac_check`;
`progress_checklist` is the status view, and `plan_get`, `step_get`, `plan_export` read back.

Launched as `uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_server.py`
after an `sh -c` cd into the git root (`uv`, `git` on PATH; PEP 723 env fetched on first launch). No project `.mcp.json` (Hermes,
worktree sessions) → use the CLI twin: `task_graph_cli.py <tool> --json`. Hermes operators:
add the proposed `mcp_servers:` entry to `~/.hermes/config.yaml`, anchoring the script path to
the project root — the declaration is project-relative.
