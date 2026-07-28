# Hermes Agent ↔ Claude Code Compatibility

How ai-badger's Claude Code features map to Hermes Agent equivalents.
Every concept the framework depends on listed with its Hermes counterpart
and any gaps that need bridging.

> **Written 2026-07-22, spot-checked against the code at 0.27.0 on 2026-07-27.** The conceptual
> mapping holds. Three corrections were applied inline (marked *Correction*); one framing caveat:
> the sections below that read as *proposals* ("Option A … recommended") describe work that has
> since **shipped**, and shipped differently. `features/common/hooks/ai_badger_hooks.py` registers
> all three hooks — `on_session_start` for the drift notice, `pre_llm_call` for context
> injection, `post_tool_call` for observation. Drift is reported at session start, not per turn,
> and `pre_llm_call` carries drift plus usage hints plus MCP tool-index recommendations. The
> advice below to inject usage context "into every turn" was explicitly walked back in 0.18.0 —
> repeated every turn, the hints became wallpaper, so they are now once per session.

## Hook systems

Claude Code has a single hook system (SessionStart, PostToolUse, etc.).
Hermes has three, each more powerful in different ways.

| Claude Code | Hermes equivalent | Notes |
|---|---|---|
| `hooks.json` in plugin root | `~/.hermes/hooks/<name>/HOOK.yaml` (gateway) or plugin `ctx.register_hook()` (CLI+gateway) | Hermes splits gateway-only hooks from universal plugin hooks |
| `SessionStart` event | `on_session_start` (plugin hook) | Fires on both CLI and gateway session start |
| `PostToolUse` event | `post_tool_call` (plugin hook) | Receives tool_name, args, result, duration_ms |
| `PreToolUse` event | `pre_tool_call` (plugin hook) | Can block tool calls by returning `{"action": "block", "message": "..."}` |
| `UserPromptSubmit` → inject context | `pre_llm_call` (plugin hook) → `{"context": "..."}` | Inject git status, drift notices, usage info into every turn |
| `Stop` event | `on_session_end` (plugin hook) | Receives completed, interrupted booleans |
| `Notification` event | Gateway hook `agent:end` | Post to Telegram/Discord/etc. when agent finishes |
| `$CLAUDE_PLUGIN_ROOT` variable | `__file__`-relative ancestor walk | Hermes plugins self-locate via `Path(__file__).resolve().parents` |
| statusLine shell command | `/usage` slash command + TUI status bar + `hermes insights` | No direct statusLine pipe; enriched via hooks + slash commands |

**Key difference:** Hermes hooks are more capable — `pre_tool_call` can block dangerous operations,
`pre_llm_call` can inject dynamic context into every turn, and gateway hooks can post to any
messaging platform. Claude's hook surface is simpler but less flexible.

## ai-badger hooks — Claude → Hermes migration

### 1. Drift notice (Tier 1)

**Claude** (`hooks/hooks.json` → `drift_notice_hook.py`):

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume",
      "hooks": [{
        "type": "command",
        "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/features/common/skills/task/scripts/drift_notice_hook.py\""
      }]
    }]
  }
}
```

Fires on every session start, reads `manifest.json` frameworkVersion, compares to plugin's VERSION,
prints a one-line notice if they differ.

*Correction (2026-07-27):* the `command` above previously read
`${CLAUDE_PLUGIN_ROOT}/skills/task/…`. The real path in `hooks/hooks.json` is
`${CLAUDE_PLUGIN_ROOT}/features/common/skills/task/…` and has been for some time; the rest of
this paragraph is accurate.

**Hermes** — two options:

**Option A: `pre_llm_call` context injection (recommended)**

Instead of a separate hook script, a Hermes plugin registers a `pre_llm_call` hook that
checks the project's `manifest.json` against the framework's VERSION on every turn and
injects a drift notice into the LLM context. This is more reliable than a once-per-session
check because it fires on every turn, not just session start.

```python
# hermes plugin register()
def register(ctx):
    ctx.register_hook("pre_llm_call", inject_drift_notice)

