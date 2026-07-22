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
