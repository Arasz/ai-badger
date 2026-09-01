# Research record: user-DB message bus (`aib-user-db-message-bus`)

**Date:** 2026-09-01 · **Method:** direct in-session gathering (two delegated research lanes died at the
write step with identical signatures; their transcripts are tee-logs with elided payloads, so this
record was re-gathered directly — every claim below was re-verified in-session against the cited source).
**Companion spec:** `.ai-badger/task-tracking/specs/aib-user-db-message-bus.feature` (zero holes) + `spec.json`.

## Angle 1 — Per-harness hook surfaces (the core unknown) — RESOLVED

The canonical event inventory lives in `features/common/hooks/hooks-manifest.json` (every entry names
its per-agent event). Findings per harness:

### Claude Code
- Events **in use today**: `SessionStart` (drift-notice, session-start-tracking), `UserPromptSubmit`
  (context-enrichment, prompt-markers), `Stop` (task-checkpoint), **`SessionEnd`**
  (task-checkpoint-session-end — `hooks-manifest.json` task-checkpoint-session-end; `hooks.json:44`).
  **Close event exists.** Verified in-tree.
- **Injection mechanism**: the in-repo precedent is
  `features/common/skills/mcp-index/scripts/context_enrichment_hook.py` — a `UserPromptSubmit` hook
  whose JSON response carries additional context; Claude injects `additionalContext` from the hook's
  JSON stdout. Session-start injection rides `SessionStart` stdout (same mechanism family).
- **Payload**: carries `session_id`; cwd via `CLAUDE_PROJECT_DIR` / payload cwd (referenced by
  context_enrichment_hook.py — grep for `CLAUDE_PROJECT_DIR`).

### Hermes
- Wiring: **real plugin directory** `~/.hermes/plugins/ai-badger/` — `plugin.yaml` + `__init__.py`
  re-exporting `ai_badger_hooks.register`; callbacks registered via `ctx.register_hook(name, cb)`
  (`features/hermes/adjustments/adjust_hooks.py`, PLUGIN_INIT at line 78).
- **VALID_HOOKS** (from `.ai-badger/skills/hermes-plugin-development/SKILL.md:43`): `api_request_error`,
  `on_session_start`, **`on_session_end`**, `on_session_finalize`, plus `pre_llm_call`, `post_tool_call`.
  **Close event exists** — `on_session_end` (and `on_session_finalize` for the final flush).
  Non-hook lifecycle callbacks also exist (`on_session_switch`, `on_memory_write`, `prefetch`,
  `sync_turn` — SKILL.md:91) — these are NOT hook-registry events; do not confuse the two lists.
- **Injection**: `pre_llm_call` context injection is a named mechanism (SKILL.md description; payload
  keys documented in the skill). **Payload has no cwd** (SKILL.md: "per-hook payload keys (no cwd)") —
  cwd must come from the session source; precedent: `features/hermes/adjustments/hermes_session_source.py`.

### pi
- Wiring: TypeScript adapter extension (jiti, no plugin.yaml) that **translates pi event shapes into
  Claude-shaped JSON for the existing Python hooks** and maps responses back
  (`features/pi/adjustments/adjust_hooks.py` docstring; adapter at `features/pi/adjustments/adapter/`).
  The bridge today covers **only `tool_call`** (`adapter/hook-bridge.ts:2`).
