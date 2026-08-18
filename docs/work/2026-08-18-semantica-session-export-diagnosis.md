# Semantica session-graph persistence — diagnosis

**Date:** 2026-08-18
**Task:** make Semantica actually get used, and make its graph survive the session
**Author:** Hermes Agent (orchestrator)

## Problem statement

Semantica was integrated as a common MCP server + skill across three tasks (0.116.3–0.116.6,
2026-08-12), but it is **not used**. No session agent records decisions through it, and no graph
snapshot is written anywhere a later session can read it. The owner wants:

1. Every session agent to actually start using Semantica.
2. The session's graph dump to be saved, per session, under a `.semantica/` directory (so
   sessions never overwrite each other).
3. AiRaccoon to watch that directory so the dumps get indexed into durable memory.

## What already exists (verified against source, not memory)

- **Catalog entry** — `features/common/mcp/semantica/` (`meta.json`, `server.md`, `tools.json`
  with 11 tools, `scripts/install.py`, `scripts/check.py`). Declared in
  `features/common/stack-mcp.json` for the common stack.
- **Skill** — `features/common/skills/semantica-knowledge-graph/` (`SKILL.md` +
  `scripts/export_semantica_graph.py`). The export script writes an atomic JSON snapshot to a
  single target path, defaults `.ai-raccoon/semantica-graph.json`.
- **Seed template** — `features/common/templates/semantica-graph.json.tmpl` (shape:
  `version/nodes/edges/decisions/metadata`).
- **ADR-0019** — `docs/adr/0019-semantica-session-graph-export-and-airaccoon-watch.md`:
  export-as-hook + seeded watch bridge. Records the core facts (in-memory per-process graph, no
  `import_graph`, `export_graph` is archival-only).
- **Tests** — `tests/test_semantica_export_hook.py`, `test_semantica_knowledge_graph_skill.py`,
  `test_mcp_semantica_catalog.py`, `test_semantica_mcp_scripts.py` (all green).

## Why it is not used — the four gaps

### Gap 1 — no lifecycle hook wires the export

`features/common/hooks/hooks-manifest.json` has **no Semantica entry** of any kind. The export
script is reachable only if an agent remembers to run it, which none do. The Hermes plugin
(`features/common/hooks/ai_badger_hooks.py` → `register`) registers only `on_session_start`,
`pre_llm_call`, `pre_tool_call`, `post_tool_call` — none of which touch Semantica. The export
path exists as dead tooling.

### Gap 2 — no guidance nudges the agent to use it

The context-enrichment hook (`pre_llm_inject_context`) injects a once-per-session "usage hints"
line and a BM25-driven "Relevant MCP tools" line from `.ai-badger/mcp-tools.json`. There is no
analogous once-per-session "record decisions via Semantica, export at end" nudge, and Semantica
is not in this repo's `mcp-tools.json` index (verified: 0 matches), so the recommender never
surfaces it either.

### Gap 3 — single-file target overrides sessions

`export_semantica_graph.py` defaults to `.ai-raccoon/semantica-graph.json` — one file. Every
export clobbers the previous session's graph. There is no `.semantica/` directory and no
per-session file, so two sessions (or a session and a subagent) destroy each other's dumps.

### Gap 4 — the watch is manual and file-scoped

The ai-raccoon-memory skill's "watch-on-docs" ritual targets the docs directory only; the
Semantica skill's step 4 tells the agent to `memory_watch_add` a single file path. Nothing
registers a watch on a `.semantica/` directory, and nothing ensures a new session's dump file is
picked up.

## Hard constraints that shape the fix

- **The graph lives in the Semantica MCP server process** (single stdio subprocess, in-memory).
  The only actor that can retrieve it is the agent calling `export_graph`; the Hermes hook
  cannot reach the MCP server (it is a peer subprocess, and `on_session_end`/`on_session_finalize`
  fire after it is gone). **Therefore the dump must be captured from the `export_graph` tool
  result, not from a session-end hook.**
- **Hermes plugin ABI** (verified in `hermes-plugin-development` skill): `VALID_HOOKS` includes
  `on_session_end`, `on_session_finalize`, `on_session_reset`, and `post_tool_call`. The
  `post_tool_call` payload carries `function_name`/`function_args`/`session_id` plus the tool
  `result` — so a `post_tool_call` observer can see the `export_graph` result JSON and write it
  to disk itself.
- **Per-session identity** is available as `session_id` in the `post_tool_call` payload.

## Proposed direction (to be planned/reviewed, not final)

1. **`.semantica/` dir + per-session file** — change the export target to
   `.semantica/<session-id>-<ts>.json` (gitignored), keyed by the session id so sessions never
   collide.
2. **Auto-save hook** — a `post_tool_call` observer detects an `export_graph` call and writes its
   result JSON to the per-session file automatically (reusing the export module's atomic write).
3. **Guidance injection** — a once-per-session `pre_llm_call` nudge telling the agent Semantica
   is available and to record decisions + export before finishing.
4. **AiRaccoon watch on `.semantica/`** — register a directory watch (not a file) so new dump
   files are indexed; update the ai-raccoon-memory + semantica skills to cover it.
5. **Update ADR-0019** and the skill to the `.semantica/` per-session design.

Open questions for the planner: whether the watch-on-directory picks up new files incrementally
(ai-raccoon server property to verify); the exact filename scheme; how Claude/Copilot (which have
a real `SessionEnd` hook but the same "can't reach the MCP server" constraint) are covered; and
whether the nudge should also extend the mcp-tools.json index entry for Semantica.
