# Improvement plan — consolidated, 2026-07-27 21:05 CEST

Supersedes the open items in
[`2026-07-27-deferred-work-plan.md`](2026-07-27-deferred-work-plan.md),
[`2026-07-27-session-checkpoint-3.md`](2026-07-27-session-checkpoint-3.md) and
[`2026-07-27-analyze-measures-the-wrong-things.md`](2026-07-27-analyze-measures-the-wrong-things.md).
Those stay as records; **this is the dispatch list.**

**Repository state at writing:** `main` @ `7af5316`, VERSION `0.33.0`, last tag
`ai-badger--v0.33.0`, **26 commits merged and unreleased**, 1117 tests passing, all ten gates
green.

Two branches are unmerged: `task/wave-7-one-framework-root` (**blocked, see W1**) and
`fix/behaviorist-evidence-vs-bookkeeping` (red tests only, see B1).

---

## Dispatch groups

Each group is independent of every other group in the same wave. Within a group, work is one
agent. **Never let two concurrent agents bump `VERSION`, write a changelog, or re-scaffold** —
every merge conflict this session came from that. The release is cut centrally.

| Wave | Groups | Gate to the next wave |
|---|---|---|
| **1 — now** | A (Wave 7 security), B (analyze), C (drift hash), D (release) | A must merge before wave 2 |
| **2 — after A** | E (Wave 6), F (Wave 16), G (hook instrumentation) | F before H |
| **3 — after E+F** | H (Wave 17) | — |

Group D can run at any time and is the only one that touches `VERSION`.

---

# WAVE 1

## Group A — Wave 7 does not merge: two reproduced regressions **[highest priority]**

Branch `task/wave-7-one-framework-root` was independently reviewed. Verdict: **do not merge.**
The four-shape work is sound and the merge is textually clean (1182 tests pass on the merged
tree), but it introduces two behaviour regressions, both reproduced.

### A1 — a tracked `manifest.json` becomes a code-execution vector (**security, blocking**)

`resolve_framework_root` step 4 reads `frameworkRoot` from the nearest `.ai-badger/manifest.json`
above **`Path.cwd()`**, the value may be **relative to the project**, and the resolved
`scripts/` is inserted at `sys.path[0]` before `import badger_lib`.

**I reproduced this directly.** A repo containing

```
.ai-badger/manifest.json   {"frameworkRoot": "vendor"}
vendor/{schemas,features}/ , vendor/scripts/badger_lib.py   # writes a marker
```

with `HOME` empty, no `$AI_BADGER`, cwd = that repo, importing
`~/.hermes/plugins/learned_skills_sync.py`: **the marker was written — attacker code ran.**
On `main` the identical fixture raises `RuntimeError` and puts nothing on `sys.path`.

Why it is new rather than inherent: on `main`, shape D consulted only its own ancestors and the
home cache — nothing repo-derived. The manifest hint lets a repo point at an **arbitrary
subdirectory it controls**, and extends that trust to `cwd`-based lookup and to two Hermes hooks
that run automatically on session start. Cloning an untrusted repo and opening it with an agent
is the whole attack.

ADR-0009 argues re-validation makes the hint safe. **Re-validation only proves the target is a
framework tree — it cannot prove whose.** That argument covers staleness, not adversarial input.

Fix direction (decide, do not assume): drop the `cwd`-based manifest lookup; or require the
recorded root to be absolute *and* outside the project; or drop the manifest hint entirely and
accept that shapes B and D need `--root`/`$AI_BADGER`. Whatever is chosen, **a repo must not be
able to steer `sys.path` of a hook that runs on session start.**

### A2 — `$AI_BADGER` outranks the ancestor walk (**reproduced**)

`$AI_BADGER` is consulted *before* the ancestor walk and refuses rather than falling through.
`docs/getting-started.md` Route B tells users to `export AI_BADGER="$PWD"`, and this project is
routinely worked in git worktrees, so several valid checkouts per machine is normal.

```
AI_BADGER=/Users/arasz/.ai-badger/framework  pytest -q
  branch: 258 failed, 900 passed, 13 errors
  main:   1117 passed
```

Failures read `module 'badger_lib' has no attribute 'default_skill_names'` — the suite loaded a
**different framework's engine** (0.13.0) against this catalog. That is precisely the
engine/catalog skew ADR-0007 exists to kill, reintroduced through a new door at higher
precedence than the unambiguous local answer.

Fix direction: put the ancestor walk **above** `$AI_BADGER` — a checkout you are standing in is
a stronger signal than a shell profile — or at minimum add `delenv("AI_BADGER")` to the root
`conftest.py` and document that a global export overrides everything. Note the four-shape test
pops `$AI_BADGER` from the subprocess env, so it will never catch this; CI won't either.

