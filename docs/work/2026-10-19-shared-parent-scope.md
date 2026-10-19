# Shared parent scope across repositories

The source collection has one shared `.ai-badger` directory. Repositories in that
collection retain their own project identities. The shared scope contains the union
of their stacks; the sync mode gives each repository its own filtered scaffold,
inheriting parent defaults and linking shareable files back to the parent.

Membership is explicit. The collection root is configurable and is independent of
the ai-badger framework checkout. Existing canonical identities must be reused
through the identity helper described in
[ADR 0036](../adr/0036-reuse-or-register-the-project-id-with-ai-raccoon.md).

The acceptance boundary includes parent stack aggregation, child inheritance and
filtering, per-repository identity, repeated sync and pruning, and protection of
parent files from ordinary child refreshes. Mutable state and rendered resources
remain private to each repository.

Source research identifies two integration hazards: `Scaffolder.run` writes into
the target scaffold, and skill refresh removes and copies skill directories. A
shared child must be identified before either path writes through a link. The
shared sync operation validates ownership before replacing its own recorded links.

Verification uses isolated temporary collection fixtures with multiple repositories,
the public collect/sync commands, and the ordinary refresh/scaffold entry points.
Safety checks compare parent and sibling contents before and after child operations.
