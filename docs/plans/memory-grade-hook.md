# Plan: memory-grade hook (ai-raccoon memory access grading)

Status: proposed · Author: architect · Target: **separate PR, after #302 (ai-raccoon integration) merges** — this plan changes files that #302 introduces (features/common/skills/ai-raccoon-memory/), so it is never added to the open PR.

## 1. Overview

A hook that fires when the agent calls the ai-raccoon MCP tool `memory_search`:

1. Appends one JSONL line per search to a **machine-wide log** with the full result payload, the query, `projectId`, `workspaceId` (null when no workspace is active), `scope`, and `usefulness: null`.
2. Stashes a one-line **grade ask** (stash/pop, the commit-reminder precedent) that `pre_llm_call` injects into the very next LLM turn (Hermes) or that the PostToolUse hook returns as `additionalContext` (Claude).
3. The agent answers by running a tiny helper script that fills the grade (and optional note) into the line in place, so every line ends with query + full result + grade + project_id + workspace_id.

Line shape matches the session's manual file `docs/work/2026-08-05-ai-raccoon-memory-quality.jsonl` (verified: `ts, query, scope, projectId, result.results[{hash, ranking, sourceFile, snippet}], usefulness, note`), with `workspaceId` added (null when absent) so manual and hook logs stay compatible.

Purpose: dogfooding the memory store — correlate retrieval usefulness per project/workspace across sessions.

## 2. Config design

**Chosen: env var `AI_BADGER_MEMORY_GRADE=1`.** Framework default OFF (absent/unset/`0`/garbage → hook fully inert: no reads, no writes, no injection).

Why, against the alternatives:

- Repo precedent: every hook knob is already an env var (`AI_BADGER_COMMIT_REMINDER_THRESHOLD`, `AI_BADGER_COMMIT_ESCALATE_AFTER`, `AI_BADGER_COMMIT_REMINDER_IMPACT`, `AI_BADGER` for the framework root). An env var is zero new machinery, trivially testable, and inherits into every agent host process (Hermes CLI/TUI, Claude Code, subagents).
- Bank settings row (`settings(key, value)` table in `~/.ai-raccoon/memory.db`) is bank-global and *looks* machine-wide, but the hook runs agent-side in the Hermes/Claude process. Reading it means either a plain `sqlite3` read — works on this machine (verified: DB is unencrypted, `AIRACCOON_DB_PASSPHRASE` unset) but silently reads OFF on any machine where the bank is SQLCipher-encrypted, and couples the framework to AiRaccoon's on-disk schema — or a new MCP settings tool plus a hook→MCP round-trip, which is over-engineering. Rejected.
- User-global file (`~/.ai-badger/...`) is the second-best shape (same precedent family as `pending.json`), but an env var needs no file IO on the hot path and matches the existing knob shape. A per-project opt-out later (not in this PR) is still possible as a `.ai-badger/config.json` check applied only when the env is on.

**Machine-wide enable on THIS machine (exact commands):**

```sh
echo 'export AI_BADGER_MEMORY_GRADE=1' >> ~/.zshrc
launchctl setenv AI_BADGER_MEMORY_GRADE 1   # GUI-launched hosts (Hermes Desktop) pick it up
```

Then restart the agent host (new shell / relaunch Hermes) and install the updated plugin copies so the hook code is actually present:

```sh
# after the PR merges and the worktree is refreshed
python3 tooling/index_build.py --check && python3 -m pytest -q   # sanity
cd <a scaffolded project> && den-refresh   # refreshes ~/.hermes/plugins/ copies
```

Probe (done-means-proven, WP7): the helper supports `probe` — `python3 ~/.hermes/plugins/memory_grade.py probe` prints the config state, the log path, and the last 3 lines, so "the hook actually fired" is checkable without a live search.

## 3. Hook wiring

New files (mirroring the commit-reminder feature shape — skill owns its scripts):

- `features/common/skills/ai-raccoon-memory/scripts/memory_grade.py` — all logic: config gate, tool matching, JSONL append/fill, pending-ask text, `grade`/`probe` CLI. No comments beyond 1–3-line contracts.
- `features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py` — Claude PostToolUse entry: reads the stdin payload, calls the same logic, prints `additionalContext` (advisory only, exit 0 — same discipline as `commit_reminder_hook.py`, docs/changelog/0.33.0).

Edits:

