---
description: 'Azure Cosmos DB data modeling and access conventions.'
applyTo: '**/*Cosmos*.cs,**/*Repository*.cs'
---

# Azure Cosmos DB

- Choose the partition key from the actual write/query shape, not convenience; justify it in the data-model doc or an ADR if it's not the tenant/owner key.
- Every entity carries its partition key as an explicit field; every query filters or partitions by it unless explicitly justified and documented.
- Use optimistic concurrency (ETag) on updates, and `TransactionalBatch` as the default pattern for multi-document writes within a single partition — never assume multi-document writes are atomic without it.
- Exactly one component writes to Cosmos; all other clients go through that component's API rather than holding their own `CosmosClient`.
- Watch RU consumption on new query shapes before they ship; a cross-partition query or a missing index is cheap to catch in review and expensive to fix in production.
