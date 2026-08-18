# Semantica session-graph persistence — implementation plan

**Date:** 2026-08-18
**Task:** semantica-session-export (issues #414–#417)
**Synthesized from:** 2 parallel MoE planning lanes (architect + test-engineer)
**Status:** PLAN (pending MoE review)

## Scope

Make Semantica actually get used, and make its per-session graph survive the session:

- **#414** — per-session graph file under `.semantica/` (stop the single-file `.ai-raccoon/semantica-graph.json` override).
- **#415** — auto-save the graph dump from the `export_graph` MCP tool result via a Hermes `post_tool_call` observer.
- **#416** — nudge every session agent to record decisions via Semantica and export before finishing.
- **#417** — ai-raccoon watches the `.semantica/` directory (one-time per-project).

## Verified constraints (checked against source)

1. The graph lives in the Semantica MCP subprocess; only the agent's `export_graph` call can retrieve it. Hermes `on_session_end`/`on_session_finalize` fire after the subprocess is gone → capture from the `export_graph` **tool result** via `post_tool_call`.
2. Hermes `post_tool_call` payload carries `function_name`/`function_args`/`result`/`session_id`, no `cwd`. `post_tool_observer` already normalizes these.
3. AiRaccoon's file-watcher (`WatchService.AddAsync` accepts a directory; `WatchEventSource` + catch-up ingest **newly created** files) → a directory watch on `.semantica/` ingests each new dump; the watch is **creation-triggered**, which dictates the filename scheme.
4. The hook runs in Hermes' process and has **no ai-raccoon client** → watch registration is an agent ritual, never a hook action.
5. `test_hooks_manifest_agent_coverage.py` forces every `hooks-manifest.json` entry to name all three agents or carry a real exemption → avoid adding a Hermes-only manifest entry for a deferred port.
6. `adjust_hooks.py` ships hook siblings via `SHARED_SKILL_MODULES` (skill scripts copied beside `ai_badger_hooks.py` in both `.ai-badger/hooks/` and `~/.hermes/plugins/ai-badger/`).

## Design decisions (synthesis — disagreements resolved)

### D1 — Per-session filename: `.semantica/<session_id>-<timestamp>.json`

- Sanitized session id (`[A-Za-z0-9._-]`, else `_`) + microsecond UTC slug (no `:`).
- **Timestamped, not stable**, because the watch is creation-triggered: a stable filename would make every re-export overwrite the same file and the watch would silently miss the final (complete) dump. Timestamp converts "overwrite" into "append a snapshot".
- `session_id` None/empty → timestamp-only filename. Still unique.
- Export script default moves off `.ai-raccoon/semantica-graph.json` to `.semantica/`.

### D2 — Auto-save reuses `export_semantica_graph.py` (no new module)

**Resolution:** the architect's reuse wins over the test-engineer's "new `semantica_autosave.py`". The test-engineer's premise ("the export script is not a plugin sibling") is wrong: adding it to `SHARED_SKILL_MODULES` makes it a sibling post-copy, exactly like `memory_first_gate.py`/`commit_reminder.py`. A second module with a duplicate atomic write is the hand-maintained-copy anti-pattern the repo's derive-or-delete invariant forbids — it would need a byte-parity test to stop the two writers drifting. One writer, no drift test.

**Refinement from the test-engineer (adopted):** the auto-save path must **skip, never seed-write**, on error. The CLI's `export_graph(raw_json=…)` falls back to `DEFAULT_SEED` on bad JSON — correct for the CLI, wrong for auto-save (an error payload must not be written as a junk graph). So auto-save validates first and only writes a valid dict.

New functions in `features/common/skills/semantica-knowledge-graph/scripts/export_semantica_graph.py` (stdlib-only):

```
SEMANTICA_DIR = ".semantica"
is_export_graph(tool_name) -> bool          # mirror _is_memory_search normalization
_sanitize_segment(value) -> str
_now_slug() -> str                          # %Y%m%dT%H%M%S%f, no ':'
session_export_target(session_id, project_dir) -> Path
extract_graph_json(result) -> dict | None   # dict passthrough | JSON-string parse | None on
                                            #   isError/error payload, non-JSON, non-dict
autosave_export(tool_name, result, session_id, project_dir) -> Path | None
                                            # gate on is_export_graph, extract_graph_json,
                                            # then export_graph(data_dict=…, target=…)
```

`export_graph(target_path, raw_json, data_dict)` stays the single atomic writer.

### D3 — Auto-save wiring (in `ai_badger_hooks.py`)

- `SEMANTICA_EXPORT_MODULE_NAME = "ai_badger_semantica_export"`; `_load_semantica_export()` via `_load_sibling_module(…, "export_semantica_graph.py", …)`.
- `_maybe_autosave_semantica(tool_name, result, session_id, cwd)` calls `module.autosave_export(…)`.
- One guarded `try/except` block in `post_tool_observer` (alongside commit/memory/follow-through), logging a warning on failure. Fail-open: a missing/broken sibling writes nothing and raises nothing.
- **Shipping:** add `("semantica-knowledge-graph", "export_semantica_graph.py")` to `adjust_hooks.py`'s `SHARED_SKILL_MODULES`.

### D4 — Guidance nudge (in `pre_llm_inject_context`)

- Reuse `_session_hints_shown` with key `"semantica"` (independent once-per-session; `reset_session_hints()` clears both). Placed after the usage-hints block, **before** the `if prompt:` block so it fires on turn 1 regardless of prompt.
- **Gated** on the MCP index containing a `semantica` source (substring match on `source.name`; index is already loaded in this function). Fail-closed: no index / no semantica → no nudge. Semantica is optional, so an unconditional nudge would teach agents to ignore it (the 0.18.0 failure mode).
- Injected text (one line): `[ai-badger] Semantica is configured: record key decisions via record_decision and call export_graph(format=json) before finishing — dumps auto-save to .semantica/ and are indexed.`

### D5 — No new hooks-manifest entry, no plugin.yaml change

Both behaviours ride already-declared hooks (`post_tool_call`, `pre_llm_call`). A new Hermes-only manifest entry would force claude/copilot exemption ceremony for a deferred port. The manifest entry arrives with the deferred Claude/Copilot port.

### D6 — Claude/Copilot deferred

They share the "SessionEnd is too late" constraint but have a `PostToolUse` event that could see the result. Defer; keep `autosave_export` host-agnostic (takes `tool_name`, `result`, `session_id`, `project_dir`) so the later port is a thin stdin-JSON shim. Track as a follow-up issue.

### D7 — Watch registration is a skill ritual (one-time per project)

Extend the ai-raccoon-memory skill's "watch-on-docs" ritual: on session start, `memory_watch_status(projectId)`; if `.semantica/` isn't watched, `mkdir -p .semantica` then `memory_watch_add(projectId, <abs path to .semantica>)`. Idempotent (re-add is a no-op, persisted ai-raccoon state). The hook cannot do it.

## Units of work (unit = isolated worktree + one PR)

| Unit | Issues | Owns (edits) | Must NOT touch | Order |
|---|---|---|---|---|
| **U1** export module | #414 + #415-core | `features/common/skills/semantica-knowledge-graph/scripts/export_semantica_graph.py`, `tests/test_semantica_export_hook.py`, `.gitignore` | ai_badger_hooks.py, adjust_hooks.py, SKILL.mds, ADR, hooks-manifest.json | wave 1 (parallel) |
| **U3** skills + ADR | #417 + docs | `features/common/skills/semantica-knowledge-graph/SKILL.md`, `features/common/skills/ai-raccoon-memory/SKILL.md`, `docs/adr/0019-*.md`, `tests/test_semantica_knowledge_graph_skill.py` | export script, ai_badger_hooks.py, adjust_hooks.py, .gitignore | wave 1 (parallel) |
| **U2** Hermes wiring | #415-wiring + #416 | `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py`, new `tests/test_semantica_session_export.py` | export script, SKILL.mds, ADR, .gitignore | wave 2 (after U1) |
| **U4** release | all | `VERSION`, `docs/changelog/{v}-{slug}.md`, `.ai-badger/mcp-tools.json` (refresh via `mcp-index update`) | any source/test/skill/docs file | last |

U1 and U3 are disjoint → parallel. U2 consumes U1's functions → serializes after U1. U4 records what the others shipped → last.

## Acceptance criteria (each is a test that can fail)

**U1**
- `is_export_graph` matches `mcp__semantica__export_graph`, `semantica:export_graph`, `export_graph`; rejects `add_entity`, `memory_search`, non-str.
- `session_export_target("sess/1:2", p)` → `p/.semantica/sess_1_2-<ts>.json`; two calls with the same id → different paths; `None` → timestamp-only path.
- `extract_graph_json`: dict passthrough, JSON-string parse, `None` on `isError`/error payload, non-JSON string, non-dict.
- `autosave_export` with a valid result writes a valid `.semantica/` JSON file (metadata.updatedAt stamped); returns `None` for non-export tool, empty result, and error payloads (no seed-write).
- `.gitignore` contains `.semantica/`; CLI `main([])` writes under `.semantica/`, returns 0.

**U2**
- `post_tool_observer(function_name="mcp__semantica__export_graph", result='{"nodes":[…]}, session_id="sess-1")` under `monkeypatch.chdir(tmp)` creates exactly one `.semantica/sess-1-*.json`; non-export tool creates none; missing sibling module raises nothing and writes nothing (fail-open).
- `pre_llm_inject_context` injects the Semantica line once per session, only when the index has a `semantica` source; no index / no source → no line.
- `adjust_hooks.adjust` ships `export_semantica_graph.py` into both `.ai-badger/hooks/` and the plugin dir.

**U3**
- `test_semantica_knowledge_graph_skill.py` green after asserting the SKILL body names `.semantica/` (directory) and the directory watch — not the single-file wording.
- `ai-raccoon-memory/SKILL.md` names `.semantica/` in its watch ritual (structural check + sensitivity companion).

**U4**
- `python3 -m pytest -q` green; `python3 tooling/index_build.py --check` green; `VERSION` bumped; changelog entry references #414–#417; `.ai-badger/mcp-tools.json` contains a `semantica` source (this is what makes the U2 nudge actually fire).

## Test-run minimization (adopted from test-engineer)

- **Local TDD loop** = one test file at a time (`pytest tests/<file>::<test>`), never the full suite.
- **CI owns the blast radius**: push a draft PR per unit; GitHub Actions runs the full suite + lint + build.
- **One new test file** (`tests/test_semantica_session_export.py` for U2); extend `test_semantica_export_hook.py` (U1) and `test_semantica_knowledge_graph_skill.py` (U3). No new test deps.
- Every gate that can fail has a companion sensitivity test (`TestExportHookChecksCanFail` / `TestSkillChecksCanFail` pattern); the primary auto-save test is the one that goes RED if the dispatch line is deleted.

## Non-goals

- Claude/Copilot auto-save + manifest entry (deferred, tracked follow-up).
- `.semantica/` cleanup/retention (the directory is the durable archive by design).
- Requiring `format=json` on the export call (not gated; `raw_unparsed` fallback is only for the CLI).
- Hook-side watch registration (impossible — no ai-raccoon client).
- Collapsing the timestamp if AiRaccoon later adds modification-triggered watch.
