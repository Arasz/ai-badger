---
name: send-message
description: >-
  Use when an agent session needs to reach another agent session, every session in a
  project, or every session on this machine without the human relaying between windows —
  1:1, project-broadcast and machine-broadcast sends through the machine-wide user-DB
  message bus.
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [message-bus, coordination, agent-messaging]
    related_skills: [task, status-report]
---

# send-message

Send one message through the user-DB message bus. The row lands in the machine-wide
user store; each receiving session's delivery hook injects the messages addressed to
it on its next delivery event.

## Usage

```bash
python3 .ai-badger/skills/send-message/scripts/send_message.py \
  --content "found it, see src/bus.py" \
  --session-id <their-session-id>
```

`--content` is always required and is delivered verbatim. The target flags decide the
shape of the send:

| Target | Flag | Shape |
| --- | --- | --- |
| one session | `--session-id <id>` | 1:1 |
| one project | `--project-id <id>` | project broadcast |
| none given | omit both | machine broadcast |

Give both `--session-id` and `--project-id` and **the session wins**: the row is
stored 1:1 and the project half is dropped — precedence is normalised at write, so no
reader can ever see a dual-target row.

On success the script prints `sent <row id>`. A refused send prints
`send refused: <reason>` on stderr and exits non-zero with nothing written.

## Sender identity is mandatory

Both halves of the sender identity are REQUIRED on every send. When either half cannot
be resolved the send is refused (non-zero exit, no row) — this is the bus's Rule 10,
not an implementation quirk:

- **sessionId** — `--sender-session <id>`, or derived in this order: the harness's
  session env var (`CLAUDE_CODE_SESSION_ID` for claude, `PI_SESSION_ID` for pi,
  `HERMES_SESSION_ID` for hermes — first set wins; each harness exports its live
  session id to the subprocesses it spawns, and that is the id its delivery consumes
  by, so own broadcasts are excluded), then a pid-ancestry match against the
  sessions store, then a unique cwd match (exactly one known session carrying this
  identity). Residual (api-review d-209): a stale foreign var inherited from an outer
  host (claude-in-shell-in-pi) beats the live one by list order — if your shell
  carries a `CLAUDE_CODE_SESSION_ID` that is not this session's, pass
  `--sender-session` explicitly.
  working directory). Ambiguous or absent → refused.
- **projectId** — `--sender-project <id>`, or `AI_BADGER_PROJECT_ID`, or the cwd
  resolver's upward walk to the nearest `.ai-badger/project-id` (minted at scaffold
  time, backfilled by den-refresh). A cwd with no `.ai-badger` in its ancestry — or
  one whose id file is absent — resolves no project: the send needs the explicit
  flag. This refuses rather than guessing.

The explicit flags exist for contexts with no derivable identity: a human running the
script by hand, a cron job, or a test.

Sender identity is asserted, not authenticated: it is derived from machine-local state
(environment variables, the sessions store, the working directory), so anything with
access to this machine can send as any session or project. Treat a sender as a claim
the local software made, not proof of authorship — the trust boundary is the machine,
not the bus.

## Targets are validated

A `--project-id` target is checked before anything is written: it must resolve on this
machine — the sender's own project resolution, the `AI_BADGER_PROJECT_ID` override, or
the stripped content of some `.ai-badger/project-id` file the machine scan finds — or
the send refuses with exit 1 and no row:

```
send refused: --project-id '<id>' does not resolve to any project on this machine — no .ai-badger/project-id carries it (ADR-0025); use a minted id or omit --project-id for a machine broadcast
```

When the scan finds ids but none matches, the refusal lists them. Named residual: the
scan is a bounded approximation — it walks at most four directory levels under the
store's home, skipping `Library`, `node_modules`, `.git`, `.cache` and similar noise
trees, and never follows directory symlinks — so a scaffolded project outside that
budget (deeper tree, another volume) is invisible and its id false-refuses. The escape
hatch is the minted-id contract above, not a bypass flag. Dual-flag sends
(`--session-id` + `--project-id`) skip validation: the session wins and the project
half is dropped at write, so there is nothing stored to validate.

## Gotchas

- No environment-specific gotchas known.
