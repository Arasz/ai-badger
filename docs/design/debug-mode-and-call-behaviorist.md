# Design — debug mode and the `call-behaviorist` skill

**Date:** 2026-07-27
**Status:** Proposed — not implemented
**Framework version at time of writing:** 0.28.2

A debug mode that makes ai-badger's own machinery observable: when a hook fires, which one,
in which project, under which agent. Today the framework is silent about its own behaviour, so
diagnosing "did that hook even run?" means adding print statements and re-scaffolding.

Two questions have to be answered before any code: **how a hook learns that debug mode is on**,
and **where the audit record goes**. Everything else follows from those.

---

## Question 1 — how debug mode is signalled

### What a hook can actually see

A hook is a separate process. It gets exactly three things: its **environment**, its **stdin
payload** (JSON: `session_id`, `cwd`, `hook_event_name`, `tool_name`), and **the filesystem**.
It does not see the session, the agent's config, or anything in memory. Any signalling design
is constrained to those three.

### Options

| Option | Verdict |
|---|---|
| Env var only (`AI_BADGER_DEBUG=1`) | Rejected as the primary mechanism. A hook inherits the *agent host's* environment, set when the host launched — usually a GUI, where the user has no way to set it per project. Same root cause as the `~/.dotnet/tools` PATH bug fixed in 0.28.0. Useful as an override, not as the mechanism. |
| Project marker file (`.ai-badger/debug.json`) | Rejected. It lands in a git-tracked directory, so enabling debug becomes a commit — and the auto-wm skill already lists "marker in the project pollutes git" as a known mistake. It also cannot cover hooks that fire outside any project. |
| Config key (`config.json: {"debug": true}`) | Rejected. Requires a re-scaffold to flip, is schema-validated, and is committed. Debug mode is an ephemeral, per-machine state; config is durable, shared project intent. Wrong lifetime. |
| **User-level state file, project scope recorded as data** | **Recommended.** |

### Recommendation

One state file at `~/.ai-badger/debug/state.json`:

```json
{
  "enabled": true,
  "scope": "project",
  "project": "/Users/…/ai-badger",
  "enabled_at": "2026-07-27T10:55:00+00:00",
  "expires_at": "2026-07-27T14:55:00+00:00"
}
```

- `scope: "user"` → log everywhere. `scope: "project"` → log only when the hook's `cwd` is
  inside `project`.
- **Project scoping is data inside a user-level file, not the file's location.** This is
  precisely the shape auto-wm already uses (`~/.claude/awm/state.json` records the project it
  was enabled in and the gate refuses elsewhere). It is proven in this codebase, keeps the
  marker out of git, and still covers hooks firing outside a project.
- `expires_at` is **required**, defaulting to 4h. Debug logging that never turns itself off
  becomes a silent disk leak and a standing privacy exposure. The hook compares wall-clock on
  every event — no timer, no cron.
- `AI_BADGER_DEBUG=1` in the environment forces logging on regardless, for one-off runs where
  editing state is inconvenient. Env **overrides** the file; the file never overrides env.

Read cost per hook: one `stat` plus a small `read_text` on a file that is usually absent.
When the file does not exist, the logger must return before doing anything else.

---

## Question 2 — where the audit file lives

### Recommendation

`~/.ai-badger/debug/audit.jsonl` — user-level, append-only, one JSON object per line.

`~/.ai-badger/` is **already** the established home for user-level ai-badger runtime state: it
holds `framework/` (the cached checkout) and `hook-errors.log`, which hooks already append to
via `record_hook_failure`. This puts the audit log beside an existing, working precedent rather
than inventing a location.

Rejected alternatives: a project-side `.ai-badger/debug/` (git pollution, and unreachable for
hooks firing outside a project) and a system temp dir (evaporates exactly when you want to read
it after a crash).

### Record shape

Small and flat. Every record carries enough context to answer "which hook, where, under what":

```json
{"ts":"2026-07-27T10:55:12+00:00","component":"prompt-markers/user_prompt_hook",
 "event":"start","project":"/Users/…/ai-badger","session":"6f1ea006","agent":"claude",
 "stack":"python","pid":41233,"ms":12}
```

- `agent` — derived from which hook contract invoked it plus env; `null` when undeterminable.
  **Never guessed.**
- `stack` — read from the project's `config.json` `stacks` when cheaply available, else omitted.
  A hook must not pay a config parse on every event just to label a line; cache per process.
- `event` — `start` / `end` / `skip`, so a hook that fires but exits early is distinguishable
  from one that never fired at all. That distinction is the whole point of the feature.

### The three properties that make this safe

