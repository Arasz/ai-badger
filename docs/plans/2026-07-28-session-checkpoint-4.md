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

## All three agents landed

| Branch | Released as |
|---|---|
| `fix/framework-cache-version-skew` | **0.35.6** — warns on stderr, never refuses: the check lives in `_bootstrap_lib()`, which ADR-0009 decision 5 requires to be one text shared by CLIs *and* session-start hooks. Mirrored into all ten shims because a stale cache imports its own `badger_lib` |
| `fix/debug-log-test-isolation` | **0.36.0** — see below; 0.35.5 had claimed this already |
| `feat/config-exclude` | **0.36.0** — Group I |

### 0.35.5 said the leak was fixed. It was not.

0.35.5 (cut by a parallel session) moved `$HOME` in a session-scoped autouse fixture.
**Measured on `main`, a full suite run still added 76 test-signature records** to the real
`~/.ai-badger/debug/audit.jsonl` — `commit_reminder_hook` 37, `ai_badger_hooks/commit_reminder`
24, `prompt_markers_hook` 6, `session_start` 6, `drift_notice` 2, `session_start_hook` 1.

A session fixture runs **after collection**, and a module imported during collection has already
resolved `Path.home()`. The agent had found this independently and been overruled by a release
it never saw. Same run after merging its `$AI_BADGER_DEBUG_DIR` override, set at conftest
*import* time: **0 records**. Both isolations kept — the `$HOME` move is the wider floor, since
the suite also writes `~/.ai-badger/hook-errors.log` and `~/.hermes/plugins/*.py`.

The merge needed hand resolution in five files; the two mechanisms collided semantically in one
test, noted in the release entry.

### Group I verified independently of the agent's own probe

Scaffolding a throwaway project with `exclude.skills=[mcp-index]` and
`exclude.invariants=[tdd-mandatory]`: neither delivered, both noted, and a typo'd key
(`"skils"`) is a schema validation error rather than a silent no-op. The invariant case is what
closes the false `getting-started.md` promise.

## Tags

`0.35.0`–`0.35.3` backfilled at session start; `0.35.6` and `0.36.0` cut and tagged here;
`0.35.4`/`0.35.5` were already tagged by the parallel session. Remote now carries an unbroken
run `0.35.0 … 0.36.0`, and `release_guard` reports clean.

## Still open

- **Wave 2 E** (Wave 6 — `Scaffolder`'s five mixins → composed collaborators) and **F**
  (Wave 16 — rename top-level `scripts/`). **Wave 3 H** (split `badger_lib.py`) needs both.
  Group I has landed, so these are now unblocked.
- **No ADR for `exclude`.** The research proposed `0009-…`, but that number is taken, so it
  would be 0010 — and the wording is the maintainer's call. Reasoning currently lives only in
  the changelog and the research doc.
- **Shape D (`~/.hermes/plugins/`) is unjudged for version skew.** `adjust_hooks` records
  `frameworkRoot` but no `frameworkVersion`, so there is nothing to compare.
- **An excluded skill's `.ai-badger/skills/<name>/` is left on disk** by design, so
  `feed-badger`'s `detect_additions` can read it as a project addition.
- Real-home pollution beyond the audit log: `~/.ai-badger/hook-errors.log` and
  `~/.hermes/plugins/*.py` are still written by the suite.
- Unscheduled items 1 (instructions carry no preserved regions) and 2 (Junie gets no root
  `AGENTS.md`) touch `scaffold.py`; item 5: 13 merged remote branches could be pruned.

## Still open

- **Wave 2 E** (Wave 6 — `Scaffolder`'s five mixins → composed collaborators) and **F**
  (Wave 16 — rename top-level `scripts/`). Both collide with Group I on `scaffold.py`, so they
  sequence after it rather than fanning out. **Wave 3 H** (split `badger_lib.py`) needs both.
- Group G (instrument the remaining hooks) is **done** — shipped in 0.35.1.
- Unscheduled items 1 (`.ai-badger/instructions/*.md` carry no preserved regions) and 2 (Junie
  gets no root `AGENTS.md`) also touch `scaffold.py`; deferred for the same reason.
- Item 5: 13 merged remote branches could be pruned. Outward-facing; offered, not actioned.
