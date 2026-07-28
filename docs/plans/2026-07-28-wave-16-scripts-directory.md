# Wave 16 — the top-level `scripts/` directory

**Branch:** `refactor/gates-directory` · **Executor:** one agent, worktree-isolated
**Parallel-safe with:** [Wave 6](2026-07-28-wave-6-scaffold-collaborators.md) — zero file overlap.

**Read §1 and §2 before doing anything.** This wave was scoped as "rename top-level `scripts/`".
The analysis below says do **phase 1 only**, and defers the rename itself pending a maintainer
decision. Phase 1 is fully specified and safe. Phase 2 is specified but **must not be started**
without an explicit go-ahead.

---

## 1. Why the rename as originally scoped is a bad trade

The screaming-architecture invariant genuinely applies: `scripts/` is exactly the generic
technical bucket the invariant names alongside `Services/` and `Utils/`. That part is right.
The cost is the problem.

**Measured blast radius of a full rename:**

| Area | `scripts/` references |
|---|---|
| `tests/` | 820 |
| `docs/` | 299 |
| `features/` | 95 |
| `skills/` (generated) | 82 |
| `scripts/` | 17 |
| `.github/` | 17 |
| lefthook / pre-commit / verify.sh | 13 |
| **Total** | **~1,340** |

**And there is a bricking hazard, which is the decisive argument.**

`is_framework_root` is:

```python
(path / "schemas").is_dir() and (path / "features").is_dir()
    and (path / "scripts" / "badger_lib.py").is_file()
```

That predicate is repeated **verbatim in 10 source shims** (8 skill scripts + 2 hooks, mirrored
to 8 more files under `skills/`), pinned by
`test_every_bootstrap_shim_is_the_same_predicate`. Every scaffolded project carries a **vendored
copy** of it.

So: rename `scripts/` → a project scaffolded before the rename has a shim that only knows
`scripts/badger_lib.py` → against a renamed framework the predicate returns False → the shim
raises at **module import**.

