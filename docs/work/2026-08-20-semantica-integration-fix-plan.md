# Semantica integration fix — plan (2026-08-20)

Task: `semantica-integration-fix` (ai-badger repo). User f:: fix bugs, wire all agents
(claude/copilot/hermes), distribute+enable by default, TDD + MoE review, PR + merge to
ai-badger, then den-refresh in ai-raccoon and welcome-ai-badger user-level update.

## Evidence (all verified live today)

E1. Semantica MCP server configured and enabled in `~/.hermes/config.yaml` (uv tool
    0.6.5, 12 tools). `get_graph_summary` → 0 nodes, 0 decisions: the live graph is empty.
E2. **Upstream bug B1 (json branch):** `semantica/mcp_server/__init__.py::_tool_export_graph`
    calls `JSONExporter().export(graph)` but `export(self, data, file_path, ...)` requires
    `file_path` → `{"error": "JSONExporter.export() missing 1 required positional argument:
    'file_path'"}`. Reproduced: MCP call, direct python call, and the 0.6.6 wheel + GitHub
    main source — all identical. 0.6.6 changelog does not mention it.
E3. **Upstream bug B2 (all RDF formats):** `RDFExporter().export_to_rdf(...)` prints a rich
    progress bar (`🔄 Semantica is exporting: ...`) to **stdout**. Over stdio MCP that
    corrupts the JSON-RPC framing → client times out (observed: `export_graph(format=json-ld)`
    timed out at 300s; direct call returns in <1s).
    Consequence: every `export_graph` format is broken over MCP in 0.6.5/0.6.6 (json → error,
    json-ld/turtle/nt/xml → hang). The whole persistence bridge is dead until this is fixed.
E4. **ai-badger hook bug B3 (proven live):** `autosave_export` wrote an error payload as a
    graph dump: `.semantica/20260820_124238_0c31b7-*.json` contains
    `{"error": "...", "metadata": {...}}`. Root cause: `extract_graph_json` unwraps the Hermes
    `{"result": "<json>"}` envelope and checks `error` only on the OUTER dict; an inner
    `{"error": ...}` passes through as a valid graph dict.
E5. No `.semantica/` watch: `memory_watch_status` → only `.ai-badger/mcp-tools.json`
    (Scanning) and `docs` (Healthy). The old `.ai-raccoon/semantica-graph.json` (Aug 13,
    empty) was never watched either.
E6. Stale project copies (ai-raccoon): installed `semantica-knowledge-graph` skill still the
    old file-scoped `.ai-raccoon/semantica-graph.json` pattern (framework has per-session
    `.semantica/<session>.json`); installed `ai-raccoon-memory` skill lacks the `.semantica/`
    watch step the framework copy has (framework `features/common/skills/ai-raccoon-memory/
    SKILL.md:32-34`); project `.ai-badger/hooks/ai_badger_hooks.py` has zero semantica code
    (the live Hermes plugin at `~/.hermes/plugins/ai-badger/` does — that is what nudges).
E7. `hooks-manifest.json` `semantica-export-autosave` wires **hermes only**; claude/copilot
    blocks absent (deferred #418). No semantica nudge exists for claude/copilot.
E8. Scaffold: `stack-mcp.json` declares semantica with `declare: true` + availability gate
    on `semantica-mcp` — distributed by default for the mcp stack; claude `.mcp.json` +
    settings approval flow exists; hermes adjust_mcp only proposes (ADR-0014, never writes
    user-global config); copilot proposes only. Version floor: `uv tool install semantica`
    installs the broken 0.6.5/0.6.6; check.py has no version floor and no functional probe.

## Units of work

### U0 — Upstream fix, semantica-agi/semantica (fork + PR, not mergeable here)
Fix `_tool_export_graph`:
- json branch: serialize to a string (`json.dumps(graph, indent=2, ensure_ascii=False)`
  or the exporter's internal conversion) instead of `JSONExporter().export(graph)`.
- all branches: suppress/redirect the progress tracker's stdout output so stdio MCP framing
  survives (redirect stdout to stderr for the duration of the export in the handler, or
  thread a progress-disable flag through `export_to_rdf`).
Test: unit test calling `_tool_export_graph({"format": "json"})` and `{"format": "json-ld"}`
asserting string results and no stdout pollution (capsys).

### U1 — ai-badger: reject error payloads in autosave (TDD)
`export_semantica_graph.py::extract_graph_json`: after unwrapping the envelope, also return
None when the inner dict carries `error`/`isError`.
Tests (RED first):
- `{"result": "{\"error\": ...}"}` → autosave writes nothing, returns None.
- `{"result": "{\"format": "json", "data": {...}}"}` → still saved (regression guard).
- existing valid double-encoded test stays green.

### U2 — ai-badger: wire claude + copilot (#418)
- `hooks-manifest.json` `semantica-export-autosave` gains:
  - claude: `hooks-json` `PostToolUse` → a thin stdin-JSON shim
    (`features/common/skills/semantica-knowledge-graph/scripts/semantica_export_autosave_hook.py`)
    that reads the PostToolUse JSON payload, extracts tool name/result/session, and calls
    `autosave_export`.
  - copilot: `hooks-json` `postToolUse` → same shim.
- Nudge for claude/copilot: add a semantica nudge line to `context_enrichment_hook.py`
  (UserPromptSubmit, mirrors the hermes pre_llm_inject_context nudge, index-gated).
- Tests: manifest validation (both blocks present), shim unit test with a fake PostToolUse
  JSON payload (valid export writes a dump; error result writes nothing).

### U3 — ai-badger: version floor + default distribution
- `meta.json`, `install.py`, `check.py`, `convert_mcp_prerequisites.py`: floor at
  `semantica>=0.6.7` (the release carrying U0) — install/check fail with an actionable
  message when older.
- `check.py`: add a functional probe that imports the installed semantica and verifies
  `_tool_export_graph`-style json export works (catch the 0.6.5/0.6.6 breakage with a
  message pointing at the fix).
- Confirm semantica stays declared by default in `stack-mcp.json` (already true) and add a
  test pinning that (guard against accidental removal).

### U4 — docs + changelog + VERSION
- SKILL.md gotchas: document the upstream export_graph bug + fixed version requirement.
- Changelog entry + VERSION bump (0.130.0).

### U5 — after merge (ai-raccoon repo)
- `den-refresh` in ai-raccoon (updates installed skills/hooks/HERMES.md).
- Register the `.semantica/` directory watch via `memory_watch_add`; gitignore `.semantica/`;
  delete the error dump file created by today's live test.
- User-level Hermes update via welcome-ai-badger / `tooling/sync_plugin_skills.py` so the
  plugin at `~/.hermes/plugins/ai-badger/` carries U1/U2.

## Gates
- U1: RED (error payload saved) → GREEN (nothing written); regression suite green.
- U2: manifest validation green; shim tests green.
- U3: check.py probe fails on 0.6.5, passes on fixed version (unit-tested with a fake).
- Whole repo: `python3 -m pytest -q` green; `tooling/validate.py --all` green; pylint clean.
- CI lanes green on the PR.
