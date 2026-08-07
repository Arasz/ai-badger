# Full-project review — findings checkpoint

Live document. Each panel expert's report is folded in as it lands, rather than batched at the
end, so a dead session can be resumed from here. Charter:
`2026-08-07-full-project-review-charter.md`.

Base: `main` at `6a3d9e5`, worktree `.ai-badger/worktrees/full-project-review`.

## Panel status

| # | Lens | Persona / model | State |
|---|---|---|---|
| E1 | Python engine/tooling architecture | architect / opus | dispatched |
| E2 | `features/dotnet` consumer guidance | architect / opus | dispatched |
| E3 | This week's 93-commit diff | code-reviewer / opus | dispatched |
| E4 | Test-suite honesty and coverage | test-engineer / opus | dispatched |
| E5 | Docs and instruction-file drift | architect / sonnet | dispatched |
| E6 | Hooks, gates, CI, release machinery | code-reviewer / opus | dispatched |
| E7 | Catalog and scaffold integrity | architect / sonnet | dispatched |

## Findings established by the orchestrator directly

### O-1 — The project's own memory bank is empty, and watching was never enabled (CONFIRMED, high)

`memory_stats` for `projectId: ai-badger` returned `entries=0, pending=0`. `memory_watch_status`
returned an empty watch list. `memory_watch_add` on `/Users/arasz/RiderProjects/ai-badger/docs`
failed with `watching-disabled: Watching is disabled for project 'ai-badger'` — the one-time CLI
setup (`ai-raccoon watch scope add`, `ai-raccoon watch enable`) was never run here. Sibling
projects in the same bank (`ai-raccoon`, `hermes-default`, `jsaa`) do hold contexts, so the
server works.