1. **Atomic appends.** Open with `"a"` and write **one** `line + "\n"` per call. POSIX
   guarantees atomicity for `O_APPEND` writes under `PIPE_BUF` (4096 bytes), so concurrent
   hooks cannot interleave partial lines. This means records must be *bounded*: truncate any
   field over a fixed length, and never log free text such as prompt content.
2. **Bounded growth.** Cap at `MAX_AUDIT_LINES` (5000) and trim oldest on write, matching
   `awm.py`'s `MAX_DECISION_LINES` / `_trim_decisions`. Strict append-only is not worth an
   unbounded file on a user's disk. *(Note: this makes it append-only in spirit, not literally —
   call it what it is.)*
3. **0600 file, 0700 directory.** The log records project paths, session ids, and working
   directories — it says where someone works and what ran. Same treatment WP40 gave the
   prompt-marker state file.

### A logging failure must never break a hook

Every logger entry point wraps in `try/except Exception: return`. This deliberately contradicts
the repo's general "no silent failure" stance, and the reason is specific: a debug facility that
can break the thing it observes is worse than no debug facility. The escape hatch is that
failures still land in the existing `hook-errors.log` via `record_hook_failure`, so the silence
is bounded and recorded elsewhere.

---

## The hard part: getting the logger into the hooks

**This is the real cost of the feature, and it is not obvious.**

Only `hook_wiring.py` imports `badger_lib` — and that is the *generator*, not a hook. Every
runtime hook (`ai_badger_hooks.py`, `user_prompt_hook.py`, `drift_notice_hook.py`,
`session_start_hook.py`, `stop_hook.py`, `mcp_index_hook.py`, `awm_gate.py`, `awm_context.py`)
imports **nothing** from the framework. They are deliberately standalone, because they run from
several deployment shapes (framework checkout, `.ai-badger/` scaffold, `~/.hermes/plugins/`,
plugin cache) where no single relative path to `badger_lib` holds.

So `badger_lib.debug_log(...)` is not reachable without adding a `_bootstrap_lib()` to all eight
hooks — which multiplies the exact duplication **Wave 7** exists to remove, and adds an import
that can fail on every hook invocation.

### Options

| Option | Cost |
|---|---|
| Add `_bootstrap_lib()` to all 8 hooks | Makes Wave 7 strictly worse and puts a failure mode in front of every hook. **Rejected.** |
| Vendor a ~30-line `debug_log.py` beside each hook group, with a sync gate asserting the copies are byte-identical | Duplication, but *checked* duplication. **Recommended.** |
| One wrapper hook that logs on behalf of others | Cannot see whether an individual hook ran or exited early — defeats the purpose. **Rejected.** |

The recommended option has direct precedent: `record_hook_failure` is **already vendored
verbatim in three places** (`awm_gate.py`, `awm_context.py`, `user_prompt_hook.py`), with its
constants. This design does not introduce the pattern; it makes the existing pattern *checked*
by adding a gate in the shape of `sync_plugin_skills --check`.

**Sequencing:** this should land **after Wave 7**, which consolidates the bootstrap copies. If
Wave 7 produces a reachable shared module for hooks, the vendored copies collapse into it and
the sync gate is deleted. Building this first means building something Wave 7 then has to undo.

---

## The `call-behaviorist` skill

Named for observing behaviour rather than asserting it. Commands mirror `auto-wm`, which users
of this framework already know:

| Command | Effect |
|---|---|
| `on [--user] [DURATION]` | Enable; project-scoped by default, `--user` for everywhere. Default 4h. |
| `off` | Disable. |
| `status` | Mode, scope, time remaining, current log size. |
| `tail [N]` | Last N records, human-formatted. |
| `clear` | Truncate the log (records the truncation as its own entry). |

The skill is instructions plus one script, `scripts/behaviorist.py`. It never edits
`state.json` by hand — every change goes through the script so it is itself audited.

---

## Open questions

1. **Does `stack` earn its cost?** It requires reading the project's `config.json`. If per-process
   caching is not enough, drop the field — `project` already identifies the repo, and the stack
   can be looked up offline.
2. **Should `end`/`ms` records exist at all?** Timing doubles the record count. Possibly gate
   duration behind a `--timing` level rather than logging it always.
3. **Redaction.** `tool_name` is safe; tool *input* is not. This design logs no tool input at
   all. If that turns out to be insufficient for real debugging, redaction rules need designing
   before the field is added — not after.

---

## Definition of done

- Failing test first, per the repo invariant.
- Enabling debug produces records; disabling stops them; expiry stops them without a timer.
- A hook whose logger raises still completes its real work — tested by injecting a failure.
- Concurrent writers never produce a malformed line — tested with parallel processes.
- The vendored copies are byte-identical, enforced by a gate.
- `VERSION` bump + `docs/changelog/{version}-{slug}.md`.