### A3 — a fifth root predicate survived, inside two files this wave rewrote

`_load_script()` still carries the old predicate at `drift.py:111`, `refresh.py:107` and both
`skills/` mirrors:

```python
if (anc / "scripts" / "badger_lib.py").exists() and (anc / "schemas").is_dir():
```

No `features/`, so it accepts trees `is_framework_root` rejects, and it ignores the
`FRAMEWORK_ROOT` resolved three lines above. `test_every_bootstrap_shim_is_the_same_predicate`
cannot see it — it only inspects text between `def _bootstrap_lib()` and `return root.resolve()`.
**The count is five, not four.** Harmless today; it is exactly the thing that was meant to stop
existing. Widen the guard test as well as fixing the site.

### A4 — the repo's own `.ai-badger/` still runs the obsolete predicates

`.ai-badger/manifest.json` has no `frameworkRoot`; `.ai-badger/hooks/ai_badger_hooks.py` and
`.ai-badger/skills/**/*.py` carry the old predicates. This is **a consequence of my instruction
not to re-scaffold**, not an implementer error — but it must happen at release. No gate catches
it, which is itself worth fixing.

### A5 — suspected, not reproduced: `--root` scavenged from `sys.argv`

`declared()` scans `sys.argv` unconditionally. `ai_badger_hooks.py` and `learned_skills_sync.py`
are imported into the **Hermes host process**, so `sys.argv` is the host's. A host launched with
an unrelated `--root <path>` makes the shim raise; `ai_badger_hooks` catches it,
`learned_skills_sync` calls `_bootstrap_lib()` unguarded at module scope and its plugin load
fails outright. No Hermes runtime available to confirm. **Verify before or while fixing A1.**

**Also from the review, lower priority:** `test_the_notice_is_silent_when_no_framework_root_resolves`
monkeypatches `FRAMEWORK_ROOT = None` instead of constructing a rootless situation, so it no
longer tests resolution at all.

---

## Group B — `call-behaviorist analyze` **— DONE, merged**

Merged. All three defects fixed, plus **a fourth nobody had diagnosed**, and that fourth one has
an uncomfortable provenance worth recording.

**B-D — `is_instrumented()` was reading a path that does not exist.** It did
`Path(script_path).read_text()` on a command string containing the literal
`${CLAUDE_PROJECT_DIR}`, which is not a real path, so the read always raised and **every
ai-badger hook was reported `not_instrumented`.** Every `not_instrumented` finding the tool has
ever emitted was noise.

**We caused it.** Hook commands only became `${CLAUDE_PROJECT_DIR}`-relative in **0.32.0**, in
the portable-hook-paths fix — before that they were absolute and readable. A fix that repaired
duplicate hook registration silently blinded the tool built to detect hook problems, and no gate
noticed because "everything is uninstrumented" is a plausible-looking report.

It also mattered for B-B: path-keying alone would not have restored the suppressed true positive,
because the instrumented twin would still have been muted as uninstrumented.

**Source-of-truth decision (B-A):** `HOOK_SOURCES` is the union of `.claude/settings.json`,
`.claude/settings.local.json` and `.ai-badger/hooks/hooks.json`, deduplicated by resolved path.
Registration is primary because that is what the agent runs; `hooks.json` is *kept* rather than
replaced, because Hermes registers hooks in `~/.hermes/config.yaml` and a Hermes- or
Copilot-only project has nothing under `.claude/` — reading only `settings.json` would have
swapped one agent-specific blind spot for another.

Third-party hooks are **classified, not filtered** — they surface as `not_instrumented` (low),
which is literally true of them. No new finding kind was invented.

Verified against this repo post-merge: components are full paths, `health: warn`, and the
findings are real signal rather than artefacts. One of them — `always_skipped` on
`ai_badger_hooks/session_start`, fired once and exited early — is worth a look on its own.

## Group B (original detail, kept for reference)

Full detail: [`2026-07-27-analyze-measures-the-wrong-things.md`](2026-07-27-analyze-measures-the-wrong-things.md).
Read it; it is written to be executed cold. Summary of the three defects, all reproduced:

- **B-A** — `_wired_hooks` reads `.ai-badger/hooks/hooks.json` (what was *intended*) instead of
  `.claude/settings.json` (what is *registered*). 2 entries vs 4 here; 2 of 5 in the reporting
  project. `drift_notice_hook` and `stop_hook` are wired and invisible to the analyzer.
- **B-B** — hooks are keyed by **basename**, so two different `user_prompt_hook.py` collapse into
  one component. This *suppresses a true positive*: if the instrumented one stopped firing, its
  uninstrumented sibling explains the silence away.
