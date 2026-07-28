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
raises at **module import**. And `den-refresh` — the command that would replace that shim — *is
itself one of those shims*.

> **The upgrade path runs through the exact thing the rename breaks.** A project cannot refresh
> its way out of the breakage, because refreshing is what breaks.

**Options considered, and why they were rejected:**

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

# PHASE 2 — the top-level rename (**DO NOT START**)

Specified so the decision is informed, **not** authorised. Requires an explicit maintainer
go-ahead and its own ADR (`docs/adr/0011-…`), because §1 shows it can strand consumers.

If it is ever approved, the only non-bricking sequence is:

1. **Release N** — `is_framework_root` accepts `scripts/badger_lib.py` **or**
   `<newname>/badger_lib.py`, in `badger_lib` *and* all 10 verbatim shims. No rename yet.
   `test_every_bootstrap_shim_is_the_same_predicate` keeps them identical.
2. **Wait at least one release** so scaffolded projects refresh into the tolerant shim.
3. **Release N+1** — perform the rename. Add to `BREAKING_VERSIONS`. Document that a project
   which never refreshed during the window must run `den-refresh --root <framework checkout>`
   once, by hand.
4. **Release N+2** — drop the `scripts/` branch of the predicate.

**Open question for the maintainer, which the ADR must answer:** the engine (`badger_lib.py`,
`unsafe_literals.py`) and the catalog tooling (`index_build`, `validate`, `sync_plugin_skills`,
`version_sync`, `install_plugins`) are two different concerns that would need two different
names. `catalog/`, `distribution/` and `release/` were all floated and are not synonyms.

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
