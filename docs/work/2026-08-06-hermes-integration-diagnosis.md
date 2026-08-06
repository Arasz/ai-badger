# Hermes integration diagnosis (2026-08-06)

Task: diagnose-and-review-hermes-integrations-in-ai-badger.
Trigger: the memory-grade hook's quality log held exactly one (synthetic) line after a
week of machine-wide enablement — organic coverage was 0%. This document explains why.

## Summary

The ai-badger Hermes-side integration is wired as *loose flat `.py` files dropped into
`~/.hermes/plugins/`*. Hermes' plugin loader only accepts **directory plugins** —
`~/.hermes/plugins/<name>/plugin.yaml` + `__init__.py` with `register(ctx)` — and user
plugins are opt-in via `plugins.enabled`. The flat files are invisible to the loader, so
**none of the four "hermes" hook entries in `hooks-manifest.json` has ever fired** in a
Hermes session. The module itself (`ai_badger_hooks.py`) is written correctly against the
Hermes plugin ABI (`register(ctx)`, `ctx.register_hook(...)`, valid hook names) — only the
packaging shape is wrong. The framework's own reference documents the false assumption as
fact (`references/hooks-subsystem.md`: "ai_badger_hooks.py is a plugin loaded from
~/.hermes/plugins/ (loose copies)").

## 1. How the Hermes integration is wired on den refresh

Chain (verified in source):

1. `features/common/skills/den-refresh/scripts/refresh.py` → `re_scaffold()` → loads and
   runs `features/common/skills/welcome-ai-badger/scripts/scaffold.py` with the project's
   existing config.
2. `Scaffolder.run()` → `run_adjustments()` runs every agent adjustment declared in
   `adjustment.json`.
3. `features/hermes/adjustments/adjust_hooks.py` (agent = hermes) copies:
   - into the project: `.ai-badger/hooks/ai_badger_hooks.py`, `mcp_index_hook.py`, plus
     sibling modules (`commit_reminder.py`, `impact_estimator.py`, `memory_grade.py`,
     `tokenizer.py`, `bm25.py`, `mcp_matcher.py`), and
   - into user scope: `~/.hermes/plugins/` — same flat files
     (`USER_PLUGINS = ("ai_badger_hooks.py", "learned_skills_sync.py")` + shared modules),
     plus `~/.hermes/plugins/.ai-badger/manifest.json` recording `frameworkRoot` +
     `copiedFromVersion` (ADR-0009).
4. `features/common/hooks/hooks-manifest.json` declares the hook surface per agent.
   The hermes entries (all `{type: plugin, entry: ai_badger_hooks.py, method: <name>}`):
   - drift-notice → `on_session_start`
   - context-enrichment (mcp-index) → `pre_llm_call`
   - commit-reminder → `post_tool_call`
   - memory-grade → `post_tool_call`
5. `features/common/hooks/ai_badger_hooks.py` ships the plugin entry point:
   `register(ctx)` calls `ctx.register_hook("on_session_start"|"pre_llm_call"|
   "post_tool_call", ...)` with `**kwargs`-tolerant callbacks, gated by
   `COPY_SKEW_REFUSAL` (stale-copy refusal via `badger_lib.copy_skew`).

The same chain runs on every fresh `welcome-ai-badger` scaffold, not only on
den-refresh; and the scaffold-freshness guard re-runs the hermes adjustment (with a
*temp* framework root) on every commit — see §3, last bullet.

## 2. Root cause: deployment shape vs. the Hermes plugin ABI

Hermes plugin contract (verified in `~/.hermes/hermes-agent/hermes_cli/plugins.py`):

- Discovery sources include `~/.hermes/plugins/` (user plugins), scanned by
  `_scan_directory`, which **skips anything that is not a subdirectory containing
  `plugin.yaml`/`plugin.yml`** ("if not child.is_dir(): continue"). Flat `.py` files are
  never even considered.
- Each directory plugin must contain a `plugin.yaml` manifest **and** an `__init__.py`
  exposing `register(ctx)`; callbacks are registered via `ctx.register_hook(name, cb)`
  for names in `VALID_HOOKS` — which includes `on_session_start`, `pre_llm_call`,
  `post_tool_call`, `pre_tool_call` (plugins.py:135-160).
- User plugins are **opt-in**: "None = opt-in default (nothing enabled)"; a manifest not
  listed in `plugins.enabled` is recorded but not loaded (plugins.py:1476-1490).

`adjust_hooks.py` deploys flat files directly into `~/.hermes/plugins/`. Result:

- `_scan_directory` finds 0 manifests → `register()` is never called → all four hermes
  hook entries in `hooks-manifest.json` are dead declarations.
- The ABI knowledge inside `ai_badger_hooks.py` is correct — the module was written as a
  plugin, then packaged as a loose file. The gap is purely the delivery shape (no plugin
  directory, no `plugin.yaml`, no `__init__.py`, no `plugins.enabled` registration).

## 3. Empirical evidence (2026-08-06)

- `~/.hermes/plugins/` has no `__pycache__` for `ai_badger_hooks.py`/`memory_grade.py` —
  Hermes never imported them (all other loaded Hermes modules leave pycache).
- `~/.hermes/logs/agent.log*` mentions `ai_badger_hooks` only in lint (pyright) and a
  blocked-command log — never as plugin execution.
- Live test: a real `memory_search` via the Hermes MCP client (projectId=ai-raccoon,
  ranking 1.0 hit) while `AI_BADGER_MEMORY_GRADE=1` is set in the shell appended **no
  line** to `~/.ai-badger/memory-grade/memory-quality.jsonl`.
- The quality log's single line ("live probe wp7", 2026-08-05T19:11:59Z) was produced by
  direct helper invocation, not by a live host: no `memory_search` tool_use exists in any
  Claude Code transcript (`~/.claude/projects/`), and Hermes never loads the plugin.
  WP7's "live probe" verified the helper pipeline (log → grade round-trip), not that any
  agent host fires the hook.
- `~/.hermes/plugins/.ai-badger/manifest.json` records
  `frameworkRoot: /private/var/folders/.../T/scaffold-freshness-9o5qq72q/work` — a temp
  dir. The scaffold-freshness guard (pre-commit, every commit) re-runs the hermes
  adjustment with a temp root and **writes real user-home files as a side effect**, so
  the recorded "where did this copy come from" pointer is garbage after the first commit.

## 4. Impact

- All four Hermes-side hooks are dead: no drift-notice, no mcp-index context enrichment,
  no commit reminders, no memory-grade logging in Hermes sessions (the host the owner
  uses for most sessions).
- The memory-grade telemetry feature — built to answer "is memory search useful?" — has
  zero organic data points; its only log line is a verification artifact.
- Claude/Copilot sides are wired correctly (hooks.json / hooks.json entries); Claude
  simply has not invoked `memory_search` in a session since deployment, so nothing was
  logged there either.

## 4a. Relationship to prior findings (2026-08-02-hermes-task-tracking.md)

`docs/work/2026-08-02-hermes-task-tracking.md` already established that the four
task-tracking hooks are Claude-only by design and that the tracker's checkpoints are
all-zero under Hermes. Its F3 treated the installed plugin as loaded: "Its `register()`
registers exactly three hooks: `on_session_start` ..., `pre_llm_call` ..., `post_tool_call`
..." — that was a reading of the file's contents, not of runtime behavior. This diagnosis
subsumes F3's premise: the plugin never loads in the first place, so none of the three
hooks it registers (drift-notice, context-enrichment, commit-reminder) — nor the
memory-grade hook added since — has ever executed in a Hermes session. The task-tracking
gap documented on 2026-08-02 is therefore a special case of the deployment-shape bug, not
a separate limitation, and the "possible follow-up" of a Hermes plugin hook for per-turn
checkpoints depends on the same fix as everything else: a properly packaged, enabled
Hermes plugin.

## 5. Fix direction (follow-up task, deliberately out of scope here)

1. Ship a real directory plugin: `~/.hermes/plugins/ai-badger/` with `plugin.yaml`
   (`name: ai-badger`, `hooks: [on_session_start, pre_llm_call, post_tool_call]`) and
   an `__init__.py` that imports `ai_badger_hooks.py`'s `register` (or a thin wrapper).
   The lazy sibling-import machinery (`_load_commit_reminder` etc. resolve
   `Path(__file__).parent`) requires the sibling modules to land **inside the plugin
   dir** — the existing `SHARED_SKILL_MODULES`/`RETRIEVAL_MODULES` copy lists already
   carry them; only the destination changes.
2. Register the plugin in `plugins.enabled` (via `hermes config set` /
   `hermes plugins enable ai-badger` — user plugins are opt-in by design). Decide who
   runs it: scaffold prints the instruction, or the adjustment edits config (needs a
   Hermes-owned mechanism, not a hand edit).
3. Re-verify with the gate WP7 was missing: a real `memory_search` inside a live Hermes
   session must append a line with `projectId`/`workspaceId`, then the grade round-trip
   must fill it in place.
4. Update `references/hooks-subsystem.md` (correct the "loose copies" claim), the
   `adjust_hooks.py` docstring, and `tests/test_hermes_plugin_install.py` (assert the
   plugin-dir shape, not just the copy lists).
5. Decide the freshness-guard side effect: either accept + document that every commit
   refreshes `~/.hermes/plugins/` (it does), or make the guard skip the user-scope
   adjustment when the root is a temp dir.

Evidence file: this document. Companion: the memory-skill design review produced by the
review subagent (same docs/work directory).