- **B-C** — the tool's own `enabled`/`disabled`/`cleared` events count as evidence, so
  `health: unknown` is unreachable and one bookkeeping line yields a high-severity alarm.

**Already done:** branch `fix/behaviorist-evidence-vs-bookkeeping` holds five tests for B-C —
four red, one guard that must stay green (genuine silence must still be reported). Order:
**C → B → A**, because until `unknown` works the other two cannot be evaluated honestly.

---

## Group C — drift reports 22 permanent `changed` entries

Found while fixing #104, unfixed, pre-existing on `main`. `run_adjustments` records
`hash = sha256(written output)` while `source` is the adjustment *script*, so `drift.compare`
hashes the script and never matches. Every run reports
`features/{copilot,hermes}/adjustments/*.py` as changed, forever.

Same bug class as the `templates`/`adjustments` false positives just fixed, and the same
consequence: a signal that is always on is a signal nobody reads.

**Related, decide together:** hooks and adjustments still get **no manifest entries at all**.
#104 turned their `drift_reports_new` off to stop the false positive, which removed the noise but
left them without provenance. Recording them properly and re-enabling reporting is the real fix.

---

## Group D — cut the release **[can run any time; owns `VERSION`]**

26 commits are unreleased. Contents: both #103 causes (plugin skills at `<plugin-root>/skills/`,
the claude skill-discovery adjustment), Wave 8's feature-type registry, the statusline capture
wiring, small batch A, the widened secret scan, and the #104 den-refresh fix.

Requirements: bump `VERSION` (minor — several change what scaffolding does), write
`docs/changelog/{version}-{slug}.md`, add the row to `docs/changelog/README.md`, **re-scaffold
this repo against itself** (which also discharges A4 if A has merged), tag
`ai-badger--v{version}`, and close **#104**.

Two consumer-visible behaviours that must be in the changelog:

> The first `den-refresh` after upgrading will report — and install — every default-scope
> framework skill your project never received, because detection was previously blind to the
> `common` stack where all of them live.

> **A skill deleted from a project will now come back on the next refresh.** Manifest absence
> meant both "not wanted" and "not yet known".

**Hold the second sentence** until the removal-semantics research lands (below) — the currently
drafted workaround ("use `optIn` scope") may not be available to a project at all, in which case
that wording is false.

---

## Group I — a project cannot decline anything **[research done; ready to dispatch]**

Full findings: [`../research/2026-07-27-skill-removal-semantics.md`](../research/2026-07-27-skill-removal-semantics.md).
Merged. Four results, each verified by running rather than reading:

1. **The opt-out we were about to document does not exist.** `config.schema.json` is
   `additionalProperties: false` with no exclusion key, and `skillScope` is `['default','local']`
   — *install* scope, not selection. `SKILL_SCOPES` is framework source, shipped read-only in the
   plugin cache. **The drafted #104 changelog sentence is false and must be rewritten.**
2. **Deleting a skill never worked in `den-refresh` either.** Pre-#104 the list came from the
   manifest, and deleting a directory does not touch `manifest.json` — the skill was still named
   there and still re-copied. "Removal by absence" always required hand-editing generated
   provenance.
3. **Deletion leaves the project broken, not merely unchanged.** After `rm -r
   .ai-badger/skills/foo`, `.claude/skills/foo` is a **dangling symlink** — `adjust_skills.py`
   only adds links, never prunes.
4. **The docs already promise the fix, and the promise is false.**
   `docs/getting-started.md` tells users, of invariants: *"Delete the ones you do not want before
   committing."* A refresh restores them. This is the decisive argument against "document it as
   non-removable" — the hole is not skills-only, and we have already told users otherwise.

**Recommendation to implement:** `"exclude": {"skills": [...]}` in `config.json`, enforced
**once, in `Scaffolder.__init__`**. Every consumer (`scaffold_skills`, `symlink_hermes_skills`,
the adjustments context, the dependency check) reads `self.skills`, so filtering there makes the
two entry points structurally unable to disagree — putting it in either caller re-creates the
#104 bug. `refresh.py` needs no change, and that is the point.

Rejected, with reasons: a **delete hook** has no trigger (nothing observes the filesystem between
runs; a user-invoked one is a command writing state — tombstones with a nicer door) and would
read `git checkout`, a revert or a bad merge as a policy declaration. **Tombstones** put a user
decision into generated provenance that `feed-badger` diffs through. **"Non-removable,
documented"** contradicts a promise already shipped in the docs.

On ADR tension: ADR-0005 governs *supply* and its failure mode is omission; an exclusion is
*demand* — per-project, explicit, and unable to reproduce that failure. Against ADR-0006, there
are currently **zero** ways to decline an artifact, so this is the first mechanism, not a fifth.

