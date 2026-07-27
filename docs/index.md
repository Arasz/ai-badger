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
| [adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md](adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md) | The authoritative record of how Hermes discovers skills: per-project symlinks under `~/.hermes/skills/<project>/`, after `skills.external_dirs` shipped in 0.7.1 and was reverted |
| [adr/0004-mcp-tool-index.md](adr/0004-mcp-tool-index.md) | MCP Tool Index with tag + intent semantic matching for reduced prompt bloat and better tool selection |

## Reviews & remediation plans

| Document | What it covers |
|---|---|
| [reviews/2026-07-26-full-project-review.md](reviews/2026-07-26-full-project-review.md) | Eight-lens parallel code review of 0.18.1 with every Critical verified against the code; confirmed/downgraded/rejected verdicts, themes, and strengths worth preserving |
| [plans/2026-07-26-remediation-plan.md](plans/2026-07-26-remediation-plan.md) | Wave-structured remediation plan derived from that review — execution order, dependency graph, agent dispatch queue, and per-package TDD entry points. Waves 1–5 landed as 0.19.0–0.23.0 |
| [plans/2026-07-27-deferred-work-plan.md](plans/2026-07-27-deferred-work-plan.md) | Waves 6–10: the work that plan deferred on purpose — Scaffolder decomposition, one framework-root definition, a feature-type registry, the hardening pass, and scanning the outbound publish path |

## Incidents

| Document | What it covers |
|---|---|
| [incidents/2026-07-27-untagged-releases.md](incidents/2026-07-27-untagged-releases.md) | 32 versions released with no tag, and why the release guard could not report it — baseline restart, rejected batching policy, and the two signals added |

## Design docs & spikes

| Document | What it covers |
|---|---|
| [ai-badger-framework-design.md](ai-badger-framework-design.md) | **Historical (pre-0.7.0).** The original design document — decision log, risk list and Mermaid diagrams. Describes a root `skills/` tree and a `plugins.json` mechanism 0.7.0 replaced; read `framework-architecture.md` for the current shape |
| [proxy-files-spike.md](proxy-files-spike.md) | Documented feature plan: replacing full agent-file copies with thin delegating proxies (not yet built) |
| [known-gaps.md](known-gaps.md) | Honest list of what the MVP does not yet do, ordered by likelihood of impact |
| [audit-symlink-hermes-skills.md](audit-symlink-hermes-skills.md) | Audit of the Hermes skill-symlink mechanism against what ADR-0003 specifies |

## Implemented designs

Kept as decision records, not as plans — each one shipped.

| Document | What it covers |
|---|---|
| [design/mcp-stack-declarations.md](design/mcp-stack-declarations.md) | Stack-declared MCP servers (shipped 0.13.0), with [its implementation plan](design/mcp-stack-declarations-impl-plan.md) |
| [design/hermes-learned-skills-sync-impl-plan.md](design/hermes-learned-skills-sync-impl-plan.md) | Hermes learned-skill sync, stages 1–3 (shipped 0.18.0) |
| [research/hermes-learned-skills-sync.md](research/hermes-learned-skills-sync.md) | The research pass behind that design |
