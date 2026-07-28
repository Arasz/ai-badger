# ai-badger documentation

Everything written down about this project, grouped by what you came here to do. Start with
[`../README.md`](../README.md) if you have not met the project yet.

Two conventions worth knowing before you read anything:

- **Dates are load-bearing.** Anything under `plans/`, `reviews/`, `incidents/`, `research/` or
  `archive/` is a record of a moment, and most carry a status header saying which version they
  were true of. Where a document has been re-verified against the code, the header says so and
  gives the date.
- **`docs/adr/` is append-only.** An accepted decision is never edited; it is superseded by a new
  one.

---

## I want to use ai-badger

| Document | What it covers |
|---|---|
| [getting-started.md](getting-started.md) | **Start here if you just found the repo.** What ai-badger is and who it is not for, plugin vs. clone, the first run end to end with real command output, what to review before committing, and the failures that actually bite |
| [`../README.md`](../README.md) | What the project is, install, quickstart, the `features/{stack\|common}/{feature}` model, supported agents and stacks |
| [framework-architecture.md](framework-architecture.md) | **The reference.** The stack × feature catalog model, the `config.json` / `manifest.json` contracts, the script-vs-agent responsibility split, plugins, `task` base + extensions, target repo structure, data-flow diagrams |
| [dictionary.md](dictionary.md) | How ai-badger's vocabulary (skills, hooks, instructions, personas, scaffolding) maps onto each supported agent's native terminology |
| [scripts.md](scripts.md) | Running the framework scripts and the test suite |
| [hermes-claude-compatibility.md](hermes-claude-compatibility.md) | Claude Code features mapped to their Hermes Agent equivalents — hook systems, session tracking, statusline, delegation, gaps. Spot-checked at 0.27.0; some sections describe shipped work in proposal voice, and say so |

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

**Decisions** — [`adr/`](adr/README.md) is the index; each entry is one decision, never edited
after acceptance. `0001` versioning and releases · `0002` `den-refresh` · `0003` Hermes skill
discovery · `0004` MCP tool index · `0005` one declaration of which skills ship · `0006` one
skill-extension mechanism · `0007` ai-badger ships as files, not a Python distribution ·
`0008` plugin skills live at the plugin skill path · `0009` one framework root, resolved rather
than searched · `0010` stack-local skill discovery · `0011` `engine/`, `tooling/` and `gates/`.

**Design records** — descriptions of work that shipped, kept because they explain why the code
looks the way it does. Not plans.

| Document | What it covers |
|---|---|
| [specs/001-plugin-hooks-adjustments-refactor.md](specs/001-plugin-hooks-adjustments-refactor.md) | The 0.7.0 refactor: plugin → skills merge, hooks as a first-class feature, the adjustments concept, per-agent install instructions. All nine phases shipped, with two deliberate deviations named in the header |
| [design/mcp-stack-declarations.md](design/mcp-stack-declarations.md) | Stack-declared MCP servers (0.13.0), with [its implementation plan](design/mcp-stack-declarations-impl-plan.md). Machinery complete; no stack declares a server yet and `targetAgents` is inert |
| [design/hermes-learned-skills-sync-impl-plan.md](design/hermes-learned-skills-sync-impl-plan.md) | Hermes learned-skill sync, stages 1–6 (0.18.0). The shipped code is now ahead of this plan |
| [design/debug-mode-and-call-behaviorist.md](design/debug-mode-and-call-behaviorist.md) | The debug log every ai-badger hook writes and the `call-behaviorist` skill that reads it (0.30.0) |
| [research/hermes-learned-skills-sync.md](research/hermes-learned-skills-sync.md) | The research pass behind that design |
| [research/2026-07-27-docs-structure-and-contribution.md](research/2026-07-27-docs-structure-and-contribution.md) | Sourced research on docs structure, what an OSS project must document, and contribution enforcement — the input to this tree's current shape |

**Audits and post-mortems**

