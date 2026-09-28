# Plan review — R1 (structure & feasibility attack), rev 1

Pass 1: read the plan, §1–§5, all three panel sections, the research record and four lanes in full. Pass 2: mechanically verified the load-bearing facts against the tree — `_VENDORED_GLOBS` (`engine/badger_store.py:319`), `tracker_lib.resolve_project_root/_project_above` (`:172-212`, `:157-169`), `badger_store.tracking_db_path/_default_badger_root/_ensure_schema_version` (`:352-370`, `:458-463`), `tests/test_status_report.py:150-171`, `tests/test_docs_match_the_catalog.py:192-203`, `tooling/validate.py:367-372,817-843`, `tests/test_schema_self_description.py:79-88`, `tests/test_badger_store_vendored.py`, `tests/conftest.py:100-120,300-345`, `features/common/hooks/hooks-manifest.json:121-134`.

**Checked and holding** (not restated below): the wave/file-ownership map is internally sound — every "parallel" pair is file-disjoint, and S2→S5, S8→S9, S12→S13 are the only shared-file joins; `tests/test_status_report.py:153,169` does pin `packages/checked/total`; `_VENDORED_GLOBS` is exactly `features/**`+`skills/**`; `gates/deps_guard.py` walks engine/tooling/features/gates (not tests); the `$schema`/Draft-2020-12 plan for S2 is viable. The failures below are where the plan does not survive.

### F1 — **MUST** · Tool I/O is never frozen, and DR6 contradicts P2-B1 on `plan_id` (§1 DR5/DR6, §2)
DR6 deletes `plan_id` ("dropped as a second identity") and adds required model fields `loop` and `research_ref` (`TaskPlan` field list). P2-B1 — authoritative where §2 is silent — keeps `PlanRef = {plan_id?, task_id?}` with "plan_id wins", requires `plan_id` on `plan_replace`, and `plan_create` accepts no `loop`/`research_ref`. §2 freezes only the 12 names and error codes, so S7's "12-tool contract" AC and S9's `mcp-plan-tools.md` have two incompatible specs, and S7/S9 run in the same wave.
**Fix:** add an explicit tool-I/O freeze to §2: `PlanRef = {task_id}`; `plan_id` absent from every input and output; `plan_create` accepts `task_description_ref`, `task_context`, `research_ref?`, `loop`, `source_refs?`, `steps`; all other P2-B1 shapes stand verbatim; add a frozen-contract fixture to S7's AC.

### F2 — **MUST** · Root resolution has three contradictory rules and the working one is unpinned (§1 P1-A1 vs P2-B3, §3 S6)
P1-A1: env → walk up from cwd for `.ai-badger/manifest.json` → collapse worktree. P2-B3: env else `Path(__file__)` four parents, "never cwd". The tree's rule is neither: `resolve_project_root` = `CLAUDE_PROJECT_DIR` → `project_above(cwd)` (marker `.ai-badger/config.json`, collapsed) → `project_above(script_dir, stop=$HOME)` → `parents[3]`; and `tracking_db_path` honours only `AI_BADGER_TRACKING_ROOT`, else `_default_badger_root()` — a file-ancestor walk with **no collapse**, which in a worktree resolves to the worktree's own empty store (the B12 split state the design forbids). S6's AC(2) pins only `collapse_worktree` equivalence, not precedence.
**Fix:** freeze the algorithm in §2 as `CLAUDE_PROJECT_DIR` → `project_above(cwd)` → `project_above(script_dir, stop=HOME)`, then set `AI_BADGER_TRACKING_ROOT=<resolved>/.ai-badger/task-tracking` before opening the vendored store (the `tracker_lib.py:468` pattern); S6 pins full precedence against `tracker_lib.resolve_project_root` on a scratch worktree, not just collapse.

### F3 — **MUST** · Two known-red gates have no owning step (`docs/scripts.md`, `tooling/validate.py`) (§3 S2)
`tests/test_docs_match_the_catalog.py:192-203` globs `tooling/*.py` and requires every script name backticked in `docs/scripts.md`; S2 adds `tooling/task_plan_schema.py` and neither file is in any step's Files. `tooling/validate.py:817-825` runs `undecided_schemas()` — every `schemas/*.schema.json` must be in `SCHEMA_INSTANCES` or `SCHEMAS_WITHOUT_LOCAL_INSTANCES`; S2 adds `schemas/task-plan.schema.json` (validates no catalog file) and never touches `tooling/validate.py`. S8's gate (`validate.py --all`) then goes red at wave 2 with no step owning the repair; S2's own gate excludes both checks.
**Fix:** add `docs/scripts.md` and `tooling/validate.py` to S2's Files; S2 AC adds the scripts-doc row, the `SCHEMAS_WITHOUT_LOCAL_INSTANCES` entry with a reason, and `tooling/validate.py --all` to its gate.

