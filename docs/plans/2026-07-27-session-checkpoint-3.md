# Session checkpoint — 2026-07-27, third

Point-in-time record, written at 17:37 CEST. Supersedes
[`2026-07-27-session-checkpoint-2.md`](2026-07-27-session-checkpoint-2.md) for anything that
disagrees; that file keeps the detail on 0.32.0/0.33.0 and the ADR-0007 consequences.

**State:** `main` @ `773dec9`, VERSION `0.33.0`, last tag `ai-badger--v0.33.0`.
**20 commits are merged and unreleased.** 1106 tests passing on `main`, all ten gates green.

## Released today

| Version | What |
|---|---|
| **0.32.0** | Four defects a real `0.18.1 → 0.31.1` refresh found, plus Waves 11 (ADR-0007), 12, 15, 18 and deps-guard |
| **0.33.0** | Stopped installing Semgrep Guardian — a tool-call interceptor — by default on every python project |

## Merged, unreleased — the next release is at least a minor

| Change | Shipped surface |
|---|---|
| **#103 cause 1** — plugin ships skills at `<plugin-root>/skills/`; `.claude/skills/` → `skills/`, 70 files moved (ADR-0008) | yes |
| **#103 cause 2** — `features/claude/adjustments/adjust_skills.py`; scaffolded projects get Claude skill discovery | yes |
| **Wave 8** — one feature-type registry; `templates` joins drift's new-item scan | yes |
| **Statusline capture wired** — opt-in `statusLineCapture.enabled`, default false | yes |
| **Small batch A** — Junie path corrected in `support.json`; `$schema` permitted by the two closed schemas; statusline unwire path | yes |
| **Secret scan widened** to `push: branches: ['**']` | CI |

**Not yet written: the 0.34.0 changelog.** That is the immediate blocker on cutting the release.
The maintainer chose it as the next task at 17:34, then redirected to the behaviorist bug below.

## In flight

### 1. Wave 7 — landed, under independent review, **deliberately not merged**

Branch `task/wave-7-one-framework-root`, rebased onto `773dec9`.

Maintainer instruction: **review it with an independent sub-agent before merging.** A reviewer is
running now. It was given the branch, the plan and ADR-0007 — **not** the implementing agent's
report — so it reviews the code rather than an account of it. Its brief is to falsify; a clean
verdict is an acceptable outcome.

Two claims from the branch that the review must settle, because both are decisions rather than
mechanics:

- It reports a **fifth** root implementation (`mcp_index._find_framework_root`) that ADR-0007
  missed. The plan said three, the ADR corrected it to four. If five is right, the count has
  been wrong at every previous telling.
- It records **`frameworkRoot` in `manifest.json`** — relative when the framework is inside the
  target, absolute otherwise. `manifest.json` is tracked, so an absolute value gets committed
  and is meaningless on a teammate's machine. The claim is that a wrong value degrades to
  pre-change behaviour rather than a wrong answer. Verify, do not accept.

**Do not merge Wave 7 until the review reports.** Waves 16 and 17 are queued behind it.

### 2. Issue #104 — den-refresh cannot deliver a new skill

Branch `fix/drift-sees-common-and-templates`, agent still running, **scope was extended
mid-flight** to cover all three defects in the issue. Shipping only the first achieves nothing
visible, which is why they are one change:

1. `detect_new_items` skips `common` — every framework skill lives in `stacks.common.skills`, so
   the whole skill catalog is discarded before comparison.
2. `refresh.py:230` reads `newItems` to gate the re-scaffold, but the report at :254-256 never
   emits it. The one signal that would have caught this was computed and thrown away.
3. `refresh.py:127` derives the re-scaffold's skill list from `manifest.entries` — a closed
   loop. Absent from manifest → absent from the list → never scaffolded → stays absent.

Coupled to it, from Wave 8: **`templates` get no manifest entries at all**, so fixing (1)
without that makes every template a permanent `new` false positive. The agent may instead land
`drift_reports_new=False` for templates as an explicit interim — the registry makes it one line.

Open judgement call it was told to make explicit: a union skill list means a **deliberately
removed** skill comes back, because manifest-absence currently means both "not wanted" and "not
yet known".

### 3. `call-behaviorist analyze` reports false alarms — RED tests parked

