## S11 complete — committed `d9026d6a` on `lane/S11-status` (not pushed)

### AC-by-AC evidence

**AC1 — new tests red→green (RED pasted), incl. fallback fixture + mapping pin.**
RED (before implementation; 9 new tests, 7 red for the 7 defect-bearing assertions, 2 regression pins pre-green):
```
>  assert progress["packages"] == ["S1 — wire the resolver (pending)",
E  AssertionError: assert [] == ['S1 — wire t...in_progress)']
E    Right contains 2 more items, first extra item: 'S1 — wire the resolver (pending)'
>  assert progress["packages"] == ["P1 legacy package (RUNNING):",
E  AssertionError: assert ['P1 legacy p...e (RUNNING):'] == ['P1 legacy p...ep (pending)']
E    Right contains one more item: 'S2 — new step (pending)'
E  AssertionError: assert '  [step] S2 — new step (pending)' in '== CURRENT TASK ==...'
>  assert progress["packages"] == ["S1 — do the thing (pending)",
E  AssertionError: assert [] == ['S1 — do the...sh (pending)']
>  assert data["progress"]["packages"][0] == "S1 — wire the resolver (pending)"
E  IndexError: list index out of range
E  assert '`progress_checklist` with `format:"text"` **IS** the "Progress checklist" section verbatim (primary); the status script's plan-file output is the fallback when no graph plan or CLI is reachable.' in '--- name: status-report ...'
E  AssertionError: assert '**S<N> …**' in '# Tracking visibility ...'
FAILED tests/test_status_report.py::TestDualReadPlanHeadings (5 script tests)
FAILED tests/test_status_report.py::TestProgressSourceContract::{skill_binds, tracking_visibility}
7 failed, 2 passed in 1.16s
```
GREEN after: `9 passed`. Fallback fixture = `HANDWRITTEN_PLAN` (banner `hand-written — graph off`, S-headings, checkboxes) parses+renders; mapping pin = `GRAPH_IS_PRIMARY` exact sentence + CLI verb path.

**AC2 — legacy P tests untouched and green.** No edits to any existing test (`git diff` adds only). `PACKAGE_RE`-by-name edits: **none** — no test referenced the symbol (repo grep found only the script and frozen `docs/work` prose). 90/90 pass in the gate file pair.

**AC3 — keys/exit-0 contract unchanged (asserted).** `test_the_progress_keys_and_exit_zero_are_frozen` asserts `plan_checklist()` returns exactly `{plan_file, matched, packages, checked, total}` (and empty-shape `{"plan_file": None, ...}`), `--json` top-level keys and `progress` key set, `packages[0]` carries the S-heading verbatim; `test_no_plan_still_prints_the_placeholder_and_exits_zero` asserts rc 0 + `(no plan file)`. Loop-step render line untouched.

**AC4 — SKILL + tracking-visibility carry the two-path contract.** `status-report/SKILL.md` (:54-64 procedure, :87 table): `progress_checklist` with `format:"text"` **IS** the section verbatim, CLI invocation named, script parse = fallback, four sections + "never delegate/never wait" + exit-0 kept. `task/references/tracking-visibility.md:24-33`: server-built/rendered plan with generated banner, `**S<N> …**` heading per step, checkbox per AC, hand-written graph-off fallback, legacy `**P<N>**` dual-read, whole-taskId + review-exclusion + "(no plan file)" + brief-never-counts kept. Both pinned by tests.

### Files changed (7)
`features/common/skills/status-report/scripts/status_report.py` (`STEP_RE`, `STEP_HEADING_RE`, dual-read `plan_checklist`, render split) · `features/common/skills/status-report/SKILL.md` · `features/common/skills/task/references/tracking-visibility.md` · `tests/test_status_report.py` (+176) · mirrors `skills/status-report/SKILL.full.md`, `skills/status-report/scripts/status_report.py`, `skills/task/references/tracking-visibility.md` (via `tooling/sync_plugin_skills.py`).

### Gates (verbatim)
```
$ .venv/bin/python3 -m pytest tests/test_status_report.py tests/test_skills_lint.py -q
........................................................................ [ 80%]
..................                                                       [100%]
90 passed in 1.48s
$ .venv/bin/python3 gates/skills_lint.py
ok       skills lint — 55 SKILL.md checked
$ .venv/bin/python3 tooling/sync_plugin_skills.py --check
47 skill(s) in sync
```

### Rejected alternatives
- **Rename `packages`→`steps` / add a `steps` key** — frozen keys/shape per DR10 and ambient `:153,:169` pins; render split carries the distinction instead.
- **Two regexes (`PACKAGE_RE`+`STEP_RE`) merging two lists** — one `[PS]` regex keeps a single ordered heading source, no precedence question, identical key shape.
- **Script calls MCP/CLI itself for progress** — violates stdlib-only (ships where `badger_lib` absent) and "never calls MCP"; the agent is the caller per DR10.
- **`heading.startswith("S")` for step detection** — a legacy package heading can start with an S-word (`**Sync the store:**`); `^S\d+` keys on the server's rendered shape.
- **Reading `tracking.db` plans table in the script** — `task_tracker.py` never reads `plans` (DR10); graph read belongs to the agent.

### Deviations
- Two extra regression pins beyond the required list: `never_delegate_never_wait_and_the_four_sections` (pre-green, behavior guard) and the tracking-visibility two-path pin (evidence for AC4). The no-plan placeholder test is an unchanged-contract assertion and was correctly green pre-change.
- `SKIP=scaffold-freshness-guard` commit authorized: hook red on exactly `.ai-badger/manifest.json` + 3 stale `.ai-badger/skills` mirrors of my two skills, nothing else — `.ai-badger/**` is outside this lane (S13 re-scaffolds).
- `skills_lint` reports 55 SKILL.md (was 54): S9's task-decomposition skill from the same base accounts for the count, not this change.
- No bus announcement / memory write, per "handoff: report only". Sub-agents: 0.