def inject_drift_notice(task_id=None, cwd=None, **kwargs):
    if not cwd:
        return None
    manifest = Path(cwd) / ".ai-badger" / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text())
        scaffold_ver = data.get("frameworkVersion")
    except (OSError, ValueError):
        return None
    fw_version = (Path(__file__).resolve().parents[3] / "VERSION").read_text().strip()
    if scaffold_ver and fw_version and scaffold_ver != fw_version:
        return {
            "context": (
                f"[ai-badger] Scaffolded with {scaffold_ver}, "
                f"framework is {fw_version}. Run den-refresh to update."
            )
        }
    return None
```

**Option B: Cron job (fire-and-forget)**

A cron job that checks daily and delivers to the user's configured platform:

```bash
hermes cron create "0 9 * * *" \
  --prompt "Check if .ai-badger/manifest.json frameworkVersion differs from the ai-badger framework VERSION. If so, notify the user to run den-refresh." \
  --name "ai-badger drift check"
```

### 2. Session tracking (task skill)

**Claude** (`session_start_hook.py`):
- Reads SessionStart payload from stdin
- Records session_id + transcript path to `current-session.json`
- Launches background `poll_limit.py` for rate-limit monitoring
- On resume, surfaces unfinished tracked tasks

**Hermes** — replaced by native features:

| Claude feature | Hermes replacement |
|---|---|
| `session_id` tracking | `session_search` — FTS5 over all past conversations; no need to track manually |
| `transcript_path` | `~/.hermes/sessions/` + `hermes sessions list` |
| `poll_limit.py` (rate limit polling) | Not needed — Hermes rotates credential pools automatically; `/usage` shows limits |
| Unfinished task notice on resume | `session_search(query="unfinished task")` or `/resume <name>` |
| Background poller | `cronjob` for scheduled work; `delegate_task` for parallel work |

**Implementation:** A `hermes` task extension provides equivalent functionality via native Hermes features rather than reimplementing Claude hooks. The extension documents that:
- Session continuity → `hermes --continue` or `/resume`
- Unfinished tasks → check `state.json` or use `session_search`
- Rate limits → `/usage` slash command

### 3. Statusline (usage display)

**Claude** (`statusline_capture.py`):
- Pipes through a user's `statusline.sh` script
- Captures rate limits, context window %, model info
- Persists to `statusline-state.json` for `poll_limit.py`

**Hermes** — three approaches:

**a) `/usage` slash command (built-in)**

Shows token usage, cost, model. Equivalent to Claude's statusline model info.
No hook needed — this is native.

**b) `pre_llm_call` context enrichment (plugin hook)**

Inject usage context into every turn so the agent sees it:

```python
def inject_usage_context(**kwargs):
    """Inject current usage stats into every agent turn."""
    return {
        "context": (
            "[Session context] Use /usage to check token consumption and rate limits. "
            "Use hermes insights for analytics."
        )
    }
```

**c) TUI status bar (native)**

Hermes TUI shows model + cost in the status bar. Toggle with `/statusbar`.
Configure with `display.show_cost: true` in config.yaml.

**d) Gateway notifications (hooks)**

For long-running tasks, a gateway hook on `agent:step` can alert when the agent exceeds N steps:

```yaml
# ~/.hermes/hooks/long-task-alert/HOOK.yaml
name: long-task-alert
events:
  - agent:step
