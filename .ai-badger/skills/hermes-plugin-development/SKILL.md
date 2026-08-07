---
name: hermes-plugin-development
description: Use when writing or debugging Hermes Agent Python plugins.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, plugins, hooks, abi, debugging]
    related_skills: [hermes-agent]
---

# Hermes plugin development

Hermes loads agent plugins as DIRECTORY plugins, not loose `.py` files. Most "my hook
never fires" reports trace to a packaging-shape mismatch. Everything below was verified
against `hermes_cli/plugins.py` in the Hermes source checkout (`~/.hermes/hermes-agent/`),
2026-08-06.

## The ABI (verified)

- **Discovery sources** (plugins.py:1350-1393): bundled `<repo>/plugins/<name>/`; user
  `~/.hermes/plugins/<name>/`; project `./.hermes/plugins/<name>/` (opt-in via
  `HERMES_ENABLE_PROJECT_PLUGINS=1`); pip packages exposing the `hermes_agent.plugins`
  entry-point group. Later sources override earlier on name collision.
- **A directory plugin MUST contain `plugin.yaml` AND `__init__.py` with a
  `register(ctx)` function.** `_scan_directory` skips anything that is not a subdirectory
  containing `plugin.yaml`/`plugin.yml` (`if not child.is_dir(): continue`) — flat `.py`
  files in `~/.hermes/plugins/` are INVISIBLE to the loader. Category layout
  (`<root>/<category>/<name>/plugin.yaml`) is supported, depth capped at two segments.
- **plugin.yaml shape** (example: bundled `plugins/disk-cleanup/plugin.yaml`):
  `name`, `version`, `description`, `author`, `hooks: [<VALID_HOOKS names>]`.
  `kind` defaults to `"standalone"`; unknown kinds warn and fall back.
- **register(ctx)**: callbacks registered with `ctx.register_hook("<hook_name>", cb)`.
  Callbacks must tolerate `**kwargs` (forward compatibility). Declare hook names in the
  manifest's `hooks:` list. `__init__.py` is imported as `hermes_plugins.<slug>` with
  `submodule_search_locations=[plugin_dir]` — so `from .sibling import register` works
  and siblings inside the dir are importable (keep lazy-imported helpers in the dir).
- **VALID_HOOKS** (plugins.py:135-216): `pre_tool_call`, `post_tool_call`,
  `transform_terminal_output`, `transform_tool_result`, `transform_llm_output`,
  `pre_llm_call`, `post_llm_call`, `pre_verify`, `pre_api_request`, `post_api_request`,
  `api_request_error`, `on_session_start`, `on_session_end`, `on_session_finalize`,
  `on_session_reset`, `on_skill_lifecycle`, `subagent_start`, `subagent_stop`,
  `pre_gateway_dispatch`, `pre_approval_request`, `post_approval_response`, plus the
  `kanban_*` task-lifecycle hooks.
- **User plugins are OPT-IN**: "None = opt-in default (nothing enabled)" — a manifest not
  listed in `plugins.enabled` (config) is recorded but NOT loaded. Enable via
  `hermes plugins enable <name>` or `hermes config set plugins.enabled [...]`. Bundled
  `backend`/`platform` plugins auto-load; standalone, user-installed and entry-point
  plugins all require `plugins.enabled`.
- **`invoke_hook` wraps every callback in its own try/except** — a raising callback logs a
  warning and the core loop continues. Callbacks should still self-guard.
- **`pre_llm_call` context injection**: callbacks may return `{"context": "..."}` (or a
  plain string) — it is injected into the USER message, never the system prompt
  (preserves the prompt-cache prefix). Injected context is ephemeral, never persisted.
- **`post_tool_call` has NO return channel into the model context** — the stash/pop
  pattern (disk stash keyed by project path, popped by `pre_llm_call`) is the way to
  inject once.
- **Debugging**: `HERMES_PLUGINS_DEBUG=1` prints verbose discovery logs (scanned dirs,
  parsed manifests, skip reasons, what `register()` registered) to stderr AND
  `~/.hermes/logs/agent.log`.

## Payload keys per hook (the trap)

Callbacks receive `**kwargs`; **no payload carries `cwd`**:

- `post_tool_call` (PLUGIN emitter, `model_tools._emit_post_tool_call_hook`):
  `function_name`, `function_args`, `result`, `session_id`, `task_id`, `tool_call_id`,
  `turn_id`, `api_request_id`, `duration_ms`, `status`, `error_type`, `error_message`,
  `middleware_trace`. Note: the shell-hook spelling (`tool_name`, `args`, `cwd` — see
  `agent/shell_hooks.py` / `hermes hooks test`) is a DIFFERENT surface; plugins get
  `function_name`/`function_args`.
- `pre_llm_call`: `session_id`, `user_message`, `conversation_history`, `is_first_turn`,
  `model`, `platform`.
- `on_session_start`: `session_id`.
- `pre_tool_call`: `tool_name`, `args`, `session_id`, `task_id`, `tool_call_id`.

