# ADR-0041: Explicit shared parent scopes

Date: 2026-10-19
Status: Accepted

## Context

A collection of repositories needs a common instruction and skill catalog while each
repository keeps its own identity, state and authored settings. A parent scaffold alone
does not make agent discovery or script execution work from a nested child repository.

## Decision

`shared_scope.py collect` takes explicit relative repository paths. It scaffolds the parent
with their stack union and materializes each selected child using that same union.
`shared_scope.py sync` materializes one child with its original local stacks. Both commands
use `Scaffolder`; there is one renderer and one native agent delivery pipeline.

The private `.ai-badger/shared-scope.json` descriptor stores the parent source, mode,
original local stacks and authored overrides. The child `config.json` is an effective
snapshot. Objects merge recursively and lists replace inherited lists, so a later parent
edit propagates without converting generated settings into authored overrides.

Only identical immutable files may link to the same relative path in the actual parent
`.ai-badger` store. Directories remain real. Identity, state, configuration, manifests,
project-owned files and contextual rendered output remain private. The manifest records
every owned link's exact raw target and original canonical parent source.

Before rendering, sync validates every recorded link and every destination ancestor. It
detaches only exact owned links to private copies, then renders and re-links identical
immutable files. Ordinary scaffold and refresh refuse enrolled children and name the sync
command. Sync writes only the selected child; it does not refresh its parent or siblings.

Existing project IDs stay byte-identical. A missing child ID uses the existing canonical
lookup and registration flow, with uncertain lookup outcomes refusing enrollment before
project writes. Runtime lookup keeps the existing nearest-child identity rule.

## Alternatives considered

A parent-only MCP index leaves instruction and skill consumers unresolved. A directory
symlink makes mutable files shared and lets ordinary scaffold writes reach the parent.
Copying everything avoids link ownership but loses shared immutable resources. A second
renderer would duplicate stack selection and agent discovery rules. The selected design
keeps the existing renderer and adds a narrow ownership layer around it.