- `features/common/hooks/ai_badger_hooks.py` — a `# Memory grade` section (config gate, matcher, log, stash/pop) wired into the existing `post_tool_observer` and `pre_llm_inject_context`; lazy sibling import of `memory_grade.py` exactly like `_load_commit_reminder`. `register()` unchanged (the two existing callbacks gain the behavior).
- `features/hermes/adjustments/adjust_hooks.py` — add `("ai-raccoon-memory", "memory_grade.py")` to `SHARED_SKILL_MODULES` so the sibling lands beside `ai_badger_hooks.py` in `~/.hermes/plugins/` and `.ai-badger/hooks/`.
- `features/common/hooks/hooks-manifest.json` — new entry `memory-grade`: claude `{hooks-json, hooks.json, PostToolUse, memory_grade_hook.py}`, hermes `{plugin, ai_badger_hooks.py, method post_tool_call}`, copilot `{hooks-json, hooks.json, postToolUse, memory_grade_hook.py}` (all three agents wired → no `HOOKS_MANIFEST_AGENT_EXEMPTIONS` entry needed; `test_hooks_manifest_agent_coverage.py` demands exactly this).
- `features/common/hooks/hooks.json` — second `PostToolUse` matcher entry:
  ```json
  { "matcher": "memory_search", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py\"" } ] }
  ```
- `features/common/skills/ai-raccoon-memory/SKILL.md` — short section: what the hook does, default off, enable commands, log path, helper command.

**Tool-name matching** (`memory_grade.is_memory_search(tool_name)`): normalize defensively, then compare the bare name:

- Hermes deferred MCP names: `mcp__ai_raccoon__memory_search` (verified naming family: `mcp__code-review-graph__*`); also tolerate `mcp__ai-raccoon__memory_search`.
- Colon form used by the index (`_record_tool_index_check` partitions on `:`): `ai-raccoon:memory_search` / `ai_raccoon:memory_search`.
- Bare form: `memory_search`.
- Non-memory tools never match (`memory_write`, `memory_stats`, `terminal`, `write_file`, `mcp__code_review_graph__get_prompt`, ...). Only `memory_search` acts (the ask is defined for search results; other memory tools are out of scope until a real caller needs them — invariant: no abstraction before a buyer).

**Log path**: `~/.ai-badger/memory-grade/memory-quality.jsonl`, machine-wide. Rationale: one file correlates across projects/workspaces by `projectId`/`workspaceId` (the requirement), and the hook never writes into a project's working tree (a repo-local log would pollute `git status` and feed the commit-reminder loop). The manual `docs/work/...jsonl` stays as the session record; shapes are compatible.

## 4. The grade round-trip

**Chosen: hook logs the full line immediately at post_tool_call time (`usefulness: null`); the helper fills the grade in place.** Rejected alternative — the agent writes the whole line via the helper: the full result payload is only reliably available to the hook (and relaying it through the injected ask is exactly the prompt-bloat risk in §6); also rejected — grading via `memory_write` into the bank: grades are telemetry, not memory content, and would corrupt retrieval.

Flow:

