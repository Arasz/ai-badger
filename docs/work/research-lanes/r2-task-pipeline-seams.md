# R2 — Seam inventory: task / quick-task / tracking pipeline vs a graph-backed `step`

**Workspace:** worktree `.../worktrees/aib-task-decomposition-workflow-graph-mcp`, branch `task/aib-task-decomposition-workflow-graph-mcp` (base `f40d8240`). Read-only; nothing written.
**Method:** `grep -rn -i -E '\b(sub-?packages?|packages?)\b' features/common/skills/ --include='*.md' --include='*.py' --include='*.json' --include='*.yaml' --include='*.yml' --include='*.mjs' --include='*.feature'` → **164 line-hits / 64 files** (verified by summing per-file `grep -c`). Mirrors compared per file with `diff -q`.
**Labels:** **[P]** planning unit · **[S]** software/dependency package · **[B]** bundle/package.json · **[A]** ambiguous · **[P\*]** planning vocabulary outside the named pipeline · HYPOTHESIS = inferred, unverified.
Paths below are under `features/common/skills/` unless prefixed.

---

## 1. Package / subpackage census

### 1a. [P] planning-unit hits — the sentences to rewrite

**task/SKILL.md (13 hits)**
- `:7` description: "plan packaging with mandatory integration package".
- `:58-59` "Integration step: always required in the high-effort variant. Every plan's last package is the integration package."
- `:67-68` "**plan** — Split work into **packages** (mergable units) and **subpackages**. Last package is the **integration package** with cross-package tests. Every package has ACs; plan AC: all checked+met."
- `:206` Phase 2 Exit: "plan split into packages and subpackages."
- `:212-216` "**Split the plan into packages.** Each package is a unit of work delivering a mergable piece. Subpackages are partial units within a package. Every package contains its test scenarios. The **last package is always the integration package** — it ensures all packages are correctly integrated and includes cross-package integration tests. Each package has its own acceptance criteria; the plan's top-level acceptance criterion is: *all packages' ACs are checked and met*."
- `:257` "Commit and push per work package (small commits)."
- `:364` checklist: "Every plan point's acceptance gate ran; plan was split into packages with the last being integration".

**task references/extensions**
- `task/references/tracking-visibility.md:26` "one `**P<N> …**` heading per package, one `- [ ]` checkbox per acceptance point".
- `task/extensions/github/extension.md:38` "Commit and push as each work package lands".
- `task/extensions/claude/extension.md:49` "arbitration when two work packages disagree about a contract".

**status-report**
- `status-report/SKILL.md:56` "**Progress checklist** (plan packages and checkbox counts)"; `:81` source row "`task-tracking/plans/*.md` — package headings + `- [x]` counts".
- `status-report/scripts/status_report.py:166` "package headings + checkbox counts"; `:169,173` `"packages": []`; `:175` extraction list; `:179` return key; `:307` empty-progress default; `:347-348` `[package]` render line.

**complete-project-scope-code-review/SKILL.md (15 hits, all package-as-work-unit)**
- `:43` "Running one work package end to end"; `:127` "A refuted number that reached a plan costs a work package."; `:149-150` "Package findings by **surface** … Every package carries acceptance criteria **and a gate that has been watched go red**."; `:160-166` serialisation/measurement/two-packages rules; `:181-182` "Each package runs through `task` … packages inside a wave run concurrently"; `:274` "routed to the package"; `:302-303` checklist rows.
- `complete-project-scope-code-review/extensions/claude/extension.md:19` "already-decided work package"; `extensions/github/extension.md:10-11` "each work package merged into it from its own lane branch … one PR per package".
- `[A]` `extensions/dotnet/extension.md:79` section heading "the deletion package" (reads as a work package of deletions).

