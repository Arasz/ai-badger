# Run ai-badger on a machine where hooks are disabled

## Use the instruction-only scaffold

For a project that must not add ai-badger project hooks, add `limited-env` to
`.ai-badger/config.json`'s `stacks` array and re-scaffold using the repository's normal
`welcome-ai-badger` workflow. The stack gives the agent memory-first and hook-independent
workflow instructions, suppresses ai-badger project hook registrations, and removes prior
registrations only where ai-badger ownership is identifiable. With Hermes or Pi, it skips a
new ai-badger user-level hook install and leaves any existing user-level plugin or extension
untouched.

This is instruction delivery, not enforcement. It does not disable administrator, plugin or
user hooks installed outside the project scaffold, and it does not prohibit repository scripts.
Automatic hook telemetry, per-turn context injection, and interruption checkpoints may be
unavailable. The task, research, prompt-marker, and raw-search skill extensions describe the
manual steps for these gaps. Do not run `limited_mode.py checkin` or `checkin --end` in this
mode; check-in executes commands from the project's hook registry.

## Use the Claude check-in mode

Use this when your organisation's managed Claude Code settings set `disableAllHooks: true`.
That setting stops every hook, including plugin and managed ones, so none of ai-badger's
session-start context, tool guards, post-tool nudges or end-of-turn checkpoints run. Limited
mode replaces what it can with things you or the agent run by hand.

Limited mode is the wrong fix for the two narrower policies. Under `allowManagedHooksOnly`,
hooks still run from plugins your managed settings force-enable. Under
`strictPluginOnlyCustomization` with `"hooks"`, hooks still run from every installed plugin.
The research record `docs/work/2026-10-17-hookless-limited-mode-research.md` (F1) has the
details.

## Know what you are opting into

`checkin` runs the same repository-controlled commands the policy stops Claude Code from
running. The only thing between them and your shell is the Bash permission prompt for
`limited_mode.py`, and `--hooks <file>` lets it run any file's commands. If your organisation
disables hooks to stop exactly that, ask before turning limited mode on.

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
- change `.ai-badger/config.json` and re-scaffold rather than hand-editing generated
  `.ai-badger/` output, and touch `.git/` only through git commands.

## Check in

```bash
python3 .ai-badger/skills/task/scripts/limited_mode.py checkin
python3 .ai-badger/skills/task/scripts/limited_mode.py checkin --end
```

Run it from the project root. `checkin` reads the project's `.ai-badger/hooks/hooks.json`,
runs every `SessionStart` command in it with the payload Claude Code would have sent, and
prints what each would have injected: unread bus mail, unfinished tracked tasks, git config
warnings. `--end` runs the `Stop`
commands instead, which checkpoint the tracked task and print its end-of-task reminders; a
reminder the Stop hook would have used to block the turn prints as `BLOCK: <reason>`.

`checkin` exits non-zero, and says why on stderr, when it could not check in: no session id
(it reads `CLAUDE_CODE_SESSION_ID`, which Claude Code sets in Bash, or `--session`), a missing
or malformed `hooks.json`, no commands registered for the event, or a command that failed or
timed out.

A subagent must not check in: it would read the parent session's mail. `checkin` refuses when
`CLAUDE_CODE_CHILD_SESSION` is set.

## What limited mode cannot replace

- **Per-turn delivery.** Mail arrives only when someone runs `checkin`, not on every turn.
- **Prompt markers.** Their expansion runs on each prompt, which `checkin` does not replay; the
  agent applies them itself.
- **State-dependent guards.** The dispatch gate, the memory-first gate and the multi-lane kill
  guard become written instructions. Nothing enforces them.
- **Memory follow-through telemetry.** No replacement; the retrieval eval loses that input.
- **Interrupted turns.** A turn that ends without `checkin --end` is not checkpointed.

## Turn it off

```bash
python3 .ai-badger/skills/task/scripts/limited_mode.py off
```

This removes only the marked block and deletes `CLAUDE.local.md` if nothing else is in it.