1. `post_tool_call` sees `memory_search` + config on → build line `{"ts": <isoformat with microseconds>, "query", "scope", "projectId", "workspaceId": <arg or null>, "result": <parsed tool result, or {"raw": result} if it is not valid JSON>, "usefulness": null, "note": null}` → append to the log → stash pending ask keyed by resolved project path (last-wins, same semantics as the commit reminder's `pending.json`, separate file `~/.ai-badger/memory-grade/pending.json` so the two features never touch each other's schema).
2. `pre_llm_call` pops the ask and injects **one short line** (Hermes). Claude's PostToolUse hook emits the same line as `additionalContext` directly (no stash needed — the hook process returns it into the next turn).
3. The agent runs the helper. Injection text (single line, embeds the helper's absolute path — computed from `__file__` at import, so each deployment shape points at its own copy):

   ```
   [ai-badger] Rate that memory_search's usefulness 1-5 (5=best, or skip): python3 <path>/memory_grade.py grade <ts> <1-5> [note]
   ```

   `<ts>` is the line's exact `ts` value (the pointer; unique per line).
4. `memory_grade.py grade <ts> <1-5> [note]` validates grade ∈ 1..5 (guard, exit 1 otherwise), finds the line by exact `ts` (exit 1 with a clear message if absent), rewrites the file with `usefulness`/`note` filled. Unanswered asks leave `usefulness: null` — honest dogfooding data, and the full line is never lost.

One line per search is preserved because the hook writes the line and the helper only mutates it.

## 5. Work packages (TDD — failing test first, then code)

Every package: RED test(s) → implementation → green → gate. Gates: `python3 -m pytest -q`, `python3 tooling/index_build.py --check`, `python3 tooling/validate.py --all`, `python3 gates/scaffold_freshness_guard.py`. Tests follow `tests/test_commit_reminder_hermes.py` conventions (`load_script` fixture, monkeypatched home/log paths, stubbed siblings).

**WP1 — Matcher + config gate.** Files: `tests/test_memory_grade_matching.py`, `tests/test_memory_grade_config.py`, `features/common/skills/ai-raccoon-memory/scripts/memory_grade.py`.
- RED: `test_namespaced_mcp_name_matches` (`mcp__ai_raccoon__memory_search`, `mcp__ai-raccoon__memory_search`), `test_colon_form_matches` (`ai-raccoon:memory_search`), `test_bare_name_matches`, `test_non_memory_tools_never_match` (`memory_write`, `memory_stats`, `terminal`, `write_file`, `mcp__code_review_graph__get_prompt`), `test_disabled_by_default` (no env → no log write, no pending write, no injection), `test_enabled_by_ai_badger_memory_grade_1`, `test_garbage_value_is_off`.
- Acceptance: matcher true iff bare name is `memory_search`; config on iff env exactly `1`; disabled path does zero IO.
- Gate: `python3 -m pytest -q tests/test_memory_grade_matching.py tests/test_memory_grade_config.py`.

**WP2 — JSONL append at post_tool_call (Hermes).** Files: `tests/test_memory_grade_log.py`, `features/common/hooks/ai_badger_hooks.py` (new `_maybe_log_memory_grade` called from `post_tool_observer`, sibling import like `_load_commit_reminder`).
- RED: `test_search_call_appends_one_line_with_all_fields` (args `{projectId, query, scope, workspaceId}`, result JSON → line has `ts/query/scope/projectId/workspaceId/result/usefulness:null/note:null`), `test_missing_workspace_id_logs_null`, `test_result_not_json_logs_raw_payload`, `test_non_search_tool_writes_nothing`, `test_disabled_config_writes_nothing`, `test_line_shape_matches_manual_jsonl` (keys are a superset of the two lines in `docs/work/2026-08-05-ai-raccoon-memory-quality.jsonl`).
- Acceptance: exactly one line per search; full result preserved; log file created lazily (mkdir -p).
- Gate: `python3 -m pytest -q tests/test_memory_grade_log.py`.

**WP3 — Grade round-trip (Hermes stash/pop).** Files: `tests/test_memory_grade_roundtrip.py` (same shape as `test_commit_reminder_hermes.py`).
- RED: `test_search_stashes_pending_ask_keyed_by_project`, `test_ask_injected_once_on_next_pre_llm_call` (ask text present in `result["context"]`), `test_ask_not_injected_a_second_time` (pop-once), `test_ask_injection_is_inert_when_disabled`, `test_ask_contains_helper_command_and_ts`.
- Acceptance: inject-once per search, one line of text, never injected when off.
- Gate: `python3 -m pytest -q tests/test_memory_grade_roundtrip.py`.

**WP4 — Helper grade fill.** Files: `tests/test_memory_grade_helper.py`, extend `memory_grade.py` CLI (`grade`, `probe`).
- RED: `test_grade_fills_the_matching_line_in_place`, `test_other_lines_unchanged_byte_for_byte`, `test_grade_out_of_range_exits_1_and_changes_nothing` (0, 6, `x`), `test_unknown_ts_exits_1_with_message`, `test_probe_prints_state_and_log_path`.
- Acceptance: after fill the line carries `usefulness` + `note`; file remains valid JSONL; validation is a guard, not a hand-rolled chain.
- Gate: `python3 -m pytest -q tests/test_memory_grade_helper.py`.

**WP5 — Claude hook + manifest wiring.** Files: `tests/test_memory_grade_claude_hook.py`, `tests/test_hooks_manifest_agent_coverage.py` (passes only once the manifest names all three agents), `features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py`, `features/common/hooks/hooks-manifest.json`, `features/common/hooks/hooks.json`.
- RED: `test_claude_hook_stdin_payload_appends_line_and_emits_additional_context` (drive `main()` with a `tool_name=tool_input=tool_response` payload), `test_claude_hook_silent_on_non_search_or_disabled`, `test_manifest_lists_all_three_agents` (the real-manifest gap test goes red before the entry exists), `test_hooks_json_post_tool_use_wires_the_script` (wiring shape check).
- Acceptance: Claude hook is advisory-only (exit 0, `additionalContext` only); the real manifest has no gaps; the rewrite source wires the script with the `memory_search` matcher.
- Gate: `python3 -m pytest -q tests/test_memory_grade_claude_hook.py tests/test_hooks_manifest_agent_coverage.py tests/test_hook_wiring_claude.py && python3 tooling/validate.py --all`.

**WP6 — Deployment + docs + release.** Files: `tests/test_hermes_plugin_install.py` (extend `SHARED_SKILL_FILES`), `features/hermes/adjustments/adjust_hooks.py`, `features/common/skills/ai-raccoon-memory/SKILL.md`, `VERSION` (0.78.0 → 0.79.0), `docs/changelog/0.79.0-memory-grade-hook.md`.
- RED: `test_adjust_hooks_copies_memory_grade_to_project_and_user_dirs` (fails until `SHARED_SKILL_MODULES` gains the tuple), then the copy code.
- Acceptance: scaffold installs `memory_grade.py` beside `ai_badger_hooks.py` in both destinations; SKILL.md documents enable/disable + log path; changelog entry records the feature and the env var.
- Gate: `python3 -m pytest -q tests/test_hermes_plugin_install.py && python3 tooling/index_build.py --check && python3 tooling/validate.py --all && python3 gates/scaffold_freshness_guard.py && python3 gates/release_guard.py`.

**WP7 — Machine-wide enable + probe on this machine.** No new code; acceptance run only.
- Steps: enable per §2 commands; refresh `~/.hermes/plugins/` via scaffold; run a live `memory_search` in a session; confirm one new line in `~/.ai-badger/memory-grade/memory-quality.jsonl` with `projectId`/`workspaceId` set; answer with `memory_grade.py grade <ts> 4`; confirm the line now carries the grade.
- Acceptance: a graded, correlated line exists in the log with the helper's own `probe` output shown.
- Gate: `python3 ~/.hermes/plugins/memory_grade.py probe` + the graded line in the log.

## 6. Risks

- **Hook flooding** — every `memory_search` = one line + one ask. Accepted for a dogfooding hook, but the ask must not nag: inject-once (stash/pop pops), and the ask text says "or skip". If flooding proves noisy, a per-session cap is a later one-line change (guarded by a session counter, like `_session_hints_shown`).
- **Prompt bloat** — the ask is one short line; the result payload is never injected (it goes to the JSONL at call time; the stash holds only the ask text + ts). Same 300-char discipline as the MCP-hint injection.
- **Result payload size in the stash** — avoided by design: the stash carries no result, only a short ask; the full result is written to disk at call time.
- **Two searches before one LLM turn** — pending ask is keyed per project, last-wins (same as the commit reminder). The earlier line stays logged with `usefulness: null`; that is honest data, not loss.
- **Multi-agent wiring differences** — Hermes has no return channel (stash/pop); Claude returns `additionalContext` from the hook process (no stash). Both share `memory_grade.py` for all logic; only the transport differs, matching the commit-reminder split.
- **Copilot** — wired via the same rewrite, but Copilot's MCP tool naming is unverified; if the matcher never fires there, it is a runtime no-op, not a manifest gap (all agents are wired; no exemption needed).
- **Encrypted banks** — irrelevant here because config is an env var, not a bank read; the hook never touches `memory.db`.
- **Log growth** — one line per search in a user-home file; truncation/rotation is out of scope until it costs something (measure-only-when-it-pays).

## 7. Verification checklist (whole PR)

- [ ] `python3 -m pytest -q` green
- [ ] `python3 tooling/index_build.py --check` green
- [ ] `python3 tooling/validate.py --all` green
- [ ] `python3 gates/scaffold_freshness_guard.py` green
- [ ] WP7 probe shows a graded, correlated line on this machine
- [ ] VERSION bumped, changelog entry added
- [ ] Separate PR, opened only after #302 merges
