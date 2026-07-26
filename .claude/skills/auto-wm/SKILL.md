---
name: auto-wm
description: Use when the user wants Claude to auto-approve tool calls — "enable autonomic/autonomous work mode", "/auto-wm", "partner mode", "work by yourself for N hours", "no one will be around to approve/answer" — or to check status, switch modes, or turn it off ("awm status", "auto-wm away 4h", "auto-wm off").
---

# auto-wm — Autonomic Work Mode

## Overview

Two modes, both auto-approving every tool call via a `PreToolUse` hook and logging each decision to an audit log. They differ on whether the user is around to be asked something, and on whether the mode expires:

- **partner** (default) — you're at the keyboard: available for questions, brainstorming, feedback, hints. Tool calls auto-approve; `AskUserQuestion` is left completely alone, same as a session with no hooks. No expiry — stays on until you switch to away or disable it.
- **away** — you're not around. Same auto-approval, but `AskUserQuestion` is denied (nothing to gain from asking) and the window expires on wall-clock time (default **4h**), checked by the hooks on every event — no cron or session timer needed.

Partner only ever starts because you explicitly ran `auto-wm` (or `/auto-wm`) — a session where auto-wm is never invoked keeps Claude Code's normal per-tool prompts. Once started, `enable`/`partner` and `away` are just the two states that mode can be in; switching between them overwrites the current one.

## Commands

All via `python3 ~/.claude/skills/auto-wm/scripts/awm.py`:

| Command | Effect |
|---|---|
| `enable` / `partner` | Switch to partner mode: auto-approve, questions untouched, no expiry |
| `away [DURATION]` | Switch to away mode: auto-approve, questions denied, expires (default 4h). Grammar: `Nh`, `Nm`, `NhMm`, or a bare number = hours (`4h`, `90m`, `1h30m`, `4`) |
| `disable` (or `off`, `stop`) | Turn AWM off entirely — normal per-tool prompts resume |
| `status` | Which mode, since when, time remaining (away only) |
| `decision "<what and why>"` | Register a judgment call in the audit log |

## Invocation

`/auto-wm [away DURATION | off | status | partner]` — no argument means `partner` (indefinite, default). Away mode must be asked for explicitly, since it changes how questions are handled and has a clock running.

1. Run the matching `awm.py` command and relay its output (partner/away both print what changed).
2. On first enable (partner or away), smoke-test that the gate hook actually fires: run any trivial command (e.g. `true`), then `tail -2 ~/.claude/awm/decisions.jsonl` — a fresh `auto_approve` entry proves auto-approval is live. If no entry appears, check registration with `jq '.hooks.PreToolUse' ~/.claude/settings.json`; if missing, merge `~/.claude/skills/auto-wm/hooks/settings-snippet.json` into `~/.claude/settings.json` (preserve existing keys), then tell the user hooks load on `/hooks` or restart.
3. In the same reply, warn once (either mode): every command will be auto-approved, including destructive ones — equivalent to `bypassPermissions` with an audit trail. For away mode, also note that questions get denied outright.

## Files (all user-level)

| File | Purpose |
|---|---|
| `~/.claude/awm/state.json` | Marker: `enabled`, `mode` (`partner`/`away`), `enabled_at`, `duration`, `expires_at` (null for partner) |
| `~/.claude/awm/decisions.jsonl` | Audit log: `mode_enabled/disabled/expired`, `auto_approve`, `question_denied`, `decision` |
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

- **Marker in the project** (`.claude/` in a repo, `CLAUDE.md` edits) — it's user-level state; project files pollute git. Use `~/.claude/awm/` only.
- **Permission allowlist ≠ AWM.** Adding `permissions.allow` entries doesn't approve everything; only the PreToolUse hook does.
- **Treating partner mode like away mode.** Partner mode does not deny `AskUserQuestion` and does not expire — don't apply away's "never ask, always log" contract when the state file says `mode: partner`.
- **Session cron for away's expiry** — dies with the session. The hooks compare `expires_at` to wall-clock instead.
- **Editing state.json by hand** — always go through `awm.py` so changes land in the audit log.

## Installing from ai-badger

This skill is user-level by design: its state (`~/.claude/awm/`) and hook scripts
(`~/.claude/skills/auto-wm/`) live outside any project, so the same install covers every repo you
work in. `welcome-ai-badger` copies this directory to `~/.claude/skills/auto-wm/` once (not into
`.ai-badger/`) and merges `hooks/settings-snippet.json` into `~/.claude/settings.json`. Re-running
`welcome-ai-badger` on another project does not reinstall it.