**Hard constraint the implementation must honour:** `hook_wiring.py` rewrites
`${CLAUDE_PLUGIN_ROOT}/…/skills/task/scripts/session_start_hook.py` into `.ai-badger/skills/`
**without checking the file exists**, so excluding `task` would wire two `SessionStart` commands
pointing at nothing. Extensions are *not* a coupling — `requires` are config predicates, never
skill names.

**Blast radius:** `config.schema.json` changes; `manifest.schema.json` deliberately does not;
**minor bump** under ADR-0001 §3. Fold in the bonus fix it found: `DEFAULT_SKILLS` should be
`default_skills_in(common)`, not `default_skill_names()` — the latter includes `auto-wm` (a
`features/claude` skill) and prints a permanent `not in index common.skills — skipped` note on
every scaffold. That is the last residue of the #104 divergence.

**Scope decision still open:** the research covers skills, but finding 4 shows invariants have
the same hole and a false doc promise. Decide whether `exclude` covers one feature type or
several before implementing.

## Superseded — research now complete

Branch `research/skill-removal-semantics`, agent running. Question: **how should a project say "I
do not want this skill"?** Today it cannot — `welcome-ai-badger` always restored deleted default
skills, `den-refresh` used not to, and #104 made them agree on "you cannot remove a skill." The
maintainer's framing was *"delete hook?"*.

The critical thing it must establish: whether `SKILL_SCOPES`/`optIn` is settable **by a project**
or is framework-only. If framework-only, the opt-out that the #104 changelog claims does not
exist. Blocks group D's second changelog sentence, nothing else.

---

# WAVE 2 — after group A merges

| Group | Work | Why it waits |
|---|---|---|
| **E** | **Wave 6** — `Scaffolder`'s five mixins → composed collaborators | Real collision: restructures `scaffold.py` and the mixins Wave 7's shim work edits |
| **F** | **Wave 16** — rename top-level `scripts/` | After 7, so the root literal lives in one predicate instead of ~20 files |
| **G** | Instrument `prompt-markers`, `task`, `mcp_index` hooks | Touches hook preambles Wave 7 rewrites. Do **after** group B, or `analyze` cannot show the result |

# WAVE 3 — after E and F

| Group | Work | Notes |
|---|---|---|
| **H** | **Wave 17** — split `badger_lib.py` | Needs 7 **and** 8 (8 is done). ADR-0007: the `badger_lib` facade is **mandatory, not tidiness** — 17 import sites, the shim's own predicate, two user-visible error messages. Flat sibling modules, never a package with `__init__.py` |

---

# Unscheduled — small, verified, no dependencies

Fold into whichever group touches the area, or batch them.

1. **`.ai-badger/instructions/*.md` carry no preserved regions** while their `.github/` copies do.
   They are `shutil.copyfile` catalog copies. Asymmetry is in the safe direction.
2. **Junie gets no root `AGENTS.md`.** `.junie/AGENTS.md` is correct and highest-precedence, but
   other agents read the root convention and nothing writes it.
3. **`~/.ai-badger/framework` does not report its own version skew** — it exists on this machine
   at **0.13.0** against a 0.33.0 catalog. Wave 7 demotes it to last but does not discharge it.
   This is the fixture that makes real-home tests pass for the wrong reason.
4. **The audit log is dominated by ai-badger's own test suite** — most `project` values are
   `pytest-of-*/pytest-NNN/...` temp dirs. Either isolate `DEBUG_DIR` in tests or teach `analyze`
   to exclude ephemeral paths.
5. **13 merged remote branches** could be pruned. Outward-facing; offered twice, not actioned.

---

## Standing rules for every dispatched agent

- **TDD is mandatory** — a failing, behaviour-focused test before any production change.
- **Do not bump `VERSION`, write a changelog, re-scaffold, or run `release_guard.py`** unless you
  are group D.
- **Push a branch; do not open a PR.** Merges happen locally after gates pass.
- Never stage anything under `.idea/` or `__pycache__/`.
- Never hand-edit `skills/`, `.claude/skills/` or `.ai-badger/skills/` — regenerate with
  `scripts/sync_plugin_skills.py`. The plugin mirror moved to `skills/` (ADR-0008).
- Use `.venv/bin/python`; `python3` on PATH is 3.14 and has no pytest.
- Gates: `pytest -q` · `pylint scripts features` · `validate.py --all` · `index_build.py --check`
  · `docs_guard.py` · `deps_guard.py` · `sync_plugin_skills.py --check` ·
  `node --test "tests/js/*.test.mjs"`.
