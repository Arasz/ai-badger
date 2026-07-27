# ADR-0007 — ai-badger Ships as Files, Not as a Python Distribution

**Date:** 2026-07-27
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent
**Supersedes:** None

## Context

Wave 11 of [the deferred-work plan](../plans/2026-07-27-deferred-work-plan.md) asks whether
`badger_lib` and the scaffold engine should become an installable Python distribution. The
question gates two other waves — Wave 7 (unify the bootstrap shims) would be largely thrown
away if the answer were yes, and Wave 16 (rename `scripts/`) cannot start until it is known
whether `scripts/` remains an importable directory at all. So the decision, not the
implementation, is the deliverable.

### What would be packaged

`scripts/` holds ten modules, 1,878 lines. `badger_lib.py` is 409 of them and is the only one
the catalog imports: seventeen `import badger_lib` sites across `features/` and `scripts/`.
(The plan's Wave 17 section records `badger_lib.py` at 353 lines — that number is stale;
it is 409 today.)

The three functions that matter for this decision are all in `badger_lib.py`:

- `_is_root(path)` — the predicate: `schemas/` **and** `features/` are both directories.
- `find_root(start)` — walks ancestors from the caller's own file for `_is_root`, then falls
  back to `~/.ai-badger/framework`. Pure lookup, no network, ever.
- `ensure_root(..., allow_network=True)` → `_clone_pinned(version)` — the one function allowed
  to reach the network. It clones the tag `ai-badger--v{version}` into `~/.ai-badger/framework`
  and **refuses if that directory already exists**: "It is never updated in place."

`ensure_root` has no callers. `grep -rn "ensure_root" --include="*.py" .` returns
`scripts/badger_lib.py` and `tests/test_badger_lib.py`, and nothing else. Nothing in the
shipped catalog ever populates the cache that `find_root` falls back to.

### The bootstrap shims, counted

`grep -rln "def _bootstrap_lib" --include="*.py" .` returns **19 files**: 7 canonical copies
under `features/`, plus the 6 shipped `.claude/` copies and the 6 `.ai-badger/` copies that
`sync_plugin_skills.py` and `scaffold.py` derive from them.

The canonical seven:

| File |
|---|
| `features/common/hooks/learned_skills_sync.py` |
| `features/common/skills/den-refresh/scripts/refresh.py` |
| `features/common/skills/feed-badger/scripts/detect_additions.py` |
| `features/common/skills/feed-badger/scripts/open_pr.py` |
| `features/common/skills/welcome-ai-badger/scripts/detect.py` |
| `features/common/skills/welcome-ai-badger/scripts/drift.py` |
| `features/common/skills/welcome-ai-badger/scripts/scaffold.py` |

**Correction to the plan.** Wave 7's table says nine and calls all nine `_bootstrap_lib`. There
are seven. The two extra files it counted — `features/common/hooks/ai_badger_hooks.py` and
`features/common/skills/task/scripts/drift_notice_hook.py` — match the grep only because each
*mentions* `_bootstrap_lib` in prose while implementing its own, different root search. That
makes the disagreement worse than filed, not better: there are **four** predicates, not three.

| Predicate | Tests for | Where |
|---|---|---|
| `badger_lib._is_root` | `schemas/` **and** `features/` | `scripts/badger_lib.py:84` |
| `_bootstrap_lib` (×7) | `scripts/badger_lib.py` **and** `schemas/` | `features/common/skills/welcome-ai-badger/scripts/scaffold.py:30` |
| `ai_badger_hooks.find_framework_root` | `VERSION` **and** `schemas/` | `features/common/hooks/ai_badger_hooks.py:52` |
| `drift_notice_hook.find_plugin_root` | `VERSION` **and** `features/common/skills/` | `features/common/skills/task/scripts/drift_notice_hook.py:35` |

### The four deployment shapes, verified rather than assumed

Following ADR-0001's method note, every claim below was checked against on-disk state, not
documentation. Shapes B and D were exercised in a temporary directory with `Path.home()`
pointed at an empty tree, which is what a machine without a hand-made cache looks like.

**A — a framework checkout.** `git clone` per
[getting-started.md Route B](../getting-started.md), `export AI_BADGER="$PWD"`,
`pip install -r scripts/requirements.txt`. Holds `schemas/`, `features/`, `scripts/`, `VERSION`
and `features/common/skills/`, so **all four predicates agree**. Works.

