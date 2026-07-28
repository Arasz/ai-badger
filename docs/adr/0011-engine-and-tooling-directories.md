# ADR-0011 — `scripts/` becomes `engine/`, `tooling/` and `gates/`

**Date:** 2026-07-28
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude Opus 5
**Supersedes:** None. Constrains [ADR-0009](0009-one-framework-root-resolution.md) by changing
the path in the root predicate; ADR-0009's resolution *order* is untouched.

## Context

The top-level `scripts/` directory holds eleven Python files serving three unrelated purposes:

| Purpose | Files | Who runs it |
|---|---|---|
| The library every bootstrap shim imports | `badger_lib.py`, `unsafe_literals.py` | every entry point, every hook, in all four deployment shapes |
| Catalog and release tooling | `index_build.py`, `validate.py`, `sync_plugin_skills.py`, `version_sync.py`, `install_plugins.py` | maintainers; documented in `RELEASING.md` |
| Repository gates | `deps_guard.py`, `docs_guard.py`, `release_guard.py`, `tdd_guard.py` | CI and the pre-push hook only; **never** a consumer |

The project's own screaming-architecture invariant forbids exactly this shape: *"avoid catch-all
`Services/`, `Controllers/`, `Utils/` buckets in favour of concept-named ones."* `scripts/` names
the file type, not the job. A reader cannot tell from the tree which of these a consumer depends
on and which exist only to police the repository.

The reason it survived so long is that the directory name is **load-bearing**.
`is_framework_root` is:

```python
(path / "schemas").is_dir() and (path / "features").is_dir()
    and (path / "scripts" / "badger_lib.py").is_file()
```

and ADR-0009 requires that predicate to be repeated **verbatim** in ten bootstrap shims, because
they run before `badger_lib` can be imported. Every scaffolded project carries a vendored copy.
Moving `badger_lib.py` therefore strands every project scaffolded before the move: its shims
answer "not a framework root" about a framework root.

## Decision

**Split `scripts/` into three concept-named directories:**

- **`engine/`** — `badger_lib.py`, `unsafe_literals.py`. The library the shims import and the
  anchor of the root predicate.
- **`tooling/`** — `index_build.py`, `validate.py`, `sync_plugin_skills.py`, `version_sync.py`,
  `install_plugins.py`. Maintainer catalog and release tooling.
- **`gates/`** — `deps_guard.py`, `docs_guard.py`, `release_guard.py`, `tdd_guard.py`. Shipped
  ahead of this ADR as phase 1, because it carries none of the risk below.

`is_framework_root` becomes `engine/badger_lib.py`, in `badger_lib` and in all ten shims.

**Ship it as a single breaking release**, listed in `BREAKING_VERSIONS`, recovered by the
existing `den-refresh`. No compatibility window, no migration script.

### Why the names

`catalog/`, `distribution/` and `release/` were considered and rejected: each names what *one* of
the five tooling scripts does and misnames the other four. `engine/` and `tooling/` divide on the
line that actually matters — **what a consumer's code imports** versus **what a maintainer
runs**.

### Why a single breaking release is safe

The obvious objection is that the upgrade path runs through the breakage: `den-refresh` is one of
the ten shims, so a stranded project cannot refresh its way out. **That objection is false**, and
we established it by running rather than reading.

Every copy of `den-refresh/SKILL.md` — catalog, plugin mirror, and the copy vendored inside a
scaffolded project — instructs the agent to run the **framework's** copy:

```
python3 "$AI_BADGER/features/common/skills/den-refresh/scripts/refresh.py" --target . --root "$AI_BADGER"
```

The vendored `.ai-badger/skills/den-refresh/scripts/refresh.py` is what gets *repaired*, never
what does the repairing. The same holds for `welcome-ai-badger` and `feed-badger`.

Verified against a project scaffolded under the old layout, with the old layout then removed from
the machine:

```
before: vendored shims still on the scripts/ predicate: 9 / 9
rc: 0   reScaffolded: True   backupPath: .../.ai-badger.bckp
after:  vendored shims still on the scripts/ predicate: 0 / 9   (all 9 import, rc=0)
```

The same command repairs `~/.hermes/plugins/`: `adjust_hooks.py` re-copies unconditionally and
rewrites its own `frameworkRoot`. Of the four deployment shapes, only `.ai-badger/` scaffolds (9
files) and `~/.hermes/plugins/` (2) carry stale shims; a framework checkout resolves by ancestor
walk and the Claude plugin cache updates wholesale, so both self-heal.

Full method and output:
[`docs/research/2026-07-28-engine-tooling-split-migration.md`](../research/2026-07-28-engine-tooling-split-migration.md).

### Why not a compatibility window

A tolerant predicate accepting either path, shipped one release ahead, buys nothing for a project
that skips that release — verified to fail identically — and costs two extra releases. It is also
a trap: a tolerant predicate **without** a tolerant `sys.path` insert resolves the root and then
raises `ImportError` one line later.

### Why not a migration script

It has the same precondition as `den-refresh` — it must be run from the new framework, because
the old project cannot bootstrap — while skipping the backup, the Hermes re-copy, and all
non-shim drift. It is `den-refresh` with fewer guarantees.

### Why not a compatibility re-export at `scripts/badger_lib.py`

Module identity here is path-based, not package-based. The shim does
`sys.path.insert(0, root/"scripts")` then `import badger_lib`, which finds the re-export itself
rather than the real module. Making it work needs `importlib` gymnastics and yields two distinct
module objects for one library — a worse defect than the naming it fixes.

## Consequences

**There is no manual escape hatch from inside a stale shim, and this is by design.** `--root`,
`$AI_BADGER`, the ancestor walk, the recorded root, the cache and `PYTHONPATH` all fail, because
`checked()` validates an operator's declaration with the *old* predicate — ADR-0009 decision 2's
"refuse rather than fall through" turns the escape hatch into a second wall. The recovery must
come from outside the project. Release notes must say so plainly and give the exact command;
"pass `--root`" is advice that does not work here.

**Three implementation constraints, each of which silently breaks something if missed:**

1. **`unsafe_literals.py` moves with `badger_lib.py`.** Left in `scripts/`, `open_pr.py` and
   `learned_skills_sync.py` raise `ModuleNotFoundError` — and in the latter that import sits
   *after* the `try/except RuntimeError` ADR-0009 relies on, so the Hermes plugin fails to load
   rather than degrading to silence. That is the exact defect 0.34.1 fixed, reintroduced.
2. **Every shim must insert both `engine/` and `tooling/`.** `scaffold.py` bare-imports
   `install_plugins`, which lands in `tooling/`.
3. **The five tooling scripts each need `parent.parent / "engine"`.**

**Load-bearing constants that must be updated together:** `release_guard.SHIPPED_PATHS`,
`deps_guard.REQUIREMENTS`, `docs_guard.CHECKED_ROOTS`.

**`gates/` is deliberately not shipped surface.** It is absent from `SHIPPED_PATHS`, so a
gate-only change no longer demands a `VERSION` bump. A consumer never runs a gate.

**Blast radius:** 462 references for the `engine/` + `tooling/` move, 374 outside record
directories.

**The predicate stays verbatim across all ten shims.**
`test_every_bootstrap_shim_is_the_same_predicate` continues to enforce it; this ADR changes the
string, not the rule.
