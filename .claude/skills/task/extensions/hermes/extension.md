# task extension: hermes

This is a **config-gated extension** of the base `task` skill (`skills/task/`), not a standalone skill. It adapts task orchestration patterns for Hermes Agent, replacing Claude-specific delegation models (Fable/Sonnet/Haiku) with Hermes equivalents.

**Activates when:** the project's `.ai-badger/config.json` has `"hermes"` in its `stacks` array.

## Hermes delegation model

Hermes uses `delegate_task` for subagent spawning instead of Claude's `/task` model dispatch:

### Plan phase (equivalent: Fable for planning)

Use a subagent with planning context:

```
delegate_task(
  goal="Plan the implementation of <task>. Read <spec/docs>, explore the codebase, and produce a bite-sized implementation plan.",
  context="<full task description, acceptance criteria, file paths>",
  role="orchestrator"
)
```

The planner returns a structured plan. Review it for completeness before dispatching implementation.

### Implement phase (equivalent: Sonnet/Haiku for implementation)

Dispatch leaf agents for each implementation step:

```
delegate_task(
  goal="<specific implementation step from the plan>",
  context="<code context, file paths, test expectations>",
  role="leaf"
)
```

Leaf agents cannot delegate further. Each gets isolated context and terminal session.

### Review phase (equivalent: review-loop agent)

After implementation, dispatch a review agent:

```
delegate_task(
  goal="Review the changes for spec compliance, code quality, and invariants.",
  context="<diff, spec, project invariants from CLAUDE.md/HERMES.md>",
  role="leaf"
)
```

## Token tracking

Instead of Claude's token counters, use Hermes:
- `/usage` slash command to check token consumption
- Model costs appear in the session when `display.show_cost` is enabled
- Config: `agent.max_turns` limits iterations per turn

## Session management

- Resume work: `hermes --continue` (most recent) or `hermes --resume <session_id>`
- Branch sessions: `/branch` or `/fork` slash commands
- Context compression: automatic at `compression.threshold`; manual: `/compress`
- Save transcripts: `/save` to file

## Cross-session continuity

Hermes has three mechanisms for persistence across turns and sessions:

1. **`memory` tool** — save durable facts (preferences, conventions, environment). These survive all sessions and are injected into every turn. Keep entries compact and declarative.

2. **`session_search`** — FTS5 search over past conversation transcripts. Use to recall what was decided without asking the user: `session_search(query="<topic>")`. Three modes: discovery (by query), scroll (by session_id + message_id), browse (no args).

3. **Skills** — procedural memory. Save complex workflows as skills with `skill_manage(action='create')`. These are loaded by subsequent sessions and accumulate over time.

## PR and GitHub workflow

When the GitHub extension is also active (requires `sourceControl.platform == "github"`):

- Use `gh` CLI for issue/PR operations (same commands as the base task skill)
- The Copilot review-loop in the GitHub extension is Claude-specific; for Hermes, use `gh pr view --json reviews` to poll for Copilot reviews, or use `gh pr review` for manual review rounds
- Prefer `delegate_task` for review work: dispatch a leaf agent with the PR diff and review criteria

## Commit and push

Same git workflow as the base `task` skill:
- Small, focused commits with Conventional Commits format (`feat:`, `fix:`, `refactor:`, etc.)
- Push immediately after each commit
- Open draft PRs early

## Notes for the base skill

- The base `task` skill's references to Fable/Sonnet/Haiku are Claude-specific and should be treated as the *purpose* (planning, implementation, review) rather than the *mechanism*. Use Hermes `delegate_task` to achieve the same purpose.
- All path-specific instructions, invariants, and commands from `HERMES.md` apply to every subagent — include them in the `context` field when delegating.
- Hermes subagents have NO memory of the parent conversation — explicitly pass all relevant context.

## Hook integration — Claude Code equivalence

ai-badger's Claude Code plugin ships three hook scripts. This extension provides
Hermes equivalents that achieve the same outcomes using Hermes's richer hook system.

### 1. Drift notice (Claude: SessionStart → Hermes: on_session_start)

**What Claude does:** `hooks/hooks.json` fires `drift_notice_hook.py` on every
session start, comparing the project's scaffold version against the plugin's VERSION
and printing a notice if they differ.

