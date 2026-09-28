Done. Commit `1d81cb84` on `lane/S10-pipeline`, working tree clean, not pushed.

# S10 report — task/quick-task pipeline rewrite

## AC 1 — pin test RED→GREEN with every row asserted

**RED verbatim** (first run, before any rewrite):

```
$ .venv/bin/python3 -m pytest tests/test_task_pipeline_vocabulary.py -q
E       AssertionError: subpackage survives in: ['task/SKILL.md']
E       assert not ['task/SKILL.md']
...
E       AssertionError: task/SKILL.md still says 'package'
E       assert not <re.Match object; span=(292, 299), match='package'>
...
FAILED tests/test_task_pipeline_vocabulary.py::TestEveryRewrittenRowCarriesItsNewPhrase::test_row_carries_its_new_phrase[task/SKILL.md::7 description]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::44 loop axis]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::58-59 integration step]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::67-68 plan step]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::134 loop/effort axis sentence]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::134 model-tier precedence]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::142-144 shared-file steps]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::166 phase-1 exit]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::169 determine the loop]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::206 phase-2 exit]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::212-216 decomposition paragraph]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::212-216 plan_create recording]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::212-216 depends_on order]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::212-216 plan AC]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md:DR12 legacy sentence]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::223-224 ready set/waves]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::226-231 every step AC+gate]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::239-240 lane-brief serialisation]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::257 commit per step]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::262 phase-4 entry]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::286 steps into one change]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::364 checklist row]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/SKILL.md::366 checklist loop]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/extensions/github/extension.md::38 per-step push]
FAILED tests/test_task_pipeline_vocabulary.py::... [task/extensions/claude/extension.md::49 step arbitration]
FAILED tests/test_task_pipeline_vocabulary.py::... [multi-agent-communication/SKILL.md::40 step/join boundaries]
FAILED tests/test_task_pipeline_vocabulary.py::... [worktree-agent-isolation/SKILL.md::228 after a step lands]
FAILED tests/test_task_pipeline_vocabulary.py::... [worktree-agent-isolation/references/shared-worktree-collisions.md::3 parallel steps]
FAILED tests/test_task_pipeline_vocabulary.py::... [personas/delegator.md:boundary sentence]
FAILED tests/test_task_pipeline_vocabulary.py::... [complete-project-scope-code-review/SKILL.md:handoff note]
FAILED tests/test_task_pipeline_vocabulary.py::... [quick-task/SKILL.md::54-56 boundary sentence]
FAILED tests/test_task_pipeline_vocabulary.py::TestRequiredVocabularyIsPresent::test_task_skill_names_the_skill_the_artifact_and_the_unit
FAILED tests/test_task_pipeline_vocabulary.py::TestRequiredVocabularyIsPresent::test_loop_and_effort_axes_are_disambiguated
FAILED tests/test_task_pipeline_vocabulary.py::TestRequiredVocabularyIsPresent::test_dr12_legacy_sentence_is_present
FAILED tests/test_task_pipeline_vocabulary.py::TestRequiredVocabularyIsPresent::test_quick_task_boundary_sentence_is_present
FAILED tests/test_task_pipeline_vocabulary.py::TestRetiredVocabularyAndStaleToolsAreGone::test_no_owned_file_says_subpackage
FAILED tests/test_task_pipeline_vocabulary.py::TestRetiredVocabularyAndStaleToolsAreGone::test_task_skill_drops_the_package_vocabulary
37 failed, 3 passed in 1.56s
```

The 3 pre-green passes were the structural guards (`every owned file has a row`, no `**P<N>**`, no stale tool names) — the stale names only ever lived in the pre-freeze plan sections, so their check is a regression guard, not the red witness. **GREEN:** `40 passed` (31 row assertions + file-coverage guard + 4 required-vocab + 4 forbidden). `test_every_owned_file_has_a_row` makes a silently skipped file fail by construction.

## AC 2 — disposition table (every C2 row + R3-F10)

