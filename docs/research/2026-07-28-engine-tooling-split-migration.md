# Splitting `scripts/` into `engine/` + `tooling/` — is the migration recoverable?

**Date:** 2026-07-28
**Status:** Research. No production code changed; every result below came from throwaway
fixtures under `mktemp -d`.
**Reads:** [ADR-0009](../adr/0009-one-framework-root-resolution.md) and its two amendments,
[ADR-0007](../adr/0007-no-python-distribution.md),
[wave 16 plan §1](../plans/2026-07-28-wave-16-scripts-directory.md).
**Models:** [`tests/test_deployment_shapes.py`](../../tests/test_deployment_shapes.py) — the
fixture shapes, the `_PROBE` import harness and the empty-`HOME` discipline are lifted from it.

---

## Recommendation, in one sentence

**Do the split, as a breaking change recovered by re-scaffolding (route a) — no migration
script, no tolerance release** — because the plan's decisive premise is wrong: `den-refresh`
is *documented to run the framework's own copy*, not the project's vendored one, and that
documented command repairs a stranded project completely and unmodified.

The plan's §1 says:

> The upgrade path runs through the exact thing the rename breaks. A project cannot refresh its
> way out of the breakage, because refreshing is what breaks.

The first sentence is false and the second follows from it. Every copy of
`den-refresh/SKILL.md` — catalog, plugin mirror, and the vendored one inside a scaffolded
project — instructs:

```bash
python3 "$AI_BADGER/features/common/skills/den-refresh/scripts/refresh.py" --target . --root "$AI_BADGER"
```

That is the *framework's* `refresh.py`, carrying the *new* shim, resolving by ancestor walk from
its own location. The vendored `.ai-badger/skills/den-refresh/scripts/refresh.py` is written
by the scaffold and then never invoked by any documented flow. It is the thing being repaired,
not the thing doing the repairing.

Everything else in §1 holds. The hazard is real — hypothesis 1 confirms there is **no** manual
escape hatch once you are inside a stale shim — it is just recoverable from outside.

---

## The fixtures

Three framework trees were built by copying this checkout
(`features schemas scripts hooks skills .claude-plugin VERSION index.json BREAKING_VERSIONS`,
per `_FRAMEWORK_TREE` in the shapes test) and then mechanically transforming them:

| Tree | Layout | Shim predicate |
|---|---|---|
| `old_fw` | today's `scripts/` | `scripts/badger_lib.py` |
| `new_fw` | `engine/` + `tooling/` | `engine/badger_lib.py` |
| `tolerant_fw` | today's `scripts/` (**no move**) | `scripts/` **or** `engine/` |
| `tolerant_split_fw` | `engine/` + `tooling/` | `scripts/` **or** `engine/` |

`new_fw` was verified healthy before being used as a comparand:

```
  checkout detect                 rc=0 root=OK
  checkout scaffold               rc=0 root=OK
  checkout drift                  rc=0 root=OK
  checkout refresh                rc=0 root=OK
  checkout detect_additions       rc=0 root=OK
  checkout open_pr                rc=0 root=OK
  checkout drift_notice_hook      rc=0 root=OK
  checkout mcp_index              rc=0 root=OK
  checkout ai_badger_hooks        rc=0 root=OK
  checkout learned_skills_sync    rc=0 root=OK
  tooling/validate.py --all                  rc=0  ok       features/common/support.json
  tooling/index_build.py --check             rc=0  index.json up to date
  tooling/sync_plugin_skills.py --check      rc=0  11 skill(s) in sync
```

The split is mechanically achievable. Three edits beyond the file moves were required, and two
of them are not obvious:

1. Each of the five tooling scripts does `sys.path.insert(0, Path(__file__).parent)` then
   `import badger_lib`. In `tooling/` that parent no longer holds the engine; each needs
   `parent.parent / "engine"`.
2. `scaffold.py` does a bare `import install_plugins` (lines 585 and 913) that today works only
   because the shim's single `sys.path.insert(root/"scripts")` covers engine *and* tooling.
   After the split the shim must insert **both** `engine/` and `tooling/` — a two-line shim
   change, replicated across all ten copies.
3. The four `*_guard.py` files (wave 16 phase 1 moves them to `gates/`) resolve `badger_lib`
   the same way and need the same repair.