**Others**
- `multi-agent-communication/SKILL.md:40` "Broadcast at package boundaries, not per commit".
- `worktree-agent-isolation/references/shared-worktree-collisions.md:3` "parallel packages can still land in the SAME worktree".
- `[A]` `worktree-agent-isolation/SKILL.md:228` "the first full-suite run after a package lands" (means a change/work package lands).
- `design-gate-audit/SKILL.md:21,25,45` "work-package plan", "TDD order per work package"; `references/http-serve-gate-audit-2026-08-06.md:5` "4 work packages (WP1 → WP4)".
- `review-tests/references/plan-format.md:35` "Each row becomes one work package, a short section directly under the table"; `review-tests/SKILL.md:217` "`### WPn` work-package block"; `:241` "else's work package".
- `scripts-tooling-refactor/SKILL.md:100` "For work packages that must be behavior byte-identical"; `references/behavior-pinning-derivation.md:9` "A work package requires behavior byte-identical".
- **[P\*] different pipeline, same word:** `ai-raccoon-memory/scripts/query_pipeline.py:30-31,47,67,70,82,87,90` — the embedded delegator contract: "each package's acceptance criterion", "arbitration between packages", "Independent packages share one tool block", "the package is not delegable yet", "one row per dispatch: package, persona". A dispatch-decomposition unit, not the task plan; decide explicitly whether it renames.

### 1b. Adjacent planning vocabulary (outside `features/common/skills/**`, still loaded by the pipeline)
- `features/common/personas/delegator.md:4,24-25,41,61,64,76,81,84` — "multi-package sessions", "each package's acceptance criterion", "every package had a named lane"; deployed mirror `.ai-badger/agents/delegator.md:23,76` etc.
- `features/common/invariants/small-commits-early-draft-pr.md:3` — "Commit one coherent work package at a time"; task Phase 3 inherits this non-negotiable.

### 1c. [S]/[B] non-planning hits — must NOT change
- **archify:** `SKILL.md:135` [B skill bundle]; `bin/archify.mjs:429` [B install bundle]; `renderers/shared/generated-brand-marks.mjs:1674` [S upstream repo path]; `vendor.json:8,41` [B tag/`package.json` hash]; `VENDOR.md:35,77` [B].
- **artifact-verification:** `SKILL.md:3,38,42,51,54` [S published dotnet tool]; `references/install-verification-protocol-review.md:39-43,67,75` [S package cache/contents].
- **code-review-evidence:** `SKILL.md:227,235,275`; `references/dotnet-sdk-exception-probes.md:6,20,27,63-66`; `hermes-memory-provider-review.md:45,66`; `sqlite-memory-semantics.md:104`; `wrapped-code-evidence.md:36,44` — all [S] NuGet/Python packages/site-packages.
- **commit-reminder/scripts/impact_estimator.py:39** [S installed package].
- **documentation-drift-audit:** `references/ai-badger-drift-audit-map.md:9` [B "scaffold package"]; `ai-badger-mcp-scaffold-declaration.md:53` [S dotnet tool]; `compaction-rewrite-passes.md:8,15,47` [S `Directory.Packages.props`/tool package]; `readme-compaction-recipe.md:15` [S].
- **explore-codebase/SKILL.md:38** [S `package.json`].
- **pre-push-gate-debugging/SKILL.md:87,111** [S site-packages/churned build dirs].
- **review-tests refs:** `governance.md:37`; `kind-architecture.md:43`; `stack-dotnet.md:20`; `stack-node.md:12`; `stack-ts-react-browser.md:25,200,339`; `universal.md:235` — all [S] package managers/libraries.
- **scripts-tooling-refactor:** `SKILL.md:51,78,135,140` [B `verify-tool-package`, namespace-package]; `behavior-pinning-derivation.md:92` [S]; `pytest-config-and-sync-contract.md:24,26,38` [B/S packages-of-tests]; `shell-to-python-port-checklist.md:1,21,42` [B].
- **spec-driven-refactoring/references/feature-design-spec-patterns.md:100** [S infrastructure packages].
- **test-economy:** `SKILL.md:93` [S Go package path]; `scripts/suite_economy.py:474` [S `package.json`].
- **welcome-ai-badger/scripts:** `dependency_check.py:6,63,68,94,99,122,193,199,267,273,276,318`; `detect.py:160-172,209,226,236,244,249,255,257,265,352,354`; `mcp_tools.py:28`; `scaffold.py:536` — all [S] Python/Node/MCP package install and scan.
- **worktree-agent-isolation/scripts/verify_hooks.py:86** [S `~/.nuget/packages`]; `references/shared-worktree-collisions.md:30,48` [S package versions/native package pins] (mixed file).
- **ai-raccoon-memory/scripts/memory_context_hook.py:36** [S "loaded by path, never by package name"].
- **complete-project-scope/extensions/dotnet/extension.md:19** [S project/package references] (mixed file).

