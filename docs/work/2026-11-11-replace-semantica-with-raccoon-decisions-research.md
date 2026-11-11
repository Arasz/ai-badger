# Replace semantica with ai-raccoon decisions — research record

**Date:** 2026-11-11
**Task:** `aib-replace-semantica-with-raccoon-decisions`
**Grades:** MEASURED (ran it), READ (read the source), INFERRED, UNVERIFIED.

## 1. The ai-raccoon decision feature (ai-raccoon 2.5.1)

| Finding | Grade | Source |
|---|---|---|
| MCP tools: `register_decision_task`, `record_decision`, `amend_decision`, `transition_decision`, `supersede_decision`, `link_decisions`, `unlink_decisions`, `get_decision`, `query_decisions`, `find_decision_precedents`, `get_decision_graph`, `export_decisions`, `preview_decisions`. | READ | MCP tool schemas in this session |
| Every write takes `projectId`, `taskId`, `sessionId`, `requestId`. A resend with the same `requestId` replays the first result. A task must be registered before its first decision. | READ | `record_decision` / `register_decision_task` schemas |
| A decision has title, category, scenario, outcome, reasoning, optional alternatives, consequences, sources, confidence, maker, validFrom/validUntil. Status: proposed, accepted, rejected, superseded, deprecated. Content changes make a new version (`amend_decision`, optimistic `expectedVersion`). | READ | schemas |
| Edges: `depends_on`, `supports`, `contradicts`; `supersedes` is made only by `supersede_decision` and is permanent. | READ | `link_decisions` / `unlink_decisions` schemas |
| CLI twin: `ai-raccoon decisions {task register, record --input <json>, get, query, export, preview}`. `export` writes JSON (lossless) or Markdown, atomically with `--output`. | MEASURED | `ai-raccoon decisions <cmd> --help` |
| Live round trip: task registered and decision `01a1cad6-300c-7550-bb94-2405e571c3db` recorded; both read back through `ai-raccoon decisions query/preview/export`. | MEASURED | CLI output 2026-11-11 |
| **Defect:** `register_decision_task`, `record_decision`, `get_decision`, `query_decisions`, `find_decision_precedents` commit on the server, but Claude Code rejects the reply: "Structured content does not match the tool's output schema: … must have required property 'nextAfterId' / 'sourceRef' / 'changeReason'". The fields are null and the schema declares them required. `preview_decisions` returns cleanly. | MEASURED | MCP calls 2026-11-11 |

## 2. What semantica occupies in ai-badger

| Area | Paths | Grade |
|---|---|---|
| MCP catalog entry | `features/common/mcp/semantica/` (meta, server.md, tools.json, check/install/wrapper scripts); `features/common/stack-mcp.json` entry | READ |
| Skill + hooks | `features/common/skills/semantica-knowledge-graph/` (SKILL.md, `export_semantica_graph.py`, `semantica_export_autosave_hook.py`); `hooks-manifest.json` `semantica-export-autosave`; `hooks.json` export_graph matcher; `features/common/templates/semantica-graph.json.tmpl` | READ |
| Prompt nudge | `NUDGE_LINE` in `features/common/retrieval/context_enrichment.py`, emitted by `features/common/skills/mcp-index/scripts/context_enrichment_hook.py` and Hermes `features/common/hooks/ai_badger_hooks.py`; stored in the `semantica_nudge` family of `engine/badger_store.py` (and its vendored copies) | READ |
| Hermes install list | `features/hermes/adjustments/adjust_hooks.py` `SHARED_SKILL_MODULES` (twin: `tests/test_hermes_plugin_install.py`) | READ |
| Dependency | `engine/requirements.txt` `semantica>=0.6.8` (wrapper guard only) | READ |
| Retrieval eval corpus | `features/common/retrieval/eval/eval_index.json` semantica server | READ |
| Prose | task SKILL reflect step, qa `related_skills`, ai-raccoon-memory `.semantica/` watch paragraph, task `file-schemas.md` nudge rows, CONTRIBUTING, SECURITY, getting-started, scripts, framework-architecture, skills.md, data-access.md | READ |
| Generated output | `skills/**` (sync_plugin_skills), `.ai-badger/**` and root agent files, `.claude/settings.json`, `.codex/config.toml`, `.github/mcp.json`, `.github/hooks/*`, `.pi/mcp.json`, `index.json` | READ |
| Tests | 6 semantica-only test files to delete; ~15 test files with semantica cases or fixture names | READ |
| ai-raccoon catalog | `features/common/mcp/ai-raccoon/{tools.json,server.md,meta.json}` list no decision tools | READ |
| ADRs | ADR-0019 is about semantica and must be superseded; 0024/0039 only mention it. Next free number 0048. | READ |

## 3. Owner decisions (2026-11-11)

1. Fold decision guidance into `ai-raccoon-memory`, the ai-raccoon catalog entry and `decision-record`; no new skill.
2. Delete the semantica nudge and its store family.
3. Proceed despite the schema defect; document the CLI read-back and same-`requestId` retry.
4. Keep history: `docs/work/**`, `docs/changelog/**` untouched; ADR-0019 marked superseded.
5. Pre-1.0 removal of a shipped feature: minor bump to 0.218.0.

## 4. Open / unverified

- Whether `sync_plugin_skills.py` prunes a deleted skill directory.
- Whether retrieval fixtures expect a semantica tool.
- How the `badger_store.py` vendored copies are kept identical.
- Consumers keep stale `.semantica/` dirs and `semantica` entries in user-edited MCP configs; generated configs drop it on re-scaffold.
