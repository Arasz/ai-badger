# Semantica session-graph persistence — MoE synthesis

**Date:** 2026-08-18
**Task:** semantica-session-export (#414–#417)
**Reviewed plan:** `docs/work/2026-08-18-semantica-session-export-plan.md`
**Code-reviewer verdict:** APPROVE-WITH-FIXES (7 findings)
**Test-engineer verdict:** APPROVE-WITH-FIXES (7 findings)
**Consensus:** APPROVED with the fixes below folded into the plan.

## Folded findings (each resolved)

1. **HIGH — extract_graph_json envelope (code-reviewer F1, test-engineer F6).** Hermes' `post_tool_call` passes the MCP tool result as a wrapped, double-encoded JSON string: `{"result": "<graph-json-as-escaped-string>"}` (text-block case) or `{"result": {<graph>}}` (structuredContent case). The contract is now: parse outer JSON → `error`/`isError` key → `None` → `result` key: re-parse when `str`, passthrough when `dict` → `structuredContent` (dict) → else passthrough. Drop `_meta`. The double-encoded case is the PRIMARY test shape. (The speculative `data`/`content` keys are dropped.)

2. **HIGH — watch-is-creation-triggered premise was FALSE (code-reviewer F2).** AiRaccoon's watcher (`NotifyFilter = FileName|DirectoryName|LastWrite`; Created/Changed/Deleted/Renamed handlers; digest re-ingests on content-hash mismatch) DOES re-ingest in-place overwrites. The timestamped filename is kept — for **session-collision prevention and a durable per-session archive** (issue #414's actual requirement), not because overwrites are missed. ADR-0019 rationale corrected accordingly; the N-snapshot accumulation is acknowledged as a non-goal.

3. **MEDIUM — `.tmp.<pid>` ingestion (code-reviewer F3).** The atomic-write temp file, under a directory watch, is ingested as junk. Fix: `export_graph` gains a `temp_dir` param (default `target_path.parent`); the autosave path passes `temp_dir=project_dir` so the temp lands outside `.semantica/` (same device, not watched).

4. **MEDIUM — manifest entry (code-reviewer F4).** A new `semantica-export-autosave` `hooks-manifest.json` entry (hermes → `post_tool_call`) with `claude`/`copilot` exemptions in `tooling/validate.py`'s `HOOKS_MANIFEST_AGENT_EXEMPTIONS` ("PostToolUse exists but the port is deferred — #418"), so the Hermes-only nature is declared, not silently missing (issue #147's failure shape).

5. **LOW — `.gitignore` is framework-scoped only (code-reviewer F5).** `.semantica/` is a consumer-local staging dir (the durable record lives in ai-raccoon memory, not the repo). The framework `.gitignore` gets `.semantica/`; the SKILL/ADR tell consumers to gitignore it in their own repo.

6. **LOW — index load + source match (code-reviewer F6, test-engineer F5).** `_load_mcp_index(project)` is currently inside `if prompt:`; the nudge must hoist its own load above that guard (and fire on an empty-prompt turn 1). Source match is by exact name or last-token `== "semantica"`, not substring (no `semantica-fork` false positive); the exact value is resolved against the real index during U4.

7. **LOW — `is_export_graph` generality (code-reviewer F7).** Keep the final-segment match (consistent with `_is_memory_search`); add a comment noting `export_graph` is generic and a future server could false-positive. No server-segment guard (over-engineering for a LOW).

8. **Test — shipping-list parity (test-engineer F1).** `test_hermes_plugin_install.py`'s hand-maintained `SHARED_SKILL_FILES` must gain the new entry AND a parity test `set(SHARED_SKILL_FILES) == set(adjust_hooks.SHARED_SKILL_MODULES)` (derive-or-delete).

9. **Test — ai-raccoon-memory SKILL has no allocated test (test-engineer F2).** The `.semantica/`-naming body check goes in `tests/test_common_ai_raccoon_mcp_server.py`.

10. **Test — sync gate (test-engineer F3).** U4's gate list adds `python3 tooling/sync_plugin_skills.py --check` (root `skills/` derived copies).

11. **Test — usage-gate membership (test-engineer F4).** Migrate the usage gate from emptiness (`if not _session_hints_shown:`) to membership (`"usage" not in _session_hints_shown`) before adding the `"semantica"` key, so the two hints are genuinely independent; pin with a test that both are once-per-session and both cleared by `reset_session_hints()`.

12. **Test — `_now_slug` uses `time.time_ns()`** (test-engineer F7) instead of microsecond `strftime`, eliminating the same-microsecond flake.

## Follow-up created

- **#418** — port Semantica auto-save + nudge to Claude/Copilot (`PostToolUse`/`postToolUse` sees the result; `context_enrichment_hook.py` for the nudge). Referenced by the manifest exemptions.