| C2 row | Disposition | Landed wording / evidence |
|---|---|---|
| `task/SKILL.md:7` | rewritten | "`task-decomposition` into a `task-plan` whose `workflow` is a DAG of `step`s" |
| `:41-47` | exempt (loop spine) | verified unchanged, no package word |
| `:58-59` | rewritten | "carries a join step when the `workflow` has more than one sink; …cross-step tests" |
| `:67-68` | rewritten | "Run `task-decomposition` into a validated `task-plan`… every step has ACs; the plan AC: all steps' ACs checked+met" |
| `:142-144` | rewritten | "name shared-file steps, which serialise by a `depends_on` edge or a merge…" |
| `:206` | rewritten | "reviewed `task-plan` recorded; every step carries criteria and a gate; shared-file steps serialised by an edge; join step present when >1 sink" |
| `:212-216` | rewritten | `task-decomposition` → `plan_create`; `depends_on` the only ordering source; no-server → hand-written frozen-shape file |
| `:223-224` | rewritten | "The server derives the ready set and waves via `steps_ready`… designed in via `depends_on` edges" |
| `:226-231` | rewritten (step not point) | AC+gate, `design-tests`, `archify` all retained |
| `:239-240` | rewritten | "steps sharing a file serialise (add a `depends_on` edge or merge them)…" |
| `:257` | rewritten | "Commit and push per step" |
| `:262` | rewritten | "Entry: every step complete, all ACs checked and committed…" |
| `:286` | rewritten | "steps into one change" |
| `:313` | exempt (state protocol) | verified untouched |
| `:364` | rewritten | "Every step's acceptance gate ran; all step ACs checked; join step carried the cross-step tests" |
| `task/extensions/github/extension.md:38` | rewritten | "Commit and push as each step lands" |
| `task/extensions/claude/extension.md:49` | rewritten | "arbitration when two steps disagree about a contract" |
| `task/references/tracking-visibility.md:24-30` | **not mine** (S11/SK4) | untouched |
| `quick-task:6,23-25,84-85,157` | exempt | verified no package vocabulary |
| `quick-task:54-56` | +1 boundary sentence | "Do not call `task-decomposition` and do not create graph state — …escalate" |
| `status-report/SKILL.md:56,81` | **not mine** (S11) | untouched |
| `status_report.py:43,165-179,295-315,338-355` | **not mine** (S11/SK4) | untouched |
| `multi-agent-communication:40` | rewritten | "Broadcast at step/join boundaries" |
| `worktree-agent-isolation` ref `:3` + SKILL `:228` | rewritten | "parallel steps can still land in the SAME worktree"; "after a step lands" |
| `complete-project-scope-code-review` (15 hits) | exempt + note | "A review work package becomes a `step` when the review plan is handed to `task`." |
| `design-gate-audit` | exempt, boundary-only | no edit (not my file) |
| `review-tests` `WPn` | exempt + mapping | no edit (not my file) |
| `scripts-tooling-refactor` | exempt | no edit |
| `invariants/small-commits-early-draft-pr.md` | exempt + note | no edit |
| `personas/delegator.md` | exempt + 1 note | "Dispatch packages are batches of `step`s; the task-plan unit is `step`." |
| `query_pipeline.py:30-90` | exempt, no touch | verified untouched (pi prompt pin) |
| `.ai-badger/skills/**` mirrors | generated | **left to the integrator's re-scaffold** (outside my file list); guard reds only on these + manifest + generated delegator copies |
| **R3-F10** `:44` | rewritten | "ask the user whether the task runs the low or high `loop`" |
| **R3-F10** `:134` + contract | rewritten | "The task `loop` (low|high) chooses the orchestration loop; a step's `effort` (low|medium|high) drives model-tier selection"; precedence `model` > `level` > `effort`-as-level > session default |
| **R3-F10** `:166` | rewritten | "Exit: loop chosen, tracker STARTED…" |
| **R3-F10** `:169` | rewritten | "**Determine the loop.**" |
| **R3-F10** `:366` | rewritten | "Task `loop` (low or high) was determined before implementation began" |
| **DR12 addition** | added | "A task with no plan row keeps its legacy plan file and manual checkboxes — never `plan_create` over an in-flight task." |

## AC 3 — gates

| Gate | Result |
|---|---|
| `pytest tests/test_task_pipeline_vocabulary.py tests/test_skills_lint.py tests/test_docs_match_the_catalog.py -q` | **120 passed** |
| `gates/skills_lint.py` | **ok — 55 SKILL.md checked** |
| `tooling/sync_plugin_skills.py --check` | **47 skill(s) in sync** |
| `gates/docs_guard.py` | **PASS** — 551 documents, every link/path/changelog entry resolves |
| commit pre-commit hooks | version-sync, index-build, changelog-index, plugin-skills-sync, docs-guard, deps-guard, shipped-paths-guard, rules-index-regen, pylint — **all Passed**; scaffold-freshness-guard **Skipped (authorized)** |
| `gates/scaffold_freshness_guard.py` (informational) | FAILED on **only** stale mirrors: 9 `.ai-badger/skills/**` + `.ai-badger/agents/delegator.md` + `.ai-badger/manifest.json` + `.claude/.github/.pi` delegator copies — every one regenerated by the integrator's re-scaffold; none is my file |

## Files changed (commit `1d81cb84`, 19 files)

Source: `task/SKILL.md`; `task/extensions/{github,claude}/extension.md`; `multi-agent-communication/SKILL.md`; `worktree-agent-isolation/SKILL.md` + `references/shared-worktree-collisions.md`; `personas/delegator.md`; `complete-project-scope-code-review/SKILL.md`; `quick-task/SKILL.md`; **new** `tests/test_task_pipeline_vocabulary.py`.
Generated mirrors (via `sync_plugin_skills.py`): `skills/task/SKILL.md` + `SKILL.full.md`, `skills/task/extensions/{github,claude}/extension.md`, `skills/multi-agent-communication/SKILL.full.md`, `skills/quick-task/SKILL.full.md`, `skills/worktree-agent-isolation/SKILL.full.md` + `references/shared-worktree-collisions.md`, `skills/complete-project-scope-code-review/SKILL.full.md`.

## Deviations

1. **Lint budget.** First rewrite pushed `task/SKILL.md` to body proxy **5116 > 5000** (skills_lint rule 7) and tripped rule 8 on a `references/` parenthetical I had added to the decomposition paragraph. I compressed the Model tier contract, the Phase-2 decomposition paragraph, the `:226-231` step paragraph, the integration/ready-set lines, and the decomposition lead (meaning preserved; every pinned phrase intact) and dropped the added parenthetical — the pre-existing conditioned `tracking-visibility.md` mention remains. Lint green; pin test unchanged and green.
2. **Contract precedence wording** follows S9's shipped `plan-vocabulary`/`decomposition-method` wording ("…> the step's `effort` used as the level > the session (or parent) default model") rather than the brief's short parenthetical, so the two skills teach one precedence; the axis sentence uses the brief's exact phrasing.
3. **`.ai-badger/**` and generated agent copies were not regenerated** (explicitly not my files). The commit used the authorized `SKIP=scaffold-freshness-guard`; no push, so no push-gate run.
4. **Not pushed**, per the operator contract.
5. Four of the `:212-216` paragraph's elements (`task-decomposition`, `plan_create`, `depends_on`, plan AC) are pinned as separate rows — all over-pinned, none weakened.

Sub-agents: 0.