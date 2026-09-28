## S12 report — dependency declarations + honest claims

**Commit `cab9b4b4` on `lane/S12-claims` (base `4bd0c7fa`), not pushed. Sub-agents: 0.**

### AC 1 — pin extension RED→GREEN, OVERCLAIM guard green

**RED (verbatim, before any claim edit):**
```
..FF......                                                               [100%]
=================================== FAILURES ===================================
_ TestTheProjectDescriptionIsTrue.test_the_summary_names_pydantic_for_the_task_plan _
>       assert "pydantic" in _summary(root).lower()
E       AssertionError: assert 'pydantic' in 'agent-instruction framework distributed as a claude code plugin. ...'
_ TestTheProjectDescriptionIsTrue.test_the_summary_names_uv_as_the_plan_server_prerequisite _
>       assert re.search(r"\buv\b", summary), "uv must be named as the plan-server prerequisite"
E       AssertionError: uv must be named as the plan-server prerequisite
E       assert None
=========================== short test summary info ============================
FAILED ...test_the_summary_names_pydantic_for_the_task_plan
FAILED ...test_the_summary_names_uv_as_the_plan_server_prerequisite
2 failed, 8 passed in 1.24s
```
The OVERCLAIM guard and the rendered-copies guard passed in the RED run. **GREEN:** `10 passed in 1.61s`; final combined run `69 passed in 2.84s`.

### AC 2 — deps_guard green, all modules present
```
183 file(s) scanned; every third-party import is declared in engine/requirements.txt (jsonschema, pydantic, semantica, yaml) — PASS
docs_guard: 551 document(s) scanned; every link, repo path and changelog entry resolves — PASS
```

### AC 3 — final `project.summary` (source of truth, `.ai-badger/config.json`)
> Agent-instruction framework distributed as a Claude Code plugin. Python 3.10+ scripts (detect/scaffold/validate/index_build/drift) materialize a per-repo .ai-badger/ scaffold from a features/{stack|common}/{feature} catalog. engine/requirements.txt declares three runtime dependencies plus one optional wrapper guard: jsonschema (required; validation refuses rather than silently passing), pyyaml (optional, guarded, and degrades to a printed note), and pydantic (required; the task-plan model and its schema generator); semantica is needed only by the optional wrapper. The task-graph plan server/CLI are PEP 723 scripts launched via `uv run --script`, so the consumer-side prerequisite is uv (it fetches pydantic>=2.12,<3 into its cache on first launch, with no pip install and no project-venv pollution). The plan DAG layer is stdlib graphlib; networkx is deliberately not used. Two .mjs helper scripts under skills/maintain-agent-instructions/.

Prose passages restated the same posture: `README.md` requirements section (runtime deps + `uv` prerequisite + graphlib); `docs/getting-started.md:159` (package posture + `uv` paragraph), plus `:42` ("the two dependencies" → "the dependencies") and the troubleshooting "other dependency / Install both" passage; `docs/authoring-a-feature.md` ("one dependency" + comment).

### AC 4 — validate --all green (dependencies.json schema-valid)
`VALIDATE_EXIT=0`, including `ok features/common/dependencies.json`. New entry: system dep `uv`, feature `task-decomposition`, presence-only (no `command`, like node), note per brief.

### Files changed (6)
`.ai-badger/config.json` (summary only), `README.md`, `docs/getting-started.md`, `docs/authoring-a-feature.md`, `features/common/dependencies.json`, `tests/test_dependency_honesty.py`. `tooling/sync_plugin_skills.py` run both `--check` ("47 skill(s) in sync") and write ("Synced 47") — no mirror diff.

### Commit gate
Pre-commit hooks: version-sync, index-build, changelog-index, plugin-skills-sync, docs-guard, deps-guard, shipped-paths-guard, rules-index-regen, pylint all **Passed**; `scaffold-freshness-guard` **Skipped** as authorized — committing with plain guard first showed it reds on exactly the 7 rendered copies + `.ai-badger/manifest.json` (`configHash`/`generatedConfig`), all regeneration of the authorized summary edit; a detached base worktree confirmed the guard was green at `4bd0c7fa`, and that temp worktree was removed.

### Deviations
1. A one-off pytest **ERROR** in `test_an_omitted_script_is_caught` during the first combined run did not reproduce (passes alone and in 3 consecutive identical combined runs; base was green too) — recorded, not attributable to this change.
2. Scope extensions inside owned files beyond the three named passages (`getting-started.md:42` and the troubleshooting "Install both" sentence; authoring's "one dependency" line) to keep every remaining dependency count claim honest.
3. Test renamed `test_both_dependencies_are_declared_in_requirements` → `test_the_runtime_dependencies_are_declared_in_requirements` (the old name was itself a count), now also asserting `pydantic`.
4. Rendered-copy check is OVERCLAIM-only and tolerant of staleness by design (7 copies regenerate at the wave join); no render or `.ai-badger/**` file other than `project.summary` was touched.