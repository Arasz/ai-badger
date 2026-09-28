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
| [skills.md](skills.md) | Every shipped skill grouped by what it's for, what it actually changes on disk, when to reach for it, and which ones are hook-backed rather than invoked by name |
| [retrieval.md](retrieval.md) | How the MCP tool index is searched: BM25 over fused fields, why the gate is a coverage ratio rather than a score, the eval fixture set, and the telemetry that tells you whether any of it ran |
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

[`adr/`](adr/README.md) is the index: every decision, numbered in order, with its status and a
one-line summary, and each superseded entry pointing forward. The ones a newcomer meets first
are `0001` versioning and releases · `0015` delegation needs a mechanism, not more prose ·
`0018` one mechanism: a skill declares its own stack and its own scope (which superseded
`0005`) · `0028` with `0029`, the whole catalog ships by default and the sqlite pair's
exception · `0031` per-prompt memory context. Everything between and after them is in the
index, which is the only list of all of them.

## I want to know what changed

| Document | What it covers |
|---|---|
| [changelog/](changelog/README.md) | One file per version, `{version}-{slug}.md`. The README reconstructs the release timeline |
| [`../BREAKING_VERSIONS`](../BREAKING_VERSIONS) | Versions that *require* a re-scaffold, not merely recommend one. `den-refresh` reads this and backs up `.ai-badger/` before re-scaffolding |

## Every directory in this tree

The complete map. A directory missing from this table is a directory nobody will find.

| Directory | What it holds |
|---|---|
| [`tutorials/`](tutorials/README.md) | Learning-oriented, we choose the goal. Empty — this framework has no tutorial yet |
| [`how-to/`](how-to/README.md) | Task-oriented, the reader's goal. Filenames start with a verb |
| [`reference/`](reference/README.md) | Information looked up mid-task. Filenames are bare nouns |
| [`explanation/`](explanation/README.md) | Understanding-oriented — why it is like this |
| [`adr/`](adr/README.md) | Decisions. Immutable, never edited after acceptance |
| [`work/`](work/README.md) | Dated records — `YYYY-MM-DD-slug`. See the scope note below |
| [`research/`](research/README.md) | Evidence-graded studies grouped by subject, currently prompt engineering. Living references, not a record of a moment |
| [`assets/`](assets/README.md) | Images and diagrams, belonging to no quadrant |
| [`meta/`](meta/README.md) | Machine state about the documentation itself |
| [`changelog/`](changelog/README.md) | One file per version, `{version}-{slug}.md`. Generated index; frozen |
| [`brand/`](brand/README.md) | The logo, palette and usage rules. Predates `assets/`; pinned by the root README |
| [`screenshots/`](screenshots/README.md) | Screenshots used by the pages above. Predates `assets/`; pinned by `skills.md` |

The four quadrants are Diátaxis. The eight root `*.md` files listed earlier have not been
re-placed into them yet — several are pinned by `README.md` and `CONTRIBUTING.md`, which makes
that a job for the `documentation` gateway's `migrate-documentation` member, with its own PR.

## What `work/` is, and is not

PR #111 trimmed this tree to product documentation and removed seven directories grouped by
document *kind* — `plans/`, `research/`, `design/`, `reviews/`, `specs/`, `incidents/`,
`archive/`. That decision stands, and this is not a reversal of it: kind is not a subject, and
all seven were the same anti-pattern. The [`research/`](research/README.md) on the map above is
the other shape: one subject, prompt engineering, carrying living studies that keep absorbing
new evidence.

What #111 assumed is that a concluded record can live in git history, because what it concluded
has already moved into a document above or into an ADR. That holds for a finished plan. It does
not hold for a record whose conclusions are still being acted on — an open review gate is an
input to work in flight, not an artefact of work completed. With nowhere legal to put one, the
two review forms from 2026-08-01 went to `.tmp/`: gitignored, hidden, and unreachable by the
ripgrep every agent's search is built on.

So `work/` is deliberately narrow. A dated record belongs here while it is still load-bearing.
Once its conclusions have landed in a quadrant page or an ADR, it leaves — `work/` is a desk, not
an archive, and it is expected to stay close to empty.