### 1d. `.ai-badger/skills/**` mirrors
- Byte-identical for the focus files: `task/SKILL.md`, `task/references/file-schemas.md`, `task/references/tracking-visibility.md`, `task/scripts/task_tracker.py`, `tracker_lib.py`, `quick-task/SKILL.md`, `status-report/SKILL.md`, `status-report/scripts/status_report.py`, `create-task-spec/SKILL.md`, `design-tests/SKILL.md`, `worktree-agent-isolation/SKILL.md`, `multi-agent-communication/SKILL.md`. So every line number above applies to both trees; rewrite `features/common/**` and re-scaffold.
- **Divergence:** `.ai-badger/skills/complete-project-scope-code-review/SKILL.md` is a different revision — its package lines are `:43,126,148-149,159-165,180-181,275,335-336,402,430-431`; a lane editing only features leaves this deployed copy stale (same word, shifted lines).
- `.ai-badger/skills/task/scripts/` additionally holds `claude_session_source.py`, `hermes_session_source.py`, `pi_session_source.py` (platform deployment, unrelated to packages). `design-tests` mirror differs only by absent `extensions/`; `worktree-agent-isolation` only by `__pycache__`.

---

## 2. Task STATE contract a graph store must coexist with

### Verbs + exit codes (`task_tracker.py`)
Docstring declares the interface: `:4-23` (0 ok, 2 bad input, 3 finish blocked; verbs start/finish/grade/subagent/reattach/drop/status/install-cron/uninstall-cron).
- `start` `:254` → 2 bad id `:262`; no session `_session_or_die` `sys.exit(2)` `:221-251`; unregistered source `:271`; session already attached to an open task `:286`; already FINISHED `:296`. Worktree git failure prints stderr but still **exit 0** `:318-325`.
- `finish` `:368` → 2 unknown `:374`, 2 no source `:393`, **3** `state.json` mtime not newer than `startedAt` `:375-383` (`--force` bypasses). FINISHED written `:398`; worktree kept-but-not-failed `:430-455`.
- `grade` `:467` → 2 range `:470`, unknown `:476`. `subagent` `:484` → 2 both/neither token modes `:490`, unknown `:496`, no source `:510`, no delegation token record `:520`. `reattach` `:542` → 2 conflict `:556`, unknown `:560`, source `:571`. `drop` `:580` → 2 unknown `:589`, may-hold-real-work `:599`. `status` `:614` always 0. Cron install/uninstall return 1 `:731,773,776,787,798,801`. Unknown verb → 2 `:882`.

### States + transitions
- Constants `tracker_lib.py:239-241` (`STARTED`, `IN_PROGRESS`, `FINISHED`).
- DDL default `STARTED` `engine/badger_store.py:146-165`; partial unique index `WHERE state <> 'FINISHED'` `:168-170`.
- `start`/prompt-hook → STARTED (`task_tracker.py:306`, `user_prompt_hook.py:92-94`); first Stop checkpoint → IN_PROGRESS (`stop_hook.py:107,121-128`); `reattach`/cron-resume → IN_PROGRESS (`task_tracker.py:573-574`, `resume_cron.py:178`); `finish` → FINISHED (`task_tracker.py:398`). FINISHED is terminal: restart refused `:291-296`. Authoritative prose: `task/references/file-schemas.md:78-80`.
- `status-report` treats STARTED as open (`status_report.py:56,103-105`) — a graph store that drops STARTED rows will regress "no task in progress".

