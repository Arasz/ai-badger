# code-review-checklist extension: cosmos

## @backend-runtime: cosmos: Cosmos DB
- [ ] **Every entity carries the owner/tenant key as partition key** — query
  methods filter by this key. No cross-partition queries without documented reason.
- [ ] **New containers registered in provisioning** — if a new entity type is
  added to Cosmos, the infrastructure-as-code must register its container.
- [ ] **Single writer invariant** — only the API layer writes to Cosmos. Every
  other client (frontend, MCP server, background job) reaches the datastore
  only through the API's surface.
- [ ] **ISecretCipher used for token storage** — not plaintext in the database.
