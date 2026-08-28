# aib-pi-review-fixes — MoE plan lane: Python adjustments + catalog/docs fixes

> **Lane doc (rev-1 MoE snapshot).** Where this document and the combined master plan disagree, the master plan wins. Findings referenced as F# come from the review report (`/tmp/aib-pi-review-findings.md`); this lane owns F1 (python half), F3 (python half), F4, F8, F9, F10, plus the F3/F7 doc halves in the pi task extension.

Task branch: `task/aib-pi-review-fixes` @ 9d2d0ce0. All paths relative to the task worktree.

## 1. Verified facts (all measured first-hand this session against the worktree and installed pi 0.84.3)

| # | Fact | Grade | Source |
|---|------|-------|--------|
| V1 | `adjust_hooks.py:45-46` returns `[]` silently when `adapter/` is missing; with hook scripts copied, `adjust()` then returns `applied: True` with no mention of the adapter | measured | worktree `features/pi/adjustments/adjust_hooks.py`; `run_adjustments()` in `skills/welcome-ai-badger/scripts/scaffold.py:649-667` appends notes either way |
| V2 | `--resume, -r` in pi 0.84.3 takes **no argument** ("Select a session to resume", interactive); `--session <path\|id>` takes a session file or partial UUID; `--session-id <id>` takes an exact project session ID; `--continue, -c` continues the previous session | measured | `pi --help` on installed pi 0.84.3 |
| V3 | `pi_session_source.py:30` returns `pi -p --resume {session_id}`; no test asserts the resume string shape (existing tests only check name/env var) | measured | worktree file + `tests/test_pi_adjustments.py` |
| V4 | pi discovers skills from `~/.pi/agent/skills/`, `~/.agents/skills/` (global), `.pi/skills/` and `.agents/skills/` (project, only after project trust), package `skills/` dirs, a settings `skills` array, and `--skill <path>`. It does **not** read project `.claude/skills/` or `~/.claude/skills/` by default — the docs tell you to add those dirs to settings explicitly | measured | installed pi `docs/skills.md` "Locations" + "Using Skills from Other Harnesses" |
| V5 | No pi skill wiring exists: `features/pi/adjustments/adjustment.json` declares hooks/mcp/task/cron only; `features/pi/skills.json` is `{"skills": []}`; nothing writes or prints a `.pi/settings.json` skills entry; claude's `adjust_skills.py` only runs when `claude` is in `config.agents` | measured | worktree files; `run_adjustments()` iterates `config.agents` only |
| V6 | `support.json:258` (`pi.skills.scaffoldedBy`) cites `pi/adjustments/adjust_skills.py`, which does not exist. The only other `adjust_skills` citations are claude/copilot (real files) and historical changelogs | measured | repo-wide search |
| V7 | Schema semantics: `supported` = agent has the capability; `aiBadgerSupport` = "whether ai-badger scaffolds anything for it"; `scaffoldedBy` = "script and function that scaffolds it". Precedent for "operator merges, ai-badger prints": hermes `mcpServers` row says `aiBadgerSupport: false` + "nothing is scaffolded: … prints the snippet for the operator to merge" | measured | `schemas/support.schema.json:76-108`; `features/common/support.json:121-125` |
| V8 | `adjust_mcp.py:46` uses `command.split()`; commands with spaces/quotes break | measured | worktree file |
| V9 | `adjust_hooks._framework_version` (pi copy) and `adjust_mcp._yaml_block` (pi copy) have zero callers anywhere (the identically-named helpers in `tooling/index_build.py` and `features/hermes/adjustments/*` are separate live functions) | measured | repo-wide search |
| V10 | Named-event count in pi's `docs/extensions.md` is not stable: my regex over `pi.on("…")` yields 35 distinct strings, two of which are callback-argument names, not events (→ 33); support.json says 34; the reviewer counted 36. All six adapter events (`input`, `tool_call`, `tool_result`, `session_start`, `session_shutdown`, `agent_settled`) do exist | measured | installed pi `docs/extensions.md` |
| V11 | `run_adjustments()` (scaffold) catches a raised exception per adjustment and appends `adjustment '<name>' for '<agent>' failed: <exc>`; `applied: True` results get notes + manifest records, `applied: False` results get a `not applied — <notes>` note | measured | `scaffold.py:649-667` |
| V12 | `tooling/validate.py` only schema-validates `support.json` — a false prose citation passes every automated gate today | measured | `tooling/validate.py:51-55` |

