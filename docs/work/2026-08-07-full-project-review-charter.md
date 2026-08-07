# Full-project review charter — 2026-08-07

Written **before** the review ran, per the "review before you plan" rule. Records what had to be
checked and how the answer would be judged, so the plan that follows is grounded in findings
rather than in guesses.

Task: `full-project-review`. Worktree `.ai-badger/worktrees/full-project-review`, branch
`task/full-project-review`, based on `main` at `6a3d9e5`.

## The request

1. Full-project review using a mixture-of-experts panel, **focused on this week's changes**.
2. Focus on the .NET architecture and its refactor opportunities.
3. Cover the whole codebase, docs, tests and scripts.
4. Save the important project facts to long-term memory.
5. Integrate the panel's results into **one** plan.
6. Decompose that plan into work items, and each work item into work chunks where that shape fits.
7. Plan for parallel execution; the orchestrating session delegates and integrates.
8. Dispatch depth is capped at two levels — a panel expert may spawn at most 3 sub-agents, those
   run at `sonnet` at most, and nothing goes deeper.

## Premise corrected before dispatch

The request named ".NET architecture used here". Measured first, not assumed:

| Extension | Tracked files |
|---|---|
| `.md` | 681 |
| `.py` | 419 |
| `.json` | 133 |
| `.mjs` | 10 |
| `.cs` | **2** |

Both `.cs` files are template fixtures under `features/dotnet/skills/`. The build, test and lint
commands are all Python. There is no .NET application code in this repository.

The user resolved the ambiguity directly: **`features/dotnet/` is guidance ai-badger ships to
consumer projects that use .NET.** So the .NET lens reviews *prescriptive advice given to other
people's codebases* — is it correct, current, coherent, and free of leakage from the project it
was harvested from — and a second lens applies the same architectural rigor to this repo's own
Python engine and tooling.

## The week under review

`git log --since="2026-08-01"`: **93 commits, 646 files, +51,883 / −4,128**, spanning releases
0.62.0 → 0.87.1.

Directories by number of file-touches this week:

| Directory | Touches |
|---|---|
| `features/common` | 224 |
| `.ai-badger/skills` | 131 |
| `features/dotnet` | 114 |
| `docs/changelog` | 99 |
| `index.json` | 48 |
| `VERSION` | 47 |
| the six agent-instruction files | 43 each |
| `docs/work` | 21 |

## The panel

Seven experts, dispatched in parallel, each read-only and each required to mark every finding
`CONFIRMED` (verified by a command it ran or a file it read) or `PLAUSIBLE` (reasoned but
unverified).

| # | Lens | Persona | Model |
|---|---|---|---|
| E1 | Python engine/tooling architecture, refactor opportunities | `architect` | opus |
| E2 | `features/dotnet` as consumer-facing .NET guidance | `architect` | opus |
| E3 | Correctness of this week's 93-commit diff | `code-reviewer` | opus |
| E4 | Test-suite honesty and coverage of the new code | `test-engineer` | opus |
| E5 | Docs tree and agent-instruction-file drift | `architect` | sonnet |
| E6 | Hooks, gates, CI and release machinery — does it run? | `code-reviewer` | opus |
| E7 | Catalog and scaffold integrity | `architect` | sonnet |

## Standing evidence rules given to every expert

- **A cited log is not evidence.** A gate's named log file can be a previous run's artifact.
  Re-run anything load-bearing and report the numbers actually observed.
- **Commit messages are claims.** Several this week assert gate results ("3301 passed",
  "freshness PASS 1342 paths"). They are hypotheses until re-run.
- **Search project memory first.** `ai-raccoon` `memory_search` with 2–3 query formulations,
  `scope=all`, before any external search or broad file scan.
- **Prefer the code graph.** `code-review-graph` MCP tools return callers, dependents and test
  coverage that file scanning cannot, at lower token cost.
- **Never present a reasoned guess as a measurement.**

## What each expert must return

- Findings ranked by value: title, severity, `file:line`, the defect, a concrete failure
  scenario, the evidence, the proposed fix, and the CONFIRMED/PLAUSIBLE mark.
- A backlog of discrete, independently-shippable work items, each carrying acceptance criteria
  and the gate that proves them — and a note of which items share files, since those serialise
  while the rest parallelise.
- Durable project facts worth long-term memory: non-obvious truths a future session would
  otherwise waste time rediscovering.

## Pass condition for the review itself

The review is done when every point in the request above has been answered with evidence, the
seven reports have been integrated into a single plan with no contradictions left unresolved,
and that plan is decomposed into work items and chunks with an explicit parallel-execution
schedule.

## Known state at dispatch

- `main` clean; no open PRs, no open issues.
- Scaffold drift: `.ai-badger/` was scaffolded by 0.87.0 while the running plugin is 0.87.1.
- Six tracker entries sit `IN_PROGRESS` from 1–5 August (`ai-badger-issues-drain-session`,
  `pr-254-takeover`, `pr-257-takeover`, `f2-third-party-fallback`,
  `enrich-last-article-about-skills`, `issue-286`). None owns a worktree. They are tracker
  residue rather than live work, and clearing them is itself a candidate work item.
- `.ai-badger/state.json` `next` points at the design-review follow-ups from
  `docs/work/2026-08-06-memory-skill-design-review.md`.