- **Event inventory** (pi docs, `docs/extensions.md` in the pi install):
  `session_start` (ext. lines 66/398), **`before_agent_start`** (line 535: "Fired after user submits
  prompt, before agent loop. **Can inject a message**" — returns `{message: {customType, content,
  display}}`, chained system-prompt mutation also available), **`session_shutdown`** (line 521).
  **Both start and close events exist**, and the injection seam is first-class (the extension returns
  the message object — no stdout parsing needed).
- **Delivery shape for the bus**: extend `hook-bridge.ts` with `session_start` /
  `before_agent_start` / `session_shutdown` translations; the bridge's child-process pattern
  (`index.ts:83–92`: spawn Python hook, feed Claude-shaped payload, read JSON) is the established
  route to the Python store. `ctx.cwd` and `ctx.sessionId` are available in the adapter (hook-bridge
  `toClaudePayload` at line 239–245).

### Copilot CLI
- Wiring: `hooks-manifest.json` → generates `.github/hooks/ai-badger-hooks.json`
  (`features/copilot/adjustments/adjust_hooks.py`).
- Events **in use today**: `sessionStart`, `userPromptSubmitted`, `preToolUse`, `postToolUse`.
- **Close event: NOT SEEN in any manifest row — HYPOTHESIS** that Copilot CLI lacks a usable
  session-end hook; its sessions' cursors die by the 4-day TTL (the spec's chosen backstop).
  Verify at implementation.

### Cross-harness summary (delivery hook design inputs)
| harness | session start | per-turn delivery | close event | injection |
|---|---|---|---|---|
| Claude Code | `SessionStart` ✓ | `UserPromptSubmit` ✓ | `SessionEnd` ✓ | hook JSON additionalContext (precedent: context_enrichment) |
| Hermes | `on_session_start` ✓ | `pre_llm_call` ✓ | `on_session_end` ✓ | pre_llm_call context injection |
| pi | `session_start` ✓ | `before_agent_start` ✓ | `session_shutdown` ✓ | extension returns message object |
| Copilot CLI | `sessionStart` ✓ | `userPromptSubmitted` ✓ | **unknown (hypothesis: none)** | hooks-JSON response |

## Angle 2 — ai-raccoon cwd resolver — CONTRACT CONFIRMED, NOT SHIPPED

Source: `~/RiderProjects/ai-raccoon/docs/plans/default-projectid-from-cwd.md` (2cda253b).
- **Status: "plan (not started)"** — the bus cannot call it; it codes against the *contract*.
- Contract: seam `ToolGate.RequireAsync` (`src/AiRaccoon/Tools/ToolGate.cs`); `IProjectIdResolver.ResolveAsync`
  → `Resolved(id) | Ambiguous(list) | None`; probe = server process cwd; candidate surface = each
  registered project's **ingest-scope paths** (authoritative) + watch paths (fallback); containment =
  cwd equal or ancestor; ambiguity refuses with candidates; **explicit projectId always wins**.
- **Design implication for the bus**: the bus's Python send/delivery scripts must reproduce the same
  cwd-containment semantics against the same registered-project surface, so bus project ids and
  memory-server project ids are the same space (the seed's sequencing note). Where the raccoon
  persists its registry (settings/registry file) is **HYPOTHESIS** — confirm the exact store location
  at implementation; alternatively planning may scope a minimal registry-reader contract.

## Angle 3 — Schema-upgrade machinery as merged (0.155.0) — MOSTLY BUILT

Source: `engine/badger_store.py` (all line numbers at 0.155.0 / commit e69eb3dc).
- `_ensure_schema_version(conn, db_path)` (lines 351–380): stamps `SCHEMA_VERSION` on fresh DBs;
  **dispatches `UPGRADE_HOOKS[version]` for older DBs inside `BEGIN IMMEDIATE`** with rollback on
  failure; **fail-closed for newer** with the den-refresh pointer naming the exact DB (D27, message
  at lines 363–370).
- `UPGRADE_HOOKS: dict[int, Callable]` — **declared at line 34, currently empty `{}`**. The dispatch
  machinery is live and tested; no migration has ever registered. **The bus registers the first one.**
  Store `SCHEMA_VERSION` is its own counter (live value: **1** — NOT the framework's 0.155.0); the bus
  bumps 1→2 (corrected by the plan-author lane, d-157).
- The queued P1.1c ("eskerda/suckless" `PRAGMA user_version` SQL-first ledger) would formalize
  authoring/verification of migrations; it is NOT built. For the bus this is a decision: register a
  plain `UPGRADE_HOOKS[155]` entry now (mechanism exists) vs build the ledger first. Planning decides;
  the mechanism does not block.
- User-DB surface: `user_db_path()` (line 299; env `AI_BADGER_USER_ROOT` else `~/.ai-badger/ai-badger.db`),
  `open_user_store` → `_open(user_db_path(), "user", USER_FAMILIES)` (line 1670–1671). Existing
  `USER_FAMILIES` (from line 439): `awm_state`, `awm_decisions`, `commit_reminder`,
  `commit_reminder_pending`, `pending_feedback`, `searches` (P1.4). New families `messages` +
  `cursors` follow the same `Family` shape (`table`, `db="user"`, `legacy_path` — none for bus
  tables: they are born in SQLite, no legacy import) + `FILE_SET_KINDS` unchanged (line 626).
- The DDL gate to extend: the sqlite-schema-review gate pattern from P0.6a (subagents-as-JSON ruling);
  `tests/test_new_schemas.py` + `tests/test_schema_self_description.py` are the schema-convention
  tests. `Store.prune_expired(table, max_age_days=60)` (60-day retention pattern) generalizes to the
  4-day messages/cursors TTL — same meta-stamp throttle discipline applies.

## Angle 4 — Repo conventions for the new surface

- **Schema file shape** (`schemas/dependencies.schema.json` as the example): draft 2020-12, `$id`
  `https://github.com/Arasz/ai-badger/schemas/<name>.schema.json`, `title`/`description`, `type:
  object`, `required` + `additionalProperties: false`, per-property descriptions. `message.schema.json`
  follows this shape for `{sender: {sessionId, projectId}, content, timestamp}`.
- **New send skill minimum file set** (D16 governed-copy discipline, enforced by
  `tests/test_badger_store_vendored.py` + the P4 E2E `tests/test_p4_integration.py`):
  `features/common/skills/<name>/SKILL.md` + `scripts/<script>.py`; the script imports a **vendored
  byte-identical `badger_store.py`** copy in the same dir; `.ai-badger/manifest.json` gains the
  governed-copies entry; propagation only via `tooling/sync_plugin_skills.py` + the scaffolder
  (manual `cp` reads as divergence — P4-join lesson); copy-skew test list updated in the same commit.
- **Hook-wiring test patterns**: per-agent rows in `hooks-manifest.json` are asserted by the existing
  adjustment tests; the delivery hook's per-harness wiring follows `task-checkpoint-session-end`
  (Claude `SessionEnd`) and the Hermes plugin `provides_hooks` block (`adjust_hooks.py:64–78`) as
  templates. The context-enrichment hook + its tests are the injection-response precedent.

## Riskiest unknowns

1. **Copilot CLI session-end** — no in-tree evidence of a close event; spec's TTL backstop covers it,
   but the per-harness verification pass must confirm (hypothesis: no close event exists).
2. **Project-id source for Python-side scripts** — the raccoon resolver is unshipped; the bus needs
   the registry surface it can read today. Exact raccoon registry location/format = hypothesis to
   settle at planning (candidate: ai-raccoon settings store, read-only consumer contract).
3. **pi injection latency** — `before_agent_start` runs on every prompt; the delivery read must be
   index-bounded and fail-open (D31) or it taxes every pi turn. The searches lesson (59 ms at 20k
   rows) makes the index a plan-level requirement, not an optimization.
