# Research: how a project's decision-record and spec format is detected, and what to write

**Date:** 2026-10-23
**Question:** Which decision-record and spec formats (ADR variants, OpenSpec, other spec frameworks) can a skill detect from a repository and the machine, and what should it write when it finds one, several, or none?

## Findings

### F1 — `openspec init` writes `openspec/config.yaml`, `openspec/specs/` and `openspec/changes/archive/` [MEASURED]

These three paths are the on-disk sign that a project uses OpenSpec. `config.yaml` holds
`schema: spec-driven` plus optional project context and per-artifact rules. Per-machine state
lives in `~/.config/openspec/`, outside the repository.

**Evidence:** `OPENSPEC_TELEMETRY=0 openspec init --tools none --no-animation --no-copilot-cloud .` in an empty `git init` scratch repo, openspec 1.14.3 (Homebrew, macOS), 2026-10-23. `find . -type f` listed `openspec/specs/.gitkeep`, `openspec/changes/archive/.gitkeep`, `openspec/config.yaml`.

### F2 — An OpenSpec change fails validation without a requirement delta, unless it declares `skip_specs: true` [MEASURED]

`openspec new change add-x` creates only `openspec/changes/add-x/.openspec.yaml`. `openspec validate add-x`
then refuses: a change needs `specs/<capability>/spec.md` with `## ADDED|MODIFIED|REMOVED|RENAMED Requirements`,
and each requirement needs at least one `#### Scenario:`. A change with no behaviour delta (refactor, tooling, docs)
sets `skip_specs: true` in `.openspec.yaml` instead. So the CLI has a validation gate a skill can run.

**Evidence:** Same scratch repo and version as F1. `openspec validate add-x` printed `✗ [ERROR] file: Change must have at least one delta. No deltas found. … set "skip_specs: true" in the change's .openspec.yaml instead.`

### F3 — OpenSpec serves each artifact's template from the CLI: proposal, specs, design, tasks [MEASURED]

`openspec instructions proposal --change add-x` prints the target path (`openspec/changes/add-x/proposal.md`) and the
required sections: Why, What Changes, Capabilities (new and modified), and Impact. It also tells the writer to run
`openspec list --specs` first and reuse existing capability paths. The decision rationale goes in `design.md`.
A skill should therefore ask the CLI for the template instead of keeping its own copy, which would drift.

**Evidence:** Same scratch repo and version as F1. Workflow names `/opsx:propose` → `proposal.md, specs/, design.md, tasks.md`, read at https://github.com/Fission-AI/OpenSpec (README, "See it in action").

### F4 — MADR 4.0.0 defaults to `docs/decisions/NNNN-title-with-dashes.md` and has a minimal and a full template [READ]

The required sections are Context and Problem Statement, Considered Options, and Decision Outcome. The optional ones
are Decision Drivers, Consequences, Confirmation, Pros and Cons of the Options, and More Information. Frontmatter
carries `status`, `date` and `decision-makers`. MADR says there is no tooling for 3.0.0+ creation, so the file is
written by hand.

**Evidence:** https://adr.github.io/madr/ — "Applying MADR to your project", "Full template", News 2024-09-17 (MADR 4.0.0, "bare" and "minimal" templates).

### F5 — adr-tools finds its directory by walking up for a `.adr-dir` file, then `doc/adr` [READ]

`_adr_dir` walks from the current directory up to `/`. At each level it returns the contents of `.adr-dir` if that
file exists, else `doc/adr` if that directory exists. If neither is found anywhere, it falls back to `doc/adr`. The CLI is `adr`
(`adr new <title>`, `adr new -s N <title>` to supersede).

**Evidence:** https://raw.githubusercontent.com/npryce/adr-tools/master/src/_adr_dir (whole file); https://github.com/npryce/adr-tools README ("The default directory is `doc/adr`").

### F6 — log4brains declares its ADR folder in `.log4brains.yml` (`project.adrFolder`) [READ]

Monorepos list package folders as well, such as `packages/<name>/docs/adr`. The marker file is the reliable signal.
The folder name is configured, so it cannot be assumed.

**Evidence:** https://github.com/thomvaill/log4brains README — "How to configure `.log4brains.yml`?", `adrFolder: ./docs/adr`.

### F7 — Spec Kit keeps its own state in `.specify/` and features in `specs/NNN-<slug>/` (`spec.md`, `plan.md`, `tasks.md`) [READ]

The CLI is `specify` (`uv tool install specify-cli`, `specify init`). The agent commands are `/speckit-specify`,
`/speckit-plan` and `/speckit-tasks`. Its bug and assessment extensions write under `.specify/bugs/` and `.specify/assessments/`.