Branch **`fix/behaviorist-evidence-vs-bookkeeping`** holds four deliberately-failing tests. **Do
not merge it as-is.**

Reported from a real project, then reproduced here and found worse than reported: with debug
logging off and a single `cleared` record, `analyze` returns

```
health: degraded   records: 1
findings: [('never_observed', 'session_start_hook', 'high'),
           ('unexpected_component', 'call-behaviorist', 'low')]
```

**One root cause.** `call-behaviorist` logs its own lifecycle events (`enabled`/`disabled`/
`cleared`) with no project. `_read_records` admits project-less records into *every* project's
analysis — deliberate, so user-scope hooks are visible — so `records` is never empty once anyone
has run `clear`, and `health = "unknown"` is gated on `not records`. The tool also counts itself
as an `unexpected_component`.

`unknown` is supposed to mean *nobody looked*. It is currently unreachable in practice, which
inverts the whole design: the report claims a verdict where it has no evidence. This is the
"cries wolf" failure the skill's own docs warn about.

**Blocked on:** the maintainer is sending the full health report. Their excerpt names a **second
defect** ("the analyzer is measuring the wrong things") that is not yet visible, and their run
showed `warn` where the local repro gives `degraded` — possibly a different path. Wait for it
before implementing; the fix design may need to widen.

The fifth test in that commit is a guard that must pass before *and* after: genuine silence must
still be reported. The fix must mute the false alarm without muting the real signal.

## Issues

| Issue | State |
|---|---|
| **#76** Hermes hooks receive no `cwd` | **closed** — fixed in 0.18.0, left open by oversight |
| **#67** sync Hermes learned skills | **closed** — delivered in 0.18.0; its question-5 assumption corrected on close |
| **#103** skills invisible to Claude Code | **closed** — both causes merged, unreleased |
| **#104** den-refresh cannot deliver a new skill | **open** — fix in flight, see above |

No open PRs. **13 merged remote branches** could be pruned; offered twice, not actioned, because
it is outward-facing.

## Queued — Part 2, after Wave 7 merges

| Work | Why it waits |
|---|---|
| **Wave 6** — five mixins → composed collaborators | Real collision: restructures `scaffold.py` and the mixins Wave 7's shim work also edits |
| **Wave 16** — rename top-level `scripts/` | After 7, so the root literal lives in one predicate not 19 files |
| **Wave 17** — split `badger_lib.py` | Needs 7 **and** 8. ADR-0007: the `badger_lib` facade is mandatory — flat siblings, never a package with `__init__.py` |
| **Small batch B** — preserved-region asymmetry in `.ai-badger/instructions/*.md`; instrument `prompt-markers` / `task` / `mcp_index` hooks | Both touch files Wave 7 edits |

## Open, not started

1. **Drift never scans the agent stacks either** — `claude`, `copilot`, `hermes`, `junie` are not
   in `config.stacks`, yet the manifest holds 20 copilot adjustments and 2 hermes ones. The
   #104 agent was told to decide and justify rather than silently fix only `common`.
2. **`~/.ai-badger/framework` does not report its own version skew.** It exists on this machine
   at VERSION **0.13.0** against a 0.33.0 catalog. Wave 7 demotes it to last in the resolution
   order but does not discharge it.
3. `.ai-badger/instructions/*.md` are `shutil.copyfile` copies and carry no preserved regions,
   while their `.github/` counterparts now do.
4. **Junie gets no root `AGENTS.md`.** `.junie/AGENTS.md` is correct and highest-precedence, but
   other agents read the root convention and nothing writes it.
5. No secret-scanning **pre-commit** hook — a decision, not an omission, now recorded in
   `SECURITY.md` with both rejected candidates and why.

## Working agreements in force

- **Merge locally, not via PR round-trips** — the gates are the record. Branch-protection bypass
  is session-scoped and deliberate.
- **Parallel agents never touch `VERSION`, the changelog, or re-scaffold.** Every merge conflict
  early in the session came from concurrent bumps. The release is cut centrally.
- **Update this checkpoint as each agent lands**, not batched at the end.
- Agents push branches and **do not open PRs**.
- Never stage anything under `.idea/` or `__pycache__/`. Never hand-edit `skills/`,
  `.claude/skills/` or `.ai-badger/skills/` — regenerate with `sync_plugin_skills.py`.
