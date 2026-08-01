---
name: auto-wm
description: Use when the user wants Claude to auto-approve tool calls — "enable autonomic/autonomous work mode", "/auto-wm", "partner mode", "work by yourself for N hours", "no one will be around to approve/answer" — or to check status, switch modes, or turn it off ("awm status", "auto-wm away 4h", "auto-wm off").
---

# auto-wm — Autonomic Work Mode

## Overview

Two modes, both auto-approving most tool calls via a `PreToolUse` hook and logging each decision to an audit log. They differ only on whether the user is around to be asked something:

- **partner** (default) — you're at the keyboard: available for questions, brainstorming, feedback, hints. Tool calls auto-approve; `AskUserQuestion` is left completely alone, same as a session with no hooks. Window defaults to **8h**.
- **away** — you're not around. Same auto-approval, but `AskUserQuestion` is denied (nothing to gain from asking). Window defaults to **4h**.

Three guards bound both modes, re-checked by the hooks on every event — no cron or session timer needed:

- **Wall-clock expiry.** No window is open-ended; anything longer than **12h** is capped to 12h. An elapsed window flips itself off and normal prompts resume.
- **Project scope.** State is kept per project: each one records its own mode and window, and a call whose `cwd` is outside every armed tree is never auto-approved. Enabling AWM in one repo neither arms the machine nor disarms another repo — two sessions in two checkouts can both be covered at once, each expiring on its own clock. The banner obeys the same scope, so a project AWM is not armed in is told nothing (#296).
- **Denylist.** Destructive shell commands (`rm -r`, `sudo`, force-pushes, piping the network into a shell, `crontab`, …), network egress (`WebFetch`, `WebSearch`), and writes outside the project are never auto-approved. They fall through to the normal permission prompt and are logged as `denylisted`.

Partner only ever starts because you explicitly ran `auto-wm` (or `/auto-wm`) — a session where auto-wm is never invoked keeps Claude Code's normal per-tool prompts. Once started, `enable`/`partner` and `away` are just the two states that mode can be in; switching between them overwrites the current one.

## Commands

All via `python3 ~/.claude/skills/auto-wm/scripts/awm.py`:

| Command | Effect |
|---|---|
| `enable` / `partner` `[DURATION]` | Switch to partner mode: auto-approve, questions untouched, expires (default 8h) |
| `away [DURATION]` | Switch to away mode: auto-approve, questions denied, expires (default 4h). Grammar: `Nh`, `Nm`, `NhMm`, or a bare number = hours (`4h`, `90m`, `1h30m`, `4`); anything over 12h is capped |
| `disable` (or `off`, `stop`) | Turn AWM off **for this project** — normal per-tool prompts resume here; other projects keep their windows |
| `status` | This project's mode, since when, and time remaining — plus any other project still armed |
| `decision "<what and why>"` | Register a judgment call in the audit log |

## Invocation

`/auto-wm [away DURATION | off | status | partner DURATION]` — no argument means `partner` (8h, default). Away mode must be asked for explicitly, since it changes how questions are handled and has a clock running.

1. Run the matching `awm.py` command and relay its output (partner/away both print what changed).
2. On first enable (partner or away), smoke-test that the gate hook actually fires: run any trivial command (e.g. `true`), then `tail -2 ~/.claude/awm/decisions.jsonl` — a fresh `auto_approve` entry proves auto-approval is live. If no entry appears, check registration with `jq '.hooks.PreToolUse' ~/.claude/settings.json`; if missing, merge `~/.claude/skills/auto-wm/hooks/settings-snippet.json` into `~/.claude/settings.json` (preserve existing keys), then tell the user hooks load on `/hooks` or restart.
3. In the same reply, warn once (either mode): tool calls will be auto-approved without asking — close to `bypassPermissions`, minus the denylist, and with an audit trail. Say which project it is scoped to and when the window expires. For away mode, also note that questions get denied outright.

## Files (all user-level)

| File | Purpose |
|---|---|
| `~/.claude/awm/state.json` | `{"version": 2, "projects": {"<path>": {`enabled`, `mode`, `enabled_at`, `duration`, `expires_at`}}}` — one entry per project. A pre-0.74 single-project file is read as one entry and rewritten in this shape on the next change. |
| `~/.claude/awm/decisions.jsonl` | Audit log: `mode_enabled/disabled/expired`, `auto_approve`, `question_denied`, `denylisted`, `out_of_scope`, `decision` |
| `~/.claude/skills/auto-wm/hooks/` | `awm_gate.py` (PreToolUse), `awm_context.py` (UserPromptSubmit) |

## While AWM is active (behavior contract)

**Partner mode:**
- Ask questions, brainstorm, or check in whenever it's genuinely useful — the user is available, so there's no reason to hold back the way away mode does. Tool calls still auto-approve, so the value of asking is about judgment and direction, not permission.
- Still worth registering notable judgment calls with `awm.py decision`, so there's a record even for things nobody was asked about.

**Away mode:**
- Never ask the user anything or wait for approval; the gate denies `AskUserQuestion` anyway. Pick the best-judgment option and continue.
- Register every significant judgment call with `awm.py decision` — option chosen, alternatives, why.
- Prefer reversible choices (branch instead of main, keep backups before overwrites); log anything risky before doing it.

## Common mistakes

- **State in the project** (`.claude/` in a repo, `CLAUDE.md` edits) — the *scripts* are scaffolded per project, but the *state* is user-level: enabled flag, window, decisions. Keep all of it in `~/.claude/awm/`; a state marker committed to a repo both leaks and misleads.
- **Permission allowlist ≠ AWM.** Adding `permissions.allow` entries doesn't approve everything; only the PreToolUse hook does.
- **Treating partner mode like away mode.** Partner mode does not deny `AskUserQuestion` — don't apply away's "never ask, always log" contract when the state file says `mode: partner`.
- **Reading a fall-through as a failure.** A denylisted or out-of-scope call is not an error: the normal permission prompt reaches the user, exactly as if AWM were off. Don't retry it a different way to get around the gate — ask.
- **Session cron for expiry** — dies with the session. The hooks compare `expires_at` to wall-clock instead.
- **Reading the banner as proof the gate will approve.** It used to be: the banner ignored scope entirely and announced away mode in every project on the machine, including ones where every call was denied (#296). Both now read the same per-project entry, but the audit log is still the only place that records what the gate actually decided.
- **Editing state.json by hand** — always go through `awm.py` so changes land in the audit log.

## Installing from ai-badger

Two things are user-level here, and one is not. Getting them mixed up is why this section used
to describe an install that never happened (review F-42).

**What `welcome-ai-badger` does:** it scaffolds this skill into `.ai-badger/skills/auto-wm/`
like every other skill. It does **not** copy anything to `~/.claude/skills/`, and it does
**not** merge `hooks/settings-snippet.json` into `~/.claude/settings.json`.

**What you do once, by hand:** the gate only fires if its two hooks are registered in
`~/.claude/settings.json`. Copy the hooks somewhere stable and merge the snippet:

```bash
mkdir -p ~/.claude/skills/auto-wm
cp -R .ai-badger/skills/auto-wm/. ~/.claude/skills/auto-wm/
# then merge hooks/settings-snippet.json into ~/.claude/settings.json, preserving existing keys
```

The snippet's commands point at `~/.claude/skills/auto-wm/hooks/`, so the registered hooks keep
working in every repo — which is the point: the state **file** is machine-wide
(`~/.claude/awm/`), but each project gets its own entry inside it, keyed by path rather than by
which copy of the scripts ran.

**Why the skill files are per project anyway:** they are versioned with the framework, so a
`den-refresh` updates them. Re-copy to `~/.claude/skills/auto-wm/` after an update that touches
`hooks/` — nothing does it for you.