---

## Hypothesis 1 — is there any manual escape hatch? **No. None of the five inputs work.**

Setup: consumer scaffolded by `old_fw`, then the checkout it recorded was upgraded in place to
the new layout — the realistic `git pull` case. All five ordered inputs of ADR-0009 were then
tried against the stale vendored `refresh.py`.

```
--- (a) --root <new framework> ---
rc: 1
RuntimeError: --root is .../old_fw, which is not an ai-badger framework root
  (no schemas/ + features/ + scripts/badger_lib.py)

--- (b) $AI_BADGER=<new framework> ---
rc: 1
RuntimeError: $AI_BADGER is .../old_fw, which is not an ai-badger framework root
  (no schemas/ + features/ + scripts/badger_lib.py)

--- (c) ancestor walk / recorded root (no flag at all) ---
rc: 1 root: __missing__
RuntimeError: could not locate the ai-badger framework: none above
  .../consumer/.ai-badger/skills/den-refresh/scripts, no $AI_BADGER, no frameworkRoot in a
  .ai-badger/manifest.json above it, and no cache at .../home/.ai-badger/framework
  — pass --root <framework> or clone https://github.com/Arasz/ai-badger

--- (d) ~/.ai-badger/framework cache holding the NEW layout ---
rc: 1 root: __missing__
RuntimeError: could not locate the ai-badger framework: ... (identical)

--- (e) PYTHONPATH pointing at the new engine/ ---
rc: 1 root: __missing__
RuntimeError: could not locate the ai-badger framework: ... (identical)
```

**This is the single most important confirmed fact.** `_declared_root` validates `--root` and
`$AI_BADGER` with the *old* predicate, so ADR-0009 decision 2's refusal semantics turn the
operator's own escape hatch into a second wall. `PYTHONPATH` does not help either: the shim
raises before any import is attempted, so putting the engine on the path is irrelevant. The
error message's own advice — "pass `--root <framework>`" — is, for this failure mode,
unreachable advice of exactly the kind ADR-0009 decision 3 set out to eliminate.

Corollary worth stating plainly: **once a project's vendored shims are stale, nothing the user
can type at that project fixes it.** The fix must come from outside.

## Hypothesis 2 — does the new framework's own entry point repair the project? **Yes, completely.**

The documented den-refresh command, run verbatim from `new_fw` against a stranded project:

```
before: vendored shims still on the scripts/ predicate: 9 / 9

$ new_fw/features/common/skills/den-refresh/scripts/refresh.py --target . --root new_fw
rc: 0
report keys: ['breakingChange', 'drift', 'frameworkVersion', 'hermesSkillLinks',
              'newStacks', 'reScaffolded', 'scaffold']
  frameworkVersion: {'scaffolded': '0.36.1', 'current': '0.36.1'}
  reScaffolded: True
  breakingChange: {'isBreaking': False, 'backupPath': '.../stranded2/.ai-badger.bckp'}

after: vendored shims still on the scripts/ predicate: 0 / 9
  ai_badger_hooks.py     rc=0 AIB_ROOT=".../new_fw"
  refresh.py             rc=0 AIB_ROOT=".../new_fw"
  detect_additions.py    rc=0 AIB_ROOT=".../new_fw"
  open_pr.py             rc=0 AIB_ROOT=".../new_fw"
  mcp_index.py           rc=0 AIB_ROOT=".../new_fw"
  drift_notice_hook.py   rc=0 AIB_ROOT=".../new_fw"
  detect.py              rc=0 AIB_ROOT=".../new_fw"
  drift.py               rc=0 AIB_ROOT=".../new_fw"
  scaffold.py            rc=0 AIB_ROOT=".../new_fw"
```

Nine of nine vendored entry points rewritten, all nine import cleanly afterwards, and the
`.ai-badger.bckp` safety copy was taken as usual. `scaffold.py --target <stranded project>`
run directly from `new_fw` produces the same result. The mirrored plugin copy
(`new_fw/skills/den-refresh/scripts/refresh.py`) also works, which matters because Claude
plugin users have that path on disk without cloning anything.

**Shape D is repaired by the same command.** `features/hermes/adjustments/adjust_hooks.py`
copies with `shutil.copy2` unconditionally and rewrites its own pointer, so after the refresh:

```
$ ls home3/.hermes/plugins/
ai_badger_hooks.py  commit_reminder.py  impact_estimator.py  learned_skills_sync.py
$ grep -c 'engine" / "badger_lib' home3/.hermes/plugins/learned_skills_sync.py
1
$ cat home3/.hermes/plugins/.ai-badger/manifest.json
{ "frameworkRoot": ".../new_fw" }
```

One command, already documented, already in every consumer's `SKILL.md`, repairs both stranded
shapes at once.

## Hypothesis 3 — which deployment shapes actually break?

Measured with the old layout removed from the machine entirely (`old_fw/scripts/badger_lib.py`
moved away), so nothing resolves for the wrong reason.

| Shape | Carries a stale shim? | Observed | Recovers how |
|---|---|---|---|
| **Framework checkout** | No — `git pull` replaces the whole tree | `detect/refresh/ai_badger_hooks rc=0 root=OK` | n/a |
| **Plugin cache** `~/.claude/plugins/cache/…/<version>/` | No — versioned dir, replaced wholesale | `detect/refresh/mcp_index rc=0 root=OK` | n/a |
| **`.ai-badger/` scaffold** | **Yes — 9 files** | 6 CLIs raise at import, 3 hooks degrade to `None` | one den-refresh from the new framework |
| **`~/.hermes/plugins/`** | **Yes — 2 files** | both degrade to `None`, `--help` still rc=0 | same den-refresh (adjust_hooks re-copies) |

Scaffold shape, verbatim:

```
  detect                 rc=1 root='__missing__' RuntimeError: could not locate the ai-badger framework
  scaffold               rc=1 root='__missing__' RuntimeError: could not locate the ai-badger framework
  drift                  rc=1 root='__missing__' RuntimeError: could not locate the ai-badger framework
  refresh                rc=1 root='__missing__' RuntimeError: could not locate the ai-badger framework
  detect_additions       rc=1 root='__missing__' RuntimeError: could not locate the ai-badger framework
  open_pr                rc=1 root='__missing__' RuntimeError: could not locate the ai-badger framework
  drift_notice_hook      rc=0 root=None
  mcp_index              rc=0 root=None
  ai_badger_hooks        rc=0 root=None

CLI invocation (what a user actually types):
  refresh      --help rc=1 RuntimeError: could not locate the ai-badger framework
  detect       --help rc=1 RuntimeError: could not locate the ai-badger framework
  drift        --help rc=1 RuntimeError: could not locate the ai-badger framework
```

**But which of those nine does anything today?** Traced through the wiring:

- `.claude/settings.json` wires `session_start_hook.py`, `user_prompt_hook.py` and
  `commit_reminder_hook.py` — **none of which carry the bootstrap shim**. Unaffected.
- `drift_notice_hook.py` is registered in the repo-root `hooks/hooks.json` under
  `${CLAUDE_PLUGIN_ROOT}`, i.e. it runs from the **plugin cache**, not the vendored copy. So
  the notice that tells the user to refresh keeps working. That closes the recovery loop.
- `welcome-ai-badger`, `den-refresh` and `feed-badger` `SKILL.md` all invoke
  `"$AI_BADGER/features/…"`. The vendored CLI copies of `detect/scaffold/drift/refresh/
  detect_additions/open_pr` are **never invoked by any documented flow**.
- `mcp-index/SKILL.md` is the one exception — it invokes
  `python3 .ai-badger/skills/mcp-index/scripts/mcp_index.py …`. Degraded, it exits with an
  ordinary CLI error, not a traceback:
  ```
  mcp_index list         rc=1 :: ERROR: index not found.
  mcp_index validate     rc=1 :: ERROR: .ai-badger/mcp-tools.yaml not found. Run 'mcp-index init' first.
  ```
- Hermes plugins degrade to silence and keep loading:
  ```
  ai_badger_hooks.py     --help rc=0 :: (silent)
  learned_skills_sync.py --help rc=0 :: usage: learned_skills_sync.py [-h] --reconcile [--target TARGET]
  ```

**Net user-visible damage from the split, before recovery:** the Hermes learned-skills sync goes
quiet, `mcp-index` reports a misleading "index not found", and the six vendored CLI copies —
which nothing calls — become tracked dead files. The drift notice still fires. No session
breaks. This is a *degraded* framework, not a bricked one.

