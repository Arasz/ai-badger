# code-review-checklist extension: azure

## @cross-cutting: azure: Security
- [ ] **Managed identity preferred over connection strings** for Azure services.
  Reserve keys for the rare case where no identity-based path exists.

## @orchestration: azure: Orchestration
- [ ] **Durable orchestrations return `202 Accepted` + `operationId`** — not
  synchronous `200`. Every other orchestration in the codebase follows this pattern.