Orchestrator-provided facts re-verified: F1 line numbers, F3 flag semantics, F4 missing file, F8 line, F9 dead code, F10 count dispute — all confirmed (V1–V10).

## 2. Decisions

| # | Decision | Provenance |
|---|----------|------------|
| D1 | **Fail loud via an explicit error note, keeping partial-success semantics.** When `install=True` and the adapter dir is missing or yields no `.ts`/`.json` files, `adjust_hooks.adjust()` appends a note beginning `ERROR:` that names the expected dir; `applied` stays `bool(files or installed)` so genuinely copied hook scripts are still recorded in the manifest. Under `install=False` the no-op stays silent (documented user-global-state rule). Rationale: the review demands "fail loudly (return an error note)"; raising would lose the hook-copy results (scaffold catches exceptions before recording), and `applied: False` would leave copied files unrecorded — manifest drift. | F1, V1, V11 |
| D2 | **Resume command becomes `pi -p --session {session_id}`.** `--session <path|id>` is the lenient documented form (accepts partial UUID). `--session-id` rejected: it demands an exact project session ID and creates one when missing — wrong semantics for "resume this recorded session". `--resume` rejected: interactive selector, takes no argument (V2). No shell-quoting added: session ids are UUID-shaped; keeping the f-string matches the claude/hermes sources' shape. | F3, V2 |
| D3 | **`adjust_mcp` uses `shlex.split(command)`.** No fallback for malformed quoting: `shlex.split` raises `ValueError` on unbalanced quotes, which `run_adjustments()` catches and reports per adjustment ("adjustment 'mcp' for 'pi' failed: …") — loud, zero extra code, and a malformed command line is a config-authoring error the user must fix, not something to paper over. | F8, V8, V11 |
| D4 | **Delete the two dead helpers.** `adjust_hooks._framework_version` and `adjust_mcp._yaml_block`, pi copies only. No test updates needed (nothing references them). `List` import in `adjust_mcp.py` stays (still used by `sections: List[str]`). | F9, V9 |
| D5 | **Correct the `pi.skills` row instead of building `pi/adjust_skills.py`.** The truth (V4, V5): the scaffold delivers skills to `.ai-badger/skills/` and pi reads nothing automatically; the operator must list that directory in pi settings' `skills` array. That is the exact hermes-`mcpServers` shape, so: `scaffoldedBy` = "nothing is scaffolded for pi discovery: scaffold.py delivers skills to .ai-badger/skills/; pi reads them only when the operator lists that path under pi settings 'skills' (pi docs/skills.md, Locations)"; `mechanism` corrected to name pi's real discovery paths instead of "from .claude/skills/"; `aiBadgerSupport` flipped to **false** per the schema's own wording ("scaffolds anything for it") and the hermes precedent. Building a real `adjust_skills.py` (e.g. writing the settings entry) is new scope — deferred, see open questions. | F4, V4–V7, ask-if-simpler |
| D6 | **Drop the unverifiable claims from the `pi.hooks.mechanism` string** — both the count and "superset of Claude" — and name the six events the adapter actually translates, pointing at pi's `docs/extensions.md` for the full list. Proposed text: "Extension events: input, tool_call, tool_result, session_start, session_shutdown, agent_settled, plus more events documented in pi's docs/extensions.md". Three independent measurements produced three different counts (V10); no number can be pinned without a counting convention that would itself drift. | F10, V10 |
| D7 | **Doc fixes edit the source file only** — `features/common/skills/task/extensions/pi/extension.md`. The copy under `skills/task/extensions/pi/` is regenerated by the integration package; it is not edited (same rule as the shipped plugin copies). Line 21's second clause "or `pi -p` (most recent)" is also wrong (plain `-p` starts a fresh print-mode session; `--continue, -c` continues the most recent session) and is fixed in the same sentence. | F3-doc, V2, task brief |
| D8 | **The hook-translation table (extension.md:31-44) stays; truthfulness is checked, not rewritten.** All six event names exist in pi 0.84.3 (V10). The table describes the adapter mechanism the TS lane ships; this lane only re-reads the section after the TS lane's design lands and fixes any drift in the prose around it (install path, scope). No TS code planned here. | F7-doc, task brief |
| D9 | **Package/commit split follows files, not findings:** WP1 (adjust_hooks.py), WP2 (adjust_mcp.py), WP3 (pi_session_source.py), WP4 (support.json), WP5 (extension.md) — one coherent commit each, small-commits-early-draft-PR. | repo invariant |