## Hypothesis 4 — does a tolerant predicate shipped in advance shrink the window?

It works, with one correction to the plan's phrasing.

```
consumerD vendored shim is tolerant: True

(a) tolerant vendored shim vs the SPLIT framework (release N+1):
   $AI_BADGER=<tolerant_split>  rc: 0 root: OK
   --root <tolerant_split> refresh rc: 0

(b) a project that SKIPPED the tolerant release (old shim vs split):
   rc: 1 :: RuntimeError: --root is .../tolerant_split_fw, which is not an
            ai-badger framework root (no schemas/ + features/ + scripts/badger_lib.py)
```

**The correction:** phase 2 step 1 of the plan says "`is_framework_root` accepts
`scripts/badger_lib.py` **or** `<newname>/badger_lib.py`". The predicate alone is not enough.
A tolerant shim also needs a tolerant `sys.path` insert — the last line of `_bootstrap_lib()` is
`sys.path.insert(0, str(root / "scripts"))`, and a shim that accepts an `engine/` root then puts
`scripts/` on the path resolves happily and `ImportError`s one line later. The tolerant fixture
that actually worked inserts every directory that exists:

```python
for _d in ("scripts", "engine", "tooling"):
    if (root / _d).is_dir():
        sys.path.insert(0, str(root / _d))
```

**What it buys:** projects that refresh during the window cross the split without noticing.
**What it does not buy:** anything for a project that skips the window — case (b) above fails
identically to no tolerance at all — and consumers cannot be enumerated, so the window has no
knowable end. **What it costs:** two extra releases (N to introduce, N+2 to remove), a period
where the checked shim invariant pins a predicate that is deliberately wrong, and a
`sys.path` that carries a directory that does not exist in one of the two layouts.

Given hypothesis 2, tolerance buys a smoother path to an outcome that is already a single
documented command. It is insurance against a cost that is one command. **Not worth two
release cycles.**

## Hypothesis 5 — is a migration script deliverable?

Yes, and it is unnecessary. The discovery half is trivial — one `rglob` finds every stranded
file with no ambiguity:

```
stranded shims discoverable by one rglob: 9
    .ai-badger/hooks/ai_badger_hooks.py
    .ai-badger/skills/den-refresh/scripts/refresh.py
    .ai-badger/skills/feed-badger/scripts/detect_additions.py
    .ai-badger/skills/feed-badger/scripts/open_pr.py
    .ai-badger/skills/mcp-index/scripts/mcp_index.py
    .ai-badger/skills/task/scripts/drift_notice_hook.py
    .ai-badger/skills/welcome-ai-badger/scripts/detect.py
    .ai-badger/skills/welcome-ai-badger/scripts/drift.py
    .ai-badger/skills/welcome-ai-badger/scripts/scaffold.py
manifest keys: ['$schema', 'agents', 'entries', 'frameworkCommit', 'frameworkDirty',
                'frameworkRoot', 'frameworkVersion', 'generatedAt', 'pluginScope', 'skillScope']
```

A 30-line script that copies each `features/` source over its `.ai-badger/` counterpart and
repoints `manifest.frameworkRoot` restores all nine:

```
rewrote 9 vendored entry points + manifest.frameworkRoot
  detect rc=0 root=OK   scaffold rc=0 root=OK   drift rc=0 root=OK   refresh rc=0 root=OK
  detect_additions rc=0 root=OK   open_pr rc=0 root=OK   drift_notice_hook rc=0 root=OK
  mcp_index rc=0 root=OK   ai_badger_hooks rc=0 root=OK
den-refresh from the repaired project rc: 0
```

**But this is a strictly worse `den-refresh`.** It must run from the new framework (the stranded
project cannot bootstrap), which is the same precondition as den-refresh; it reimplements the
`SCAFFOLD_PATHS` → `features/` mapping, the manifest rewrite and the `~/.hermes/plugins/`
re-copy that `scaffold.py` already owns; and it does *not* take the `.ai-badger.bckp` backup,
re-materialise `hooks.json`, or refresh the non-shim files that also changed. It would be a
second, less careful scaffolder maintained for one release. **Reject route (b).**

`manifest.json`'s `frameworkRoot` needs no special handling: the scaffold rewrites it to
whatever `--root` was passed, and per ADR-0009 decision 4 it is re-validated before use, so a
stale value degrades to "ignored", never to a wrong answer.

