# Code Review — PR #311: Hermes directory-plugin fix (branch `task/hermes-plugin-fix`)

**Reviewer:** Hermes code-reviewer gate · **Date:** 2026-08-06
**Commits reviewed:** `17d0042` (RED) · `4771da5` (GREEN) · `8c43e75` (release 0.80.0) · `4c73e49` (shape-test fixes)
**Scope:** correctness, architecture, test honesty, docs accuracy. Full suite was already run by the gate (3196 passed / 18 skipped, pylint 10.00, index_build clean) — not re-run. RED-verification was re-executed independently (below).

---

## Verdict: APPROVE-WITH-NITS

The fix is real, well-pinned, and honest. The core contract — Hermes directory plugin at `~/.hermes/plugins/ai-badger/` (plugin.yaml + `__init__.py` re-exporting `register`), payload normalization for the verified emitter shapes, host/sessionId log attribution — is implemented correctly, tested by tests that were verified RED against `main` (22 behavioral failures, see F-07), and live-verified in a real Hermes session. The two MODERATE findings are non-blocking: one is a stale manual-install instruction in a skill extension doc (no runtime effect on the scaffold path this PR fixes), the other is a host-attribution edge on the Copilot path of a feature this PR ships. Both are cheap follow-ups listed under Merge conditions.

---

## Findings

### F-01 [MODERATE] Docs: `task` skill's Hermes extension still instructs the exact broken flat-file install

`features/common/skills/task/extensions/hermes/extension.md:113-116` (and its mirrored copy `.ai-badger/skills/task/extensions/hermes/extension.md:115`):

```bash
# Copy the hook module to your Hermes plugins directory
cp features/common/hooks/ai_badger_hooks.py ~/.hermes/plugins/
```

This is the precise failure mode this PR exists to fix (flat `.py` in `~/.hermes/plugins/` is invisible to Hermes' directory-plugin loader — the file would be silently dead). It is a *live instruction* shipped in framework source and in every scaffolded `.ai-badger/` mirror, not a historical record. The PR updated `adjust_hooks.py` notes, SKILL.md §8, and the changelog, but missed this surface. A user or agent following the task skill's Hermes-extension doc re-creates the bug.

**Fix:** rewrite the installation block to point at the scaffold/`den-refresh` install (`~/.hermes/plugins/ai-badger/` + `hermes plugins enable ai-badger`) or, for the manual path, at least `cp` into `~/.hermes/plugins/ai-badger/` including `plugin.yaml`/`__init__.py` — or delete the manual path entirely and defer to the adjustment.

### F-02 [MODERATE] Host attribution is hardcoded `"claude"` in a script shared with Copilot — and the new fields are untested

`features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py:37` passes `host="claude"` unconditionally, but `features/common/hooks/hooks-manifest.json` (memory-grade entry) assigns this same script to **Copilot** (`copilot → hooks-json → postToolUse → memory_grade_hook.py`) as well as Claude. The PR's own changelog (docs/changelog/0.80.0-hermes-plugin-fix.md) and SKILL.md §8 advertise `host` ∈ {hermes, claude, copilot}; in practice a Copilot-originated search line will claim `host="claude"`, silently defeating the "no usage vs no capture" diagnostic the field exists for on one of the three named hosts. (If Copilot's payload field spellings also differ from `tool_name`/`tool_input`/`tool_response`, the hook writes no line at all — untested either way.)

Additionally, the two new lines in this file (`host="claude"`, defensive `session_id`) have **no test coverage**: `tests/test_memory_grade_claude_hook.py` contains no `host`/`session` assertion (grep: none), and no test exercises a Copilot-shaped payload. Every other behavior change in this PR is pinned by a test; this one is not.

**Fix (recommended follow-up, non-blocking):** detect the host from the payload/environment (e.g. Copilot env vars or payload keys) instead of hardcoding, or accept-and-document; add one assertion in `test_memory_grade_claude_hook.py` for `host`/`sessionId` forwarding.

### F-03 [NIT] Module docstring still describes the flat two-file deployment

`features/common/hooks/ai_badger_hooks.py:8-14` (and its byte-identical scaffold mirror `.ai-badger/hooks/ai_badger_hooks.py`):

> "Installation: `welcome-ai-badger` copies this file and learned_skills_sync.py into ~/.hermes/plugins/ … In ~/.hermes/plugins/ there is no framework above these two loose files, so the root recorded in the project's .ai-badger/manifest.json is what answers (ADR-0007)."