Adapters must normalize both spellings (`tool_name|function_name`, `args|function_args`)
and derive the project dir via `os.getcwd()` at callback time — matching what the
`pre_llm_call` pop side resolves (`_project_cwd(os.getcwd())`). Keep stash keys and pop
keys symmetric or the round-trip silently misses (test with `monkeypatch.chdir`).

## Memory provider plugins (specialized type)

Memory providers are a SPECIALIZED plugin type, not plain hook plugins: single-select,
routed through `memory.provider` in config.yaml (NOT `plugins.enabled`), auto-detected as
`kind: exclusive`. The interface is the `MemoryProvider` ABC in
`agent/memory_provider.py` — 4 abstract members (`name`, `is_available()`,
`initialize(session_id, **kwargs)`, `get_tool_schemas()`) plus ~14 optional hooks
(`prefetch`, `sync_turn`, `on_session_end`, `on_session_switch`, `on_memory_write`,
`get_config_schema`, `save_config`, `backup_paths`, ...). Registration:
`register(ctx)` → `ctx.register_memory_provider(provider)`. Discovery scans bundled
`plugins/memory/<name>/` and `$HERMES_HOME/plugins/<name>/` (text heuristic:
`register_memory_provider` or `MemoryProvider` in `__init__.py`; bundled wins on
collision; a bare MemoryProvider subclass also loads). Tool schemas are OpenAI
function-calling format; `handle_tool_call` returns a JSON string. The provider runs
IN-PROCESS — no MCP/IPC anywhere in the call path, so a server-backed memory (e.g. an
MCP memory server) plugs in as a thin Python shim. Full ABC surface, per-turn call
points, threading contract, config/CLI surfaces, and a live loader probe:
`references/memory-provider-interface.md`.

## Empirical verification — a plugin file present ≠ a plugin loaded

Never infer execution from file contents (a `register()` body reads as if it runs) or
from a manifest that declares the hook. Check in order:

1. **`__pycache__`**: a loaded plugin module leaves a pycache next to it. Absent pycache
   in `~/.hermes/plugins/` = never imported.
2. **Logs**: `grep <plugin-name> ~/.hermes/logs/agent.log*` for execution lines (logger
   output, "Plugin discovery complete: N found, M enabled") — not lint mentions.
3. **Live probe**: trigger the hook's event and observe its side effect (e.g. run a
   tool with a hook's env on, then confirm the expected side-effect file lands).
4. **Live gate**: hooks load at SESSION START — enabling mid-session changes nothing in
   the current session. Run a fresh `hermes chat -q "<prompt that exercises the hook>"`
   and check the side effect (log line, file, message). A one-shot session is the only
   honest end-to-end probe.
5. For script-hook payload shapes, `hermes hooks test`/`doctor` show `_DEFAULT_PAYLOADS`;
   for the plugin emitter, read `model_tools._emit_post_tool_call_hook`.

## Pitfalls

- **Flat-file deployment = dead plugin.** Loose `.py` files copied into
  `~/.hermes/plugins/` (plus a `.ai-badger/manifest.json` record, say) produce ZERO
  manifests → zero plugins loaded → no hook ever fires, while the module's
  `register(ctx)` + `ctx.register_hook(...)` calls are written correctly against the
  ABI; only the packaging shape is wrong. Forensic signals: the flat modules never
  produce a `__pycache__` entry and never appear in `~/.hermes/logs/agent.log`. Fix
  direction: real directory plugin, `plugins.enabled` registration, and a live-session
  verification gate.
- **Sibling modules must ship INSIDE the plugin directory**: lazy sibling imports resolve
  `Path(__file__).parent` — a module that loads a sibling from its own dir breaks if
  siblings land elsewhere.
- **Staleness/refusal guards run at register() time** — a `COPY_SKEW_REFUSAL`-style gate
  never runs if the plugin never loads; it cannot be the only protection. If the module
  has a "copies are stale, refuse to register" check, the installer record must sit where
  the checker reads it — INSIDE the plugin dir, not beside it, or the protection silently
  no-ops.
- **Graceful degradation** — `register()` returning early (stale copies, missing
  framework root) is fine: the plugin loads, hooks absent, session unaffected. A dead
  recorded `frameworkRoot` degrades to no-version-context, never a broken session.
- **Legacy cleanup** — when moving from a flat layout to the directory shape, delete the
  old flat files and the old manifest dir (only framework-owned names) so the loader
  scans a clean user scope.
- **Prior research can misread file contents as runtime**: a written record that treated
  an installed `register()` body as proof of registration is exactly the failure mode
  the empirical checks above exist for. Any "the plugin registers X" claim needs the
  empirical checks.

## Verification checklist

- [ ] Plugin lives at `~/.hermes/plugins/<name>/` with `plugin.yaml` + `__init__.py`
- [ ] `hermes plugins list` shows it enabled (or `plugins.enabled` contains its key)
- [ ] pycache exists / agent.log shows registration after a fresh session
- [ ] Live side-effect probe confirms the hook fires end-to-end
