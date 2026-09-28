**Status: complete.** Committed as `eca7cdbc` on `lane/S9-skill` (not pushed); working tree clean. Sub-agents: 0.

## AC-by-AC evidence

**AC1 — contract test red→green (RED pasted), incl. five rule names + stale-name absence.**
- RED (before any skill file existed): `FFFFFFFFFFFF.F  [100%]` → `13 failed, 1 passed in 1.84s`, first failure verbatim:
  ```
  >       assert SKILL_MD.is_file()
  E       AssertionError: assert False
  E        +  where False = is_file()
  E        +    where is_file = PosixPath('.../features/common/skills/task-decomposition/SKILL.md').is_file
  ```
  and the reference row: `AssertionError: features/common/skills/task-decomposition/references/decomposition-method.md does not exist`.
- RED for the docs half (docs reverted to `bda62842`, new skill present): `6 failed, 20 passed` — `test_the_catalog_total_is_right`, `test_the_common_total_is_right`, `test_each_scope_total_is_right[default…]`, `test_the_tree_total_is_right`, `test_the_these_sentence_matches_the_page_total` (restored cleanly afterwards).
- Adversarial red witness for the absence check: appended `plan_build` to SKILL.md → `FAILED …test_no_stale_tool_name_survives_anywhere_in_the_skill; 1 failed in 1.12s`; restored → `2 passed`.
- GREEN: `tests/test_task_decomposition_contract.py` → `14 passed in 0.95s`. It pins `scope: default`, `Use when`, the five rule names (`granularity`, `actionability`, `error[- ]propagation`, `completeness`, `stop[- ]rules`), join rule + `integration_ok` derived, all eight headings, three references + condition-checked mentions (reusing `skills_lint.references_without_conditions`, non-vacuously: mentions must exist), degraded-path sentence + exact CLI, 12 frozen tool names, and absence of all four stale names across the whole source skill dir.

**AC2 — skills_lint + validate green.**
```
ok       skills lint — 55 SKILL.md checked        (exit 0)
tooling/validate.py --all  … exit=0
```

**AC3 — docs/skills.md green at recomputed numerals.** Computed at run time from `badger_lib.skill_scope_in` + globs:
```
computed: catalog=49 common=48 default=46 optIn=2 tree=55 these=49
```
The page now states 49 / 48 / **46 default** / 2 opt-in / tree 55 / "These 49", and the row for `task-decomposition` is present. `tests/test_docs_match_the_catalog.py` green.

**AC4 — plugin mirror + `sync_plugin_skills.py --check` green.**
```
47 skill(s) in sync        (exit 0)
```
`skills/task-decomposition/` carries the pointer `SKILL.md`, `SKILL.full.md`, the three references and the eight frozen scripts.

**AC5 — `index_build.py --check` green.**
```
index.json up to date     (exit 0)
```
`index.json` gained only `{"name": "task-decomposition", "path": "features/common/skills/task-decomposition", "scope": "default"}`.

**Final gate sweep at `eca7cdbc`:**
```
pytest <5 files>: 1 failed, 104 passed   ← the one failure is pre-existing, see Deviations
gates/skills_lint.py: ok — 55 SKILL.md
tooling/validate.py --all: exit 0
tooling/index_build.py --check: up to date
tooling/sync_plugin_skills.py --check: 47 in sync
```

## Pre-existing failure (not mine, orchestrator-owned)

`tests/test_agent_doc_budget.py::test_every_agent_discovery_file_is_within_this_repos_budget` is red at base `bda62842` and unchanged by this lane: `HERMES.md` and `.hermes.md` are 277 lines / 18,458 chars vs `agentDocs` 264 / 17,800. Cause: the wave-2 join re-scaffold (`bda62842`) added the task-graph declaration (262→277). The fix lives in `.ai-badger/config.json` or catalog MCP content — files I don't own — so I report it rather than patch it. Commit used the authorized `SKIP=scaffold-freshness-guard` (the guard fails because `.ai-badger/skills/task-decomposition/` is not yet mirrored/manifest-rowed; the wave join re-scaffolds it).

## Rejected alternatives

- **Stale names verbatim in `plan-vocabulary.md`** — the brief requires both a normalisation table and their absence tree-wide. I kept the normalisation readable but non-literal (`plan_` + `build` ⇒ `plan_create`, …), so no callable-looking stale literal ever ships. Verbatim reproduction would have failed the pinned absence test.
- **`plan_replace` "with a note"** — no `note` field exists in the frozen `PlanReplaceInput` (`task_graph_server.py:191`); the skill states the real contract (idempotent content, `expected_revision`, `plan-in-progress` refusal).
- **P3-C2 disposition table verbatim** — its status-report row quotes stale tool names; dispositions are expressed without them.
- **Hand-copied docs numerals** — rejected in favour of the derived set above.

## Files changed (`git diff bda62842..HEAD`)

New: `features/common/skills/task-decomposition/{SKILL.md,references/{decomposition-method.md,plan-vocabulary.md,mcp-plan-tools.md}}`; `tests/test_task_decomposition_contract.py`. Modified: `docs/skills.md`, `index.json`. Generated: `skills/task-decomposition/**` (13 files). Nothing outside my owned set; `VERSION`, `docs/changelog/**`, `.ai-badger/**`, `scripts/**` untouched.

## Deviations

1. The agent-doc budget failure above (pre-existing, orchestrator-owned).
2. `SKIP=scaffold-freshness-guard` on the commit, as the brief authorises.
3. The contract-test file was amended once (mention-existence assertion) after the RED capture, so the RED log's line numbers predate that edit; the witness itself is unaffected.

Handoff: report back only, no pushes, no memory writes.