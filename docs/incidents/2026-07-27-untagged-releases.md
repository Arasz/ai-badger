# Incident — 32 versions were released without a tag, and the gate that should have caught it could not

**Date raised:** 2026-07-27
**Detected by:** the eight-lens project review (F-11, with F-10 as the compounding defect)
**Status:** resolved forward — baseline tag cut, guard hardened, detector added
**Affects:** every version between `0.3.0` and `0.19.0`

## What happened

[ADR-0001 decision 2](../adr/0001-versioning-and-release-model.md) says a version denotes
exactly one commit, forever, as an immutable `ai-badger--v{version}` tag.
[RELEASING.md](../../RELEASING.md) step 7 is the step that creates one. Between 2026-07-19 and
2026-07-27, `VERSION` moved through **35 distinct values** and **two tags** existed:
`ai-badger--v0.1.0` and `ai-badger--v0.2.0`. Step 7 was skipped 32 consecutive times.

Nothing reported it, because the one mechanism that reads tags was itself disabled by the
missing tags:

```
$ python3 scripts/release_guard.py          # before this incident was closed
shipped surface changed since ai-badger--v0.2.0 and VERSION was bumped (0.2.0 -> 0.20.0) — PASS
```

`release_guard.py` compares the working tree against the **last release tag**. With that tag 18
minor versions stale, every run found changes, found a differing `VERSION`, and passed. The
guard was green for 32 releases without ever being capable of red. A gate that cannot fail is
not a gate — it is a green light with a plausible label.

## Why it went unnoticed for eight days

Three properties compounded, and each one alone would have been survivable.

1. **The guard's PASS message is indistinguishable between "correct" and "inert."** Both print
   `— PASS`. Nothing in the output said *how far back* the baseline was, so a 16-version-old
   comparison read exactly like a one-version-old one.
2. **Consumers kept working.** Claude Code resolves by `version` in `plugin.json`, and Hermes
   consumers re-scaffold from a checkout via `den-refresh`. Neither path reads a git tag, so
   the missing tags produced no user-visible symptom — only an unprovable history.
3. **The release checklist's only unautomated step was the one that was skipped.** Steps 1–6
   of RELEASING.md are enforced by `version_sync.py`, `release_guard.py`, pytest, pylint and
   CI. Step 7 (`claude plugin tag --push`) runs after merge, by hand, on a green PR that
   already feels finished.

The ledger drifted in both directions, which is the sharpest evidence that no mechanism was
reading it: `0.13.1`, `0.15.0` and `0.17.3` have changelog entries but never appeared in
`VERSION`, while `0.1.0`–`0.6.0` held `VERSION` with no changelog entry at all.

## Impact

- **No release point is resolvable.** A bug report against "0.14.1" cannot be pinned to a
  commit, because no object in the repository claims to be 0.14.1.
- **`release_guard.py` provided no protection for 32 releases.** Any shipped-surface change
  that forgot a `VERSION` bump would have passed CI.
- **Not affected:** the content consumers received. Both distribution paths resolve by version
  string or by checkout, so shipped fixes did reach users. What was missing is the immutable
  point they can be reproduced from — the review's original "never shipped to any consumer"
  claim was checked and is overstated.

## Resolution

**Batching was rejected as an explanation.** The alternative fix on the table was to amend
ADR-0001 and RELEASING.md to say tags are cut in batches, matching what history actually did.
That was declined: 32 skipped tags is not a batching cadence, and writing the drift into the
policy would have retired the guard's only baseline rather than repaired it.

**Tagged forward, not backfilled.** `ai-badger--v0.20.0` now points at `4e89872`, the Wave 2
merge — a commit that carried `VERSION` 0.20.0 through the full CI gate set. The 32 historical
versions are **deliberately left untagged**: retro-tagging them would assert they passed
RELEASING.md's mandatory content verification, which they did not. A fabricated release point
is worse than an acknowledged gap, and this document is the acknowledgement.

The baseline now being current, the guard failed for the first time in its existence — on the
commit that hardened it:

```
$ python3 scripts/release_guard.py
shipped surface changed since ai-badger--v0.20.0 but VERSION is still 0.20.0:
    - scripts/release_guard.py
bump VERSION
```

## Prevention

| Change | Property it gives the gate |
|---|---|
| `_git` raises `GitCommandFailed` instead of returning `""`; `check()` prints `GIT COMMAND FAILED` and exits 1 (F-10) | A failed git command can no longer be read as "nothing changed" |
| `skipped_versions()` prints `UNTAGGED RELEASES` naming every changelog version between the last tag and `VERSION` | The drift becomes visible in CI output on the *first* skipped tag, not the 32nd |
| RELEASING.md step 7 marked as the release, not a follow-up | Names the step whose skipping is invisible |

The detector is informational and does not fail the build: one unreleased version in flight is
the documented model ("Several PRs, one release"). Two or more is the anomaly, and it now says
so out loud every CI run.

## What this incident is really about

The repo did not lack a release policy — it had a well-argued ADR, a written checklist and an
automated guard. It lacked *a way to notice the policy had stopped being followed*. Every
mechanism that could have reported the drift derived its baseline from the artefact that was
missing. When a check's authority comes from the thing it is checking, its silence carries no
information.