---

## `unsafe_literals.py` — it must move with `badger_lib.py`, and a partial move breaks a session

There is exactly one `sys.path` entry for both. Splitting them apart is not survivable:

```
engine/ holds badger_lib only; unsafe_literals left in scripts/
  open_pr                rc=1 ModuleNotFoundError: No module named 'unsafe_literals'
  learned_skills_sync    rc=1 ModuleNotFoundError: No module named 'unsafe_literals'
  detect                 rc=0

engine/ holds badger_lib AND unsafe_literals
  open_pr                rc=0
  learned_skills_sync    rc=0
  detect                 rc=0
```

The `learned_skills_sync` result is the sharp one. ADR-0009's "a hook degrades to silence" only
catches `RuntimeError` from `_bootstrap_lib()`; `import unsafe_literals` sits *after* the
guard, inside `if FRAMEWORK_ROOT is not None:`, and an `ImportError` there fails the Hermes
plugin load outright. Moving the two engine files together is therefore not a preference — it
is a hard constraint, and it should be an assertion in the phase-2 test suite.

## What outside this repo could pin `scripts/`

462 references name one of the seven engine/tooling files by path; 374 of them are outside the
record directories (`docs/adr/`, `docs/changelog/`, `docs/plans/`, `docs/research/`,
`docs/reviews/`, `docs/specs/`, `docs/design/`, `docs/incidents/`, `docs/archive/`) and must be
rewritten. The heaviest:

| File | Live refs |
|---|---|
| `tests/test_badger_lib.py` | 66 |
| `tests/test_new_schemas.py` | 29 |
| `tests/test_sync_plugin_skills.py` | 19 |
| `tests/test_install_plugins.py` | 19 |
| `tests/test_index_build.py` | 14 |
| `tests/test_validate.py` | 13 |
| `CONTRIBUTING.md` | 8 |
| `docs/scripts.md` | 7 |
| `docs/getting-started.md` | 5 |
| `.lefthook/pre-push/verify.sh` | 4 |
| `.github/workflows/pylint.yml` | 4 |
| `.pre-commit-config.yaml` | 3 |

Load-bearing constants, each of which must be changed deliberately rather than mechanically:

- `scripts/release_guard.py` — `SHIPPED_PATHS = ["skills", "features", "scripts", "schemas", "index.json"]`.
  `engine` and `tooling` must both be added; leaving `scripts` in is harmless only while the
  gates still live there.
- `scripts/deps_guard.py` — `REQUIREMENTS = "scripts/requirements.txt"`. The declared-dependency
  file has to land somewhere and the guard has to be told. `engine/requirements.txt` is the
  natural home (that is what the fixture used) but it moves a path CONTRIBUTING.md,
  `welcome-ai-badger/SKILL.md` and `den-refresh/SKILL.md` all print to users.
- `scripts/docs_guard.py` — `CHECKED_ROOTS = ("scripts", "features", …)`. Without `engine` and
  `tooling` added, check 2 silently stops verifying every new path, which is precisely the
  failure mode that gate exists to prevent.
- `.ai-badger/config.json` and the three `SKILL.md` copies of welcome-ai-badger/den-refresh
  print `$AI_BADGER/scripts/…` commands to users in their troubleshooting tables.

Nothing genuinely *external* pins the layout: there is no package on any index
(ADR-0007 declined distribution), no entry point, no installed console script. The pins are
prose that tells users what to type, plus this repo's own `.ai-badger/` scaffold — which is a
shape-B consumer of itself and self-heals when the split commit re-scaffolds it.

---

## Route comparison

| | (a) breaking change + re-scaffold | (b) dedicated migration script |
|---|---|---|
| Runs from | the new framework | the new framework — same precondition |
| Command | already documented, unchanged | new, one-release-only |
| Repairs `.ai-badger/` | yes (9/9, verified) | yes (9/9, verified) |
| Repairs `~/.hermes/plugins/` | yes (verified) | only if it reimplements `adjust_hooks` |
| Takes `.ai-badger.bckp` | yes | no |
| Repairs non-shim drift | yes | no |
| New code to maintain | none | a second, weaker scaffolder |
| Discoverability | drift notice still fires from the plugin cache | needs its own announcement |