**Hermes equivalent:** `ai_badger_hooks.py` (shipped in this extension) registers
an `on_session_start` plugin hook that does the same comparison. Logs a warning
to the Hermes log when drift is detected, plus injects a context notice via
`pre_llm_call` on every turn. Silent on match and on any read error.

**Installation:**
```bash
# Copy the hook module to your Hermes plugins directory
cp features/common/hooks/ai_badger_hooks.py ~/.hermes/plugins/
```

### 2. Context enrichment (Claude: UserPromptSubmit → Hermes: pre_llm_call)

**What Claude does:** The `UserPromptSubmit` hook can inject context before
each user prompt is sent to the model. ai-badger uses this for statusline info.

**Hermes equivalent:** `pre_llm_call` hook in `ai_badger_hooks.py` injects
framework version status and Hermes usage hints into every turn:
- Drift notice if the project is behind the framework
- `/usage` and `hermes insights` hints
- `session_search` reminder for cross-session recall

This fires **once per turn** before the tool-calling loop — more efficient
than Claude's per-prompt injection.

### 3. Statusline / usage display (Claude: statusLine → Hermes: native + hooks)

**What Claude does:** `statusline_capture.py` pipes through a user's
`statusline.sh`, capturing rate limits, context window %, and model info.
The background `poll_limit.py` reads `statusline-state.json` to avoid
unnecessary rate-limit probes.

**Hermes equivalent — no custom code needed.** Hermes has richer native tooling:

| Claude statusline info | Hermes equivalent |
|---|---|
| Model name | TUI status bar (always visible) |
| Token usage / cost | `/usage` slash command |
| Rate limits | Not needed — Hermes rotates credential pools |
| Context window % | TUI shows context; `/compress` when near limit |
| Session ID | `/status` or `hermes sessions list` |
| Weekly analytics | `hermes insights --days 7` |

The background `poll_limit.py` is completely unnecessary in Hermes —
the credential pool system auto-rotates exhausted keys, and rate limits
are surfaced via `/usage` rather than polled.

**For users who want persistent status:** enable `display.show_cost: true` in
`~/.hermes/config.yaml` to show cost in the TUI status bar on every turn.

**For gateway users:** a gateway hook on `agent:step` can alert when the agent
has been running for many iterations (see Hermes Event Hooks docs for the
`long-task-alert` example that posts to Telegram).

### 4. Session tracking (Claude: SessionStart → Hermes: native)

**What Claude does:** `session_start_hook.py` records `session_id` +
transcript path to `current-session.json` and launches `poll_limit.py`.

**Hermes equivalent — all native, no custom code:**
- Session continuity: `hermes --continue` or `/resume <name>`
- Transcript search: `session_search(query="...")` — FTS5 over all past sessions
- Unfinished tasks: check `.ai-badger/state.json` or use `session_search`
- Rate limits: `/usage` (no polling needed)

The `session_start_hook.py` and `poll_limit.py` are Claude-specific and
are NOT scaffolded when `hermes` is in the agent list. Their functionality
is fully covered by Hermes native features.

### Hook comparison summary

| Feature | Claude Code | Hermes Agent | Which is better? |
|---|---|---|---|
| Session-start check | SessionStart hook via hooks.json | on_session_start plugin hook | Equivalent |
| Per-turn context injection | UserPromptSubmit (rare, inefficient) | pre_llm_call (every turn, efficient) | **Hermes** — fires once per turn not per prompt |
| Tool call blocking | PreToolUse | pre_tool_call → `{"action": "block"}` | **Hermes** — can actually veto |
| Tool call observing | PostToolUse | post_tool_call (with duration_ms) | **Hermes** — includes timing |
| Gateway notifications | Not available | Gateway hooks (agent:end, agent:step) | **Hermes-only** — post to Telegram/Discord/etc. |
| Status display | statusLine pipe | TUI status bar + /usage + insights | **Hermes** — richer, no custom scripts |
| Rate limit polling | Custom poll_limit.py | Credential pools (auto-rotate) | **Hermes** — zero code needed |

See `docs/hermes-claude-compatibility.md` for the full compatibility reference.
