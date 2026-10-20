# ADR-0041: Explicit shared parent scopes

Date: 2026-10-19
Status: Accepted
Amended by: ADR-0042 (the parent-side path discovers the members; the explicit path below
still does not)

## Context

A collection of repositories needs a common instruction and skill catalog while each
repository keeps its own identity, state and authored settings. A parent scaffold alone
does not make agent discovery or script execution work from a nested child repository.

## Decision

`shared_scope.py collect` takes explicit relative repository paths. It scaffolds the parent
with their stack union and materializes each selected child using that same union.
`shared_scope.py sync` materializes one child with its original local stacks, and
`shared_scope.py prune` removes one enrolled member. All three use `Scaffolder`; there is
one renderer and one native agent delivery pipeline.

The private `.ai-badger/shared-scope.json` descriptor stores the parent source, mode,
original local stacks and authored overrides. The child `config.json` is an effective
snapshot. Objects merge recursively and lists replace inherited lists, so a later parent
edit propagates without converting generated settings into authored overrides. The
descriptor is a closed shape (`schemas/shared-scope.schema.json`): an unknown field is a
mistake, not an extension.

Only identical immutable files may link to the same relative path in the actual parent
`.ai-badger` store. Directories remain real. Identity, state, configuration, manifests,
project-owned files and contextual rendered output remain private. The manifest records
every owned link's exact raw target and original canonical parent source.

Pruning removes one enrolled member: its shared files become private copies, its
identity is untouched, the parent's union shrinks to the remaining members, and the pruned
repository rejoins the ordinary scaffold and refresh flow. A collection keeps at least one
member: the last one cannot be pruned, because an empty collection is not a state the
configuration can express.

Before rendering, sync validates every recorded link and every destination ancestor. It
detaches only exact owned links to private copies, then renders and re-links identical
immutable files. An owned link whose parent file is gone — the union shrank, or the parent
was edited — is dropped instead of left dangling, so a smaller membership never strands a
child. Ordinary scaffold and refresh refuse enrolled children and name the command that
restores them: `collect` for a child that carries the union, `sync` for one that carries its
own stacks. Sync writes only the selected child; it does not refresh its parent or siblings.

The ownership ledger records paths, not this machine's layout: a link's source is relative
to the parent's `.ai-badger`, and the collection's own path is relative to the child. The
child's manifest is a committed file, so an absolute path in it would ship one machine's
directory into every clone.

Enrollment decides every member's identity before it writes anything, so a refusal leaves
the collection exactly as it was. A child that arrives carrying another collection's
identity is refused rather than enrolled twice.

Existing project IDs stay byte-identical. A missing child ID goes through the existing
canonical lookup and registration flow: the bank's id for that name is reused verbatim, a
name the bank does not know is minted locally, and an uncertain outcome — the lookup is
unavailable, ambiguous, or malformed — refuses the enrollment before any project write. The
decision is made once, in one place, and the write path never re-decides it, so a lookup
that comes back ambiguous on the way in cannot turn into a minted id on the way out. The
shared scope does not write to the bank unless `--register` says so: a collection must not
silently register projects in the operator's memory bank. A shared collection never invents
an identity in doubt. Runtime lookup keeps the existing nearest-child identity rule.

## Alternatives considered

A parent-only MCP index leaves instruction and skill consumers unresolved. A directory
symlink makes mutable files shared and lets ordinary scaffold writes reach the parent.
Copying everything avoids link ownership but loses shared immutable resources. A second
renderer would duplicate stack selection and agent discovery rules. The selected design
keeps the existing renderer and adds a narrow ownership layer around it.
