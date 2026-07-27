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

---

## Amendment — 2026-07-27: the working directory is not an input

**Status:** Accepted. Decisions 6-8 below revise decisions 2, 3 and 4 above; the earlier text
is left standing as the record of what was decided and why it was wrong.

Review of `task/wave-7-one-framework-root` reproduced two behaviour regressions. Both trace to
the same root cause: resolution accepted inputs that neither the operator nor the installer
controls.

### The reproduction

A repository containing a tracked `.ai-badger/manifest.json` with `"frameworkRoot": "vendor"`,
and a `vendor/` tree satisfying the predicate whose `scripts/badger_lib.py` writes a marker
file, was cloned and opened with `HOME` empty, no `$AI_BADGER`, and the working directory set
to that repo. Importing `~/.hermes/plugins/learned_skills_sync.py` — which Hermes loads
automatically on session start — **executed the repository's code**. On the pre-wave-7 resolver
the identical fixture raised and put nothing on `sys.path`.

Decision 4 argued that re-validation makes the hint safe. That argument is sound against
*staleness* and worthless against *adversarial input*: **re-validation proves the target is a
framework tree, never whose.** A repo that supplies the tree it points at passes validation by
construction.

### 6. Every input is derived from the script's own location or from an operator

The recorded root is read only from a `.ai-badger/manifest.json` **above the script file**.
`Path.cwd()` is no longer consulted, and `resolve_framework_root` no longer takes a `cwd`
argument — a parameter that exists is a parameter that gets passed.

The line is ownership, not path shape. A manifest above the script belongs to whoever installed
the script, which is the trust already granted by running it — the same boundary the ancestor
walk has always used. A manifest above the working directory belongs to whatever repository the
user happened to open, and a session-start hook's working directory is any repo they cloned.

**The invariant: a repository cannot steer the `sys.path` of a hook that runs on session start.**

Two alternatives were weighed and rejected:

- *Require the recorded root to be absolute and outside the project.* Weaker than it looks. An
  attacker-controlled manifest can name an absolute path outside the project just as easily as
  a relative one; the constraint filters accidents, not adversaries. It would also break the
  self-hosted `.` that decision 4 correctly wanted.
- *Drop the hint entirely and require `--root`/`$AI_BADGER` in shapes B and D.* Honest, and
  genuinely costly: ADR-0007 established that the ancestor walk **structurally cannot** answer
  those shapes, so this re-breaks the two shapes wave 7 existed to fix. Rejected because the
  hint is not the defect — reading it from an untrusted directory was.

Shape D keeps working because the installer now records the pointer where the shape can use it:
`adjust_hooks.py` writes `~/.hermes/plugins/.ai-badger/manifest.json` with an absolute
`frameworkRoot` at the moment it copies the two plugin files. That record is machine-local,
user-scope, above the script, and outside every repository — exactly ADR-0007's "record the
root at copy time, which costs nothing".

### 7. The ancestor walk outranks `$AI_BADGER`

The new order is `--root`, the ancestor walk, `$AI_BADGER`, the recorded root, the cache.

`getting-started.md` Route B tells users to `export AI_BADGER="$PWD"`, and more than one
checkout per machine is normal — worktrees make it routine. With the environment variable
ranked above the walk, a stale export paired a foreign engine with this repository's catalog:
running this project's own suite under `AI_BADGER=~/.ai-badger/framework` (VERSION 0.13.0)
produced 269 failures and 13 errors, all variants of `module 'badger_lib' has no attribute
...`. That is precisely the engine/catalog skew ADR-0007 exists to eliminate, reintroduced at
higher precedence than the unambiguous local answer.

A script living inside a framework tree is not ambiguous about which engine belongs to it. A
shell profile is a guess about a different machine state. Decision 2's refusal semantics are
unchanged: when `$AI_BADGER` *is* consulted — no framework above the script — naming a
non-root still raises rather than falling through.

### 8. `--root` is read from `sys.argv` only when this file is the program

Decision 3 had the shim scan `sys.argv` unconditionally. `ai_badger_hooks.py` and
`learned_skills_sync.py` are imported into the Hermes host process, where `sys.argv` belongs to
the host. A host launched with an unrelated `--root <path>` made the shim raise; verified by
simulating the host's argv, `ai_badger_hooks` degraded to `None` as designed while
`learned_skills_sync` — which calls `_bootstrap_lib()` unguarded at module scope — failed its
plugin load outright.

The shim now compares `Path(sys.argv[0]).resolve()` against `Path(__file__).resolve()` and
peeks only when they agree. Decision 3's purpose survives intact: a script invoked as
`python detect.py --root X` is its own program and still reads the flag before argparse exists.

### Consequences

- `test_every_bootstrap_shim_is_the_same_predicate` only inspected text *between*
  `def _bootstrap_lib()` and `return root.resolve()`, so a fifth root predicate survived inside
  `_load_script()` in `drift.py` and `refresh.py`. Those now use the already-resolved
  `FRAMEWORK_ROOT`, and `test_no_root_predicate_lives_outside_a_bootstrap_shim` asserts every
  quoted mention of `badger_lib.py` in `features/` and `skills/` lies inside a shim.
- `tests/test_deployment_shapes.py` pops `$AI_BADGER` from the subprocess environment, so
  neither it nor CI could observe decision 7's defect.
  `test_an_exported_env_var_never_displaces_the_checkout_a_script_lives_in` sets it deliberately.
- `learned_skills_sync` still calls `_bootstrap_lib()` unguarded at module scope, so a genuinely
  rootless machine breaks its plugin load rather than degrading to silence. That predates this
  wave and is not fixed here: the module imports `badger_lib` at module scope throughout, so
  degrading properly means making the whole module lazy. It is worth its own change.