**B — a `.ai-badger/` scaffold inside a consumer repo.** What `scaffold.py` writes: `skills/`,
`hooks/`, `instructions/`, `invariants/`, `agents/`, `agent-instructions/`, `plugins/`,
`skills-data/`, `config.json`, `manifest.json`, `state.json`, `mcp-tools.yaml`, and the three
agent files. **No `schemas/`, no `features/`, no `scripts/`, no `VERSION`.** It satisfies
**none** of the four predicates, and no ancestor of it does either unless the consumer repo
*is* ai-badger. Running the scaffolded `detect.py` on a clean home:

```
RuntimeError: could not locate ai-badger scripts/badger_lib.py locally or at
<home>/.ai-badger/framework — run with --root <framework> or clone …
```

The advice in that message is unreachable. `_bootstrap_lib()` is called at module scope,
immediately before `import badger_lib as bl`, so the failure happens at import — argparse
never runs and `--root` can never be supplied.

**C — the Claude plugin cache**, `~/.claude/plugins/cache/ai-badger/ai-badger/<version>/`. The
marketplace entry is `"source": "./"`, so the cache is a full copy of the repository. Same as
shape A minus the `.git` directory: **all four predicates agree**. Works. Note what it is: a
plain file copy performed by the CLI. There is no install step, no interpreter, and no hook
that could run one.

**D — `~/.hermes/plugins/`.** `features/hermes/adjustments/adjust_hooks.py` copies exactly two
loose files there: `ai_badger_hooks.py` and `learned_skills_sync.py`. Nothing else. Its
ancestors are `~/.hermes`, `~`, `/`. Importing `learned_skills_sync` on a clean home:

```
RuntimeError: could not locate ai-badger scripts/badger_lib.py locally or at
<home>/.ai-badger/framework — clone https://github.com/Arasz/ai-badger
```

`ai_badger_hooks.find_framework_root` returns `None` in the same shape, so the Hermes drift
notice — ADR-0001 decision 5, Tier 1 — is silently a no-op there, exactly as
`$CLAUDE_PLUGIN_ROOT` was before #24.

### Why nobody has noticed

Both broken shapes fall through to `~/.ai-badger/framework`, and on the maintainer's machine
that directory exists. It contains **`VERSION` = 0.13.0** while the repository is at **0.31.1**.
It satisfies `_is_root`, so `find_root` returns it, and `_clone_pinned` refuses to touch a
directory that already exists — so it will never be updated. Eighteen minor versions of engine
skew, resolved silently, on the only two shapes that need the fallback.

That is ADR-0001's Context recurring one layer down. There a version string denoted four
different code states; here a resolution path returns an engine eighteen minors older than the
catalog it is asked to operate on, and nothing reports it.

### The constraints any answer must satisfy

- **Python 3.8 floor**, matching the CI matrix (`.github/workflows/pylint.yml`: 3.8, 3.9, 3.10)
  and `pyproject.toml`'s `py-version`.
- **No install step in a consumer repo.** An agent runs `python3 .ai-badger/skills/…/x.py`
  directly, in whatever interpreter it happens to hold. `docs/getting-started.md` states this as
  a product boundary under "Who it is not for": *"The scripts are standalone Python files with
  no install step and no public API."*
- **Two dependencies, deliberately asymmetric** ([CONTRIBUTING.md](../../CONTRIBUTING.md)):
  `jsonschema` is required and imported unguarded, because validation that silently no-ops is
  worse than a missing dependency; `pyyaml` is optional, guarded, and degrades to a printed
  note. *"Do not add a third runtime dependency without a very good reason."*
- **One version literal, mechanically enforced** (ADR-0001 decision 1). `version_sync.py`
  writes `VERSION` into `plugin.json`, `marketplace.json` and `index.json`, and `--check` fails
  CI on disagreement.

## Decision

**No. `badger_lib` and the scaffold engine are not published as a Python distribution, and no
`[project]` table is added to `pyproject.toml`. `scripts/` stays a directory of standalone
modules, resolved by path and imported by name.**

The reasoning is one sentence: **packaging fixes the two shapes that already work and does
nothing for the two that are broken.**

Shapes A and C resolve the engine correctly today, by all four predicates, because they carry
the whole repository. Shapes B and D fail — and they fail for a reason packaging does not
address. `~/.hermes/plugins/ai_badger_hooks.py` and `.ai-badger/skills/…/detect.py` are not
failing to *import a library*; they are failing to *find the catalog they were copied away
from*. `badger_lib` is not the payload. `features/` and `schemas/` are, and they are data, not
importable code. A `pip install ai-badger` that put only `badger_lib` on `sys.path` would let
shape B past its `RuntimeError` and then fail one line later, where `find_root` looks for the
`schemas/` and `features/` it did not deliver. A wheel *could* carry the catalog as package
data — that is the honest counter, and it is worse rather than better: the catalog would then
exist in a site-packages copy with its own release cadence, alongside the plugin cache copy and
the checkout copy, and `den-refresh` and the drift tiers would have a third tree to reconcile.
The problem is a missing pointer between copies; adding a copy is not a fix for it.

