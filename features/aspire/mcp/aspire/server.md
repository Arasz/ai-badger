<!-- aspire MCP tools -->
## MCP Tools: aspire

This project runs under an Aspire AppHost. **When the question is about the running system —
what is up, why a resource is unhealthy, what a request did — ask the AppHost through these
tools instead of reading code and inferring.** `list_resources` first: it names every resource
and its state, and the other calls take those names.

Then `list_console_logs` for a resource that died on startup, `list_structured_logs` when the
console is too noisy, `list_traces` + `list_trace_structured_logs` to follow one request across
services, and `select_apphost` when several are running. `execute_resource_command` starts,
stops and restarts — the only write here. `search_docs`/`get_doc` and `list_integrations`/
`get_integration_docs` beat recalling a builder API; `doctor` when a failure is environmental.
All of it needs a running AppHost (`aspire start`).
