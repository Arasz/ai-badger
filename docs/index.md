# ai-badger documentation

Everything written down about this project, grouped by what you came here to do. Start with
[`../README.md`](../README.md) if you have not met the project yet.

`docs/adr/` is append-only: an accepted decision is never edited, only superseded by a new one.

---

## I want to use ai-badger

| Document | What it covers |
|---|---|
| [getting-started.md](getting-started.md) | **Start here if you just found the repo.** What ai-badger is and who it is not for, plugin vs. clone, the first run end to end with real command output, what to review before committing, and the failures that actually bite |
| [`../README.md`](../README.md) | What the project is, install, quickstart, the `features/{stack\|common}/{feature}` model, supported agents and stacks |
| [framework-architecture.md](framework-architecture.md) | **The reference.** The stack × feature catalog model, the `config.json` / `manifest.json` contracts, the script-vs-agent responsibility split, plugins, `task` base + extensions, target repo structure, data-flow diagrams |
| [dictionary.md](dictionary.md) | How ai-badger's vocabulary (skills, hooks, instructions, personas, scaffolding) maps onto each supported agent's native terminology |
| [scripts.md](scripts.md) | Running the framework scripts and the test suite |
| [hermes-claude-compatibility.md](hermes-claude-compatibility.md) | Claude Code features mapped to their Hermes Agent equivalents — hook systems, session tracking, statusline, delegation, gaps |

## I want to contribute

| Document | What it covers |
|---|---|
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | **Start here.** Setup, the failing-test-first workflow, every gate matched to the CI step that runs it, when a change is a release and when it is not |
| [`../CLAUDE.md`](../CLAUDE.md) | The non-negotiable invariants. These override anything else in this tree |
| [authoring-a-feature.md](authoring-a-feature.md) | How to add a stack, persona, invariant, instruction, plugin entry, or skill to the catalog |
| [`../RELEASING.md`](../RELEASING.md) | Semver for a catalog, cutting a release, the mandatory content verification, why tags are never batched |
| [`../SECURITY.md`](../SECURITY.md) | How to report a vulnerability, the real threat model, and what hardening already shipped |
| [`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | Contributor Covenant 2.1 |

## I want to understand why something is the way it is

[`adr/`](adr/README.md) is the index; each entry is one decision, never edited after acceptance.
`0001` versioning and releases · `0002` `den-refresh` · `0003` Hermes skill discovery ·
`0004` MCP tool index · `0005` one declaration of which skills ship · `0006` one
skill-extension mechanism · `0007` ai-badger ships as files, not a Python distribution ·
`0008` plugin skills live at the plugin skill path · `0009` one framework root, resolved rather
than searched · `0010` stack-local skill discovery · `0011` `engine/`, `tooling/` and `gates/`.

## I want to know what changed

| Document | What it covers |
|---|---|
| [changelog/](changelog/README.md) | One file per version, `{version}-{slug}.md`. The README reconstructs the release timeline |
| [`../BREAKING_VERSIONS`](../BREAKING_VERSIONS) | Versions that *require* a re-scaffold, not merely recommend one. `den-refresh` reads this and backs up `.ai-badger/` before re-scaffolding |

## What is not here

This tree documents the product, not the work that produced it. Plans, session checkpoints,
reviews, audits, incident post-mortems, research passes and superseded design documents are not
tracked: what they concluded lives in the documents above or in an ADR, and the documents
themselves stay in git history. `git log --diff-filter=D --name-only -- docs/` finds them.