```

See Hermes docs for the full handler example (posts to Telegram when iteration > 10).

## Project context files

| Claude Code | Hermes Agent | Notes |
|---|---|---|
| `CLAUDE.md` (cwd) | `CLAUDE.md` (priority 3) | Hermes reads Claude files as fallback |
| `AGENTS.md` | `AGENTS.md` (priority 2) | Portability layer |
| — | `HERMES.md` / `.hermes.md` (priority 1) | Hermes-specific; walks parents to git root |
| `.cursorrules` | `.cursorrules` (priority 4) | Cursor migration |
| `.claude/settings.json` | `~/.hermes/config.yaml` | Config location |
| `.claude-plugin/` | `~/.hermes/plugins/` | Plugin location |
| `$CLAUDE_PLUGIN_ROOT` | `__file__` ancestor walk | Self-location pattern |

## Tool comparison

| Claude Code tool | Hermes tool | Notes |
|---|---|---|
| `Bash` | `terminal` | Same: shell command execution |
| `Read` / `Write` / `Edit` | `read_file` / `write_file` / `patch` | Same: file operations |
| `Grep` / `Glob` | `search_files` | Same: code search |
| `Task` (subagent) | `delegate_task` | Hermes: isolated context + terminal, parallel batch |
| `WebSearch` / `WebFetch` | `web_search` / `web_extract` | Same: web access |
| `NotebookEdit` | `execute_code` | Hermes: Python sandbox with tool access |
| `TodoWrite` | `todo` | Same: task tracking |
| — | `memory` | **Hermes-only**: persistent cross-session memory |
| — | `session_search` | **Hermes-only**: FTS5 search over past conversations |
| — | `cronjob` | **Hermes-only**: durable recurring tasks |
| — | `computer_use` | **Hermes-only**: background desktop automation |
| — | `skill_manage` / `skill_view` | **Hermes-only**: self-improving procedural memory |

## Delegation

| Claude Code | Hermes Agent |
|---|---|
| `/task` with model routing (Fable/Sonnet/Haiku) | `delegate_task(goal, context, role)` with leaf/orchestrator roles |
| Model names are Anthropic-specific | Provider-agnostic: any model, any provider |
| Single subagent per command | Batch mode: up to 3 parallel subagents |
| Console output inline | Live transcripts at `cache/delegation/live/<id>/` |

## Gap analysis

| Feature | Claude has it | Hermes has it | How to bridge |
|---|---|---|---|
| SessionStart hook | Yes (plugin hooks.json) | Yes (on_session_start) | Plugin registration |
| Per-turn context injection | Yes (UserPromptSubmit) | Yes (pre_llm_call → context return) | Plugin hook |
| Status line (model/limits/context) | Yes (statusLine) | Partial (TUI bar + /usage) | pre_llm_call enrichment |
| Plugin auto-update | Yes (plugin update) | Yes (hermes skills update) | Same concept |
| Rate limit polling | Custom (poll_limit.py) | Not needed (credential pools) | Remove entirely |
| Unfinished task notice | Custom (session_start_hook.py) | session_search + /resume | Document, don't reimplement |

## ai-badger framework surface for Hermes

What the framework ships and where:

| Artifact | Claude path | Hermes path |
|---|---|---|
| Drift notice | `hooks/hooks.json` + `drift_notice_hook.py` | `features/common/hooks/ai_badger_hooks.py`, installed into `~/.hermes/plugins/` by `features/hermes/adjustments/adjust_hooks.py` |
| Session tracking | `session_start_hook.py` in scaffolded `.ai-badger/` | Documented in task extension; replaced by native Hermes features |
| Statusline capture | `statusline_capture.py` | `/usage` + `pre_llm_call` enrichment in task extension |
| Background poller | `poll_limit.py` | Not needed; documented removal in task extension |
| User statusline | `statusline.sh` (~/.claude/) | TUI status bar + `/statusbar` + `display.show_cost` |

### Learned-skill sync

Hermes can author skills at runtime; ai-badger's plugin captures them into the project. The
`post_tool_call` hook fires only on a successful `skill_manage` call whose action creates or
edits a skill, and only when the working directory holds a `.ai-badger/manifest.json`. The skill
is copied to `.ai-badger/skills/learned/<category>/<name>/` — `uncategorized` when Hermes
declares none — and recorded in `.ai-badger/skills-data/hermes/learned.json`, deliberately
separate from `manifest.json`: the manifest means "the framework placed this and owns it",
which a learned skill is not.

Writes are one-way, confined and additive. The sync refuses rather than resolves: a name or
category containing `/`, `\` or `..`; a skill whose name is framework-owned; a destination
resolving outside `learned/`; a symlink anywhere under the source directory *or* on any path
segment above it; and any file matching `engine/unsafe_literals.py` — reported as
`{file, pattern}` from a closed vocabulary, never as the matched text, and never as a partial
copy. A destination that exists but is absent from `learned.json` is left alone and reported as
a conflict. Deleting a skill in Hermes does not delete it here; the record is marked `orphaned`
and the files stay. Re-syncing an unchanged skill is a no-op, decided by `sourceHash`.

Reconciliation is opt-in and never automatic:

```bash
python3 "$AI_BADGER/features/common/hooks/learned_skills_sync.py" --reconcile --target . [--dry-run]
```
