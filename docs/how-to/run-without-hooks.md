# Run ai-badger on a machine where hooks are disabled

Use this when your organisation's managed Claude Code settings set `disableAllHooks: true`.
That setting stops every hook, including plugin and managed ones, so none of ai-badger's
session-start context, tool guards, post-tool nudges or end-of-turn checkpoints run. Limited
mode replaces what it can with things you or the agent run by hand.

If the policy is `allowManagedHooksOnly` or `strictPluginOnlyCustomization` instead, hooks from
a force-enabled or installed plugin still run, and limited mode is the wrong fix. The research
record `docs/work/2026-10-17-hookless-limited-mode-research.md` (F1) explains the difference.

## Check which policy applies

Run `/status` in Claude Code and read the **Setting sources** line, or ask your administrator
for the managed settings JSON. Turn limited mode on only if it contains `disableAllHooks: true`.

## Turn limited mode on

From any checkout or worktree of the project:

```bash
python3 .ai-badger/skills/task/scripts/limited_mode.py on
```

This writes a marked block into `CLAUDE.local.md` at the main checkout's root. Claude Code loads
that file from the working directory and every directory above it, so worktrees nested under
the checkout pick it up too. The file is gitignored by ai-badger's managed `.gitignore` block,
so the switch stays on your machine. Teammates outside the policy keep their hooks, and
`.claude/settings.json` is not changed.

The block tells the agent to:

- run the check-in at session start, before opening a PR, and before finishing a task;
- apply prompt markers itself, name a `model` on every dispatch, and search memory before
  repo text search, because no hook checks any of these;
- edit `features/` sources rather than generated `.ai-badger/` output, and touch `.git/` only
  through git commands.

## Check in

```bash
python3 .ai-badger/skills/task/scripts/limited_mode.py checkin
python3 .ai-badger/skills/task/scripts/limited_mode.py checkin --end
```

`checkin` reads the project's `.ai-badger/hooks/hooks.json`, runs every `SessionStart` command
in it with the payload Claude Code would have sent, and prints what each would have injected:
unread bus mail, unfinished tracked tasks, git config warnings. `--end` runs the `Stop`
commands instead, which checkpoint the tracked task and print its end-of-task reminders.

A subagent must not check in: it would read the parent session's mail. `checkin` refuses when
`CLAUDE_CODE_CHILD_SESSION` is set.

## What limited mode cannot replace

- **Per-turn delivery.** Mail and prompt-marker expansion arrive only when someone runs
  `checkin`, not on every turn.
- **State-dependent guards.** The dispatch gate, the memory-first gate and the multi-lane kill
  guard become written instructions. Nothing enforces them.
- **Memory follow-through telemetry.** No replacement; the retrieval eval loses that input.
- **Interrupted turns.** A turn that ends without `checkin --end` is not checkpointed.

## Turn it off

```bash
python3 .ai-badger/skills/task/scripts/limited_mode.py off
```

This removes only the marked block and deletes `CLAUDE.local.md` if nothing else is in it.