| Document | What it covers |
|---|---|
| [reviews/2026-07-26-full-project-review.md](reviews/2026-07-26-full-project-review.md) | Eight-lens parallel review of 0.18.1, every Critical verified against the code, with confirmed / downgraded / rejected verdicts. Together with the deferred-work plan this is the **current gap surface** |
| [incidents/2026-07-27-untagged-releases.md](incidents/2026-07-27-untagged-releases.md) | 32 versions released with no tag, why the release guard could not report it, and the two signals added |
| [audit-symlink-hermes-skills.md](audit-symlink-hermes-skills.md) | Whether `symlink_hermes_skills()` is still needed, audited against ADR-0003. **Closed** — every finding resolved |

## I want to know what changed

| Document | What it covers |
|---|---|
| [changelog/](changelog/README.md) | One file per version, `{version}-{slug}.md`. The README reconstructs the release timeline |
| [`../BREAKING_VERSIONS`](../BREAKING_VERSIONS) | Versions that *require* a re-scaffold, not merely recommend one. `den-refresh` reads this and backs up `.ai-badger/` before re-scaffolding |

## Work in flight

| Document | Status |
|---|---|
| [plans/2026-07-27-deferred-work-plan.md](plans/2026-07-27-deferred-work-plan.md) | **Active.** Waves 6–19. Eight resolved (9, 10, 12, 13, 14, 15, 18, 19) and 11 decided by ADR-0007; Waves 6 and 16 shipped as 0.37.0; Waves 7, 8 and 17 remain |
| [plans/2026-07-28-wave-6-scaffold-collaborators.md](plans/2026-07-28-wave-6-scaffold-collaborators.md) | **Complete.** Shipped as 0.37.0 — `Scaffolder`'s six mixins became composed collaborators |
| [plans/2026-07-28-wave-16-scripts-directory.md](plans/2026-07-28-wave-16-scripts-directory.md) | **Complete.** Phase 1 shipped as 0.36.2 (`gates/`), phase 2 as 0.37.0 (`engine/` + `tooling/`, ADR-0011) |
| [plans/2026-07-27-improvement-plan.md](plans/2026-07-27-improvement-plan.md) | **The dispatch list.** Everything open, grouped for independent agents by dependency; Wave 7 is blocked on a reproduced security regression |
| [plans/2026-07-27-analyze-measures-the-wrong-things.md](plans/2026-07-27-analyze-measures-the-wrong-things.md) | **Next up.** Three reproduced defects in `call-behaviorist analyze`, ordered, with the red tests already parked on a branch |
| [plans/2026-07-28-session-checkpoint-4.md](plans/2026-07-28-session-checkpoint-4.md) | **Current.** Continues checkpoint 3: the backfilled release tags, and the releases that followed |
| [plans/2026-07-27-session-checkpoint-3.md](plans/2026-07-27-session-checkpoint-3.md) | Superseded by checkpoint 4. 20 commits unreleased; Wave 7 under independent review; #104 and the `analyze` defects in flight |
| [plans/2026-07-27-session-checkpoint-2.md](plans/2026-07-27-session-checkpoint-2.md) | Superseded. What 0.32.0 shipped, the decisions behind it, and what ADR-0007 means for Waves 6, 7, 16 and 17 |
| [plans/2026-07-27-session-checkpoint.md](plans/2026-07-27-session-checkpoint.md) | Resume notes for the documentation work — step 1 (research) and step 2 (this refactor) done, step 3 (a docs-sync gate) sized as a wave in the plan above |
| [plans/2026-07-26-remediation-plan.md](plans/2026-07-26-remediation-plan.md) | **Complete.** All 28 work packages shipped as 0.19.0–0.23.0; kept as the record of what was fixed |

## Historical

Kept for the reasoning, not as a description of the present.

| Document | Written against |
|---|---|
| [archive/](archive/README.md) | Dated point-in-time records that a better-maintained document now supersedes — the 0.10.1 gap list, the 0.14.1 graph snapshot, a 0.9.0 editorial note |
| [ai-badger-framework-design.md](ai-badger-framework-design.md) | **Pre-0.7.0.** The original design document — decision log, risk list, Mermaid diagrams. Describes a root `skills/` tree and a `plugins.json` mechanism that 0.7.0 replaced; read `framework-architecture.md` for the current shape |
| [proxy-files-spike.md](proxy-files-spike.md) | **0.1.0.** Replacing full agent-file copies with thin delegating proxies. Still unbuilt — and recorded as *Dropped*, not deferred: symlinks break on Windows and Copilot does not follow references |
