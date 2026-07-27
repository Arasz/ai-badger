# Deferred-work plan — Waves 6–18

**Date:** 2026-07-27 (revised the same day to cover every §7 item)
**Source:** `docs/plans/2026-07-26-remediation-plan.md` §7 "Explicitly out of scope for these PRs"
**Predecessor:** Waves 1–5 landed as 0.19.0 → 0.23.0 (#78–#82)

Every one of the **fourteen** items §7 excluded is now scheduled, with the reason for its
original deferral re-checked against the code as it stands. Nothing here was a live defect at
the time of the review; two have since been found to be sharper than filed, and those are
called out where they occur.

Each wave is self-contained: executable by someone who has read only this document and the
review sections it cites. **Work-package numbering is continuous** — a WP number never means
two things.

## Status

| Wave | Item | §7 source | State |
|---|---|---|---|
| 6 | `Scaffolder`'s five mixins → composed collaborators | architecture I1 / R10 | planned |
| 7 | Nine `_bootstrap_lib()` copies; three root predicates | architecture I6 / R9 | planned |
| 8 | Single feature-type registry | architecture I11 / R6 | planned |
| 9 | The hardening pass (+ prompt-marker/AWM privacy) | security I1, I2, I5, I7, sugg. 1 & 3 | **done — 0.25.0 (#85)** |
| 10 | `feed-badger` outbound scan + explicit pathspec | security I4 | **done — 0.24.0 (#84)** |
| 11 | Package `badger_lib` as an installable distribution | architecture I6 / R11 | planned — **ADR first** |
| 12 | Collapse the 3+1 MCP config writers | architecture I3 / R5 | planned |
| 13 | Derive `DEFAULT_SKILLS`/`COMMON_SKILLS`; decide `code-review-checklist` | architecture I8 / R7 | **done — 0.26.0 (#87)** |
| 14 | Pick one extension mechanism | architecture I5 / R8 | planned |
| 15 | Split `test_drift.py` / `test_scaffold.py` | python I6, tests sugg. | planned |
| 16 | Rename top-level `scripts/` | architecture S1 | planned — **ADR first, after 11** |
| 17 | Split `badger_lib.py` | architecture S2 | planned — after 7 and 8 |
| 18 | gitleaks/trufflehog in CI | security sugg. 6 | planned |

## Recommended execution order

Numbering is not priority. Two constraints are hard; the rest is judgement.

1. **Wave 11's ADR before Wave 7.** Packaging would retire Wave 7's shim work entirely.
   Decide it first, or knowingly spend Wave 7 twice.
2. **Wave 16 after Wave 11.** Renaming `scripts/` touches every `_bootstrap_lib` path, and
   packaging changes what those paths are.

Suggested sequence: **14 → 13 → 8 → 15 → 12 → 18 → 11 (ADR) → 6 → 7 → 17 → 16.**
Small and decisive first; the two ADR-gated renames last.

---

## Wave 6 — `Scaffolder` is five mixins pretending to be one object

**Deferred because:** *"~2,900 lines of test construct `Scaffolder` directly. Mechanically
safe but wide, and mixing it with any behaviour change makes the diff unreviewable."*

**Still true?** Yes, and the preconditions are met: WP6's sync gate, WP13's atomic writes and
WP17's partial-manifest marker have all landed. **77 direct `Scaffolder(...)` constructions
across 11 test files** (50 in `tests/test_scaffold.py`).

The coupling is smaller than the shape suggests. Everything the five mixins reach for:

| Attribute | Read by |
|---|---|
| `root`, `target`, `config`, `notes` | all five |
| `aib` | hook_wiring, agent_files |
| `stacks` | mcp_tools |
| `index`, `overwrite` | template_rendering |
| `_merged_external_tools`, `_external_tools_merged` | mcp_tools, template_rendering |

That is a `ScaffoldContext`, not a god object.

| WP | Work | Files |
|---|---|---|
| **WP29** | `ScaffoldContext` dataclass; `Scaffolder.__init__` builds one and keeps its attributes as read-through properties — **no test changes** | `scaffold.py`, new `scaffold_context.py` |
| **WP30** | Mixins become collaborators taking a context; `Scaffolder` composes and delegates. Public method names unchanged | the five mixin modules, `scaffold.py` |
| **WP31** | Drop the shims; move tests that reach into internals onto the collaborator that owns them | `test_scaffold.py`, `test_stack_mcp_servers.py`, `test_external_mcp_tools.py` |

**TDD entry point:** `tests/test_scaffold_context.py::test_context_is_the_only_state_the_collaborators_share`
— construct each collaborator with a context and assert it works with no `Scaffolder` in scope.
*Fails today: the mixins cannot be instantiated alone.*

**Constraints.** WP29 must change zero tests — that is the checkpoint proving it is
behaviour-preserving. `run()`'s step order is load-bearing (WP17 records it); assert
`manifest.json.partial`'s `completedSteps` before and after. Do not split the test files here
— that is Wave 15.

**Release:** `0.26.0`, `docs/changelog/0.26.0-scaffold-context.md`.

---

## Wave 7 — nine bootstrap shims and three disagreeing definitions of "framework root"

**Deferred because:** *"The shim must work in three deployment shapes… Needs an integration
test per shape written first. Highest-risk refactor in the review."*

**Still true?** Yes. WP12 has split `find_root`, so the precondition is met. The risk is
unchanged: **this is the one that can brick every entry point in every deployment shape at
once.**

`_bootstrap_lib()` is copied into **9 source files** (16 with the shipped `.claude/` copies).
Three predicates answer "is this a framework root?", and they disagree:

| Predicate | Test | Where |
|---|---|---|
| `badger_lib._is_root` | `schemas/` **and** `features/` | `scripts/badger_lib.py:85` |
| `_bootstrap_lib` (×9) | `scripts/badger_lib.py` **and** `schemas/` | e.g. `scaffold.py:34` |
| `ai_badger_hooks.find_framework_root` | `VERSION` **and** `schemas/` | `ai_badger_hooks.py:50` |

A plugin cache satisfies all three; a `.ai-badger/` scaffold satisfies none; a partial clone
can satisfy exactly one. That is why the disagreement has never been felt — and why unifying
them is a behaviour change, not a cleanup.

| WP | Work | Files |
|---|---|---|
| **WP32** | **Integration test per deployment shape, first.** All three shapes under `tmp_path`; assert each entry point imports and runs. Must pass before any shim changes | `tests/test_deployment_shapes.py` *(new)* |
| **WP33** | One canonical `resolve_framework_root()` with the predicate stated once and the three-shape contract in its docstring | `scripts/badger_lib.py` |
| **WP34** | Shrink the nine shims to a path search with **one** definition of the predicate. The shim cannot import `badger_lib` — that is the bootstrap problem — so it stays duplicated but stops disagreeing | the 9 files + `.claude/` copies |

**TDD entry point:** `test_every_entry_point_resolves_the_root_in_all_three_shapes`,
parametrised over (entry point × shape). *Fails today for the `.ai-badger/` scaffold shape.*

**Constraints.** Nothing else ships in this PR. If Wave 11's ADR is accepted, most of WP34 is
thrown away — decide first.

**Release:** `0.27.0`, `docs/changelog/0.27.0-one-framework-root.md`.

---

## Wave 8 — three hardcoded feature lists that already disagree

**Deferred because:** *"The four already disagree about `templates`, so unifying them will
change drift output."*

**Still true? Partly — and it is a live bug, not a latent one.** WP16 replaced `validate.py`'s
if-chain with a table, so **three** lists remain:

| List | Contents | Where |
|---|---|---|
| `badger_lib.FEATURES` | …, **templates**, hooks, adjustments | `badger_lib.py:23` |
| `index_build`'s if-chain | skills / hooks / adjustments / **templates** / else-md | `index_build.py:97-105` |
| `drift.py`'s tuple | skills, personas, invariants, instructions, hooks, adjustments — **no templates** | `drift.py:100` |

**Consequence:** a new template is indexed, is scaffolded, and is invisible to drift. A
consumer running `den-refresh` is never told a template appeared.

| WP | Work | Files |
|---|---|---|
| **WP35** | One registry: name, `.md`-carrying, index-builder, drift-reports-new. `FEATURES` derives from it | `badger_lib.py`, `tests/test_badger_lib.py` |
| **WP36** | Route `index_build` and `drift.py` through it. **`templates` starts being reported** — the intended correction; call it out in the changelog | `index_build.py`, `drift.py`, `tests/test_drift.py` |

**TDD entry point:** `tests/test_drift.py::test_a_new_template_is_reported_as_a_new_item`.
*Fails today: `templates` is not in the tuple.*

**Constraint.** `index.json` must stay byte-identical (`index_build --check` proves it).

**Release:** `0.28.0`, `docs/changelog/0.28.0-feature-type-registry.md`.

---

## Wave 9 — the hardening pass ✅ **done (0.25.0, #85)**

Covered §7's *"path-traversal hardening of `project.name`, `shell=True` in the skill
installer, dependency auto-install consent, `.mjs` ReDoS caps, manifest absolute-path
containment"* **and** *"prompt-marker state and AWM decision-log privacy"*, which §7 assigned
to the same PR.

WP37 (argv, no shell) · WP38 (install consent; **breaking**, in `BREAKING_VERSIONS`) ·
WP39 (pattern and file caps in both `.mjs`) · WP40 (`0600`, capped logs, gitignore) ·
WP41 (`project.name` containment) · WP41b (manifest `target` containment).

**Correction to the original verdict.** §7 called these *"catalog-controlled inputs"*. That
does not cover `project.name`: the schema constrains it to a non-empty string and nothing
else, and it is interpolated into a `$HOME` path. A foot-gun rather than pure
defence-in-depth. Recorded in `docs/changelog/0.25.0-hardening.md`.

---

## Wave 10 — the outbound publish path ✅ **done (0.24.0, #84)**

Covered §7's *"`feed-badger` outbound secret scan + replacing `git add -A` with an explicit
pathspec"*. WP42 extracted the scanner to `scripts/unsafe_literals.py` (shared by both
directions); WP43 scans every declared path before any git command and made `--path` required.

§7 scheduled this *"immediately after Wave 3"*; it ran after Wave 5. Taken first among the
deferred waves for that reason.

---

## Wave 11 — package `badger_lib` + the scaffold engine as an installable distribution

**Deferred because:** *"Changes how the plugin ships and how scaffolded projects resolve the
engine. **Needs its own ADR.** Would retire the nine `_bootstrap_lib` copies and most of
F-17's root cause — high value, wrong time."*

**Still true?** Yes, and it is now the highest-leverage item on this list: it subsumes Wave 7
and unblocks Wave 16. It also has the widest blast radius of anything here — it changes what
"installed" means for every consumer.

| WP | Work | Files |
|---|---|---|
| **WP44** | **ADR-0005: how ai-badger ships.** Options: status quo (vendored + shims), a PyPI distribution, or a vendored single-file amalgamation. Must answer: how a plugin-cache install resolves the engine; how a `.ai-badger/` scaffold does; how `~/.hermes/plugins/` does; what happens when the installed engine and the scaffold disagree on version; whether pure-stdlib survives | `docs/adr/0005-*.md` |
| **WP45** | *Only if the ADR chooses packaging:* the packaging itself, plus the shim reduction it enables | `pyproject.toml`, `scripts/`, the 9 shims |

**TDD entry point:** none — WP44 is a decision. WP45 inherits Wave 7's
`tests/test_deployment_shapes.py`, which must exist and pass first either way.

**Constraint.** Do not start WP45 before the ADR is accepted, and do not let the ADR be
written by whoever is mid-way through Wave 7 — that is how a sunk cost becomes a decision.

**Release:** ADR only, no version bump. WP45 would be a major-ish minor: `0.3x.0` with a
`BREAKING_VERSIONS` entry.

---

## Wave 12 — collapse the 3+1 MCP config writers

**Deferred because:** *"~215 lines → ~90, no test names the module, and the `.mcp.json`
command-splitting heuristic diverges from `_parse_command` and must be preserved verbatim or
deliberately unified. WP19 fixes only the `for … break` correctness bug."*

**Still true?** Yes, and WP19 (Wave 4) made it cleaner: each writer now resolves overrides
through its own owner constant (`MCP_JSON_OWNER`, `COPILOT_MCP_OWNER`, `HERMES_MCP_OWNER`), so
the per-file differences are already explicit — the table this wave writes has its columns
named for it. `tests/test_stack_mcp_servers.py` now covers all four writers, so the "no test
names the module" objection is gone.

The four writers: `_generate_mcp_json` (project `.mcp.json`), `_scaffold_claude_mcp_user`
(`~/.claude/settings.json`), `_scaffold_hermes_mcp_user` (`~/.hermes/config.yaml`, YAML),
`_generate_copilot_mcp_config` (`.github/copilot/mcp-config.json`).

| WP | Work | Files |
|---|---|---|
| **WP46** | Characterisation tests pinning the `.mcp.json` command-splitting heuristic against `_parse_command`, **before** touching either | `tests/test_stack_mcp_servers.py` |
| **WP47** | One table-driven writer: (path, format, owning agent, scope, merge strategy). Either preserve the heuristic verbatim or unify it **and say so in the changelog** — silently changing generated `.mcp.json` content is the failure mode | `mcp_tools.py` |

**TDD entry point:** `test_the_two_command_splitters_agree_or_are_documented_to_differ` —
feed both the same commands and assert the current outputs. *Passes today by construction;
its job is to fail the moment WP47 changes one.*

**Release:** `0.29.0`, `docs/changelog/0.29.0-one-mcp-writer.md`.

---

## Wave 13 — decide what the default skill set is — **DONE (0.26.0, PR #87)**

**Deferred because:** *"Changes the default skill set — a product decision, not a bug fix.
`code-review-checklist` is currently in the catalog, indexed, tested, and reachable by
**neither** default path; somebody has to decide, not just refactor."*

**Was true, with one correction.** `code-review-checklist` was in `index.json`'s common skills
and in **neither** `scaffold.DEFAULT_SKILLS` (8 names) nor `sync_plugin_skills.COMMON_SKILLS`,
so it shipped to nobody by either route. It was *not* in `features/common/skills.json` — that
file is the **external** skills list (superpowers, pr-review-toolkit), not the in-repo catalog;
the earlier draft of this plan had that wrong.

**The decision (made by the maintainer): move it to common — it ships by default.**

| WP | Work | Files |
|---|---|---|
| **WP48** | ✅ Decision recorded with its reason | `docs/adr/0005-default-skill-set.md`, `docs/changelog/0.26.0-default-skill-set.md` |
| **WP49** | ✅ Both lists derive from one declaration, `badger_lib.SKILL_SCOPES` (`default` / `optIn`); `skill_scope()` raises `UnknownSkillScope` rather than assuming; `index_build` stamps `scope` onto each skill entry | `badger_lib.py`, `scaffold.py`, `sync_plugin_skills.py`, `index_build.py`, `schemas/index.schema.json` |

**TDD entry point (as planned):** `tests/test_sync_plugin_skills.py::TestCatalogRouting::test_every_catalog_skill_is_reachable_by_a_declared_route`
— failed on `code-review-checklist`, along with four siblings covering the reverse direction
(a declaration naming a skill that no longer exists), plugin-copy reachability, and the raise.

**Not done as scoped:** the declaration is a constant in `badger_lib`, not a `scope:` field in
SKILL.md frontmatter as WP49 originally sketched. No script parses YAML frontmatter today and
pyyaml is a guarded optional import; adding a parser for one scalar is a worse trade than the
constant. Reasoning in ADR-0005. `features/*/skills.json` was untouched — it is the external
list, so it was never in scope once the correction above surfaced.

**Released:** `0.26.0`, `docs/changelog/0.26.0-default-skill-set.md`.

---

## Wave 14 — pick one extension mechanism

**Deferred because:** *"Zero catalog instances exist, so 'delete' is behaviour-preserving
today — but it removes a schema field, which is a compatibility decision."*

**Still true? Confirmed.** `find features -name "*-extensions"` returns **nothing**: the
`<stack>/skills/<base>-extensions/<ext>/` mechanism (`index_build.py:110-125`,
`extensions.py`, and the `extensions` field in `index.schema.json:51`) has no instances at
all. Meanwhile `<skill>/extensions/<name>/` is used by `task` for claude, github, hermes and
copilot. **Two mechanisms, one of them dead.**

Smallest wave here, and a good first one.

| WP | Work | Files |
|---|---|---|
| **WP50** | Delete the unused mechanism: `_embed_extensions`, `index_build.py:110-125`, and the `extensions` field from `index.schema.json`. Removing a schema field is a compatibility change — an older manifest carrying it must still validate or be told to re-scaffold | `extensions.py`, `index_build.py`, `index.schema.json`, `tests/` |

**TDD entry point:** `tests/test_index_build.py::test_a_manifest_from_before_the_field_was_removed_still_validates`.
*Write it before deleting anything.*

**Constraint.** Confirm zero instances **at the moment of deletion**, not from this document —
a catalog entry could appear between writing and doing.

**Release:** `0.31.0`, `docs/changelog/0.31.0-one-extension-mechanism.md`.

---

## Wave 15 — split the two oversized test files

**Deferred because:** *"Purely mechanical, and both files are touched by Waves 2–3. Splitting
them mid-remediation guarantees merge conflicts."*

**Still true?** The conflict risk is gone once Waves 6–8 land — but **Wave 6 touches
`test_scaffold.py` heavily**, so this goes after it, not before. Current sizes:
`test_scaffold.py` **1,338 lines**, `test_drift.py` **1,006** — both over the C0302 threshold,
and `test_scaffold.py` has grown 187 lines across Waves 2–9.

| WP | Work | Files |
|---|---|---|
| **WP51** | Split both along their existing `# ---` domain boundaries. Pure moves: no renames, no assertion edits, no new coverage. The diff must be reviewable as "these lines moved" | `tests/test_scaffold.py`, `tests/test_drift.py` → several files each |

**TDD entry point:** none — the test count before and after **must be identical**, and that is
the check. Record the number in the PR body.

**Constraint.** Only C0302 lint debt; CI's pylint scope excludes `tests/`. Do not bundle this
with anything.

**Release:** patch bump, no behaviour change.

---

## Wave 16 — rename top-level `scripts/`

**Deferred because:** *"The screaming-architecture invariant genuinely applies. But this
renames every entry point, every `_bootstrap_lib` path, and every doc reference. Own PR, own
ADR, after packaging is decided."*

**Still true?** Yes, and it is now **doubly gated**: on Wave 11's packaging ADR (which decides
whether `scripts/` remains an importable directory at all) and on Wave 7 (which is what makes
the `_bootstrap_lib` paths mechanical to change).

| WP | Work | Files |
|---|---|---|
| **WP52** | ADR: what the directory is *for*, and therefore its name. `catalog/`, `distribution/`, `release/` were all proposed — they are not synonyms, and the answer decides whether it is one directory or several | `docs/adr/` |
| **WP53** | The rename, mechanically, with every reference updated in one commit | `scripts/` → chosen name; the 9 shims; docs; CI; pre-commit |

**TDD entry point:** Wave 7's `tests/test_deployment_shapes.py` is the safety net. Do not
attempt this wave without it.

**Release:** `BREAKING_VERSIONS` entry; consumers with a pinned path will break.

---

## Wave 17 — split `badger_lib.py`

**Deferred because:** *"Same reason [as the `scripts/` rename]; WP12 and WP13 both touch this
file and should land first."*

**Still true?** WP12 and WP13 have landed, so the stated blocker is cleared — but Waves 7 and
8 both add to this file (`resolve_framework_root`, the feature-type registry). Doing it before
them means splitting a file that is about to change shape. **After 7 and 8.**

Current state: **353 lines**, already grouped by domain — breaking versions, roots/IO,
hashing, schema validation, catalog iteration.

| WP | Work | Files |
|---|---|---|
| **WP54** | Split into `catalog.py` / `fingerprint.py` / `versioning.py` along the existing section comments. `badger_lib` becomes a re-export facade so the nine shims and every `import badger_lib as bl` keep working unchanged | `scripts/badger_lib.py` → three modules |

**TDD entry point:** `tests/test_badger_lib.py` must pass **untouched** — it imports through
the facade. If it needs editing, the facade is wrong.

**Release:** patch bump, no behaviour change.

---

## Wave 18 — secret scanning in CI

**Deferred because:** *"Cheap and sensible, but it is a new external dependency in CI and will
produce an initial finding backlog. Separate task."*

**Still true?** Yes, with one update: Wave 10 added `scripts/unsafe_literals.py`, which scans
the **outbound contribution path** only. It is a guard on one door, not the repository history
— which is exactly what gitleaks/trufflehog covers and it does not.

| WP | Work | Files |
|---|---|---|
| **WP55** | Add the scanner to CI on a **new-findings-only** baseline first, so the initial backlog does not block every PR. Record the baseline and its size | `.github/workflows/` |
| **WP56** | Work the backlog down, then remove the baseline. A permanently-baselined scanner is theatre | as found |

**TDD entry point:** none (CI configuration). Verify by pushing a branch with an obviously
fake credential and confirming the job fails — the same way Wave 5's `tdd_guard` was verified.

**Constraint.** Do not let this replace `unsafe_literals`: one guards outbound content at the
moment of publishing, the other scans history. Different doors.

**Release:** patch bump.

---

## Definition of done, per wave

1. The wave's TDD entry-point test was written first and observed failing.
2. All gates green: `pytest -q`, `node --test "tests/js/*.test.mjs"`, `pylint` (scripts) at
   10.00, `index_build --check`, `validate --all`, `version_sync --check`,
   `sync_plugin_skills --check`, `release_guard`, `tdd_guard`.
3. `VERSION` bumped and a changelog entry added — plus a `BREAKING_VERSIONS` line where the
   wave says so.
4. One PR, merged, **then tagged** `ai-badger--v{version}` — the step whose 32 consecutive
   omissions are recorded in `docs/incidents/2026-07-27-untagged-releases.md`.
5. Any pre-existing test rewritten to a new contract is named in the PR body. Rewriting a test
   to match new behaviour is the move that most deserves review.