### Store surface
- One write lock: `tracker_lib.tracking_transaction()` `:479-505` (migrate families, `BEGIN IMMEDIATE`, commit); `load_tasks`/`save_tasks` `:518-556` upsert per `taskId`, never `INSERT OR REPLACE`; `load_usage`/`save_usage` `:559-576`.
- Tables: `tasks` `engine/badger_store.py:146-172`, `token_usage` `:175-185`, `sessions` `:187-193`; accessors `tasks_all:1095`, `usage_all:1120`, `sessions_map:1139`, `task_upsert:1168`, `usage_upsert:1198`, `session_upsert:1224`; column maps `:658-672`.
- Invariants: nothing outside the store module touches tables (`file-schemas.md:28-29`); newer `schema_version` fails closed (`file-schemas.md:25-28`, `engine/badger_store.py:430-476`); `engine/badger_store.py` is **vendored byte-identical** into each skill's `scripts/` (`file-schemas.md:3-4`; `tests/test_badger_store_vendored.py:1-10`) — a graph table belongs in the Family/DDL/`UPGRADE_HOOKS` path plus re-vendoring, not a side file.
- Concurrent writers a graph tool must not break: `stop_hook.py:98-146` (checkpoint + enforcement), `user_prompt_hook.py:73-109`, `session_start_hook.py:78`, `poll_limit.py:186`, `resume_cron.py:150-183`, `dispatch_ledger.py` (`dispatch_lanes` user table).

### Other readers of `status-notes.json` / `state.json`
- **`status-notes.json`: no code reads it anywhere.** Grep over `features/`, `engine/`, `skills/` yields only `task/references/file-schemas.md:179,196,209-210,214,245`. It is hand-edited tracked content, keyed by task id, shape `{notes, gapsRequiringDecision}` (`:214-219`), with `hasNotes` mirrored into `state.json` lean entries (`:209-210`).
- **`state.json`:** `tracker_lib.py:1023-1028` reads only its **mtime** (finish gate); `status_report.py:284-288` reads `next`; task Phase 0/5 and auto-continue read/write it (`task/SKILL.md:164-167,313,329`); `documentation-drift-audit/references/post-merge-tracking-conflict-recipe.md:36-38` merges `completedTasks`/`next`; initial shape `features/common/templates/state.json`. Full schema `file-schemas.md:185-211`.
- **Legacy JSON** (`executed-tasks.json`, `token-usage.json`, `current-session.json`) remain dual-read surfaces until migrated (`file-schemas.md:43,256-266`; `status_report.py:82-95,195-211,219-227`).

---

## 3. `status-report` progress checklist — the exact MCP seam

- Skill: run the script once (`status-report/SKILL.md:46`), answer four sections (`:48-57`); source table `:81` says progress = plan files' package headings + checkbox counts. "Never delegate, never wait" contract `:26-33`; exit-0/placeholder contract `:48-53`.
- Script chain: `PACKAGE_RE = ^\*\*(P\d+[^*]*)\*\*` `status_report.py:43`; plan filename match `_match`/`_plan_for` `:118-163`; `plan_checklist()` returns `{plan_file, matched, packages, checked, total}` `:165-179`; `report()` embeds it at `:306-308` (empty default `:305-308` is the literal seam to replace); `render()` prints `[package]` lines and `checklist: x/y` `:345-352`, then a hardcoded loop-step line `:353-355`.
- **Replace target:** `report()["progress"]` at `:306-308` + the PROGRESS CHECKLIST block at `:338-352`. The `packages`/`checked`/`total` keys and the `[package]` prefix are pinned by `tests/test_status_report.py:153,169` (444-line suite); the loop line `:353-355` is a second step-ordering display.
- Constraints: stdlib-only, ships where `badger_lib` doesn't exist (`status_report.py:12-16`); HYPOTHESIS — an MCP checklist tool cannot be called by this script itself, so the caller (skill/model) must call MCP and the script's fallback behavior when the server is absent is an open contract decision.

