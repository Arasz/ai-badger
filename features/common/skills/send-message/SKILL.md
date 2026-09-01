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
  session env var (`CLAUDE_CODE_SESSION_ID`), then a pid-ancestry match against the
  sessions store, then a unique cwd match (exactly one known session carrying this
  working directory). Ambiguous or absent → refused.
- **projectId** — `--sender-project <id>`, or `AI_BADGER_PROJECT_ID`, or the cwd
  resolver's read of the ai-raccoon registry (containment: the working directory equal
  to or under a registered project's scope paths). Several registered projects
  containing the cwd refuse with the candidate list — pick one explicitly. A cwd
  outside every registered project refuses rather than guessing.

The explicit flags exist for contexts with no derivable identity: a human running the
script by hand, a cron job, or a test.

## Gotchas

- No environment-specific gotchas known.