Now false in three ways: the install is a directory plugin (9 files + plugin.yaml + __init__.py), the manifest record sits *inside* the plugin dir (not the project's), and the framework root is answered by the plugin dir's own `.ai-badger/manifest.json`. The docstring's mechanism description will mislead any future maintainer of this exact file.

### F-04 [NIT] ADR-0007 Shape D description is now factually wrong

`docs/adr/0007-no-python-distribution.md:101-102` ("copies exactly two loose files there: `ai_badger_hooks.py` and `learned_skills_sync.py`. Nothing else."), plus the shape-D analysis at :153, :206, :265. The deployment shape changed materially (directory plugin, manifest inside the dir, 10 files); the ADR's core decision (no python distribution; self-locating shim) is untouched, but its description of the current Hermes shape — which code comments cite as authority ("ADR-0007") — is stale. Amend the Shape D section in a follow-up.

### F-05 [NIT] `debug_log` stays dead in the Hermes plugin — and the import-time `sys.path` insertion remains a shadowing risk

`features/common/hooks/ai_badger_hooks.py:28-34` imports `debug_log` from `sys.path.insert(0, plugin_dir)`; `debug_log.py` exists in `features/common/hooks/` but is not in any copy list in `features/hermes/adjustments/adjust_hooks.py` (USER_PLUGINS / SHARED_SKILL_MODULES / RETRIEVAL_MODULES), so the call-behaviorist debug instrument (`_debug(...)` calls throughout) silently no-ops in Hermes sessions — pre-existing, but this PR was the moment to ship it. Related: the same `sys.path.insert(0, …)` at import time puts the plugin dir (containing generic names `bm25.py`, `tokenizer.py`, `memory_grade.py`) at the head of the Hermes process's `sys.path`; low risk (Hermes imports its own modules qualified), pre-existing pattern, worth a comment or a narrower insertion.

### F-06 [NIT] Payload normalization: non-dict `function_args` would degrade silently

`features/common/hooks/ai_badger_hooks.py:825-827`: `args = kwargs.get("args") or kwargs.get("function_args") or {}`. If a transport ever sends `function_args` as a JSON *string* (not a dict), `args.get(...)` in `_maybe_log_memory_grade` (line 801-804) raises AttributeError, swallowed by the broad except at :848 → "memory grade logging failed" and no line. Live verification shows the real Hermes emitter sends a dict, so this is defensive hardening only; a `json.loads` attempt for string values would make the adapter fully robust.

### F-07 (evidence) RED tests are genuinely red — verified against `main`

Copied the five changed test files into a detached worktree of `main` (27fe1e2) and ran them with the repo venv: **22 failed, 122 passed, 16 skipped**. Failures are behavioral, not setup errors: directory-shape assertions (`test_scaffold_installs_hermes_plugin_as_directory_plugin` — `plugins/ai-badger` doesn't exist), payload-normalization tests (observer gets `tool_name=""` from a `function_name` payload → no log line), host/session assertions (fields absent), manifest-location tests, and shape tests failing because `shapes["hermes"]/ai-badger/` doesn't exist on main. TDD order is real.

---

## Checklist against the review brief

**A. Test-pinned contract vs implementation — SATISFIED.**
- Directory shape: `test_hermes_plugin_install.py:76-92` pins dir + no flat files; implemented at `adjust_hooks.py:108-141`.
- plugin.yaml declares exactly the three hooks (`test_hermes_plugin_install.py:217-230`; `adjust_hooks.py:43-58`); `__init__.py` re-exports `register` (`test_hermes_plugin_install.py:232-262`; `adjust_hooks.py:59-60`).
- Manifest inside plugin dir (`test_hermes_plugin_install.py:265-275`; `adjust_hooks.py:79-95`) — matches `badger_lib.copy_skew` reading `copies_dir/.ai-badger/manifest.json`; `_copy_skew_refusal` passes `Path(__file__).parent` = the plugin dir (`ai_badger_hooks.py:169`).
- Legacy flat removal (`test_hermes_plugin_install.py:278-298`; `adjust_hooks.py:98-105`). Legacy list is complete: `git show main:...adjust_hooks.py` confirms the old installer's flat set was exactly USER_PLUGINS + SHARED_SKILL_MODULES + RETRIEVAL_MODULES (memory_grade_hook.py and debug_log.py were never deployed flat). Cleanup runs only when the new install succeeded (`if installed:`), touches only framework-owned names, and the old manifest dir is installer-owned. Safe.
- Payload adapter: real-emitter payload accepted (`test_hermes_plugin_payloads.py:59-89`); legacy spelling still works (:92-108); non-search tool writes nothing (:111-118); pre_llm payload accepted and pop-side key match round-tripped (:121-140); session-only on_session_start (:143-145). Implementation at `ai_badger_hooks.py:825-828, 847`.
- Host/session fields: `memory_grade.py:65-83` (`_build_line`), :133-152 (`log_search`), null in manual lines (test_memory_grade_log.py new tests). Claude transport forwards (`memory_grade_hook.py:37-38`) — but see F-02.

**B. Architecture — CLEAN, with two caveats (F-02, F-06).**
- Install is idempotent (copy2 refresh, `test_scaffold_refreshes_stale_hermes_plugin`), notes tell the user to enable (`adjust_hooks.py:196-200`), opt-in reality acknowledged in code and docs.
- Stash/pop key match: both `post_tool_observer` and `pre_llm_inject_context` resolve `_project_cwd(cwd)` → `os.getcwd()` (`ai_badger_hooks.py:196-202`), pending stores keyed by resolved absolute path (`ai_badger_hooks.py:709-723`; `memory_grade.py:126-130, 155-164`). Same process, stable cwd in Hermes sessions. Verified by the round-trip test.
- Edge cases: `result` bytes handled (`memory_grade.py:52-56`); `result=None` guarded (`len(result) if result else 0`); `session_id` absent → null (tested); non-dict args → silent skip (F-06); `duration_ms`/`status`/`tool_call_id`/`turn_id` absorbed by `**kwargs`.

**C. Bootstrap interplay — CONFIRMED against code.**
From `~/.hermes/plugins/ai-badger/`, `_bootstrap_lib` (`ai_badger_hooks.py:49-150`) checks the plugin dir's own `.ai-badger/manifest.json` at the first ancestor (`manifests()` at :87-100 handles `anc/.ai-badger/manifest.json` for `anc.name != ".ai-badger"`). `recorded()` (:102-112) requires `is_root` (schemas/ + features/ + engine/badger_lib.py). Dead/temp root → `recorded` returns None → cache fallback → `RuntimeError` at :140-146 → caught at :153-156 → `FRAMEWORK_ROOT=None` → `_copy_skew_refusal` returns None at :165-166 → `COPY_SKEW_REFUSAL=None` → `register` proceeds (:873-880). All downstream `FRAMEWORK_ROOT` uses are None-guarded (`_read_framework_version` :188-193; MCP index is cwd-based :298-306; sibling lazy loads are file-path based, unaffected). Degradation matches the claimed control flow exactly.

**D. Test honesty — HIGH.** RED verified (F-07); shape tests exercise the real layout through the real scaffolder (the `shapes` fixture runs `scaffold.py --no-install` with a redirected home, `test_deployment_shapes.py:135-163`, and `_entry_path` resolves `…/plugins/ai-badger/<file>` at :180); payload tests use the verified emitter field set; `fake_memory_grade` injects the *real* module, not a stub. One gap: F-02 (Claude-hook host/session change unpinned, Copilot path untested).

**E. Docs — MOSTLY ACCURATE, three stale surfaces.**
- SKILL.md §8 (features/common/skills/ai-raccoon-memory/SKILL.md, mirrored in SKILL.full.md and .ai-badger copies): accurate — host-coverage statement, `hermes plugins enable ai-badger` instruction, capture-verification checklist, corrected helper paths, superset field list.
- Changelog 0.80.0: accurate and appropriately self-critical about the 0.79.0 "all three agents wired" claim.
- Stale: F-01 (extension.md ×2 — actionable), F-03 (docstring), F-04 (ADR-0007). `docs/plans/memory-grade-hook.md:42,133` still references `~/.hermes/plugins/memory_grade.py` — historical plan doc, acceptable as-is. `tests/test_deployment_shapes.py:416` comment ("hooks load automatically") and `tests/test_badger_lib.py:182` docstring are mildly stale; cosmetic.

---

## Merge conditions

1. **Recommended before merge (trivial):** fix `extension.md:115` in both copies (F-01) — one line that re-creates the bug this PR fixes; it should not merge in the same state as the fix it contradicts.
2. **Fast-follow (non-blocking, tracked):** Copilot host detection or documented acceptance + one test assertion for `memory_grade_hook.py` host/session (F-02).
3. **Follow-up (non-blocking):** amend ADR-0007 Shape D and the `ai_badger_hooks.py` docstring (F-03, F-04).
4. **Optional:** ship `debug_log.py` into the plugin dir so the call-behaviorist instrument works in Hermes (F-05); defensive `json.loads` for string `function_args` (F-06).

Core fix verified live by the gate (plugin discovered/enabled, organic `memory_search` line with `host=hermes` + `sessionId` — the first organic line in the quality log). No blockers.