---

## 4. `create-task-spec` manifest + where a `task-plan` slots in

- **Emitted pair** (`create-task-spec/SKILL.md:111-120`): `<Name>.feature` = user story header, `Rule` blocks, scenarios with steps, deferred items step-less with `@deferred` (`:115-117`); `spec.json` = "scope and explicit out-of-scope, non-functional requirements, target paths and constraints, gate verdicts with their provenance, deferred decisions with their chosen fallbacks, and the spec file's path" (`:118-120`). Gate: `spec_holes.py` exits non-zero while a hole is open (`:123-130`); optional render takes `--manifest` and prints it generically (`render_spec.py:264`, `_render_manifest` `:220-231`).
- **Task consumption today** (`task/SKILL.md:176-180`): a `spec.json` path ⇒ read manifest + companion `.feature`; manifest supplies scope/out-of-scope/constraints/deferred, spec supplies acceptance criteria; both feed the Phase 2 planning agent; non-deferred scenarios are Phase 4's pass condition. Handoff stated at `create-task-spec/SKILL.md:139-141`.
- **Slot for `task-plan`:** the same Phase 1 injection point (`task/SKILL.md:176-180`) that currently accepts `spec.json`, plus the Phase 2 decomposition at `:210-216` that currently emits packages. `review-tests/references/plan-format.md:33-38` records the deliberate rule that `spec.json` exists because `task` consumes it and no plan manifest was invented — a `task-plan` artifact is exactly that missing consumer-facing manifest.

---

## 5. Sentence inventory for the rewrite lane

**`task/SKILL.md`** (package/plan-point/step-ordering sentences, by line): `7`, `41-47` (loop spine ordering low/high), `58-59`, `67-68`, `142-144` (parallelise vs serialise sections), `206`, `212-216`, `223-224` ("Split the plan into sections that can be worked independently…"), `226-231` (every point carries AC+gate; `design-tests`; archify), `239-240` ("sections sharing a file serialise, the rest parallelise"), `257`, `262` ("all plan points implemented"), `286`, `313` (`completedTasks` protocol), `364`.
Plus: `task/references/tracking-visibility.md:24-30` (plan filename + `**P<N>**` heading per package + checkbox per acceptance point); `task/extensions/github/extension.md:38`; `task/extensions/claude/extension.md:49`. `task/references/lane-dispatch-brief.md` contains **no** package vocabulary — its `Task`/`Acceptance criteria`/`Files you own`/`Sub-agents` slots (template `:20-55`) are the fields a `step`'s goal/instructions/AC would populate.

**`quick-task/SKILL.md`:** zero occurrences of package/subpackage/integration package/plan point. Planning sentences that a "consume decomposition" change touches: `:6` (frontmatter "a minimal plan"), `:23-25` ("planned in minutes… no plan document"), `:54-56` ("**Minimal plan.** Three to six bullets… No plan file, no ledger record, no tracking artifacts. If the plan needs more than six bullets, escalate."), `:84-85` ("re-read the diff against the plan bullets"), `:157` ("Plan was three to six bullets; no tracking artifacts created"). The Flow's numbered steps `:46-122` are its own procedure, not decomposition ordering; the only "dependency" mention (`:43`) is a software bump.

---

## 6. Seam → files → what changes → risk if missed

