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

## E1 — Python architecture of the framework itself (architect/opus)

Thirteen findings, each labelled by how it is known — measured, delegated-and-reported, or
reasoned. Three carry unusual weight.

### The three that change what we build

- **F2 (high, measured) — `import jsonschema` costs ~470 ms of `badger_lib`'s ~500 ms import, and
  11 of 13 entry points never validate.** Best-of-5 warm subprocess timings on this machine:
  `python3 -c "pass"` 0.12 s, `import framework_copies` 0.17 s, `import badger_lib` **0.62 s**,
  `import jsonschema` 0.59 s. Only `index_build.py` and `validate.py` ever call the validators; the
  other eleven — `changelog_index`, `install_plugins`, `retrieval_eval`, `sync_plugin_skills`,
  `version_sync` and all six `gates/*.py` — pay it for nothing on every pre-push run. The same
  unguarded import is the *documented* reason `engine/framework_copies.py` restates
  `is_framework_root` and `read_version`. Fix is ~5 lines: move the import inside the three
  validation functions. It must still **raise** — "validation refuses rather than silently
  passing" is the invariant, and a lazy import that swallowed `ImportError` would quietly turn
  validation into a no-op.
- **F1 (high) — ADR-0005 wrote its own expiry condition, and it fired four days ago unnoticed.**
  The ADR rejected frontmatter-declared skill scope because *"no script in `scripts/` parses YAML
  frontmatter today … worth revisiting if anything else ever needs frontmatter at build time."*
  Commit `7cebf20` (#324, this week) added exactly that parser at `tooling/validate.py:277`. The
  ADR still reads as settled, while `engine/badger_lib.py:664-702` carries a 39-entry hand-kept
  `SKILL_SCOPES` dict and line 1 carries `# pylint: disable=too-many-lines … (ADR-0005)`. The file
  is over its lint ceiling because of a data table whose justification has lapsed.
- **F10 (medium, over-engineering) — 672 LOC of retrieval-evaluation machinery gates nothing.**
  `grep` over `.github/`, `.lefthook/` and `lefthook.yml` finds no reference to
  `tooling/retrieval_eval.py` (398 LOC) or `tooling/fixture_harvest.py` (274 LOC). Their tests
  exercise synthetic fixtures only. ADR-0012 ratified "BM25 retrieval with a falsifiable eval";
  the eval has never been fired at the real corpus. Two honest options — wire it into a lane with
  a stated threshold, or delete the harvester and demote the eval to a documented manual tool.
  Choosing the first and not doing it is the current state.

### The rest

- **F3 (high)** — `validate.py` accreted a markdown convention linter (+187 lines in one commit).
  `skills_lint()` enforces ten *authoring* conventions, which is a repo gate; ADR-0011 already
  names `gates/` as the home for exactly that. It also parses the same file three times with three
  different parsers, and carries five-line provenance comments against the minimal-comments
  invariant.
- **F5 (medium, cost not bug) — the triplication is a generated pipeline with a hard gate, not
  debt.** Source is `features/{common,claude}/skills/`; `skills/` is pointer-rendered by
  `sync_plugin_skills.render_into()`; `.ai-badger/skills/` is this repo scaffolded against itself.
  `check_skill()` re-renders with the same function used to write and compares content hashes — the
  render *is* the contract. Both derived trees are gated in lefthook and CI; both checks were run
  live and came back green. Real cost: ~126 files / ~1.3 MB per tree and enforcement after the
  fact, so a hand-edit to a derived copy is caught at push rather than at edit time. Worth one
  cheap PreToolUse guard that refuses the edit and points at `features/`.
- **F4 (medium-high)** — `badger_lib.py` is seven domains with clean seams (framework root
  resolution, content hashing, schema validation, skill routing). **But E1 argues against splitting
  it yet**: do F2 first and re-measure, because if the lazy import lands, the architectural case
  collapses to "1002 lines is a lot", which does not clear the "abstraction before a real caller"
  bar. Ship it only if a second stdlib-only consumer appears or F1 removes `SKILL_SCOPES`.
- **F6 (medium)** — one gate-report shape copy-pasted three times and *already drifted*:
  `deps_guard.py:69-71` dropped the line-less fallback, so a missing `engine/requirements.txt`
  prints `engine/requirements.txt:0`. Five report shapes exist for one concept.
- **F8 (medium)** — eight `VERSION` readers; six guard a missing file, `version_sync.py:44` and
  `release_guard.py:217` raise an uncaught `FileNotFoundError`.
- **F9 (medium)** — four frontmatter parsers, two of them one file apart.
- **F11–F13 (low-medium)** — a doc-budget checker living inside the task tracker's state store,
  crontab management bundled into the task CLI, and an analyzer bolted onto a log switch. All three
  carry the same blocking caveat: those files claim **lockstep with an upstream
  `job-search-ai-assistant` repo**, so a refactor has an owner question attached before it has a
  design.
- **F7 (low) — flagged expressly so nobody "fixes" it.** The 12× `--root` idiom and 13× sys.path
  bootstrap are ratified at `pyproject.toml:23-28` as *"a deliberate deployability property, not
  debt to refactor away."* Same for the five byte-identical `debug_log.py` copies.

### E1's backlog, with its own serialisation

B1 lazy jsonschema · B2 supersede ADR-0005 · B3 extract skills lint to a gate · B4 shared gate
`Problem`/`report()` · B5 guarded `read_version` · B6 decide the retrieval eval · B7 PreToolUse
guard on derived trees · B8 one frontmatter extractor · B9 split `badger_lib` (conditional on
B1+B2) · B10 task-script splits (blocked on the lockstep question).

Serialisation: B2 → B8 → B3 all touch `tooling/validate.py`. B1 → B5 → B9 all touch
`engine/badger_lib.py`, B1 first as cheapest-and-highest-value, B9 last and conditional. B4 before
B3 so the new gate can adopt the shared type. **Independently parallelisable now: B4, B6, B7,
B10.** Anything touching `features/` or `skills/` must regenerate both derived trees before commit.

## E7 — Catalog and scaffold integrity (architect/sonnet)

Used all three sub-agent slots. Corrected two numbers in its own brief, which is the behaviour the
evidence rules were written to produce.

### Corrections to the charter's figures

- **18 stack directories plus `common`**, not 20. My count included `common` and a non-stack dir.
- The 137-item `index.json` claim from a commit message is **accurate** — independently
  re-derived by reproducing `index_build.py`'s counting logic and confirming all 137 `path` fields
  resolve on disk, with all 51 `SKILL.md` files mapping 1:1 onto index entries.
- All three gates pass right now, re-run not cited: `index_build.py --check` → "index.json up to
  date"; `validate.py --all` → all ok including "skills lint"; `sync_plugin_skills.py --check` →
  "15 skill(s) in sync" (the plugin-mirrored subset, not all 51).
- `bedef94`'s fix ("an included optIn skill reaches the agent") **still holds** — traced end to end
  through `scaffold.py`, live-tested with a scratch scaffold opting into `update-documentation`,
  backed by a 26-test regression suite that names the scenario.

### Confirmed findings

- **1 (high) — 20 SKILL.md files carry a duplicate `description:` key, and the lint validates the
  wrong one.** `badger_lib.skill_description()` reads the **first** `description:` line; a real
  YAML parser resolves duplicate mapping keys to the **last** — the opposite. #320 introduced the
  duplicates; the 0.87.0 conformance commit `7cebf20` then added the required frontmatter block
  directly beneath the pre-existing duplicate without noticing. **Six of the twenty would fail the
  lint's own rule 5 under correct YAML semantics**: `dotnet-hosted-service-testing`,
  `dotnet-mcp-server`, `design-gate-audit`, `sqlite-schema-review`, `parallel-expert-review`,
  `artifact-verification`. The gate is green on a reading no real parser agrees with.
- **2 (high) — `features/github` is an advertised shell stack that this repo itself selects.** It
  holds exactly one file, `skills.json` with `{"skills": []}`, and no `stack.json`. It does not
  appear in `index.json.stacks` (18 keys) at all. Yet `.ai-badger/config.json` lists `github` among
  selected stacks and `CLAUDE.md` advertises it. `schemas/config.schema.json:67` states the
  membership rule only as a **description string**, never as an enforced construct — so nothing
  catches it.
- **3 (medium-high) — a live orphan in this repo's own `.ai-badger/`, and a general blind spot.**
  `.ai-badger/agent-instructions/model.schema.json` is byte-identical to the current output name
  `schema.json` and has survived every re-scaffold since v0.1.0. Root cause:
  `superseded_prune.py:60-71` only deletes a file whose feature type is excludable, and
  `FEATURE_TYPES` sets `drift_reports_new=False` for `templates`/`hooks`/`adjustments` — deliberate,
  so rendered output doesn't false-positive as "new" in `drift.py`, but as a side effect it exempts
  those three types from pruning entirely. **Any renamed destination filename in those types is
  permanently orphaned, invisible to both `drift.py` and `superseded_prune.py`.**
- **4 (medium) — 21 JSON catalog files under `features/` are unschema'd.** Notably
  `features/common/hooks/hooks.json` (real hook-wiring data feeding `.claude/settings.json`, easily
  confused with the *validated* `hooks-manifest.json`), `mcp-tags.json` (declares `$schema`/`$id`
  as if it were a schema but lives outside `schemas/`, so it is validated as neither), and 13×
  `extension.json` sharing an undocumented shape with no schema anywhere.
- **5 (medium) — one `SCHEMA_INSTANCES` entry is inert.** `validate.py` validates
  `model.schema.json` against glob `features/*/agent-instructions/model.json`, which matches **zero
  files**; the real file is one directory deeper under a different name. Unlike the honestly
  exempted entries, this one silently validates nothing while claiming to.
- **6 (medium) — three dangling skill-name references** that no rule catches:
  `scripts-tooling-refactor` cites a nonexistent `ai-badger-project-ops` three times;
  `research-record-audit` names `grounded-citations`; `worktree-agent-isolation` names
  `git-worktree-isolation` (apparently confusing its own name). Rule 10 checks only that
  `related_skills` is *present*, never that its values resolve.
- **7 (low-medium) — the brief's own premise was wrong, and E7 said so.** `dependencies.json` is
  scoped by its schema to **package** dependencies (one entry, untouched by #320). The real
  mechanism is `badger_lib.SKILL_GROUPS`, which declares exactly one group and was never extended
  to any of #320's 30 skills, despite `981212c`'s commit message promising "skills that cannot work
  alone travel together".
- **8–9 (low)** — two skill-description pairs overlap enough to hurt agent discriminability
  (`documentation-drift-audit`/`update-documentation`, `refactor-safely`/`spec-driven-refactoring`)
  with no "not for X, use Y" clause, unlike the good trio pattern already in the corpus; and one
  `references/` file about C# string interpolation sits inside `worktree-agent-isolation`, topically
  foreign to its skill. Against the charter's suspicion, E7 found the reference splits are
  **coherent complete-sentence splits, not arbitrary line-count chops**, and rule-9 Gotchas content
  was substantive rather than padding.
- **10 (low) — no two scaffolds are ever byte-identical.** `wire_hooks()` and `statusline.wire()`
  both write `.claude/settings.json` in one run; the second differs from the first, so a
  timestamped `.bak-*` is stamped even on a completely fresh target. Bounded (does not accumulate
  over repeated runs — verified by scaffolding three times), but it will break any naive
  golden-file idempotence test.
- **11 (info, by design) — the drift notice this session opened with is a known false positive.**
  Live-ran `drift.py --target .`: reports `versionChanged` 0.87.0→0.87.1 even though 0.87.1's only
  change touched build tooling that is never scaffolded into any project. Zero actual catalog
  drift, yet every scaffolded project gets nagged. Documented as intentional at `drift.py:352-353`
  (issue #110). Re-scaffolding does converge. This is a product decision, not a defect — answering
  charter item O-4.

### E7's backlog

B1 dedupe the 20 descriptions + a real-YAML duplicate-key rule · B2 resolve the `github` shell
stack and machine-enforce config↔index membership · B3 delete the orphan and fix the
templates/hooks/adjustments pruning blind spot · B4 schema-cover `hooks.json`, `mcp-tags.json` and
the 13 `extension.json` · B5 fix the inert glob · B6 fix the three dangling references + a
resolves-to-a-real-skill rule · B7 extend `SKILL_GROUPS` for #320 · B8 disambiguate the two skill
pairs · B9 relocate the misfiled reference · B10 collapse the double `settings.json` write · B11
owner decision on the version-only drift notice.

Overlaps: B1, B4, B5 and B6 all touch `tooling/validate.py` — they serialise. B2 also touches it
plus `schemas/config.schema.json`. B3 and B7 touch `engine/badger_lib.py`. B8, B9, B10 are
independent.

## Integrated plan

Written once the panel has reported. Not started.
