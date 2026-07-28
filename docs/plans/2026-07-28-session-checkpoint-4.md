# Session checkpoint 4 — 2026-07-28

Continues [session checkpoint 3](2026-07-27-session-checkpoint-3.md). Plan of record:
[improvement plan](2026-07-27-improvement-plan.md).

## State at session start

`main` clean, one unpushed commit, `VERSION` 0.35.2. Three releases — **0.35.0, 0.35.1 and
0.35.2 — had shipped with no `ai-badger--v*` tag**. Because `release_guard` resolves its
baseline as the highest-semver tag, every run since had been comparing the shipped surface
against **0.34.1**.

## Shipped this session

### Tags backfilled

`ai-badger--v0.35.0` → `97999a2`, `v0.35.1` → `bea9c85`, `v0.35.2` → `d26db3f`, each at the
last commit carrying that `VERSION`. Baseline is correct again.

### 0.35.3 — an untagged release fails the guard

`release_guard` **already detected** this exact condition. It printed `UNTAGGED RELEASES: …`
and returned 0, with a test asserting that deliberately:

```python
assert rc == 0  # informational: the bump itself is correct
```

A warning on a passing gate is read by nobody. Two changes:

- **Returns 1.** The message is unchanged; the exit code is not.
- **Runs before the diff, and independently of it.** It used to sit only on the path where the
  shipped surface changed *and* `VERSION` was bumped — so the docs-only pushes that actually
  followed 0.35.0 took the early `no shipped-surface changes — PASS` return and never looked at
  tags at all. That is the specific reason detection existed and still failed to stop anything.

Verified by replaying the real history: a clone with the three tags removed, checked out at
`d26db3f`, exits 1 and names 0.35.0 and 0.35.1 while correctly exempting 0.35.2 as in flight.

**Known limit, documented:** the guard only sees versions *above* the highest tag, so it catches
the release you just shipped, not archaeology — and it catches it one push late, since no tag can
exist for the version being pushed at the moment it is pushed.

## Decision taken without the maintainer

**Group I `exclude` scope: the four name-addressable feature types** — `skills`, `personas`,
`invariants`, `instructions`, derived from `[ft.name for ft in FEATURE_TYPES if
ft.drift_reports_new]` rather than a second hardcoded list.

Asked; no answer after 300s; proceeded. Reasoning: those four are the types scaffold records
under the item's own index name, so "exclude by name" has a stable referent. `templates`,
`hooks` and `adjustments` materialise outputs under names of their own, so the key would have
nothing to bind to. Including `invariants` also closes the false promise in
`getting-started.md` ("Delete the ones you do not want before committing" — a refresh restores
them) in the same change. **Reversible**: narrowing to skills-only later is a schema edit.

## In flight — three worktree-isolated agents

| Branch | Work |
|---|---|
| `feat/config-exclude` | Group I. Enforced once in `Scaffolder.__init__`; must handle `hook_wiring.py` wiring hooks for an excluded `task` skill without checking the file exists, and must prune what an earlier run installed |
| `fix/debug-log-test-isolation` | The audit log is written by ai-badger's own test suite. Acceptance: full suite runs, real `audit.jsonl` gains zero entries |
| `fix/framework-cache-version-skew` | `~/.ai-badger/framework` (0.13.0 here) is silent about skew when selected as last-resort root |

None bumps `VERSION` or writes a changelog; the release is cut centrally.

## Still open

- **Wave 2 E** (Wave 6 — `Scaffolder`'s five mixins → composed collaborators) and **F**
  (Wave 16 — rename top-level `scripts/`). Both collide with Group I on `scaffold.py`, so they
  sequence after it rather than fanning out. **Wave 3 H** (split `badger_lib.py`) needs both.
- Group G (instrument the remaining hooks) is **done** — shipped in 0.35.1.
- Unscheduled items 1 (`.ai-badger/instructions/*.md` carry no preserved regions) and 2 (Junie
  gets no root `AGENTS.md`) also touch `scaffold.py`; deferred for the same reason.
- Item 5: 13 merged remote branches could be pruned. Outward-facing; offered, not actioned.