| Seam | File(s):line | What changes | Risk if missed |
|---|---|---|---|
| Package decomposition vocabulary | `task/SKILL.md:7,58-59,67-68,206,212-216,257,364`; refs/extensions above | Rewrite to graph `step`s; plan AC = all steps' AC | Planning agents and lane briefs keep emitting packages; graph has no source of nodes |
| Plan file format + naming | `task/references/tracking-visibility.md:24-30`; `status_report.py:43,118-179` | Replace `**P<N>**` headings/checkboxes with graph state (or dual-format) | Status silently reads "(no plan file)" or another task's plan |
| Status progress + render | `status_report.py:165-179,295-315,338-355`; `SKILL.md:46,55-57,81`; `tests/test_status_report.py:153,169` | Progress from MCP checklist tool; keep exit-0/placeholders/`--json` | Suite red; status stalls when MCP down; four-section contract broken |
| Task state store | `tracker_lib.py:479-556`; `engine/badger_store.py:146-193,430-476,1095-1224`; `file-schemas.md:25-29,43` | Add graph table/rows via Family+DDL+upgrade, re-vendor store copies | Schema fail-closed on old clients; vendored-copy test red; direct table writes violate access surface |
| Transitions/verbs | `task_tracker.py:221-614`; `tracker_lib.py:239-241`; `stop_hook.py:107,121-128`; `resume_cron.py:178` | MCP `mark complete`/transitions alongside task states; never bypass attach-conflict/FINISHED-terminal | Double session attach; tasks stuck STARTED; finish gate (exit 3) not honored |
| Spec → plan handoff | `create-task-spec/SKILL.md:111-120,139-141`; `task/SKILL.md:176-180,210-216` | `task-plan` emitted from analyze/research, consumed at the same Phase 1 injection; spec stays requirements | Planning agent fed neither or both; non-deferred scenarios lose AC linkage |
| Review rows → packages | `review-tests/references/plan-format.md:33-38`; `review-tests/SKILL.md:217,241` | WPn blocks become steps with gates | `/task` handoff loses per-row gate/proof |
| Whole-project review waves | `complete-project-scope-code-review/SKILL.md:149-182,302-303` + extensions; stale mirror | Packages → steps; waves order steps | Review still requests package-shaped plans; mirror stale |
| Peripheral package vocab | `design-gate-audit/SKILL.md:21,25,45`; `scripts-tooling-refactor/SKILL.md:100`; `design-tests/SKILL.md:66` [S] | Design-gate/refactor "work package" wording; leave repo-package senses | Conflicting vocabulary across skills |
| Quick-task path | `quick-task/SKILL.md:54-56,84-85,157` | Decide consumption of decomposition; reconcile "no tracking artifacts" | Escalation boundary undefined; graph state and quick-task's no-artifact rule clash |
| Delegator/dispatch vocab | `ai-raccoon-memory/scripts/query_pipeline.py:30-90`; `personas/delegator.md:24-84` | Rename to `step` or explicitly exempt | Two vocabularies in every brief; lane ledger stays "package" |
| Bus announcements | `multi-agent-communication/SKILL.md:40` | "package boundaries" → step/join boundaries | Broadcasts fire per step or never |
| MCP server packaging | `features/common/mcp/<name>/{meta.json,tools.json,server.md}` (pattern: `features/common/mcp/ai-raccoon/meta.json`); `welcome-ai-badger/scripts/mcp_tools.py:291,708-709`; `mcp-index/SKILL.md:6,31` | New stdio server declared in config `mcp` + `.mcp.json` + `.ai-badger/mcp-tools.json` | Server not scaffolded or recommended; tools invisible |
| Knowledge log untouched | `file-schemas.md:185-251`; `status_report.py:284-288`; `task/SKILL.md:313,329` | Keep graph state out of `state.json`/`status-notes.json` | Mid-task rewriting of always-loaded context (cache invalidation) + drift-audit merge breakage |
| Hooks/tests/gates | `stop_hook.py`, `user_prompt_hook.py`, `session_start_hook.py`; `tests/test_status_report.py`, `test_badger_store_vendored.py`, `test_task_tracker.py`; `tooling/index_build.py --check` | Update pins with the change | CI red on shape pins; new skill missing from index |

**Open decision this map surfaces (not designed here):** whether graph state lives inside `tracking.db` (coexistence via store discipline) or beside it; every seam above resolves differently on that choice, and the `status-report` stdlib-only contract (`status_report.py:12-16`) is the binding constraint on how an MCP checklist reaches it.