## 3. Work packages

Order: WP1–WP3 are independent Python fixes (any order); WP4/WP5 are file-only edits and can land any time. The suite is `tests/test_pi_adjustments.py` (14 tests today, all `install: False`) run via `.venv/bin/python3 -m pytest tests/test_pi_adjustments.py -q` from the main checkout's venv per the venv invariant. TDD: the named failing test lands **before** its production edit, and each RED run is witnessed (run it, watch it fail for the stated reason, then fix).

### WP1 — adjust_hooks: fail loud on missing adapter + dead-code removal (F1-py, F9a)

Owner files: `features/pi/adjustments/adjust_hooks.py`; test wired by test lane in `tests/test_pi_adjustments.py`.

Steps:
1. RED: add `test_adjust_hooks_missing_adapter_fails_loud` — build a context with `feature_dir=tmp_path` (no `adapter/` inside, mirroring `test_adjust_cron_with_pi_no_cron_dir`), `install=True`, real `framework_root`; assert `result["applied"]` is True (hook scripts still copied) **and** `"ERROR:" in result["notes"]` **and** the note names the adapter dir. Witness it fail: current code returns `[]` silently, so the `ERROR:` assertion goes red for exactly the finding-1 defect.
2. GREEN: in `_install_user_extension`, when `install=True` and (`not adapter_dir.is_dir()` or the copy loop yields nothing), return a sentinel the caller turns into an `ERROR:` note naming `adapter_dir`; `adjust()` composes notes as: error (if any) + hook-count note (if files) + adapter-install note (if installed); `applied = bool(files or installed)`. Keep the `install=False` early return and its docstring ("no-op under --no-install") unchanged.
3. Delete `_framework_version` (lines 30-34). `Path` import stays (used by `ADAPTER_DIR` typing/`USER_EXTENSIONS_DIR`).
4. Suite green; no other test changes.

Test-design rows for the test lane:

| Test | Failure mode it targets | Mutation that proves it real |
|------|--------------------------|------------------------------|
| `test_adjust_hooks_missing_adapter_fails_loud` | silent `applied: True` with no adapter (finding 1) | remove the `ERROR:` note branch → red |
| `test_adjust_hooks_installs_adapter_files` (happy path; fixture-based) | copy loop regressions (wrong suffix filter, wrong dest) | give a fake `feature_dir` an `adapter/` with dummy `adapter.ts` + `package.json`, monkeypatch the module's `USER_EXTENSIONS_DIR` to a tmp path, assert both files land and the install note lists them; break the suffix filter → red. Independent of the TS lane — no real adapter needed |
| `test_adjust_hooks_installs_real_adapter` (integration; after TS lane delivers `features/pi/adjustments/adapter/`) | the shipped adapter files themselves missing/empty | run against the real `feature_dir` and assert the real filenames land; delete the dir → red. Blocks on TS lane delivery |

