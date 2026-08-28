# Test Strategy — aib-pi-review-fixes (test-engineer lane)

**Repo:** ai-badger, worktree `.ai-badger/worktrees/aib-pi-review-fixes`, branch `task/aib-pi-review-fixes` @ `9d2d0ce0`.
**Basis:** findings report `/tmp/aib-pi-review-findings.md`; anchor finding **F6** (install path untested → two blockers invisible). Sources read directly in this worktree; nothing assumed from memory.
**Scope:** plan only. The implementing lanes (pi-ts-extensions, python-adjustments, pi-mcp-tools-fork) own production changes; this document owns what proves them.

---

## 0. Verified pre-flight facts (evidence, cited — re-run as step-0 acceptance)

| Fact | Evidence |
|---|---|
| Runner: `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest tests/test_pi_adjustments.py -q` (repo .venv, run from the worktree) | Baseline witnessed this session: **14 passed in 1.70s** |
| The hooks adapter does not exist pre-fix | `find features/pi -type f` → no `adapter/` anywhere; `adjust_hooks.py:26` `ADAPTER_DIR = "adapter"`, `:45-46` silently `return []` when the dir is missing |
| `features/pi/cron/` holds only `index.ts` + `package.json` — no `run-job.ts` | same find; `cron/index.ts:44` registers `join(__dirname, "run-job.ts")` with `Bun.cron` |
| Plist template has no scheduling key | `cron/index.ts:53-74`: `RunAtLoad=false`, `KeepAlive=false`, no `StartCalendarInterval`/`StartInterval` |
| noAgent default not implemented | `cron/index.ts:103` `if (job.noAgent)` — jobs without the field are silently skipped |
| Resume string is wrong | `pi_session_source.py:30` `f"pi -p --resume {session_id}"`; repeated at `features/common/skills/task/extensions/pi/extension.md:21` |
| **install:True is the production default** — the untested branch is the mainline | `scaffold.py:822` `install=not args.no_install`; `scaffold.py:639` puts `"install": self.install` into the adjustment context; `adjust_hooks.py:101` / `adjust_cron.py:55` default to True when the key is absent |
| Both pi tests that touch hooks/cron run with `install: False` | `tests/test_pi_adjustments.py:73` (`test_adjust_hooks_with_pi`), `:122` (`test_adjust_cron_with_pi_no_cron_dir`) |
| `USER_EXTENSIONS_DIR` is a module-level `Path.home()`-based constant in both adjusters | `adjust_hooks.py:27`, `adjust_cron.py:14`; a fresh module object is built per `load_script` call and registered in `sys.modules` under its dotted name (`tests/conftest.py:508-527`) |
| Monkeypatch-a-module-constant precedent exists | `tests/test_mcp_user_tool_paths.py:44-56` `_fake_tool_dirs` → `monkeypatch.setattr(mcp_tools, "USER_TOOL_DIRS", ...)` |
| conftest already provides layered isolation | `tests/conftest.py`: `_home_off_limits` (session `$HOME` redirect, :174-189), `_test_write` gate refusing real checkouts + real home (:87-104), FS/tracking observers, `REAL_HOME` captured at import (:31) |
| The task extension doc exists in multiple copies | `features/common/skills/task/extensions/pi/extension.md` (source), `skills/task/extensions/pi/extension.md` (scaffold copy), `.ai-badger/skills/...` (installed); `test_copy_skew.py` covers **plugin** copies only — no gate found comparing skills copies (searched `test_copy_skew.py`, `test_framework_copies.py` for `extension.md`: no hits) |
| `red_proof.py` interface (skill-local tool) | `~/.hermes/skills/ai-badger/design-tests/scripts/red_proof.py --file F --line N --replace "old" --with "new" --run "<cmd>"`; exits 0 = red-then-green; refuses dirty files; journal at `.design-tests/red-proof.journal.json` |
| Stale `plan.md` in worktree root belongs to a *different* task (consolidate-stack-skills) | read this session; this document is separate from it |

---

## 1. Why the green suite missed the blockers (F6, restated as the design driver)

