# ai-badger documentation

## Getting started

| Document | What it covers |
|---|---|
| [README.md](../README.md) | Project overview, install, quickstart, architecture overview |

## Core concepts

| Document | What it covers |
|---|---|
| [framework-architecture.md](framework-architecture.md) | The stack×feature catalog model, `config.json`/`manifest.json` contracts, script vs agent responsibility split, plugins, `task` base+extensions, target repo structure, data flow diagrams |
| [authoring-a-feature.md](authoring-a-feature.md) | How to add a new stack, persona, invariant, instruction, plugin entry, or skill to the catalog |
| [scripts.md](scripts.md) | How to run framework scripts and the test suite |
| [dictionary.md](dictionary.md) | How ai-badger concepts (skills, hooks, instructions, personas, scaffolding) map to each supported agent's native terminology |

## Agent compatibility

| Document | What it covers |
|---|---|
| [hermes-claude-compatibility.md](hermes-claude-compatibility.md) | How ai-badger's Claude Code features map to Hermes Agent equivalents — hook systems, session tracking, statusline, tool comparison, delegation, gap analysis |

## Specifications

| Document | What it covers |
|---|---|
| [specs/001-plugin-hooks-adjustments-refactor.md](specs/001-plugin-hooks-adjustments-refactor.md) | Major refactor spec: plugin→skills merge, hooks as first-class feature, adjustments concept, per-agent install instructions |

## Changelog

| Document | What it covers |
|---|---|
| [changelog/](changelog/) | Per-version change history |

## Design decisions (ADRs)

| Document | What it covers |
|---|---|
| [adr/0001-versioning-and-release-model.md](adr/0001-versioning-and-release-model.md) | Versioning, immutable release tags, semver for a catalog, provenance in `manifest.json`, two-tier drift detection |
| [adr/0002-den-refresh-skill.md](adr/0002-den-refresh-skill.md) | Why `den-refresh` exists as a separate skill from `welcome-ai-badger` |
| [adr/ADR-0002-mcp-tool-index.md](adr/ADR-0002-mcp-tool-index.md) | MCP Tool Index with tag + intent semantic matching for reduced prompt bloat and better tool selection |

## Design docs & spikes

| Document | What it covers |
|---|---|
| [ai-badger-framework-design.md](ai-badger-framework-design.md) | The original design document this repo implements — full decision log, risk list, and Mermaid diagrams |
| [proxy-files-spike.md](proxy-files-spike.md) | Documented feature plan: replacing full agent-file copies with thin delegating proxies (not yet built) |
| [known-gaps.md](known-gaps.md) | Honest list of what the MVP does not yet do, ordered by likelihood of impact |
