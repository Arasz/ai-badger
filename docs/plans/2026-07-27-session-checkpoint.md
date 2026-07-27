# Session checkpoint — 2026-07-27

State at the point the session approached its limit, so the next session can resume without
re-deriving anything. Delete this file once the outstanding work below is picked up.

## Where the code is

| Thing | State |
|---|---|
| `main` | `0.27.0`, tagged `ai-badger--v0.27.0`; `release_guard` PASS |
| Tags | `ai-badger--v0.20.0` … `v0.27.0` exist; earlier versions deliberately untagged (`docs/incidents/2026-07-27-untagged-releases.md`) |
| **PR #89** | **OPEN** — this checkpoint + the research report. Docs only, no version bump, no tag. |
| This branch | `task/docs-research-and-refactor` — holds the research report + this checkpoint only |

### Immediate next action

Merge PR #89, then pick up the documentation work below, or the next wave from the
deferred-work plan.

**Never skip a release tag.** `release_guard` compares against the last release tag, so a
skipped tag silently disables the guard — that is what caused the 32-release gap recorded in
the incident report.

## Waves done this session

| Wave | Release | PR | What |
|---|---|---|---|
| 9 | 0.25.0 | #85 | Hardening (shell=True, dependency consent, ReDoS caps, state-file privacy) |
| 10 | 0.24.0 | #84 | feed-badger outbound secret scan + explicit pathspec |
| — | — | #86 | Plan rewritten to cover all fourteen §7 items as Waves 6–18 |
| 13 | 0.26.0 | #87 | One declaration of which skills ship; `code-review-checklist` now default |
| 14 | 0.27.0 | #88 | One skill-extension mechanism; legacy layout now refused, not ignored |

Remaining planned waves: **6, 7, 8, 11, 12, 15, 16, 17, 18** — all specified in
`docs/plans/2026-07-27-deferred-work-plan.md`, with a suggested order and two hard ordering
constraints (Wave 11's ADR gates 7 and 16; Wave 17 must follow 7 and 8).

## Outstanding: the documentation work (user-requested, mid-flight)

The user asked for three things, in order. **Step 1 is done; steps 2 and 3 are not started.**

1. ✅ **Research** — best-practice docs structure, what to document in OSS, contribution guides
   and enforcement. Complete: `docs/research/2026-07-27-docs-structure-and-contribution.md`.
2. ⬜ **Refactor the docs** against the current project state, using that research.
3. ⬜ **Keep docs in sync with the project from then on** — an ongoing enforcement mechanism,
   not a one-off.

### What the refactor has to contend with

`docs/` currently holds **69 markdown files** across `adr/`, `changelog/`, `plans/`, `reviews/`,
`incidents/`, `research/`, `design/`, `specs/`, `article-update-notes/`, plus ~10 loose
top-level files (`framework-architecture.md`, `codebase-analysis-report.md`, `known-gaps.md`,
`dictionary.md`, `scripts.md`, `index.md`, and others).

Known issues to weigh, from the research and from this session's own experience:

- **The repo root has only `README.md` and `LICENSE`.** No `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, or `SECURITY.md` anywhere — `SECURITY.md` is the highest-value gap
  (enables GitHub private vulnerability reporting; required by the OpenSSF badge).
- **`docs/changelog/{version}-{slug}.md` is a minority convention.** The research says per-file
  changelogs exist to avoid merge conflicts on one growing file. At 1–2 maintainers that
  pressure doesn't exist — but CLAUDE.md mandates the per-file format as a non-negotiable
  invariant, so **changing it is a maintainer decision, not a refactor**. Treat it the way
  Wave 13 treated `code-review-checklist`: surface the question, don't answer it unilaterally.
- **Several docs are point-in-time and now partly stale** — `known-gaps.md`,
  `codebase-analysis-report.md`, and the two `docs/plans/` files describe a project that has
  moved five releases since. Dated, archived, or refreshed are all defensible; silence is not.
- `docs/index.md` exists and should end up as the entry point that makes the tree navigable.

### For step 3, the mechanism

The research's concrete levers: **Vale** (prose), **markdownlint** (structure), **lychee**
(dead links), run in CI on `docs/**` and mirrored in `.pre-commit-config.yaml`. This repo
already has the right shape for it — `scripts/release_guard.py`, `tdd_guard.py`, and
`version_sync.py` are all "a gate script plus a CI step", so a `docs_guard.py` would sit
naturally beside them. **Size this as its own wave in the deferred-work plan** rather than
bolting it onto the refactor PR.

## Conventions this session followed (keep following them)

- **TDD is not optional**: the failing test comes first, and the PR body says which tests were
  red before implementation.
- **Any pre-existing test rewritten to a new contract gets named in the PR body.** Added as the
  fifth definition-of-done item in #86; Waves 9, 10, 13 and 14 all had to do it.
- One PR per wave; never push to `main`; bump `VERSION` and add a changelog entry every release.
- Re-scaffold the repo against itself after touching `features/common/skills/welcome-ai-badger/`
  or `scripts/` — `.claude/skills/` and `.ai-badger/` carry copies that go stale and fail
  `sync_plugin_skills --check` and pylint:
  ```
  python3 scripts/sync_plugin_skills.py
  python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py \
      --config .ai-badger/config.json --target . --root .
  ```
- Use `.venv/bin/python3` — the system `python3` is 3.14 and has no pytest.
- `git rebase` needs `-c rebase.autoStash=true`: there is a long-standing unstaged deletion of
  `.idea/ai-badger@2.iml` in the working tree that is not ours to commit.

## Full gate command list

```
.venv/bin/python3 -m pytest -q
.venv/bin/python3 -m pylint scripts features          # 10.00 required
.venv/bin/python3 scripts/index_build.py --check
.venv/bin/python3 scripts/validate.py --all
.venv/bin/python3 scripts/version_sync.py --check
.venv/bin/python3 scripts/sync_plugin_skills.py --check
.venv/bin/python3 scripts/release_guard.py
.venv/bin/python3 scripts/tdd_guard.py
node --test tests/js/*.test.mjs
```
