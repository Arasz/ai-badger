---
name: call-behaviorist
description: >-
  Use when ai-badger's own machinery needs to be observed — "did that hook even run?", "enable
  debug logging", "why is the drift notice silent?", "turn on the audit log", "what did the
  hooks do?" — or to check, tail, or switch off that logging. Records which hook ran, in which
  project, under which version, to an append-only log.
---

# call-behaviorist

Named for observing behaviour rather than asserting it. ai-badger is normally silent about its
own machinery, so "did that hook fire?" has no answer short of adding print statements and
re-scaffolding. This turns the machinery's own behaviour into a record.

**Off by default.** Nothing is written, and no directory is created, until you switch it on.

## Commands

All via `python3 .ai-badger/skills/call-behaviorist/scripts/behaviorist.py`:

| Command | Effect |
|---|---|
| `on [DURATION]` | Enable for **every project** (default 4h). Grammar: `4h`, `90m`, `1h30m`, or a bare number of hours. Capped at 24h. |
| `on [DURATION] --project` | Enable for the current directory only |
| `off` | Disable |
| `status` | Mode, scope, expiry, record count |
| `tail [N]` | Last N records, one line each (default 20) |
| `clear` | Truncate the log, recording the truncation |

`AI_BADGER_DEBUG=1` in the environment forces logging on regardless of stored state, for a
one-off run where editing state is inconvenient.

## What a record holds

`tail` renders records readably:

```
2026-07-27T09:22:56+00:00  ai_badger_hooks/session_start  skip  v0.30.0  project=/repo scaffold_version=0.30.0 framework_version=0.30.0
```

On disk they are compact, one JSON object per line:

```json
{"t":"2026-07-27T09:22:56+00:00","c":"ai_badger_hooks/session_start","e":"skip","v":"0.30.0","p":"/repo"}
```

| Key | Meaning |
|---|---|
| `t` | timestamp, UTC, seconds |
| `c` | component — which hook or script |
| `e` | event — `start`, `skip`, or a domain outcome |
| `v` | version of the copy of the code that ran |
| `p` | project directory, when determinable |
| `s` | session id, when the host supplies one |

The single-letter keys are a budget, not cosmetics: a record must stay under `PIPE_BUF`
(4096 bytes) for concurrent appends to be atomic, and the fixed keys repeat on every line.
Fields a caller adds keep their full names — they are the payload, and they do not repeat.

- **`version` is on every record** — it is the VERSION of the *copy of the code that ran*. This
  is what makes a stale plugin running against a newer scaffold visible rather than something
  you have to deduce.
- `event` distinguishes `start` from `skip`, so a hook that fired and exited early is
  distinguishable from one that never fired. That distinction is the whole point.
- `project` is recorded whenever it can be determined.

No tool input, prompt text, or file content is ever recorded.

## Where things live

| Path | Purpose |
|---|---|
| `~/.ai-badger/debug/state.json` | Whether logging is on, its scope and expiry |
| `~/.ai-badger/debug/audit.jsonl` | The records, one JSON object per line |

Both are user-level and `0600` — the log says where you work and what ran, so it never lands in
a project directory or in git. It is capped at 5000 records, oldest trimmed first.

## Reading the log

`tail` is for a quick look. For anything more, the file is one JSON object per line:

```bash
jq -r 'select(.event=="drift")' ~/.ai-badger/debug/audit.jsonl
jq -r '[.component, .version] | @tsv' ~/.ai-badger/debug/audit.jsonl | sort | uniq -c
```

The second is the useful one when several copies of ai-badger are installed: it shows which
version each component actually ran at.

## Turn it off when you are done

The window expires on wall-clock time, checked on every event — no timer and no cron. Debug
logging that never switches itself off is a slow disk leak and a standing privacy exposure,
which is why `on` always takes an expiry and caps it at 24 hours.