Every existing pi hooks/cron test passes `install: False`, so `_install_user_extension` — the branch that copies TypeScript deliverables into `~/.pi/agent/extensions/` — never executes under test. Since the production default is `install: True` (fact row 6), the untested branch is the mainline. F1 (missing adapter dir) and F2a (missing run-job.ts) live exactly in that branch, which is why 14 green tests shipped them.

The strategy therefore has three layers, in order:
1. **Install-path tests** through the real `adjust()` entry point with `install: True` (§3 T1–T3).
2. **Source-contract tests** for the TypeScript deliverables pytest cannot execute (§3 T4–T7) — pinned honestly at string/structure level, with everything needing a live pi declared out of scope, not faked.
3. **Red-proof discipline** for every test (§4): natural RED where the defect is still in-tree; `red_proof.py` mutations where the fix already landed.

---

## 2. Prerequisite: the `pi_user_extensions` fixture (complete monkeypatching)

New module-local fixture in `tests/test_pi_adjustments.py` (conftest stays untouched until a second file needs it):

- Load both modules via `load_script`, then `monkeypatch.setattr(module, "USER_EXTENSIONS_DIR", tmp_path / "pi" / "agent" / "extensions" / <name>)` for **both** `adjust_hooks` and `adjust_cron`. Patch **after** loading, **before** calling `adjust()` — the module global is what `_install_user_extension` and the notes strings read, and each `load_script` call produces a fresh module object, so a patch must be applied to the object the test actually holds.
- Why not `$HOME` redirection alone: conftest's session `_home_off_limits` makes `Path.home()` resolve to scratch during tests, but the incident record (an earlier test version monkeypatched incompletely and wrote the real `~/.pi`) and the 0.141.0 scaffold leak (fixed in `6ba7f706`) both show constant-based paths must be redirected explicitly and deterministically. The fixture is the control; conftest is the floor. Layered defense, both named.
- Isolation rules for every test below: reads from `features/` are fine (install copies *from* the framework root *to* tmp); **all writes go to `tmp_path`** — never `features/`, never `.ai-badger/`, never the real home. This is the exact failure mode `test-file-isolation` names.

---

## 3. Test plan