Route (a) dominates on every row. The migration script's only advantage would be working when
den-refresh cannot — and hypothesis 2 shows den-refresh always can, because it never runs the
broken file.

## Recommended sequencing

1. **Phase 1 first** (`gates/`), as already decided and in flight. It is independent.
2. **One release, one commit, all of it:** move `badger_lib.py` + `unsafe_literals.py` to
   `engine/` and the five tooling scripts to `tooling/`; update the predicate and *both*
   `sys.path` inserts in `badger_lib.is_framework_root` and all ten shims; fix the five
   tooling scripts' `parent.parent / "engine"`; fix the gates; update `SHIPPED_PATHS`,
   `REQUIREMENTS`, `CHECKED_ROOTS`, the pylint targets, lefthook, pre-commit and CI; rewrite the
   374 live references; re-scaffold this repo's own `.ai-badger/`.
3. **Add the version to `BREAKING_VERSIONS`.** It does not repair anything by itself — a
   stranded project cannot read the framework's `BREAKING_VERSIONS` at all — but it makes the
   *first successful* den-refresh do a full backup-and-re-scaffold rather than an incremental
   one, which is the right behaviour when every vendored script changed.
4. **Document the one-time command** in the changelog entry and in `docs/getting-started.md`'s
   troubleshooting section, in the form that needs no git clone for plugin users:
   ```bash
   python3 "$AI_BADGER/features/common/skills/den-refresh/scripts/refresh.py" --target . --root "$AI_BADGER"
   ```
5. **Do not ship a tolerance release. Do not write a migration script.**
6. **Write an ADR** (`docs/adr/0011-…`) recording the `engine/` + `tooling/` names, the
   engine-files-move-together constraint, and the finding that the vendored CLI shims are not
   on any documented invocation path — that last one is the load-bearing fact and it should not
   have to be rediscovered.

**Tests phase 2 must add**, beyond updating `test_every_bootstrap_shim_is_the_same_predicate`:

- *"the engine's two modules resolve from one `sys.path` entry"* — assert `badger_lib` and
  `unsafe_literals` live in the same directory. This is the constraint whose violation kills a
  Hermes session.
- *"every documented skill invocation names a framework path, not a vendored one"* — parse the
  `python3 "…"` lines out of each `SKILL.md` and assert the recovery premise holds. If a future
  edit points den-refresh at `.ai-badger/`, the recoverability argument in this document
  silently evaporates.
- A deployment-shape case asserting a stale vendored shim degrades rather than raising in the
  three hook entry points — it passes today by accident of the `try` in ADR-0009 decision 5, and
  after this change it is the only thing between a split and a broken session.

---

## What I could not establish

- **How many consumers exist.** Unchanged from ADR-0007. The recommendation does not depend on
  it — recovery is one command whether there is one consumer or fifty — but the *cost* of not
  announcing does.
- **Whether the Claude plugin cache always updates before a user next opens a scaffolded
  project.** I modelled the cache as a versioned directory replaced wholesale, which matches
  `tests/test_deployment_shapes.py`, and confirmed a new-layout cache is self-consistent. I did
  not exercise Claude Code's actual update trigger, so the window between "framework released"
  and "this machine's cache carries it" is unmeasured. During that window the drift notice fires
  from the *old* cache and still works.
- **Whether `~/.ai-badger/framework` is populated on any real machine.** ADR-0009 amendment 9
  made it announce skew, and it is last in the order; I confirmed a stale cache in the old
  layout simply fails the new predicate and falls through. Whether any user relies on it as
  their only framework is unknown, and such a user is not reachable by any recovery command
  until they update it.
- **Whether the 374 live references rewrite cleanly.** I verified the *runtime* consequences of
  the move, not the full text rewrite. `docs/scripts.md` is a whole document about the
  directory and needs rewriting rather than sed-ing, and the 66 references in
  `tests/test_badger_lib.py` include fixture builders (`_make_root`) whose structure encodes the
  predicate.
- **The right name for the requirements file's new home.** `engine/requirements.txt` worked in
  the fixture, but it appears in user-facing troubleshooting prose in three `SKILL.md` files and
  `CONTRIBUTING.md`; whether the declared dependencies belong to the engine or to the repo is a
  judgement I did not make.
