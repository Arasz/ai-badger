# task extension: pi

This is a **config-gated extension** of the base `task` skill, not a standalone skill.
It adapts task orchestration patterns for the pi coding agent.

**Activates when:** the project's `.ai-badger/config.json` has `"pi"` in its `agents` array.

## Subagent delegation

pi subagents are **real OS child processes** with their own `cwd`, `--model`, and `--tools`.
Use the built-in subagent extension or spawn via:

```
pi --mode json -p --no-session --model <model> --tools <toolset> "<task>"
```

The reference subagent implementation is at `examples/extensions/subagent/` in the pi repo.

## Session management

- Resume work: `pi --resume <session_id>` or `pi -p` (most recent)
- pi has no built-in `/branch` or `/fork` — use git worktrees for parallel work
- Context compression: automatic by default

## Token tracking

pi does not expose per-session token usage through an env var or file API.
The task tracker reports zeroes for pi sessions. Record token usage manually
with `task_tracker.py subagent <taskId> <total_tokens>`.

## Hook integration

pi loads extensions from `~/.pi/agent/extensions/` (user scope). The
ai-badger adapter extension translates pi event shapes to Claude-shaped JSON
that the existing Python hooks expect, and maps responses back to pi's format.

| Claude event | pi event | Purpose |
|---|---|---|
| `UserPromptSubmit` | `input` | Transform user prompt |
| `PreToolUse` | `tool_call` | Block/modify tool calls |
| `PostToolUse` | `tool_result` | Observe tool results |
| `SessionStart` | `session_start` | Side effects |
| `SessionEnd` | `session_shutdown` | Cleanup |
| `Stop` | `agent_settled` | Task checkpoint |

## Scope extension

pi's `input` event exposes `streamingBehavior` (`"steer"` | `"followUp"` | `undefined`),
which may fix ai-badger's documented mid-turn marker defect. `undefined` when idle,
`steer` for mid-stream interrupts, `followUp` for messages queued until the agent finishes.