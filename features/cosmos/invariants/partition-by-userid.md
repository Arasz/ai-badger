# Partition by the tenant/owner key

Every entity carries the tenant/owner key (e.g. `userId` in a single-tenant-per-partition design) as an explicit field, and it is also the partition key. Every query filters or partitions by it unless there's an explicit, documented reason for a cross-partition query.