So the deficiency Wave 11 was reaching for is real, and it is not a packaging deficiency. It is
that **a copied file carries no pointer back to its origin**, while the framework already
records that origin: `.ai-badger/manifest.json` carries `frameworkVersion`, `frameworkCommit`
and `frameworkDirty` (ADR-0001 decision 4). What it does not carry is a path. Fixing resolution
is a matter of *recording where the root is* rather than *searching harder for it* — and that
is Wave 7's job, not a distribution's.

Two further reasons this decision is not close:

**A distribution would create a version literal ADR-0001 cannot reach.** `pyproject.toml`
already refuses one, in a comment written before this question was asked: `py-version` is
declared under `[tool.pylint.main]` *"rather than in a `[project]` table because that would
introduce a fourth version literal, which ADR-0001 exists to prevent."* A published package adds
a fifth — installed in an environment `version_sync.py --check` cannot see, on a machine no CI
job runs on, watched by no drift tier.

**A consumer repo's Python environment is not ours to occupy.** ai-badger scaffolds .NET repos,
TypeScript repos and repos with no Python environment at all. Requiring one — or worse,
installing into whichever interpreter an agent happened to invoke — is precisely the behaviour
Wave 9's WP38 made consent-gated for third-party skills. Doing it to ourselves, silently, would
be the same error with the framework's own name on it.

## Alternatives considered

**1. Status quo, unchanged.** Rejected as an *outcome*, accepted as a *starting point*. The
four-predicate disagreement and the two broken shapes are real defects; declining to package is
not declining to fix them. The fix belongs in Wave 7, and the Consequences below say what it
must now include.

**2. A PyPI-published distribution — `pip install ai-badger`.** Rejected against all four shapes:

- *Shape A* — the only shape it helps, and it already works. A contributor's `pip install -e .`
  saves one `sys.path` line in a checkout that has none of the problem.
- *Shape B* — the shape that most needs help, and the one it fails hardest. There may be no
  Python environment; if there is, it belongs to the consumer's project. An agent invoking
  `python3 .ai-badger/skills/…/scaffold.py` picks an interpreter we do not choose and cannot
  probe. And it would not even work: `badger_lib` on `sys.path` still has no `features/` or
  `schemas/` to read, so `find_root` fails one line later.
- *Shape C* — the plugin cache is a file copy made by the CLI. Nothing runs on install;
  `autoUpdate` defaults to `false` for third-party marketplaces (ADR-0001, Context). A pip
  dependency would either be permanently unsatisfied or need a runtime auto-installer, which
  WP38 exists to forbid.
- *Shape D* — genuinely helped, and the only one. Two loose files in `~/.hermes/plugins/` would
  gain a real import. It is not worth the other three, and the same shape is fixed by recording
  a root at copy time, which costs nothing.

Also rejected on premise: the project's whole distribution model is "cloned, or installed as a
plugin". A PyPI package would be a second, divergent way to obtain the framework, releasing on
its own cadence, and ADR-0001 decision 2 — a version denotes exactly one commit, forever —
would then have two publication surfaces to hold to that promise instead of one tag.

**3. A vendored package directory that every shape adds to `sys.path` once.** The most
attractive option, and rejected on the same fault line. It is a real improvement for shapes A
and C, where the tree is present — and a no-op for B and D, where it is not: "add it to
`sys.path` once" needs something to point at, and neither a `.ai-badger/` scaffold nor
`~/.hermes/plugins/` contains the package. Making it work there means vendoring the engine
*into* the consumer's repository: 1,878 lines of framework code committed to somebody else's
git history, versioned by both `VERSION` and their commit log, and needing a shim to be found
anyway. That trades seven small shims for one shim plus a second copy of the engine that drifts
— and `den-refresh` would then have to reconcile engine code as well as catalog content.

