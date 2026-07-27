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
| `analyze [--project DIR] [--json]` | Health state and findings for a project |
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
| `n` | project name from `.ai-badger/config.json`, read once per process |
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

## Producing a health report

`analyze` compares what a project **registers** against what was **observed**, and hands you
findings rather than a verdict. Run it with `--json` and write the report yourself.

```bash
python3 .ai-badger/skills/call-behaviorist/scripts/behaviorist.py analyze --json
```

### Where the expected components come from

Hooks run from what is **registered** with the agent, so that is what is audited — in order,
`.claude/settings.json`, `.claude/settings.local.json`, then `.ai-badger/hooks/hooks.json`.
The last is ai-badger's own declaration and the only project-level record in a deployment that
registers hooks elsewhere (Hermes, Copilot), so it never stops counting. A script registered in
more than one of them is one component.

Components are named by their **project-relative path**, not their filename: several skills
ship a `user_prompt_hook.py`, and merging them lets one hook's silence hide behind another's
excuse. A hook ai-badger did not wire is still listed — someone else's hook is information, and
it lands in `not_instrumented` because it cannot report on itself. A hook whose command runs no
`.py` script (an installed binary, a shell one-liner) has nothing to inspect and is not listed.

### What the findings mean

| `kind` | Severity | Means |
|---|---|---|
| `never_observed` | high | Registered **and** instrumented, but produced no record while the log holds records from elsewhere. It may never load, or never fire. This is the failure the tool exists to catch. |
| `not_instrumented` | low | Registered but calls no debug logger, so it *cannot* produce records. Its silence says nothing about health — do not report it as broken. |
| `version_skew` | high | One component ran at more than one framework version. Copies disagree — typically a plugin cache against a `.ai-badger/` scaffold. |
| `always_skipped` | medium | Fired every time and exited early every time. Live, but doing nothing. |
| `unexpected_component` | low | Produced records but is not registered by this project. Often legitimate (a plugin-side hook); worth a glance. |

`health` is `ok`, `warn`, `degraded`, or **`unknown`**. Treat `unknown` as *nobody looked* — it
means there is no evidence, not that everything is fine. Say so plainly in the report rather
than implying health.

**Evidence is not the same as lines in the log.** This tool records its own `enabled`,
`disabled` and `cleared` events; those prove the log exists and nothing more. They are excluded
from the record count, from `observed`, and from the health verdict. With no evidence,
`never_observed` is withheld too — when nothing at all was observed, every component is
trivially silent, and reporting that as a high-severity failure would be crying wolf.

### Writing it up

1. Run `analyze --json` and read the findings. **Do not restate them.** For each one, check the
   actual file before claiming a cause — `not_instrumented` and `never_observed` look identical
   in a summary and mean opposite things.
2. Lead with what is *wrong*, not with counts. "Two wired hooks never fire" beats "5 findings".
3. Include the observation window and record count, so a reader knows how much evidence there
   is. A `degraded` verdict from three records deserves that caveat.
4. Name the versions involved for any `version_skew` — that is the actionable part.

### Filing it

**Read the project's `CONTRIBUTING.md` first and follow it.** How issues are filed is a
project's own decision — the tracker, the required template, the labels, whether an issue is
even the right channel. This skill ships into repositories it knows nothing about, so it does
not prescribe a command.

If the project has no `CONTRIBUTING.md`, or it is silent on issues, ask before filing.

Two things regardless of process:

- **Do not paste raw JSON as the issue body.** The written report is the deliverable; the
  `--json` output is your evidence for it.
- Title it so the headline is legible in a list: `ai-badger health: <project> — <what is
  wrong>`, not `health report`.

## Turn it off when you are done

The window expires on wall-clock time, checked on every event — no timer and no cron. Debug
logging that never switches itself off is a slow disk leak and a standing privacy exposure,
which is why `on` always takes an expiry and caps it at 24 hours.