The subsystem around it is fully shipped: `0.78.0` (#302) ai-raccoon as the common memory store,
`0.79.0` (#304) the memory-grade hook, `0.82.0` (#316) HTTP serve as default, `0.84.0` (#319)
memory-first consultation enforced on all three agents. `CLAUDE.md` instructs every agent to
"Search memory FIRST — before web search, code search, or asking the user". Every one of those
agents has been searching an empty bank.

This is the project's recurring defect class — registered, instructed, not running — appearing in
its newest subsystem. It also means the seven panel experts, all instructed to search memory
first, will get zero hits; their fallback behaviour is itself a useful observation.

**Fix:** enable watching and seed the bank. The enable step is a user-run CLI action.
**Gate:** `memory_stats` reports a non-zero entry count and `memory_watch_status` reports a
healthy watch on `docs/`.

### O-2 — The commit-time gate chain does run inside a worktree (CONFIRMED, informational)

Committing the charter from `.ai-badger/worktrees/full-project-review` fired eight gates, all
passing: `version-sync`, `index-build`, `changelog-index`, `plugin-skills-sync`, `docs-guard`,
`deps-guard`, `shipped-paths-guard`, `scaffold-freshness-guard` (`pylint` skipped — no Python
files staged). The `code-review-graph` incremental indexer also ran.

This is a counterweight to the recorded hazard that worktree hooks resolve `${CLAUDE_PROJECT_DIR}`
against the main checkout: on the commit path, in this worktree, they resolved. It says nothing
yet about the **pre-push** chain, which is where the SIGKILL symptom was recorded and where
`--no-verify` was used on #323/#324/#325. E6 owns that question.

### O-3 — Six tracker entries are stuck IN_PROGRESS (CONFIRMED, low)

`task_tracker.py status` shows `ai-badger-issues-drain-session`, `pr-254-takeover`,
`pr-257-takeover`, `f2-third-party-fallback`, `enrich-last-article-about-skills` and `issue-286`
open since 1–5 August. `git worktree list` shows none of them owns a worktree, and there are no
open PRs or issues. They are tracker residue: `status` misreports the project as having six live
work streams, which is exactly the failure the skill's own gotchas warn about for a recorded
branch nothing created.

**Fix:** finish or park all six.
**Gate:** `task_tracker.py status` shows no `IN_PROGRESS` entry older than the current task.

### O-4 — Scaffold drift at session start (CONFIRMED, low)

`.ai-badger/` was scaffolded by `0.87.0`; the running plugin is `0.87.1`. Expected after a release
that did not re-scaffold, and `scaffold-freshness-guard` passes regardless — worth confirming that
the guard is meant to tolerate a one-patch gap rather than failing to notice it. E7 owns this.

### O-5 — Token tracking has been dead for eleven consecutive tasks (CONFIRMED, high)

`task_tracker.py` resolves its state directory `.ai-badger/task-tracking/` **relative to the
current working directory**. The skill's Phase 1 step 4 says: *"Work in the worktree `start` just
created — Every command for the rest of the task runs there, not in the main checkout."* A task
worktree carries its own empty `.ai-badger/task-tracking/`, so a session that obeys the skill
literally gets `No tracked tasks` from `status`, and `subagent <taskId> …` fails with
`Unknown task <taskId>. Run start first.`

Measured here: the identical command printed `No tracked tasks` from
`.ai-badger/worktrees/full-project-review` and the full task list from the main checkout. Both
`.ai-badger/task-tracking` and `.ai-badger/worktrees/full-project-review/.ai-badger/task-tracking`
exist as separate directories.

The fingerprint is in the tracker's own data. Every task from `memory-grade-hook` (2026-08-05)
through `skills-shape` (2026-08-07) reports `tokens=0` — eleven in a row, including all five of
this week's release tasks. `full-project-review`, run deliberately from the main checkout, reports
`tokens=56702846 cacheEff=0.926 mix=sonnet-5:51%`. Tasks predating the worktree default do carry
counts (`gherkin-specbinder` 12.5M, `observe-prs-review-changes` 38.4M), which places the
regression at `0.69.0` (#272, "a task owns its worktree", 2026-08-01).

The consequence is that the skill's own stated grading criterion — *"Judge a run by its model mix
… not by cache efficiency"* — has been unmeasurable for every task since. The missing numbers read
as tasks that simply did not record, rather than as a defect.

**Fix:** resolve the tracking directory from `git rev-parse --git-common-dir` so a worktree and
its main checkout share one store. Workaround until then: run every `task_tracker.py` invocation
from the main checkout.
**Gate:** a test that registers a task from the main checkout, then reads it back with cwd set to
a worktree, and asserts the task is found. It must fail on today's code.

## E5 — Documentation tree and agent-instruction truth (architect/sonnet)

Ran every check itself: the shared 20-slot concurrent-agent pool was exhausted by the other panel
experts on both attempts, so its three sub-agent slots went unused. Worth noting for the execution
plan — **the panel width was itself a constraint**, and a fan-out plan has to budget for it.

### Confirmed findings

- **F1 (high) — `docs/skills.md` documents 23 of 37 shipped skills, and contradicts itself.**
  Line 3 claims "twenty-two skills … twenty-one live under `features/common/skills/` … fourteen
  are default … eight are `optIn`" — 14+8=22≠21, wrong before you check reality. The table has 23
  rows. On disk: 36 `SKILL.md` under `features/common/skills/` plus `features/claude/skills/auto-wm`
  = 37, and `SKILL_SCOPES` in `engine/badger_lib.py` (the actual routing source of truth) names all
  36. Fourteen real optIn skills are entirely undocumented, all landed in #320 today.
  **Nothing in the repo checks that the catalog and its own documentation agree** — `skills_lint()`
  only reads `SKILL.md` frontmatter, and `docs_guard` cannot see a prose undercount.
- **F2 (medium-high) — `docs/work/README.md` indexes two files that never merged.**
  `2026-08-07-mcp-skills-distribution.md` and `2026-08-07-mcp-skills-tools-pattern.md` are
  described in the table and absent from the tree. Independently re-verified by the orchestrator:
  both `ls` calls return "No such file or directory". They exist only on the unmerged branch
  `feat/memory-first-gate`; the README rows arrived via #321's squash. The canonical-tree test
  checks only "every file is named", never "every named thing exists".
- **F3 (medium) — `docs/plans/` was declared removed in PR #111 and still holds a shipped plan.**
  `docs/plans/memory-grade-hook.md` still says `Status: proposed` for a feature that shipped as
  `0.79.0`, eight releases ago. The canonical-tree test passes only because `docs/README.md`
  contains the substring `plans/` inside prose *explaining that the directory was removed* — a
  false positive.
- **F4 (low) — `docs/scripts.md` lists 6 of 8 `tooling/` scripts**, omitting `fixture_harvest.py`
  and `retrieval_eval.py`. Pre-existing, not this week's drift.

### Checked and clean — stated explicitly rather than by silence

- **Junie removal is complete.** A full sweep of `schemas/`, `tooling/`, `engine/`, `features/`,
  `gates/` found zero functional remnants; `tests/test_three_agent_scope.py` actively asserts the
  absence and passes. Every surviving mention is legitimate historical record (ADRs, changelog
  entries ≤0.83.0, a dated `state.json` row) or a worked teaching example.
- **The six-file instruction family is consistent.** `validate.py --all` green including
  `skills lint`; `check-agent-drift.mjs` passed; all three source/copy pairs hand-diffed and differ
  only by the expected "Managed by ai-badger" header.
- **Changelog integrity is sound.** `changelog_index.py --check` → 154 versions, 199 entries;
  independently re-derived: no duplicates, strictly descending, zero mismatches in either
  direction, VERSION 0.87.1 has its entry. The recorded "index row conflicts on every concurrent
  PR" hazard is **not currently manifesting**.
- **`docs_guard.py` passes on 252 documents** — re-run, not cited. It is a real but narrow gate,
  and its own design doc is honest that prose is unlinted.

### E5's backlog

| ID | Item | Gate | Shared files |
|---|---|---|---|
| W1 | Document the 14 missing skills; fix the count prose. Better: generate the table from `SKILL_SCOPES` so it cannot drift again | new pytest asserting every `SKILL_SCOPES` key appears in `docs/skills.md` | `docs/skills.md`, new test |
| W2 | Resolve the two dangling `docs/work/README.md` rows — delete, or restore the files from `feat/memory-first-gate` | `docs_guard` post-W5 | `docs/work/README.md` — **serialises with this review's own commits** |
| W3 | Move `docs/plans/memory-grade-hook.md` into `docs/work/` under a dated name, or delete it | `pytest tests/test_docs_tree_is_canonical.py` | `docs/plans/`, `docs/work/` |
| W4 | Add the two missing scripts to `docs/scripts.md` | manual, or a new coverage test | `docs/scripts.md` |
| W5 | Harden the gates against F2/F3 shapes: bidirectional `docs/work/README.md` check, and replace the naive substring directory check with a real `CANONICAL_DIRS`/`FROZEN_DIRS` membership test | new test must fail on synthetic dangling-reference and residue-directory fixtures before passing clean | `gates/docs_guard.py` or `tests/test_docs_tree_is_canonical.py` |

W2 → W5 serialise (fix the data, then write the test against a clean tree). W1, W3, W4 are
mutually independent and independent of W2/W5.

## Integrated plan

Written once the panel has reported. Not started.