**Evidence:** https://github.com/github/spec-kit README ("Get started", "Bug fixing") and `spec-driven.md` ("The `/speckit.specify` Command": `specs/003-chat-system/spec.md`, `plan.md`, `tasks.md`).

### F8 — Kiro writes specs to `.kiro/specs/<slug>/requirements.md`, `design.md`, `tasks.md` [READ]

Requirements are in EARS form. These sources are secondary: Kiro's own specs page rendered with no text through the fetcher.

**Evidence:** https://github.com/aws-samples/sample-kiro-cli-prompts-for-product-teams/blob/main/.kiro/steering/prd-guide.md ("Create directory: .kiro/specs/[product-slug]/"); https://kiro.dev/docs/specs/best-practices/ search snippet ("requirements.md, design.md, and tasks.md").

### F9 — This repository has 46 MADR-shaped ADRs in `docs/adr/` with an index a test enforces, and no spec framework [MEASURED]

`docs/adr/` holds `0001`–`0046` and a `README.md` index. The `Amended` column is checked by `tests/test_adr_index.py`,
so a new ADR here must add an index row. There is no `openspec/`, `.specify/`, `.kiro/`, `.adr-dir` or `.log4brains.yml`.
`openspec` is on PATH (1.14.3). `specify`, `adr` and `log4brains` are not.

**Evidence:** `ls docs/adr | wc -l` → 47 (46 ADRs + README); `ls openspec .specify .kiro doc/adr docs/decisions` → all missing; `command -v openspec specify adr log4brains` → only `/opt/homebrew/bin/openspec`; macOS, main checkout at `a9fa995a`.

### F10 — ADRs and spec frameworks record different halves of a decision, so where both exist the record is a linked pair [INFERRED]

Reasoned from F3 and F4. OpenSpec and Spec Kit artifacts state *what* the system must do: requirements, scenarios,
tasks. MADR states *why* this option won over the alternatives. OpenSpec's `design.md` overlaps an ADR, and copying
the rationale into both makes two sources of truth. In a combination project, the spec change carries the
requirements and links to the ADR. The ADR carries the options and the choice and links back to the change.

### F11 — A CLI on PATH is not evidence that the project uses it [INFERRED]

Reasoned from F1 and F9. `openspec` is installed machine-wide here, but this repo has never run `openspec init`.
A detector that counted the binary as adoption would start writing OpenSpec changes into a repo whose
decisions live in `docs/adr/`. Tools only decide *how* to write into a format the repo already shows (CLI vs. by hand).
They never decide *which* format to use.

### F12 — The agent-file budget has room for one more invariant line [MEASURED]

`config.json` caps generated agent docs at 282 lines / 19,200 chars (`agentDocs`). `CLAUDE.md` is at 164 lines and
15,956 chars, so one invariant bullet of about 200 chars fits.

**Evidence:** `wc -lc CLAUDE.md` in the worktree off `a9fa995a`; `.ai-badger/config.json` key `agentDocs`.

### F13 — Whether agents act on a "record decisions" invariant with no gate behind it [UNVERIFIED]

I did not measure this. ADR-0015 records a delegation policy that two prose statements did not enforce (205 dispatches, 101 named no
model). That suggests prose alone is weak, but it is about a different rule. Wiring the step into the `task`
skill's loop is the only mechanism this change adds.

## Still open

- Kiro's layout comes from secondary sources only (F8). Kiro's own docs page did not render through the fetcher.
- Nothing mechanically checks that a behaviour-changing PR carries a decision record (F13). A gate would need a
  definition of "meaningful" that a script can evaluate, and none exists yet.
- Spec Kit 1.0 (October 2026) may have renamed feature files. F7 reads `spec-driven.md` on `main`, not a tagged release.
- OpenSpec telemetry is on by default (README "Telemetry"). The skill sets `OPENSPEC_TELEMETRY=0` on every call it makes.
- How OpenSpec Stores (beta) change detection: a repo can point at a store outside its own tree. This was not tested.

## Sources

- https://openspec.dev, https://openspec.dev/docs/installation, https://github.com/Fission-AI/OpenSpec
- https://adr.github.io/madr/
- https://github.com/npryce/adr-tools, `src/_adr_dir`
- https://github.com/thomvaill/log4brains
- https://github.com/github/spec-kit, `spec-driven.md`
- https://kiro.dev/docs/specs/, https://github.com/aws-samples/sample-kiro-cli-prompts-for-product-teams
- Local: openspec 1.14.3 CLI runs in a scratch repo; this repo's `docs/adr/`, `tests/test_adr_index.py`, `.ai-badger/config.json`
