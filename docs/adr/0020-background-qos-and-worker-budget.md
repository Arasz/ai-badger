# ADR-0020 — Background QoS and a derived worker budget; an admission queue rejected

**Date:** 2026-08-16
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude, from a measured architect lane
**Scope:** `features/common/skills/worktree-agent-isolation/scripts/run_suite.py`, `features/common/skills/worktree-agent-isolation/references/machine-load.md`
**Supersedes:** Nothing.

## Context

Running several agents in parallel worktrees on one machine (M4, this repo's own workflow —
see ADR-0009/0011 and `references/shared-worktree-collisions.md`) made the machine "almost
unusable": foreground interactive work (typing, an IDE, a browser) competed with N saturating
`dotnet test`/`bun test`/build processes for the same CPU, and nothing distinguished "the human
is waiting on this" from "a background agent kicked this off ten minutes ago."

An architect lane measured the mechanisms available to fix this, on the same M4, under 20
concurrent saturating processes, before proposing anything:

| Condition | Foreground work vs idle |
|---|---|
| No mitigation | 4.8x slower |
| `nice` (max niceness) | 4.4x slower |
| `taskpolicy -b` | 1.07x slower |
| `taskpolicy -b`, applied late to a running PID | 1.45x slower |
| `taskpolicy -b`, applied from birth | 1.49x slower |
| `taskpolicy -b`, inherited by children | 2.65x slower |
| Foreground work while `-b` background load runs | 1.0x of idle |
| Cost to the `-b`'d work itself | 2.11x slower |

`taskpolicy -b` puts a process in macOS's background QoS class (CPU, I/O, and timer
coalescing all throttled together), not just CPU niceness — which is the whole gap between
4.4x and 1.07x. `nice` only touches CPU scheduling priority and left foreground work at 4.4x
of idle, statistically indistinguishable from doing nothing.

