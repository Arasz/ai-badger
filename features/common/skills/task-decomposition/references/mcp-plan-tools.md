# The task-graph tools

The frozen surface is 12 tools. Their names, inputs and payloads are pinned by the transport
goldens; the skill teaches these and no others. Every call is `PlanRef = {task_id}` — `plan_id`
does not exist.

## The 12 tools

| Tool | Reach for it when |
|---|---|
| `plan_create` | After decomposing a brief into steps with acceptance criteria, when the plan should become the graph execution lanes dispatch from. Validates the DAG and persists revision 0; identical content is idempotent (`created:false`), different content under an existing `task_id` is `already-exists`. |
| `plan_replace` | Before execution starts, when review feedback changes the step set — replaces the whole plan under an `expected_revision` check; `plan-in-progress` once any step left pending/skipped. |
| `plan_get` | First read after a gap or handoff: counts, ready set, blocked steps and the current revision before any mutation (`include` is `summary`, `full`, `steps` or `state`). |
| `plan_export` | At a review or release boundary, to get the canonical stored plan document, schema URL included, as an artifact. |
| `step_get` | When one step's instructions, dependencies, blockers or criteria must be seen in full — cheaper than exporting the whole plan. |
| `step_start` | Take a ready step just before dispatching a lane so `in_progress` and `started_at` are recorded; after a failure this is a retry. |
| `step_complete` | When a lane's verification passed: record the evidence and per-criterion results that close the step; `force` is the only way past failed criteria and requires a reason. |
| `step_fail` | When a lane could not deliver: record the reason and evidence so dependents show blocked instead of silently waiting. |
| `step_skip` | When a step is deliberately not done (superseded, descoped): `skipped` still satisfies readiness, unlike `failed`. |
| `ac_check` | During verification, per acceptance criterion: record passed or failed with evidence while the step is `in_progress`; completion freezes it. |
| `steps_ready` | Before each wave dispatch: the ready frontier, the waves packed around file and resource conflicts, and steps blocked by failures. |
| `progress_checklist` | For a status report or checkpoint: per-step markers, criterion tallies, next and blocked; its `format:"text"` output is the status section verbatim. |

## The CLI twin

With no MCP host, the CLI takes the same 12 names and the same argument objects:

```bash
uv run --script .ai-badger/skills/task-decomposition/scripts/task_graph_cli.py <tool-name> --json <args>
```

`<tool-name>` is one of the frozen twelve; `<args>` is the JSON **object** the tool's input
model accepts. Exit 0 prints the payload, exit 1 prints the closed error envelope, exit 2 is a
usage error (unknown verb, unparseable `--json`, non-object `--json`). Payloads are the
server's by construction — the CLI loads the same handlers.

## Error codes (closed)

Only these codes are emitted; anything else is a bug, not a shape to handle:

`invalid-arguments`, `not-found`, `already-exists`, `conflict`, `invalid-transition`,
`dependencies-incomplete`, `criteria-unmet`, `plan-in-progress`, `schema-version-unsupported`,
`prerequisite-missing`, `config-error`, `store-error`.

The ones a planner meets first: `already-exists` (different content under a live `task_id` —
revise with `plan_replace`), `conflict` (stale `expected_revision`), `plan-in-progress`
(replace attempted after a step left pending/skipped), `dependencies-incomplete` (completion
before a dependency), `criteria-unmet` (completion with unchecked criteria — `force` is the
orchestrator-only way past it).

## Degraded path

No server listed and the CLI does not run means the graph is off. Write the plan file by hand
to `.ai-badger/task-tracking/plans/<YYYY-MM-DD>-<taskId>.md` in the frozen shape: one
`**S<N> …**` heading per step, one `- [ ]` per acceptance criterion, and the generated-banner
note `hand-written — graph off`. Say the graph is off, and never hand-write `tracking.db`.
Without the graph, failure blocking, force, blocked-descendant and join enforcement are not
applied — checkbox state is the only status. Never `plan_create` over an in-flight task that
has no plan row: that is the legacy plan-file path, read and maintained by hand.