### F4 — **MUST** · The re-vendor count is false in all three places it appears (§1 DR4, §3 S3)
`git ls-files | grep -c badger_store.py` = 38 (37 non-test), but that includes `engine/badger_store.py` and 12 `.ai-badger/**` copies, which the gate never checks: `_VENDORED_GLOBS = ("features/**/badger_store.py", "skills/**/badger_store.py")` (`engine/badger_store.py:319`) — 23 files today. DR4's "37 + test", S3's "37 + the new skill copy #38", and P1-A3's "12 + copy #13" are each wrong as written; a lane told to produce "copy #38" will edit a file outside the gate while the plugin mirror's copy (created later by S9's sync) is what makes 24→25.
**Fix:** DR4/S3 say "re-vendor every file matched by `_VENDORED_GLOBS` — 23 today plus the new skill copy; the `.ai-badger/**` copies are outside the gate and regenerate at S13; delete `#38`".

### F5 — **MUST** · The frozen tool names contradict the source S10 is told to apply verbatim (§1 DR5/DR8, §3 S10)
P3-C2/C1/C3 call the tools `plan_build`, `plan_progress`, `ac_record`; P3-C1's pipe ends at `plan_build`; DR8 itself says "`plan_state`/`progress_checklist` flag `integration_ok`" although `plan_state` is not one of DR5's 12. S10 says "P3-C2's rewrite map applied verbatim", and its pin test checks only `task-decomposition`/`task-plan`/`step`/`join step` — so a committed SKILL.md can instruct agents to call four tools the server does not expose, and every gate stays green.
**Fix:** add a normalisation row to §2 ("where a section says `plan_build`/`plan_progress`/`ac_record`/`plan_state`, read `plan_create`/`progress_checklist`/`ac_check`/(`progress_checklist` + `plan_get`), and `plan_id` does not exist"); extend S10's pin test to require the 12 frozen names and forbid the four stale ones; drop `plan_state` from DR8.

### F6 — **MUST** · The load-bearing CLI fallback has no launch contract (§1 DR3, §3 S7)
DR3 rules the CLI "load-bearing" because Claude/pi worktree sessions have no `.mcp.json`, but nothing states how it is invoked. The obvious reading — `python3 .ai-badger/skills/task-decomposition/scripts/task_graph_cli.py` — dies at import on any consumer without pydantic (`uv run --script` wraps only the server, per DR2/S7), which is precisely the failure class P1 measured. S7's AC(6) smokes only the server's `--check`.
**Fix:** §2 freezes `CLI launch: uv run --script <path>/task_graph_cli.py` (same PEP 723 header); S7 adds a CLI `--check` uv smoke to AC(6); S9's `mcp-plan-tools.md` names that exact command in the degraded path.

### F7 — **SHOULD** · The sealed-schema `$schema` requirement is unaccounted (§3 S2, DR6)
`tests/test_schema_self_description.py:79-88` fails every root-`additionalProperties:false` schema whose `properties` lacks `$schema`. Pydantic `extra="forbid"` emits exactly that root, and DR6's "field names exactly" omits `$schema` (P2-B2 mentions tolerance). S2's gate does not run this test.
**Fix:** DR6/§2 add `$schema` as an optional alias excluded from hashing; S2 AC adds `tests/test_schema_self_description.py` and requires the generated schema to declare `properties.$schema`.

### F8 — **SHOULD** · New tests/smokes can open and stamp the repo's real tracking DB to v3 (§3 S3/S6/S7/S13)
`tracking_db_path()` falls back to `_default_badger_root()` from `__file__` — `<repo>/.ai-badger/task-tracking/tracking.db` for any script in this tree. `tests/conftest.py` sets `CLAUDE_PROJECT_DIR` but never `AI_BADGER_TRACKING_ROOT` (grep empty), and `_real_tracking_state_is_untouched` fails only on suite-attributed `tracker_lib.save_json` writes. S3's two-process race test and S7/S13 subprocess smokes, if not env-pinned, can upgrade the live DB to v3 while this session's v2 machinery still runs.
**Fix:** S3/S6/S7/S13 state that every new test and subprocess smoke sets `AI_BADGER_TRACKING_ROOT` to `tmp_path`; add an AC asserting no new test path reaches `_default_badger_root()`.

### F9 — **SHOULD** · Risk R-D understates the v3 upgrade blast radius (§5)
`_ensure_schema_version` fail-closes for `stored > SCHEMA_VERSION` (`badger_store.py:458-463`). The machinery on that DB is the task lifecycle: `stop_hook.py:27` → `tracker_lib` (which sets the tracking root and opens the store at `:468`), `task_tracker.py`, `poll_limit.py`, `statusline_capture.py`. A consumer who updates the plugin but has not re-scaffolded can have the DB stamped v3 by any new client and lose statusline/Stop-hook/task commands until den-refresh — R-D's "changelog upgrade notes" is not a mitigation.
**Fix:** replace R-D with a named risk: "v3 tracking.db is unreadable by every pre-0.179 vendored copy"; mitigation — changelog Upgrade note "run den-refresh before the next task command", plus S13's ordering statement that no local step may open the repo's real root before re-scaffold.

### F10 — **SHOULD** · P2-B3's host-cwd HYPOTHESIS is missing from the risk register (§1 DR3, §3 S8/S13)
The declared command is project-relative (`uv run --script .ai-badger/...`); only Claude gets a `${CLAUDE_PROJECT_DIR}` override, and P2-B3 itself labels cwd=project-root a HYPOTHESIS with a named shim flip. S8's AC tests only a scaffold fixture, which never launches a host.
**Fix:** add R-F with P2-B3's flip (install shim, bare `task-graph` command, `availability.command`), and one manual host smoke in S13's ACs (Claude, pi, Copilot).

### F11 — **SHOULD** · Jev enable/disable polarity conflicts and the prompt pin has no stable oracle (§1 DR9, §3 S4)
DR9 says master `AI_BADGER_JEV=1` (opt-in) and P1-A5/R4 say off by default; P2-B4 says "only the literal `0` disables" (default-on kill switch). S4's AC(3) asserts flags-off means zero network, which only one reading satisfies. S4 AC(4) pins the prompts "byte-equal R4 §3–4", but P2-B4 adapts question names (`<id>_tier`) and state shape, and R4 is a `docs/work/` lane file rather than a test fixture.
**Fix:** §2 freezes polarity ("absent or not `1` = off; the master alone gates any network"); S4's pin targets a checked-in fixture of the runtime prompt payload, with R4 quoted in its provenance comment.

### F12 — **SHOULD** · S2's local gate needs pydantic in the repo venv, which nothing installs (§3 S2/S13)
`engine/requirements.txt` gains pydantic in S2, but the main checkout `.venv` has only jsonschema (verified), the local invariant runs Python through that venv, and S13's suite command is `python3 -m pytest -q` (system interpreter). Until someone installs it, S2's red test cannot even import.
**Fix:** S2's Do adds `<main>/.venv/bin/pip install 'pydantic>=2.12,<3'` before the first red test and `uv --version` as the S7 prerequisite; S13 uses the repo venv interpreter.

### NITs
- **N1** (§3 S6/S7, §2): the rendered plan path `.ai-badger/task-tracking/plans/` is created nowhere in the tree — state that the server `mkdir`s it on first render.
- **N2** (§3 S5): "`task_plan_model.py` (or `task_graph.py` sibling)" leaves a filename open across a wave boundary; freeze `task_plan_model.py` in §2.
- **N3** (§1 DR4): P2-B3's `FAMILIES["task_plan"]` silently loses to P1-A3's "born in SQLite, no Family entry"; say so in DR4 so no legacy-import path is wired for a family with no legacy source.

## Still open
- Whether the pi `decision-router-client.ts` source (`:133/:327/:391`) is reachable at implementation time — not present in this tree; only P2-B4's prose spec is an in-tree oracle for the port.
- Whether hosts actually spawn project stdio servers with cwd = project root (P2-B3 HYPOTHESIS); only a live Claude/pi/Copilot smoke settles it.
- Whether `uv run --script` resolves pydantic for the Python 3.10 floor on first consumer launch (not measured here; `uv` is present, pydantic 2.12 metadata was read by P2 only).
- Exact post-S9 copy count under `_VENDORED_GLOBS` depends on where `sync_plugin_skills.py` is run from; the fix in F4 is count-free on purpose.

**Verdict: PROCEED AFTER MUSTS** (F1–F6; F7–F12 degrade the build or the release if unaddressed).