**4. A single-file amalgamation** — generate one vendored `badger_lib` into `.ai-badger/`
(the plan's third option under WP44). Rejected: it is a build artifact requiring its own
`--check` gate to stay byte-identical, it puts generated code in the consumer's history, and it
makes drift detection responsible for hashing the engine as well as the catalog. It also fails
the property that makes an agent-facing scaffold auditable — every file under `.ai-badger/` is
currently something a human can read and recognise as the framework's, and a 400-line generated
blob is not.

**5. A `zipapp` (`ai-badger.pyz`).** Rejected: `jsonschema` would have to be vendored into the
archive to keep it self-contained, which is a supply-chain position this project does not want
and CONTRIBUTING.md's dependency rule does not permit; the invocation is still
interpreter-dependent, so shape B gains nothing; and it removes the read-the-script-you-run
property for the same reason as option 4.

**6. A `[project]` table with no publish**, purely so `pip install -e .` works in a checkout.
Rejected: it buys shape A a convenience it does not need and costs a version literal outside
`version_sync.py`'s enforcement — the exact thing the existing comment in `pyproject.toml`
declines.

## Consequences

**The pure-stdlib-plus-two posture survives unchanged.** `scripts/requirements.txt` remains the
only dependency declaration; the `jsonschema`-required / `pyyaml`-optional split documented in
CONTRIBUTING.md stands; `pyproject.toml` keeps tool configuration only.

**"Installed engine vs. scaffold version" stays a two-party question**, which ADR-0001
decision 5's two-tier drift already answers. WP44 asked what happens when they disagree; the
answer is that this decision declines to create a third party for them to disagree with.

**The `~/.ai-badger/framework` fallback is now known to be a liability, not a safety net.** It
is populated by nothing in the shipped catalog, never refreshed once created, and on at least
one real machine resolves an 0.13.0 engine for a 0.31.1 catalog. Whoever touches root
resolution next owns this: either the cache reports its own version skew, or it stops being a
silent fallback.

### Wave 7 — proceed, unreduced, with one addition

Nothing in WP32–WP34 is retired by this ADR. Specifically:

- **WP32 (integration test per shape) is now the first thing to write, and it must cover four
  shapes, not three.** `~/.hermes/plugins/` is a distinct shape — two loose files with no
  framework above them — and it is the one the plan's three-shape framing omits. The test must
  run with `Path.home()` pointed somewhere empty; with the maintainer's real home it passes for
  the wrong reason.
- **WP33 (one canonical `resolve_framework_root()`) must unify four predicates, not three**, per
  the table in Context. `drift_notice_hook.find_plugin_root` is the fourth.
- **WP33 must resolve, not merely search.** The canonical resolver takes an ordered list of
  inputs — an explicit `--root`, `$AI_BADGER` (already documented in getting-started.md
  Route B), an ancestor walk, a root recorded in `.ai-badger/manifest.json`, and only then the
  cache — because the ancestor walk *structurally cannot* succeed in shapes B and D. Recording
  the root at scaffold time is the change that makes those shapes work for the first time; it
  is a manifest addition and therefore a minor-version, blast-radius change under ADR-0001
  decision 3.
- **WP34 (shrink the shims) stands in full.** The shim still cannot import `badger_lib` — that
  is the bootstrap problem, and no packaging option removes it. Seven canonical copies, plus
  the twelve generated ones, keep their duplication and stop disagreeing.
- The plan's note that *"if Wave 11's ADR is accepted, most of WP34 is thrown away"* is now
  resolved: **nothing is thrown away.** Wave 7 can start.

### Wave 16 — unblocked, and its ADR has one fewer question

`scripts/` remains an importable directory resolved by path, so the rename is a rename and
nothing more. Consequences for WP52's ADR:

- The name is **not** a distribution name and carries no PyPI namespace, no import-path
  compatibility promise, and no `[project]` entry. It answers only to the
  screaming-architecture invariant: what is this directory *for*.
- Whatever it is called, the name becomes a **literal inside the canonical predicate** — the
  shims test for `<ancestor>/scripts/badger_lib.py`. Do Wave 16 after Wave 7, so the literal
  lives in one place instead of the seven-plus-twelve it lives in today.
- It stays **one directory**. The `catalog/` / `distribution/` / `release/` split floated in the
  plan would multiply the path the shim has to know, which is the cost this decision is spending
  Wave 7 to reduce.
- `BREAKING_VERSIONS` still applies: consumers with a pinned path break.

### Wave 17 — the facade is now mandatory, not a convenience

WP54 splits `badger_lib.py` into `catalog.py` / `fingerprint.py` / `versioning.py` with
`badger_lib` as a re-export facade. Because there is no package:

- The split modules must be **flat siblings in the same directory**, not a package with an
  `__init__.py`. The shim inserts one directory on `sys.path` and imports top-level module
  names; a package would need a different insertion point and would break every existing shim.
- **`badger_lib` must keep working as an import name indefinitely.** It is named in seventeen
  import sites, in the shim's own predicate (`scripts/badger_lib.py`), and in the two error
  messages users actually see. The facade is load-bearing, not tidiness.
- Do it after Waves 7 and 8, as planned. Wave 7's `resolve_framework_root()` and Wave 8's
  feature-type registry both land in this file first.