> ### ⚠ Correction — the argument this section was built on is wrong
>
> This section originally continued: *"`den-refresh` — the command that would replace that shim
> — is itself one of those shims. The upgrade path runs through the exact thing the rename
> breaks."*
>
> **That is false, and it was the decisive argument.** Every copy of `den-refresh/SKILL.md`,
> including the one vendored inside a scaffolded project, instructs the agent to run the
> **framework's** copy: `"$AI_BADGER/features/common/skills/den-refresh/scripts/refresh.py"
> --target . --root "$AI_BADGER"`. The vendored copy is what gets *repaired*, never what does
> the repairing. Verified against a real stranded project — see **§5b** and
> [the research](../research/2026-07-28-engine-tooling-split-migration.md).
>
> What this section got **right** and is confirmed: there is no manual escape hatch from inside
> a stale shim. `--root`, `$AI_BADGER`, the ancestor walk, the recorded root, the cache and
> `PYTHONPATH` all fail. The fix must come from outside the project — it just already exists.
>
> **Read §5b before treating anything below as a reason not to proceed.**

**Options considered, and why they were rejected** (kept as the record; the third is superseded
by §5b):

- **A compatibility re-export at `scripts/badger_lib.py`.** *Rejected.* Module identity here is
  path-based, not package-based: the shim does `sys.path.insert(0, root/"scripts")` then
  `import badger_lib`, which finds the re-export itself, not the real module. Making that work
  needs `importlib` gymnastics and yields two distinct module objects for one library — a worse
  defect than the naming it fixes.
- **Tolerant predicate first, rename one release later.** *Viable but incomplete.* Projects that
  skip the tolerance release still brick, and we cannot enumerate consumers.
- **Rename anyway and document it as breaking.** *Rejected on cost/benefit:* ~1,340 reference
  updates and an unrecoverable failure mode for unknown consumers, purchasing a directory name.

## 2. **DECIDED** — split by concern instead, and keep the predicate's anchor still

`scripts/` holds three genuinely different things. The older plan asked "one directory or
several?" — the answer is **several**, and the split is where the value is. The *name*
`scripts/` was never the real problem; the undifferentiated bucket was.

| Concern | Files | Who runs it | Move? |
|---|---|---|---|
| **Engine / library** | `badger_lib.py`, `unsafe_literals.py` | imported by all 10 shims | **NO — load-bearing for root detection** |
| **Catalog tooling** | `index_build.py`, `validate.py`, `sync_plugin_skills.py`, `version_sync.py`, `install_plugins.py` | maintainers, documented in `RELEASING.md` | not in phase 1 |
| **Repo gates** | `deps_guard.py`, `docs_guard.py`, `release_guard.py`, `tdd_guard.py` | **only** CI and the pre-push hook — never a consumer | **YES → `gates/`** |

**Phase 1 = move the four gates to `gates/`.** They are the cleanest cut: nothing imports them,
no shim references them, `is_framework_root` never looks at them, and their name-by-purpose
(`gates/`) is exactly what the invariant asks for. ~50 references, zero bricking risk.

---

# PHASE 1 — `scripts/` gates → `gates/` (do this now)

## 3. Work packages

### F1 — move the four files
`git mv` each of `deps_guard.py`, `docs_guard.py`, `release_guard.py`, `tdd_guard.py` from
`scripts/` to a new top-level `gates/`. Use `git mv` so the diff reads as a rename.

Each of these does `sys.path.insert` / imports `badger_lib`. **`badger_lib.py` does not move**,
so fix each one's path to reach `../scripts`. Verify by running each file directly.

### F2 — update every caller
Exhaustive list — check each one off:
- `lefthook.yml` and `.lefthook/pre-push/verify.sh` (the `deps`, `docs`, `release`, `tdd` lanes)
- `.pre-commit-config.yaml` (`deps-guard`, `docs-guard` hooks)
- `.github/workflows/*.yml`
- `docs/` prose referencing `scripts/release_guard.py` etc. — `docs_guard.py` will fail the
  build if you miss one, so let it tell you
- `scripts/release_guard.py`'s own `SHIPPED_PATHS` — **see F3, this is the subtle one**

### F3 — the two guards that reason about their own paths
**Read carefully; these are where a mechanical rename goes wrong.**

1. **`release_guard.SHIPPED_PATHS`** contains `scripts`. It defines what counts as
   shipped surface. Decide and state in the commit message: are the gates shipped surface?
   **DECIDED: no.** They are repo-internal tooling; a consumer never runs them. So `gates/`
   is **not** added to `SHIPPED_PATHS`, and `scripts` stays (it still holds the engine and
   catalog tooling). This means gate-only changes stop demanding a VERSION bump — which is
   correct, and is a behaviour change you must call out.
2. **`deps_guard.py`** scans a file list for undeclared imports. Make sure `gates/` is still
   scanned, or it stops guarding itself.

### F4 — pylint targets
`pylint scripts features` is the gate command in `CLAUDE.md`, `lefthook.yml` and CI. It must
become `pylint scripts features gates` **everywhere**, or the four moved files silently stop
being linted. Prove it: introduce a deliberate lint error in `gates/tdd_guard.py`, confirm the
gate fails, then remove it.

## 4. Test cases you must write

`tests/test_gates_layout.py`:

```python
def test_every_gate_lives_in_the_gates_directory():
    """A gate in scripts/ is a gate the pylint target and CI lane can silently miss."""
```
Assert `scripts/` contains no `*_guard.py`, and `gates/` contains exactly the four.

```python
def test_every_gate_runs_from_its_new_home():
    """Each gate resolves badger_lib after the move; an ImportError here is the whole risk."""
```
Run each of the four as a subprocess with `--help` (or its no-arg form) and assert it exits
without an ImportError/traceback.

```python
def test_every_gate_is_a_pylint_target():
    """The lint target must name every directory holding Python we own."""
```
Parse the pylint invocation out of `lefthook.yml` (or wherever it is declared) and assert every
top-level directory containing our `*.py` appears in it. This is the test that stops the next
directory from being silently unlinted.

Also update, do not delete:
- any existing test asserting `release_guard.py` lives at `scripts/release_guard.py`
- `tests/test_release_guard.py` — it loads the script by path

## 5. Phase 1 acceptance checklist

- [ ] `git log --follow gates/release_guard.py` shows history across the move (proves `git mv`)
- [ ] Each of the four runs standalone: `.venv/bin/python gates/<name>.py --help`
- [ ] `.venv/bin/python -m pytest -q` — 1430 passed, 17 skipped, or higher
- [ ] `.venv/bin/python -m pylint scripts features gates` — exactly `10.00/10`
- [ ] `grep -rn "scripts/deps_guard\|scripts/docs_guard\|scripts/release_guard\|scripts/tdd_guard" . --exclude-dir=.git --exclude-dir=.venv` returns **nothing**
- [ ] Deliberate-lint-error probe (F4) fails the gate, then is removed
- [ ] `.venv/bin/python scripts/docs_guard.py` — passes from its new path
- [ ] `.venv/bin/python scripts/validate.py --all` · `index_build.py --check` ·
      `sync_plugin_skills.py --check` · `node --test "tests/js/*.test.mjs"` (24 pass)
- [ ] A real `git push` on the branch runs the pre-push gate green — this is the only proof the
      lefthook lanes were rewired correctly
- [ ] Branch `refactor/gates-directory` pushed. **No PR.**

---

# PHASE 2 — `engine/` + `tooling/` (**DO NOT START**)

Specified so the decision is informed, **not** authorised. Requires an explicit maintainer
go-ahead and its own ADR (`docs/adr/0011-…`).

## 5a. The naming question is answered: `engine/` + `tooling/`

The open question below has a decision. `scripts/` becomes two directories, not one renamed one:

| New home | Files | Why |
|---|---|---|
| `engine/` | `badger_lib.py`, `unsafe_literals.py` | the library every shim imports; the root predicate's anchor |
| `tooling/` | `index_build.py`, `validate.py`, `sync_plugin_skills.py`, `version_sync.py`, `install_plugins.py` | maintainer catalog/release tooling; documented in `RELEASING.md` and `CONTRIBUTING.md` |

`catalog/`, `distribution/` and `release/` were rejected: each names one of the five tooling
scripts' jobs and misnames the other four.

## 5b. The bricking premise in §1 is wrong — recovery is one existing command

Researched empirically on 2026-07-28; full method, fixtures and pasted output in
[docs/research/2026-07-28-engine-tooling-split-migration.md](../research/2026-07-28-engine-tooling-split-migration.md).

§1 says *"a project cannot refresh its way out of the breakage, because refreshing is what
breaks."* That is false. Every copy of `den-refresh/SKILL.md` — catalog, plugin mirror, and the
vendored one inside a scaffolded project — instructs the agent to run
`"$AI_BADGER/features/common/skills/den-refresh/scripts/refresh.py" --target . --root "$AI_BADGER"`,
i.e. the **framework's** copy carrying the **new** shim. The vendored
`.ai-badger/skills/den-refresh/scripts/refresh.py` is what gets repaired, never what does the
repairing. The same holds for `welcome-ai-badger` and `feed-badger`; `mcp-index` is the only
skill that documents a vendored path, and it degrades to an ordinary CLI error.

Verified against a real stranded project (scaffolded by the old layout, then the framework moved
to `engine/` + `tooling/` and the old layout removed from the machine):

```
before: vendored shims still on the scripts/ predicate: 9 / 9
$ new_fw/features/common/skills/den-refresh/scripts/refresh.py --target . --root new_fw
rc: 0   reScaffolded: True   backupPath: .../.ai-badger.bckp
after:  vendored shims still on the scripts/ predicate: 0 / 9   (all 9 import, rc=0)
```

The same command also repaired `~/.hermes/plugins/` — `adjust_hooks.py` re-copies with
`shutil.copy2` and rewrites its own `frameworkRoot` pointer.

**What §1 got right and is confirmed:** there is *no* manual escape hatch from inside a stale
shim. `--root`, `$AI_BADGER`, the ancestor walk, the recorded root, the cache and `PYTHONPATH`
all fail — the first two because `checked()` validates them with the *old* predicate, so
ADR-0009 decision 2's refusal turns the operator's escape hatch into a second wall. The fix
must come from outside the project; it just already exists.

## 5c. Per-shape breakage

| Shape | Stale shims | Behaviour | Recovery |
|---|---|---|---|
| Framework checkout | none — `git pull` replaces the tree | all 10 entry points `rc=0` | n/a |
| Plugin cache | none — versioned dir replaced wholesale | all 8 mirrored entry points `rc=0` | n/a |
| `.ai-badger/` scaffold | **9 files** | 6 CLIs raise at import (none of which any documented flow invokes), 3 hooks degrade to `FRAMEWORK_ROOT = None` | one den-refresh |
| `~/.hermes/plugins/` | **2 files** | both degrade to `None`; learned-skills sync goes quiet | the same den-refresh |

`drift_notice_hook.py` runs from `${CLAUDE_PLUGIN_ROOT}` (repo-root `hooks/hooks.json`), so it
keeps firing from the self-healed plugin cache and keeps telling the user to refresh. That
closes the recovery loop. The three hooks wired into `.claude/settings.json`
(`session_start_hook.py`, `user_prompt_hook.py`, `commit_reminder_hook.py`) do **not** carry the
bootstrap shim and are unaffected.

## 5d. Sequencing — one release, not four

The four-release tolerance ladder previously written here is **withdrawn**. A tolerant shim was
built and does work, but it buys nothing a project that skips the window can use (verified: an
old shim against a tolerant-split framework fails identically to no tolerance at all), while
costing two extra releases and a period where the pinned shim invariant asserts a deliberately
wrong predicate. A dedicated migration script was also built and works (9/9 files repaired), but
it has the same "run it from the new framework" precondition as den-refresh while skipping the
`.ai-badger.bckp` backup, the `~/.hermes/plugins/` re-copy and all non-shim drift — a second,
weaker scaffolder maintained for one release. **Both rejected.**

1. **Phase 1 first** (`gates/`) — independent, already in flight.
2. **One release, one commit:** the two moves; the predicate and *both* `sys.path` inserts in
   `badger_lib.is_framework_root` and all 10 shims; the five tooling scripts' own
   `parent.parent / "engine"`; the four gates; `SHIPPED_PATHS`, `REQUIREMENTS`,
   `CHECKED_ROOTS`, pylint targets, lefthook, pre-commit, CI; the 374 live references; and a
   re-scaffold of this repo's own `.ai-badger/`.
3. **Add the version to `BREAKING_VERSIONS`** — it repairs nothing on its own (a stranded
   project cannot read the framework's copy), but it makes the first successful den-refresh do a
   full backup-and-re-scaffold instead of an incremental one, which is correct when every
   vendored script changed.
4. **Document the one-time command** in the changelog entry and `docs/getting-started.md`
   troubleshooting, in the `$AI_BADGER/features/…` form that needs no git clone.

## 5e. Three findings that change the work, not just the sequencing

1. **`unsafe_literals.py` must move with `badger_lib.py`.** There is one `sys.path` entry for
   both. Leaving it in `scripts/` produced
   `ModuleNotFoundError: No module named 'unsafe_literals'` in `open_pr.py` **and in
   `learned_skills_sync.py`** — and that import sits *after* the `try` that ADR-0009 decision 5
   relies on, so it fails the Hermes plugin load outright rather than degrading. Hard constraint;
   assert it in a test.
2. **A tolerant predicate is not sufficient on its own.** The last line of `_bootstrap_lib()` is
   `sys.path.insert(0, str(root / "scripts"))`. A shim that accepts an `engine/` root and then
   puts `scripts/` on the path resolves happily and `ImportError`s one line later. Any tolerance
   work must make both tolerant. (Recorded because the withdrawn ladder said "predicate" only.)
3. **`scaffold.py` bare-imports `install_plugins`** (lines 585 and 913), which works today only
   because one `sys.path.insert` covers engine *and* tooling. After the split the shim must
   insert **both** `engine/` and `tooling/`, in all 10 copies.

Tests phase 2 must add, beyond updating `test_every_bootstrap_shim_is_the_same_predicate`:

- *"the engine's two modules resolve from one sys.path entry"* — `badger_lib` and
  `unsafe_literals` share a directory. Finding 1 is what this guards.
- *"every documented skill invocation names a framework path, not a vendored one"* — parse the
  `python3 "…"` lines out of each `SKILL.md`. This is the invariant the whole recoverability
  argument rests on; if a future edit points den-refresh at `.ai-badger/`, it evaporates
  silently.
- a deployment-shape case asserting a stale vendored shim **degrades** rather than raising in
  the three hook entry points.

---

## 6. Standing rules

- **TDD is mandatory.** Failing test first. Run it, see it fail, then implement.
- **Do NOT bump `VERSION`, write a changelog, re-scaffold, or run `release_guard.py`.** The
  release is cut centrally. Report that phase 1 is **patch**-worthy — no consumer-visible
  surface moves.
- **Push a branch; do not open a PR.**
- Stage files explicitly. **Never `git add -A`** — this is a shared checkout.
- Never stage `.idea/` or `__pycache__/`.
- Use `.venv/bin/python`. `python3` on PATH is 3.14 and has no pytest. Python 3.8 is the floor.
- Comments: 1–3 lines, contract not rationale. Test docstrings: one sentence or none.

## 7. Stop and ask if

- Anything under `features/` or `skills/` turns out to import a gate — that would make the gates
  shipped surface and invalidate the F3 decision.
- A gate cannot resolve `badger_lib` from `gates/` without changing `badger_lib` itself.
- You conclude phase 1 is not worth doing on its own. Say so with evidence rather than drifting
  into phase 2.

## 8. Report back

Branch name; proof the four gates run from `gates/`; the deliberate-lint-error probe result;
confirmation that a real `git push` ran the rewired lanes green; the `SHIPPED_PATHS` decision
and its consequence; and **every test you rewrote or deleted, named individually**.