Sequencing note: tests 1–2 can land immediately; test 3 must wait for the TS lane's `features/pi/adjustments/adapter/` (adapter.ts + package.json). Until then the missing-adapter test is the standing guard that keeps the failure loud.

Proof of done: `test_adjust_hooks_missing_adapter_fails_loud` witnessed RED then GREEN; suite 14+N green via `.venv/bin/python3 -m pytest tests/test_pi_adjustments.py -q`.

### WP2 — adjust_mcp: shlex.split + dead-code removal (F8, F9b)

Owner files: `features/pi/adjustments/adjust_mcp.py`; test wired by test lane in `tests/test_pi_adjustments.py`.

Steps:
1. RED: add `test_adjust_mcp_quoted_command_survives` — declarations `{"fs": {"command": "node \"/path with space/server.js\" --port 3000"}}`; assert the JSON in `result["notes"]` parses and `entry["command"] == ["node", "/path with space/server.js", "--port", "3000"]`. Witness it fail: `str.split()` yields `['node', '"/path', 'with', ...]`.
2. GREEN: `parts = shlex.split(command)` (add `import shlex`). Malformed quoting raises `ValueError`, which the scaffold reports per adjustment (D3) — no try/except here.
3. Optional test (name for the test lane): `test_adjust_mcp_unbalanced_quote_raises` — `command='npx -y "pkg'` raises `ValueError`; pins the no-fallback decision.
4. Delete `_yaml_block` (lines 64-66). Keep `List` import.
5. Suite green.

Proof of done: quoted-command test witnessed RED then GREEN; suite green.

### WP3 — pi_session_source: correct resume command (F3-py)

Owner files: `features/pi/adjustments/pi_session_source.py`; test wired by test lane in `tests/test_pi_adjustments.py`.

Steps:
1. RED: add `test_pi_session_source_resume_command` — register with the existing `FakeTrackerLib` pattern; capture `resume`; assert `resume("s-123") == "pi -p --session s-123"` and `"--resume" not in resume("s-123")`. Witness it fail (current: `pi -p --resume s-123`).
2. GREEN: `resume=lambda session_id: f"pi -p --session {session_id}"` (D2).
3. Suite green.

Proof of done: resume test witnessed RED then GREEN; suite green.

### WP4 — support.json catalog corrections (F4, F10)

Owner file: `features/common/support.json` (pi agent block only: `skills` row and `hooks.mechanism`).

