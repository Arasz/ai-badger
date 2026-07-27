# ADR-0009 — One Framework Root, Resolved Rather Than Searched

**Date:** 2026-07-27
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent
**Supersedes:** None

## Context

[ADR-0007](0007-no-python-distribution.md) declined packaging and handed Wave 7 three
instructions: unify the four disagreeing root predicates, make the resolver *resolve* rather
than search, and keep the bootstrap shims duplicated but in agreement. It named the ordered
inputs — `--root`, `$AI_BADGER`, an ancestor walk, a root recorded in `manifest.json`, the
cache — and stopped there. Implementing that order raised three questions it did not answer,
each of which changes observable behaviour. This ADR records the answers.

The four shapes and the four predicates are stated in ADR-0007's Context and are not repeated
here. What matters below is that shapes B (`.ai-badger/` scaffold) and D (`~/.hermes/plugins/`)
hold no framework above them, so only a recorded pointer can answer them.

## Decision

### 1. One predicate: `schemas/` + `features/` + `scripts/badger_lib.py`

The four old predicates tested four different pairs. The union of what their callers actually
need is the catalog (`schemas/`, `features/`) *and* the engine (`scripts/badger_lib.py`): every
caller either reads the catalog, imports the engine, or does both. All four deployment shapes
that are meant to work satisfy all three.

This **narrows** `badger_lib._is_root`, which tested `schemas/` + `features/` only. A tree
carrying a catalog but no engine — which nothing ships, but a partial clone or a hand-made
`~/.ai-badger/framework` could be — stops being a root. That is the point: the failure ADR-0007
found in the wild was a cache resolving silently for eighteen minor versions, and a predicate
that accepts trees no caller can actually use is how a resolver returns something unusable
without saying so.

`VERSION` is deliberately *not* in the predicate. Only the drift tiers read it, they already
handle its absence, and adding it would make the predicate answer a question ("is this
releasable?") that root resolution is not asking.

### 2. A declared root refuses; a discovered root falls through

`--root` and `$AI_BADGER` are operator declarations. When either names something that is not a
framework root, resolution raises instead of continuing down the list. The remaining three
inputs — ancestor walk, recorded root, cache — are discovery, and a miss there is normal, so
they fall through silently.

The asymmetry is the whole lesson of ADR-0007's "why nobody has noticed": an operator who says
where the framework is and is wrong must be told, because the alternative is the framework
resolving *somewhere else* and the operator never learning their pointer was stale. A stale
`export AI_BADGER=...` in a shell profile is exactly that case.

### 3. `--root` is read by the shim, from `sys.argv`, before argparse exists

ADR-0007 noted that `detect.py`'s own error message — "run with `--root <framework>`" — is
unreachable advice, because `_bootstrap_lib()` runs at module import and argparse never gets a
turn. Rather than delete the advice, the shim now peeks at `sys.argv` for `--root` / `--root=`
itself. This is the only way `--root` can be input #1 as ADR-0007 specifies: by the time a
parser could run, the import that needs the framework has already happened.

A script whose CLI has no `--root` is unaffected — the peek finds nothing and moves on.

### 4. `frameworkRoot` in `manifest.json` is a hint, relative when it can be

`scaffold.py` records where the framework was. The value is **relative to the project when the
framework is inside it** (a repo that scaffolds itself records `.`) and absolute otherwise.

The cost is real and worth naming: `.ai-badger/manifest.json` is a tracked file, so a consumer
repo scaffolded from a checkout at `/Users/someone/ai-badger` commits that path. It is
meaningless on a teammate's machine and in CI. Three things make it acceptable rather than
merely tolerable:

- It is **always re-validated** against the predicate before use. A path that is not a framework
  root *here* is ignored, and resolution continues to the cache — so the wrong value degrades to
  the behaviour that existed before this ADR, never to a wrong answer.
- It is **fourth in the order**. Any shape that can answer by ancestor walk never reads it.
- The self-hosted case, which is the one that recurs across machines, records `.` and is
  therefore machine-independent.

The alternative — an untracked side file — was rejected: it would be a fifth thing to keep in
sync, it would not survive the `den-refresh` backup/restore cycle that `manifest.json` already
survives, and ADR-0007 asked for a manifest addition specifically because the manifest is
already the record of "where this scaffold came from".

Per ADR-0001 decision 3 this is a manifest addition and therefore a **minor** version bump. The
field is optional in `schemas/manifest.schema.json`: manifests written before it exist, and
resolution treats a missing key exactly like an unreadable one.

### 5. The shim stays duplicated, and a test enforces that it stays identical

Ten entry points carry `_bootstrap_lib()` verbatim; `sync_plugin_skills.py` derives more copies
under `skills/`, and a scaffold run derives more under `.ai-badger/`. They cannot import
`badger_lib` — locating it is what they exist to do. `test_every_bootstrap_shim_is_the_same_predicate`
asserts every copy in `features/` and `skills/` is byte-identical, and
`test_the_shim_and_badger_lib_state_one_predicate` asserts the shim and `badger_lib` state the
same predicate. Duplication is now a checked invariant rather than an accident.

The three entry points that never import `badger_lib` — `ai_badger_hooks.py`,
`drift_notice_hook.py`, `mcp_index.py` — carry the same shim but call it inside a `try`, because
a hook that raises breaks a session. They degrade to `FRAMEWORK_ROOT = None` and stay silent, as
they did before.

Every entry point now exposes `FRAMEWORK_ROOT` as a module attribute. That is what makes a
per-shape integration test possible at all: `tests/test_deployment_shapes.py` builds all four
shapes under one empty `HOME` and asserts each entry point both imports and reports a real root.

## Consequences

- `badger_lib.find_root` keeps its name and its seventeen import sites, and now delegates to
  `resolve_framework_root`. It gained an optional `cwd` argument so a caller can be hermetic.
- Three tests changed meaning and are named here rather than buried in a diff:
  `test_find_plugin_root_walks_ancestors_not_a_fixed_depth` and
  `test_find_plugin_root_returns_none_when_no_ancestor_qualifies` were replaced by
  `test_the_hook_resolves_the_same_root_from_two_different_depths` (the catalog copy at depth 5
  and the generated copy at depth 3 must agree) and
  `test_the_notice_is_silent_when_no_framework_root_resolves`. The fixed-depth regression they
  guarded is now guarded by the four-shape test, which exercises three different depths.
  `tests/test_badger_lib.py::_make_root` gained `scripts/badger_lib.py`, per decision 1.
- **The `~/.ai-badger/framework` liability ADR-0007 handed to "whoever touches root resolution
  next" is reduced, not discharged.** It is now last in the order and reached only when nothing
  else answers, so the two shapes that used to depend on it no longer do. It still does not
  report its own version skew. Making the cache announce a version mismatch — or removing it —
  remains open, and is the right scope for its own change rather than a rider on this one.
- Wave 16 (renaming `scripts/`) now has exactly one literal to change per shim copy, plus
  `badger_lib.is_framework_root`. ADR-0007 asked for Wave 7 first for this reason.