Separately, five worktrees running `dotnet test`, Vitest, and Playwright at once oversubscribe
the machine even with QoS solved, because none of these tools' default parallelism is aware of
sibling worktrees: `dotnet build`/`bun test` default to sequential (not a culprit), but
`dotnet test`, xUnit v3, Vitest, and Playwright each default to reading the *whole machine's*
core count independently. A percentage cap (Vitest's `maxWorkers: "50%"`) does not fix this —
it is 50% of the whole machine **in every worktree**, so five worktrees collectively ask for
250%.

## Decision

Ship two layers. A third — an admission queue — is designed in the same review and explicitly
**not built**.

### Layer 1: `taskpolicy -b` on the test/build runner, macOS only

`scripts/run_suite.py` prefixes the wrapped command with `taskpolicy -b` when the platform is
macOS, `--no-qos` was not passed, and `AI_BADGER_QOS` is not `off`. Any one of the three
disables it, independently. `taskpolicy` missing from `PATH` is a stderr warning, not a
failure — the command still runs unprefixed.

This alone fully answers "the machine is almost unusable," independent of how many agents are
running: 1.0x of idle under `-b` at 20 concurrent processes is not a partial mitigation, it is
the fix. It costs the QoS'd process itself 2.11x — accepted, because that process was never
the one the human was waiting on.

### Layer 2: a derived parallelism budget, exported for tool config to read

```
budget = max(1, (cores - reserve) // min(agents, slots or agents))
```

`cores` comes from `os.process_cpu_count()` (respects a cgroup/`taskset` limit), falling back
to `os.cpu_count()` — never `os.sched_getaffinity` directly, which is Linux-only and raises on
macOS/Windows, and which `process_cpu_count` already reads internally where it applies.
`reserve` defaults to 2 (cores left for the OS/orchestrator). The result is exported as
`AI_BADGER_TEST_WORKERS`, and never overwrites a value the caller already set.

`max(1, ...)` is load-bearing, not defensive boilerplate: at `agents=20, cores=10, reserve=2`,
`(10-2)//20` is `0`, and most tools treat a 0 worker count as "ignore this and use my own
default" rather than "run with 0 workers" — silently discarding the whole point of this layer
at exactly the oversubscription level it exists to defend.

Because **neither Vitest nor Playwright has a native worker env var**, their own config files
must read `AI_BADGER_TEST_WORKERS` explicitly — the same shape `playwright.config.ts` already
uses for `CI`. `dotnet test` and xUnit v3 take the value as an explicit CLI flag instead
(`--max-parallel-test-modules`, `--max-threads`), since they have no env-var seam either. Full
per-tool table and config snippets: `references/machine-load.md`.

### Machinery failures never block the wrapped command

Every step in `run_suite.py` — core-count detection, budget computation, QoS resolution, the
best-effort state-log write used for post-hoc diagnosis — is wrapped so that a failure prints a
warning to stderr and the script proceeds to run the command anyway. A false "your tests never
ran" from the wrapper's own bookkeeping is a worse failure mode than transient
oversubscription, so nothing in this script's own machinery is allowed to be a hard failure.

## Rejected alternatives

**An admission queue (layer 3).** Shared state across agents — who holds a slot, who is
waiting — needs a coordination point: a lockfile, a daemon, or a database row. Its only
remaining justification after layers 1-2 ship is memory pressure, and it barely addresses that.
Swap was measured 94% full (11,538 M of 12,288 M, verified twice) on the loaded machine, but
the dominant memory consumer is ~20 resident agent sessions at 0.5-0.7 GiB each — a queue
staggers *when* a process starts, it does not evict a process that is already resident and
idle. No scheduling mechanism reaches that. Designed (interface, slot model, eviction policy)
but **not built**: the cost (shared state, a new failure mode — a stale lock outliving its
process) is not paid back by a benefit layers 1-2 do not already cover.

**A daemon.** Same shared-state problem as the queue, plus a lifecycle problem the queue does
not have on its own: something has to start it, keep it alive across machine sleep/wake, and
be trusted not to be the thing that is itself wedged when the machine is under load — the
exact condition this ADR exists to fix. Rejected for the same reason as the queue, plus this.

**A `PreToolUse` hook that throttles or queues a tool call.** Hooks run per-invocation inside
one agent's session; they have no visibility into what *other* sessions are doing, which is the
entire problem (oversubscription is a cross-session fact). A hook could only ever see and act
on its own session's calls, which cannot solve a resource contention problem between sessions.

**`flock`.** Considered as the queue's coordination primitive if layer 3 were built. Rejected
independent of the queue decision: `flock` is POSIX-only and this skill declares `platforms:
[linux, macos, windows]` (35 of 38 skills in this catalog make the same declaration) — a
Windows-only agent session would get a script that cannot even import, not one that degrades.
`scripts/run_suite.py` imports no `fcntl` for this reason, and a lint gate (blocking `fcntl` via
`sys.meta_path` in the test suite) pins it.

**`nice`.** Measured directly against `taskpolicy -b` under identical load (table above): 4.4x
vs 1.07x. `nice` only reorders CPU scheduling priority; it does not touch I/O priority or timer
coalescing, which is where most of the "almost unusable" feeling actually comes from on a
CPU-idle-but-I/O-thrashing machine. Rejected on its own measurement, not as a fallback from
`taskpolicy -b` being unavailable.

## Two proxies the architect lane got wrong, and had to redo

Recorded here because both are exactly the kind of thing that gets silently re-proposed if
nobody writes down why they were replaced:

1. **Sleep-wakeup latency as a usability metric.** An early pass measured how long a sleeping
   process took to wake and resume scheduling once `taskpolicy -b` was applied, and reported
   that number as "how unusable does the machine feel." It does not measure that. A background
   QoS process spends most of its life running, not asleep waiting to wake — the number that
   answers "does the machine feel usable" is foreground throughput *while the background load
   is actively running*, which is the 1.0x-of-idle figure in the table above, not a wake-latency
   number. The wake-latency figure was dropped from the write-up entirely rather than kept as a
   secondary metric, because it does not correlate with the thing it was being used to argue for.
2. **A first late-application measurement with no control.** The first attempt to measure
   "does applying `-b` to an already-running PID work as well as applying it at birth" ran the
   late-application case once, got a favorable number, and reported it without ever running the
   birth-applied case under the same load conditions to compare against. Redone with both
   conditions measured back-to-back under identical load: birth-applied 1.49x, late-applied
   1.45x — close enough that late application is validated as a real recovery tool, but only
   because the second pass added the missing control. The first pass's number, in isolation,
   proved nothing about "as well as."

## Consequences

- **The stated complaint is solved.** Foreground work returns to ~1.0x of idle under 20
  concurrent saturating processes with layer 1 alone, independent of agent count.
- **Every fixed timeout on a QoS'd process tightens by ~2.11x.** This is not hypothetical —
  `apphost-lock.ts:9-12` in the job-search-ai-assistant repo records two overlapping worktrees
  producing `TaskCanceledException` at `AspireInfraFixture.InitializeAsync`, a startup timeout
  with no assertion involved. Mitigation is documentation, not code: never wrap long-lived
  infrastructure (AppHost, dev servers, emulators) with `-b` — only the test/build runner
  invocation itself, since children inherit it — and raise fixed timeouts on timing-sensitive
  suites by >=2.5x when QoS is active. `AI_BADGER_QOS=off` exempts a lane (e.g. a CI runner
  that owns the whole machine) entirely.
- **Layer 3 stays designed but unbuilt.** If resident-session memory pressure becomes the
  dominant complaint (not CPU contention, which layers 1-2 already fix), the queue design is
  available to revisit — but the memory argument, not a re-measurement of CPU contention, is
  the trigger to reopen this ADR.
- **No new runtime dependency.** `run_suite.py` is Python 3 stdlib only, matching the rest of
  this repo's 103 `.py` files.