Steps:
1. `skills` row: replace `scaffoldedBy` and correct `mechanism`'s location claim per D5 (exact proposed text in D5; final wording at edit time must keep every claim traceable to pi `docs/skills.md`). Flip `aiBadgerSupport` to `false` per the schema wording and hermes precedent — owner-visible boolean flip, called out in the PR description.
2. `hooks.mechanism`: apply D6 text (drop count + "superset of Claude", keep the six adapter events, reference pi docs/extensions.md).
3. No other rows touched (scoped-instruction rows etc. are not in this lane's findings).
4. Gates: `.venv/bin/python3 -m pytest tests/ -q` subset that touches support schema (validate/schema tests) + `python3 tooling/index_build.py --check` (the repo `build` gate) — support.json edits must not drift the index.

Proof of done: every claim in the two edited strings maps to V4/V7/V10 sources; schema validation passes; build check passes.

### WP5 — pi task-extension doc fixes (F3-doc, F7-doc, D8 check)

Owner file: `features/common/skills/task/extensions/pi/extension.md` (source only — the `skills/task/extensions/pi/` copy is regenerated; do not edit it).

Steps:
1. Line 11 (F7-doc): drop "built-in". Reword so the example subagent extension's status and install step are stated (it requires manual installation per `examples/extensions/subagent/README.md` in the pi repo), e.g. "pi ships no built-in subagent extension; the example one (`examples/extensions/subagent/` in the pi repo) needs manual installation — or spawn directly:" (keep the existing line-17 reference consistent, avoid duplication).
2. Line 21 (F3-doc): "Resume work: `pi -p --session <session_id>`; continue the most recent session: `pi -c`" (V2). Remove the false "or `pi -p` (most recent)" claim (D7).
3. Lines 31-44 (D8): after the TS lane's adapter design lands, re-read the hook section and fix drift in the prose only (install path/scope must match what `adjust_hooks` actually does). The event table itself is verified correct against pi 0.84.3 (V10) and stays.
4. Gate: markdown/docs instructions apply (`.ai-badger/instructions/documentation.instructions.md`); no tests assert this file's prose — the acceptance check is the diff itself plus the extension doc matching `pi --help` output line-for-line on the flags it names.

Proof of done: no sentence in the file claims a mechanism that pi 0.84.3 does not have (checked against `pi --help` and `docs/skills.md`); shipped copy untouched.

## 4. Risks

- **Boolean flip in a published matrix (D5/WP4):** `aiBadgerSupport: false` for pi skills changes what the catalog advertises. It is the honest value under the schema's own definition, but it is the owner's matrix — flagged in the PR and open questions, not snuck in.
- **Sequencing with the TS lane:** the happy-path/integration tests in WP1 need the real `adapter/` dir; landing them before the adapter exists would go red for the wrong reason. The fixture-based tests are deliberately TS-independent.
- **`shlex` behavior change (D3):** commands that previously "worked" via naive split (e.g. stray quotes producing garbage args) will now raise for unbalanced quotes. That is the intended fail-loud behavior, and the scaffold reports it per-adjustment without aborting the run.
- **Line-number drift:** findings cite `file:line`; these shift as soon as WP1's edit lands. Implementers should locate by content (function names given here), not line numbers.

## 5. Open questions (for the master plan / owner)

1. D5 boolean: confirm `aiBadgerSupport: false` for `pi.skills`, or decide to build a real `pi/adjust_skills.py` (write the pi settings `skills` entry, or symlink into `.pi/skills/` — noting project-scope skills only load after project trust, and headless pi ignores untrusted project state). Recommended: correct the row now; build the adjustment as its own follow-up task if the owner wants zero-touch discovery.
2. Adjacent drift found while verifying V6/V7 (not in this lane's findings): the **claude** `skills.scaffoldedBy` string reads "scaffold.py symlink_hermes_skills() for hermes; direct copy for claude" — inside the *claude* row it should describe claude's own mechanism (`claude/adjustments/adjust_skills.py` symlinks into `.claude/skills/`, not a copy). Fold into WP4 or a follow-up?
3. Extension.md line 14's spawn command (`pi --mode json -p --no-session …`) was verified by the review's "explicit answers" section but not re-measured by this lane; left untouched per scope.
4. WP4's `mechanism` wording: keep the "79/79 load unmodified" figure (research-lane evidence) or drop it under the same reasoning as D6? Recommended: keep — it is a one-time measured claim about loading the whole catalog, not a version-coupled surface count; flag if the owner disagrees.

## 6. Named tests summary (hand to the test-honesty lane)

| Test (in `tests/test_pi_adjustments.py`) | WP | Depends on TS lane |
|-------------------------------------------|----|--------------------|
| `test_adjust_hooks_missing_adapter_fails_loud` | WP1 | no |
| `test_adjust_hooks_installs_adapter_files` (fixture adapter) | WP1 | no |
| `test_adjust_hooks_installs_real_adapter` | WP1 | yes — after `features/pi/adjustments/adapter/` lands |
| `test_adjust_mcp_quoted_command_survives` | WP2 | no |
| `test_adjust_mcp_unbalanced_quote_raises` (optional) | WP2 | no |
| `test_pi_session_source_resume_command` | WP3 | no |
