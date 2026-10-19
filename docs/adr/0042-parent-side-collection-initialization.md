# ADR-0042: Parent-side collection initialization

Date: 2026-10-19
Status: Accepted
Amends: ADR-0041 (the "the collection never discovers neighbouring repositories on its own"
rule)

## Context

ADR-0041 made a collection's membership explicit: `shared_scope.py collect` takes one
`--repo` path per member, and every member must already be a scaffolded repository with
its own `.ai-badger/config.json` and its own `project-id`. That is the right default for a
hand-picked set of repositories, but it does not serve the operator who owns a directory of
fifty projects and wants one ai-badger scope over all of them. Enrolling fifty members by
hand is fifty invocations, and each one needs the member to be scaffolded first.

The operator's request is one command run in the parent directory: find the repositories
next to it, work out what each one is made of, keep that as an index, initialize the parent
with the sum, and initialize every child with a reference to the parent.

## Decision

The shared scope grows a parent-side entry point. Discovery is one level deep, and it is
the only thing that discovery means here.

`shared_scope.py discover --target DIR` is read-only. It lists the direct subdirectories of
`DIR` that carry a `.git` entry — a directory or a file, so a linked worktree counts — and
prints one `dir:stacks` line per child plus the union of the stacks. A child's stacks are
its own `.ai-badger/config.json` stacks when it has them, and a fresh detection otherwise.
Nothing is written. A child that is itself a collection parent, and a child that is a
symlinked directory, are reported as skipped: neither can be enrolled without a decision
this command does not make.

`shared_scope.py init --target DIR` does the work. It discovers the same children, then
decides everything before it writes anything:

- each child's identity, through the existing canonical lookup: an existing `project-id` is
  kept byte for byte, a missing one reuses the bank's id for that name or mints a local
  one, and an answer the lookup cannot be trusted on refuses the run;
- each child's authored settings: its own `shared-scope.json` descriptor when it is already
  enrolled, its own `config.json` stacks and overrides when it is already scaffolded, and a
  fresh detection when it is new.

A child that arrives enrolled in another collection is refused before the first write. The
parent is then scaffolded with the union of the children's stacks — its own
`.ai-badger/config.json` is the base when it has one, a fresh detection otherwise — and every
child is materialized in `inherit` mode, so each child carries the union and links to the
parent. The parent keeps its own identity, and each child records the parent's identity as
its `parentId`, which is what tells one collection's member from another's.

`--dry-run` reports the members, the union and the identity decisions and writes nothing.
`--register` is the only way a minted id reaches the operator's bank.

The `dir:stacks` index is kept in the parent's own descriptor, as an optional `memberStacks`
map in the collection branch of `schemas/shared-scope.schema.json`. The descriptor stays a
closed shape: an unknown field is still refused, and the child's descriptor shape is
unchanged.

This reverses ADR-0041's "the collection never discovers neighbouring repositories on its
own". The reversal is bounded by four rules, and every one of them is a refusal the command
makes: discovery is one level deep and never recurses; a directory is a child only when it
carries a `.git` entry; every decision is made before the first write, so a refusal leaves
the directory exactly as it was; and every child that is not enrolled is named in the
report, so the operator sees what was skipped.

## Consequences

Positive: a directory of repositories becomes a collection with one command, and the
operator can see the shape of it — the members, their stacks, the union — before anything
is written. A child that was already scaffolded keeps its own settings and its own
identity, and becomes a member of the union rather than a separate scope.

Negative: the command is not selective. It enrolls every repository it finds next to the
target, so it is the wrong tool for a directory that holds repositories meant to stay
outside the scope; `collect` remains the explicit path. The parent is a scope of its own
and carries its own identity, which is one more identity to keep track of. The detection of
a fresh child's stacks is a guess until the operator reads the report.

Neutral: `collect`, `sync` and `prune` keep their current contracts, including the rule
that a member of `collect` must already be a scaffolded repository. The `dir:stacks` index
is derivable from each child's own descriptor, so it is a convenience for the operator and
a record of the last run, not a second source of truth.

## Alternatives considered

Keeping membership explicit and writing a wrapper that expands the list was rejected: the
expansion is the whole feature, and a wrapper would keep the membership implicit while
adding a second interface to it.

A recursive discovery was rejected: a repository nested inside another repository is
usually a fixture, a vendored checkout or a worktree of the parent, and enrolling it would
make the union depend on a filesystem accident.

A separate `parent_scope.py` script was rejected: the parent and the children are one
scope, and one scope has one owner — the existing descriptor, the existing renderer and the
existing refusals.

A membership file naming the children was rejected as the only mechanism: it duplicates
what discovery already knows, and it goes stale the moment a repository is added. It
remains a reasonable way to *restrict* a collection, which `collect` already is.
