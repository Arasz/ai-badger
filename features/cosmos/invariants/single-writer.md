# Single writer to Cosmos

Exactly one component (typically the API layer) writes to Cosmos DB; every other client (frontend, MCP server, background job) reaches the datastore only through that writer's API. This avoids the dual-writer races and non-atomic multi-document saves that are a recurring real-world Cosmos bug class.
