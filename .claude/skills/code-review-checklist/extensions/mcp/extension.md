# code-review-checklist extension: mcp

## @architecture: mcp: MCP Tool Wiring
- [ ] **MCP tools register with `.WithTools<T>()`** — new MCP tool classes must
  be wired in the server host configuration.
- [ ] **MCP tools are thin HTTP clients** — zero business logic. Each method maps
  1:1 to a REST endpoint. No domain type references in the MCP project.