Oracle rule: expected values come from the documented contract (the finding text, pi's documented extension surface, POSIX `expanduser` behavior), **never** from the code under test. TS source contracts derive from the review's documented launchd/Bun semantics, not from what `cron/index.ts` happens to say today.

### T1 — `test_adjust_hooks_with_pi_install_copies_adapter` (F1)
- **Unit/behaviour:** `adjust_hooks.adjust` with `install: True` and `feature_dir = root / "features" / "pi" / "adjustments"` → the adapter extension lands in the (patched) user extensions dir.
- **Assertions:** `result["applied"]` True; note names the extensions dir; **`adapter.ts` and `package.json` exist** under the patched `USER_EXTENSIONS_DIR`; the installed `package.json` parses as JSON (`json.loads`); hook scripts still land in `target_dir/hooks/` (keep the existing copy assertions).
- **Oracle:** the module docstring's extension structure contract (`adjust_hooks.py:14-17`) — adapter.ts + package.json are the declared deliverables.
- **Red proof:** born RED pre-fix — the adapter dir does not exist, so the files cannot land (witness the failure on the file-existence assertion, not on setup). Post-fix regression mutation: `red_proof.py` against `adjust_hooks.py`, replacing the copy loop with an early `return []` → T1 red; revert → green. For the file-absence dimension use tmp copies of `feature_dir` without `adapter/` (see §4 rule 3) — the real `features/` tree is never mutated.

### T2 — `test_adjust_cron_with_pi_install_copies_extension` (F2a)
- **Unit/behaviour:** `adjust_cron.adjust` with `install: True` and the real `feature_dir` (cron dir resolves to `features/pi/cron`) → the cron extension lands, **including `run-job.ts`**.
- **Assertions:** `applied` True; note names the pi-cron dir; `index.ts`, `package.json`, **and `run-job.ts`** exist under the patched dir; `package.json` parses.
- **Oracle:** `cron/index.ts:44` — `Bun.cron` is registered against `run-job.ts`; a scheduled job that references a script that does not ship is the defect (F2a verbatim).
- **Red proof:** born RED pre-fix (run-job.ts missing → assertion fails). Post-fix mutation: point `feature_dir` at a tmp copy with `run-job.ts` deleted → red; restore the copy → green.
- The existing `test_adjust_cron_with_pi_no_cron_dir` (negative case) stays; it becomes meaningful because the positive case now exists.

### T3 — `test_adjust_hooks_missing_adapter_dir_fails_loud` (F1 fix: fail-loud)
- **Unit/behaviour:** `install: True` with a **tmp_path-built `feature_dir` lacking `adapter/`** → `adjust()` must not report the silent-success state that shipped in 0.141.0 (`applied: True` with nothing installed).
- **Invariant pinned (holds under either fix shape):** `not (result["applied"] and nothing was installed)` — i.e. when install was requested and the adapter dir is missing, the result is either `applied: False` with a note naming the missing dir, or a loud error. Exact assertion shape is finalized once the python-adjustments lane picks its contract (open question 1); the *invariant* is not negotiable.
- **Red proof:** pre-fix the silent state exists → born RED (applied is True with empty install). Post-fix mutation: restore `return []` at `adjust_hooks.py:45-46` via `red_proof.py` → red; revert → green.

### T4 — `test_cron_plist_template_has_scheduling_keys` (F2b) — source contract
- **Unit/behaviour:** the launchd fallback in `features/pi/cron/index.ts` produces a plist launchd can actually fire.
- **Assertions (string-level, honest ceiling):** the plist template contains `StartCalendarInterval` **or** `StartInterval`; schedule-derived content (`job.schedule` or a parsed form) is interpolated into that key's block; `RunAtLoad`/`KeepAlive` remain `false` (so the scheduling key is the only fire mechanism).
- **Oracle:** the launchd contract cited by finding F2 (a plist with neither scheduling key never fires); NOT the current template.
- **Red proof:** born RED pre-fix (no key present). Post-fix: `red_proof.py` removing the key line from the template → red; revert → green.
- **Out of scope, stated:** whether launchd *actually fires* the plist on a real macOS host — manual E2E probe, documented, not automated (no theatre test).

### T5 — `test_cron_registers_jobs_without_explicit_no_agent` (F5) — source contract
- **Unit/behaviour:** jobs in `cron.json` without an explicit `noAgent` field are registered, not silently dropped (the documented "no_agent=true by default" is about how jobs *run*, but the review's fix makes un-annotated jobs eligible for registration; whichever variant the TS lane lands — open question 3 — the test pins: a job without the field is not skipped silently).
- **Assertions:** registration branch in `cron/index.ts` matches `noAgent !== false` (or the lane's chosen default-on form); **and** either nothing silently skips, or the skip path notifies (`ctx.ui.notify`) per the review's alternative fix. Pin the regex/substring once the variant is known.
- **Oracle:** finding F5's documented default (`adjust_cron.py:5` docstring claim).
- **Red proof:** born RED pre-fix (`if (job.noAgent)` present, default-on form absent). Post-fix: `red_proof.py` reverting the comparison → red; revert → green.
- **Out of scope, stated:** semantic verification that a field-less job actually *executes* needs a live pi (or the TS lane's harness). Pytest pins the source contract only.

### T6 — `test_pi_session_source_resume_uses_session_flag` (F3)
- **Unit/behaviour:** the resume lambda registered with `tracker_lib` builds a command pi accepts.
- **Assertions:** extend the existing `FakeTrackerLib` pattern — capture the `resume` callable, invoke with `"sess-abc-123"`, assert result equals `"pi -p --session sess-abc-123"` **and** `"--resume"` is not in it (`--resume` takes no argument — an id after it would be a separate argv token, silently ignored).
- **Oracle:** pi's CLI contract as documented in the findings (`--resume` = interactive selector, no argument; `--session <id>` = resume by id).
- **Red proof:** born RED pre-fix (line 30 still emits `--resume`). Post-fix: `red_proof.py` on `pi_session_source.py:30` reverting the flag → red; revert → green.
- **Doc call site:** `features/common/skills/task/extensions/pi/extension.md:21` repeats the bad string. Optional low-priority pin: a test asserting no `--resume <session_id>` pattern survives in the doc — brittle if over-broad; keep it to the one line. Both copies (features/ source + skills/ scaffold copy) must change in lockstep; no existing gate compares them (open question 4).

### T7 — `test_away_mode_extension_ships_and_registers` (new deliverable)
- **Unit/behaviour:** the away-mode extension ships as installable extension files and registers the pi surface that auto-answers tool-approval confirms.
- **Assertions:** files exist (extension `.ts` + `package.json`) at the location the pi-ts-extensions lane lands them; `package.json` parses; source registers the gating pi event (`tool_call`) and the confirm auto-answer call — exact substrings pinned **after** the lane names its API (open question 2). If the away-mode extension is installed by an adjuster, extend T1's install test to assert its files land too; if it is documented as manual-install, assert only source-level presence and say so in the test docstring.
- **Red proof:** born RED pre-delivery (files absent). Post-delivery: mutation = rename the extension file in a tmp copy / revert the registration line → red; restore → green.
- **Out of scope, stated:** that pi actually suppresses a real confirm is live-pi behavior — manual E2E.

### T8 — (conditional) `test_adjust_mcp_command_splits_with_shlex` (F8)
Only if the python-adjustments lane takes F8. Declaration `command` containing a quoted path with spaces → `_server_entry` produces a correctly split argv (`shlex.split` semantics), e.g. `command: 'npx -y server "--flag a b"'` → `["npx", "-y", "server", "--flag a b"]`. Oracle: POSIX tokenization rule. Born RED pre-fix (`command.split()` mangles). Red proof: `red_proof.py` reverting to `.split()`.

### T9 — (recommended, conditional) `test_support_scaffoldedby_paths_exist` (F4)
A derive-or-delete guard, framework-general rather than pi-specific: walk every `features/*/support.json`, and for every `scaffoldedBy` value, assert each named script path exists in the repo. Catches today's `adjust_skills.py` phantom (F4) **and every future one** — this is the invariant the finding names. Born RED today. Red proof: re-add a phantom path → red. Lives in its own file (`tests/test_support_scaffolded_by.py`) since it walks all agents. **Caveat:** before writing it, audit whether *other* agents' `scaffoldedBy` entries resolve — if more are broken, the gate reds on unrelated agents and the lanes must decide fix-vs-correct-the-field per entry (open question 5).

### Explicitly out of scope (honest, not forgotten)
| Item | Why not a pytest |
|---|---|
| pi actually loading `adapter.ts` via jiti; events actually firing end-to-end | needs a live pi + a project under test — manual E2E probe |
| launchd actually firing the plist; `Bun.cron` actually executing `run-job.ts` | OS-scheduler behavior — manual E2E on a macOS host |
| away-mode actually suppressing a real `ctx.ui.confirm` | live-pi behavior — manual E2E |
| Findings F11–F18 (pi-mcp-tools fork) | owned by the fork lane's vitest suite (46 tests, its own runner); pytest cannot even import that tree |
| F7 (doc wording), F9 (dead code), F10 (event count) | doc-only / deletions — no behavior to pin; F9's deletion is verified by `grep` in review, F10 by dropping the number |

---

## 4. Red-proof requirements (per `prove-the-check-fails` + design-tests Stage 5)

1. **Every new test witnesses its RED before it is called a check.** Two admissible forms:
   - **Natural RED** (preferred where available): the defect is still in the tree (T1, T2, T3, T4, T5, T6, T8, T9 pre-fix) — write the test first, run it, paste the runner output with the failing **assertion line** visible. A failure on import, fixture setup, or any line other than the intended assertion does not count.
   - **Mutation RED** (`red_proof.py`, exit 0, both runs pasted): required when the test is authored after its fix landed, and re-run at review time for regression value on the born-red tests whose fixes are now present.
2. **`red_proof.py` invocation:** from the worktree, e.g.
   `~/.hermes/skills/ai-badger/design-tests/scripts/red_proof.py --file features/pi/adjustments/pi_session_source.py --line 30 --replace '--resume' --with '--session' --run '/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3 -m pytest tests/test_pi_adjustments.py::test_pi_session_source_resume_uses_session_flag -q'`
   Preconditions: target file clean in `git status`; `--replace` must occur exactly on `--line`. Exit 0 = red-then-green. If killed mid-run, the journal at `.design-tests/red-proof.journal.json` is restored on next start — inspect it, delete it, re-run (open question 6: whether `.design-tests/` is gitignored here; if not, a stray journal trips the freshness gate).
3. **File-absence proofs never mutate the real tree.** To prove T1/T2 red against a missing deliverable, build a `feature_dir` copy under `tmp_path` without the file — that is also how T3 constructs its scenario. The worktree's `features/` tree is read-only to tests, always.
4. **Evidence recorded per test** (red-proof skill step 5): pre-fix state (commit or mutation applied), the intended-assertion failure line, post-fix pass count. Report format: design-tests Stage 7 table — Behaviour | Test | Runner + duration | Red evidence | Oracle.
5. **Scope of runs:** scoped pytest by node id during development; full `tests/test_pi_adjustments.py` (and then the full suite) once green. A scoped run resolving to zero tests exits 0 and proves nothing — the pasted output must show a non-zero test count.

---

## 5. Sequencing for the implementing lanes

1. **First commit (test lane):** `pi_user_extensions` fixture + T1, T2, T3, T4, T5, T6 — all born RED against `9d2d0ce0`. Paste the six RED runs (TDD-mandatory satisfied: failing, behavior-focused tests precede the fixes).
2. **Production lanes land fixes** (adapter dir, run-job.ts, plist keys, noAgent default, fail-loud guard, resume string, away-mode) → tests go green **one at a time**, never batched (design-tests Stage 5).
3. **Post-merge:** mutation red-proofs per §4 rule 1 for every test; `review-tests` pass on the new tests (tests-are-designed-and-reviewed invariant — the suite must be judged by someone other than its author); full suite green; conftest's FS/tracking observers silent (no write outside `tmp_path`).
4. **Acceptance criteria for this lane's deliverable:** ≥ 6 new witnessed-RED tests (T1–T6), fixture with complete two-module monkeypatching, every test's red evidence recorded, zero tests touching the real scaffold or real home. Target: `tests/test_pi_adjustments.py` grows 14 → ~20–22 tests (T7–T9 add up to 3 more, conditional on open questions).

---

## 6. Open questions (need answers before or during implementation)

1. **Fail-loud contract shape (T3):** does the python-adjustments lane choose `applied: False` + error note, or `applied: True` + explicit warning? The invariant `not (applied and nothing-installed)` holds either way; the exact assertion is pinned to the choice.
2. **Away-mode extension (T7):** file paths, `package.json` name, which pi event/API auto-answers confirms, and which adjuster (if any) installs it — needed from the pi-ts-extensions lane before the substrings can be pinned.
3. **noAgent fix variant (T5):** default-on (`noAgent !== false`) vs notify-on-skip — finding F5 allows both; T5's regex differs per variant.
4. **Doc copy lockstep:** `extension.md` exists in features/ (source), skills/ (scaffold copy), and installed trees; no existing gate compares skills copies (`test_copy_skew.py` is plugin-scoped). Does the fix change both copies, and is a skills-copy drift gate wanted here or as a separate feed-badger contribution?
5. **T9 generality:** audit other agents' `support.json` `scaffoldedBy` entries before making the gate repo-wide — unrelated broken entries would redden the gate on non-pi agents.
6. **`.design-tests/` gitignore status:** a killed `red_proof.py` run leaves a journal there; if untracked files trip this repo's freshness gate, add the ignore entry in the same commit as the tests.
