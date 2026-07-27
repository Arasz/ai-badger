# Deferred-work plan — Waves 6–10

**Date:** 2026-07-27
**Source:** `docs/plans/2026-07-26-remediation-plan.md` §7 "Explicitly out of scope for these PRs"
**Predecessor:** Waves 1–5 landed as 0.19.0 → 0.23.0 (#78, #79, #80, #81, #82)

Every item below was excluded from the remediation waves *with a stated reason*, not
forgotten. Waves 1–5 are now merged, so each reason has been re-checked against the code as
it stands today; where the reason has changed, this document says so. Nothing here is a live
defect — these are structural debts and defence-in-depth, and each is sized as one PR.

Each wave is self-contained: it can be executed alone, in any order, by someone who has read
only this document and the sections of the review it cites. **Work-package numbering continues
from WP28** so a WP number never means two things.

---

## Recommended execution order

The waves are numbered as listed, but numbering is not priority. Recommended order and why:

| Order | Wave | Reason |
|---|---|---|
| 1st | **Wave 10** (feed-badger publish path) | It is the only path that *publishes* repo content outward. Smallest of the five, and it unblocks nothing else — do it while it is cheap. |
| 2nd | **Wave 9** (hardening) | Defence-in-depth, but it touches the same `shell=True`/consent surfaces that any later refactor would otherwise re-plumb. |
| 3rd | **Wave 8** (feature-type registry) | Small, mechanically bounded, and it *changes drift output* — a correction that wants its own changelog line rather than being buried in a refactor. |
| 4th | **Wave 6** (Scaffolder split) | Wide but mechanical. Do it before Wave 7 so the bootstrap work lands on a `Scaffolder` that no longer hides state in `self`. |
| 5th | **Wave 7** (bootstrap unification) | Highest-risk refactor in the whole review. It must go last, and it must not share a PR with anything else. |

A reader who disagrees should still keep **Wave 7 last** and **Wave 10 not last**.

---

## Wave 6 — `Scaffolder` is five mixins pretending to be one object

**Original reason for deferral:** *"~2,900 lines of test construct `Scaffolder` directly.
Mechanically safe but wide, and mixing it with any behaviour change makes the diff
unreviewable. Needs its own PR after Wave 3, with WP6's sync gate and WP13's atomic writes
already in place."* (architecture I1 / R10)

**Still true?** Yes, and the preconditions are now met: WP6's `sync_plugin_skills --check`,
WP13's atomic writes and WP17's partial-manifest marker have all landed. The count is
**77 direct `Scaffolder(...)` constructions across 11 test files** (50 of them in
`tests/test_scaffold.py`).

### What is actually there

`Scaffolder` (`scaffold.py:205`) inherits five mixins — `McpToolsMixin`, `HookWiringMixin`,
`TemplateRenderingMixin`, `AgentFilesMixin`, `ExtensionsMixin` — spread over 964 lines in five
files. The coupling is smaller than the shape suggests. Every attribute the mixins reach for:

| Attribute | Read by |
|---|---|
| `root`, `target`, `config`, `notes` | all five |
| `aib` | hook_wiring, agent_files |
| `stacks` | mcp_tools |
| `index`, `overwrite` | template_rendering |
| `_merged_external_tools`, `_external_tools_merged` | mcp_tools, template_rendering |

That is a `ScaffoldContext`, not a god object — the mixins are already nearly pure functions
over a small shared record.

### Work packages

| WP | Work | Files owned |
|---|---|---|
| **WP29** | Introduce `ScaffoldContext` (frozen dataclass for `root`/`target`/`aib`/`config`/`stacks`/`index`/`overwrite`/`reset_seed_files`/`execute`/`install`, plus the mutable `notes` and `entries` lists). `Scaffolder.__init__` builds one and keeps its current attributes as read-through properties, so **no test changes yet**. | `scaffold.py`, new `scaffold_context.py` |
| **WP30** | Convert the five mixins to collaborators taking a `ScaffoldContext` in their constructor. `Scaffolder` composes them and delegates. Public method names on `Scaffolder` stay identical. | the five mixin modules, `scaffold.py` |
| **WP31** | Delete the read-through properties that no longer have callers; update the tests that reach into internals (`_collect_external_tools`, `_generate_mcp_json`, `_scaffold_claude_mcp_user`, …) to go through the collaborator they now live on. | `tests/test_scaffold.py`, `tests/test_stack_mcp_servers.py`, `tests/test_external_mcp_tools.py` |

### TDD entry point

`tests/test_scaffold_context.py::test_context_is_the_only_state_the_collaborators_share` —
construct each collaborator with a `ScaffoldContext` and assert it produces its output without
a `Scaffolder` in scope at all. **Fails today: the mixins cannot be instantiated alone.**

### Constraints

- **WP29 must not change a single test.** If a test needs editing during WP29, the property
  shim is wrong. That is the checkpoint that proves the refactor is behaviour-preserving.
- Do **not** split `tests/test_scaffold.py` (1,268 lines) in this PR — that is its own
  mechanical PR, and combining them makes the diff unreviewable, which is the whole reason
  this was deferred.
- `run()`'s step order is load-bearing (WP17's progress marker records it). Preserve it
  exactly; assert on `manifest.json.partial`'s `completedSteps` before and after.

**Release:** `VERSION` → `0.24.0`, `docs/changelog/0.24.0-scaffold-context.md`.

---

## Wave 7 — nine bootstrap shims and three disagreeing definitions of "framework root"

**Original reason for deferral:** *"The shim must work in three deployment shapes (framework
checkout, `.ai-badger/` scaffold, `~/.hermes/plugins/`). Needs an integration test per shape
written first. Highest-risk refactor in the review; do it after WP12 has already split
`find_root`."* (architecture I6 / R9)

**Still true?** Yes. WP12 has landed, so `find_root()` is now a pure lookup that raises — the
precondition is met. The risk assessment is unchanged: **this is the one that can brick every
entry point in every deployment shape at once.**

### What is actually there

`_bootstrap_lib()` is copied into **9 source files** (16 including the shipped `.claude/`
copies): `learned_skills_sync.py`, `ai_badger_hooks.py`, `detect_additions.py`, `open_pr.py`,
`detect.py`, `drift.py`, `scaffold.py`, `drift_notice_hook.py`, `refresh.py`.

Three different predicates answer "is this a framework root?", and they disagree:

| Predicate | Test | Where |
|---|---|---|
| `badger_lib._is_root` | `schemas/` **and** `features/` | `scripts/badger_lib.py:85` |
| `_bootstrap_lib` (×9) | `scripts/badger_lib.py` **and** `schemas/` | e.g. `scaffold.py:34` |
| `ai_badger_hooks.find_framework_root` | `VERSION` **and** `schemas/` | `features/common/hooks/ai_badger_hooks.py:50` |

A plugin-cache install satisfies all three; a `.ai-badger/` scaffold satisfies none; a partial
clone can satisfy exactly one. That is why the disagreement has never been felt — and why
unifying them is a behaviour change, not a cleanup.

### Work packages

| WP | Work | Files owned |
|---|---|---|
| **WP32** | **Integration test per deployment shape, first.** Build all three shapes under `tmp_path` (framework checkout, a scaffolded project, a `~/.hermes/plugins/` copy) and assert each entry point imports and runs. This test must exist and pass *before* any shim changes. | `tests/test_deployment_shapes.py` *(new)* |
| **WP33** | One canonical `resolve_framework_root()` in `badger_lib`, with the predicate stated once and the three-shape contract in its docstring. Keep the existing names as thin aliases. | `scripts/badger_lib.py` |
| **WP34** | Replace the nine `_bootstrap_lib()` bodies with the smallest possible shim that finds `badger_lib` and delegates. The shim itself cannot import `badger_lib` — that is the bootstrap problem — so it stays duplicated but shrinks to a path search with **one** definition of the predicate, sourced from a single literal. | the 9 files + their `.claude/` copies via `sync_plugin_skills.py` |

### TDD entry point

`tests/test_deployment_shapes.py::test_every_entry_point_resolves_the_root_in_all_three_shapes`
— parametrised over (entry point × shape). **Fails today for at least the `.ai-badger/`
scaffold shape**, which is exactly the gap the three predicates paper over.

### Constraints

- **Nothing else ships in this PR.** No behaviour change, no doc pass, no version-adjacent edit.
- The packaging option (*"package `badger_lib` as an installable `ai_badger` distribution"*,
  architecture I6 / R11) would retire this entire class of problem. It is still out of scope
  and **still needs its own ADR** — but write that ADR *before* Wave 7 if there is any appetite
  for it, because Wave 7's shim work is thrown away by it.

**Release:** `VERSION` → `0.25.0`, `docs/changelog/0.25.0-one-framework-root.md`.

---

## Wave 8 — four hardcoded feature lists that already disagree

**Original reason for deferral:** *"The four already disagree about `templates`, so unifying
them will change drift output. That is an intentional correction that deserves its own PR and
changelog, not a side effect of WP16."* (architecture I11 / R6)

**Still true?** Partly — and the shape has changed. WP16 replaced `validate.py`'s if-chain
with the `SCHEMA_INSTANCES` table, so **three** lists remain, not four:

| List | Contents | Where |
|---|---|---|
| `badger_lib.FEATURES` | skills, personas, invariants, instructions, **templates**, hooks, adjustments | `scripts/badger_lib.py:23` |
| `index_build`'s if-chain | dispatches skills / hooks / adjustments / **templates** / else-md | `scripts/index_build.py:97-105` |
| `drift.py`'s tuple | skills, personas, invariants, instructions, hooks, adjustments — **no templates** | `.../drift.py:100` |

**The disagreement is confirmed and it is a real bug:** a new template added to the catalog is
indexed, is scaffolded, and is invisible to `drift.py`'s "new items" report. A consumer running
`den-refresh` is never told a template appeared.

### Work packages

| WP | Work | Files owned |
|---|---|---|
| **WP35** | A single feature-type registry in `badger_lib`: name, whether it carries `.md` items, its index-builder, and whether drift reports new items for it. `FEATURES` becomes derived from it. | `scripts/badger_lib.py`, `tests/test_badger_lib.py` |
| **WP36** | Route `index_build`'s if-chain and `drift.py`'s tuple through the registry. **`templates` starts being reported by drift** — that is the intended correction; call it out in the changelog as a behaviour change. | `scripts/index_build.py`, `.../drift.py`, `tests/test_drift.py` |

### TDD entry point

`tests/test_drift.py::test_a_new_template_is_reported_as_a_new_item` — add a template to a
fixture catalog, run drift against a manifest that predates it, assert it appears.
**Fails today: `templates` is not in the tuple, so the item is silently dropped.**

### Constraints

- `index.json` must stay **byte-identical** after WP35 (`index_build.py --check` is the proof).
  The registry changes who decides, not what is produced.
- Expect drift output to grow for real consumers. That is the point, and it is the only
  user-visible change in this wave.

**Release:** `VERSION` → `0.26.0`, `docs/changelog/0.26.0-feature-type-registry.md`.

---

## Wave 9 — the hardening pass

**Original reason for deferral:** *"All confirmed by the security reviewer as defence-in-depth,
not exploitable from a hostile repo today (catalog-controlled inputs, pattern-constrained
`config.stacks`). Real work; belongs in a dedicated hardening PR after Wave 3, sized as one
wave of its own."* (security I1, I2, I5, I7, suggestions 1 & 3)

**Still true?** Mostly. Every item was re-verified as still present, and the two the review
left unquantified were pinned down (WP41, WP41b below). One correction to the original verdict:
*"catalog-controlled or schema-constrained"* does not cover `project.name` — the schema
constrains it to a non-empty string and nothing else, and it is interpolated into a `$HOME`
path. Still not a hostile-repo exploit (the user writes their own `config.json`), but it is a
foot-gun rather than pure defence-in-depth.

### What is actually there

| Item | Verified | Where |
|---|---|---|
| `shell=True` on skill-install commands | present | `scaffold.py:419` |
| `npm install -g` with no consent prompt | present | `dependency_check.py:101` |
| `pip install` into a venv with no consent prompt | present | `dependency_check.py:79-81` |
| `new RegExp(pattern)` built from model-supplied patterns, no length or complexity cap | present, 2 files | `check-agent-drift.mjs:24`, `validate-agent-instructions.mjs:27` |
| No `0600` on `~/.claude/awm/state.json`, `decisions.jsonl`, prompt-marker transformation log | present (no `chmod` anywhere) | `awm.py`, `awm_gate.py`, `user_prompt_hook.py` |
| `project.name` interpolated into a `$HOME` path with no pattern constraint | **confirmed** | `scaffold.py:161-163`, `schemas/config.schema.json` |
| Manifest `target` joined with no containment check | **confirmed** | `drift.py:180-182` |

### Work packages

| WP | Work | Files owned |
|---|---|---|
| **WP37** | Replace `shell=True` with an argv list. The install commands come from `plugins-instructions.json` templates, so they can be tokenised at build time instead of concatenated into a string — `install_plugins._build_command` should return a list. | `scripts/install_plugins.py`, `.../scaffold.py`, `tests/test_install_plugins.py` |
| **WP38** | Consent gate on anything installed outside the project: `npm install -g` and the venv `pip install` both print exactly what they will run and require an explicit opt-in (flag or prompt), defaulting to **print-and-skip**. Mirrors what WP9 already did for skill installs. | `.../dependency_check.py`, `tests/test_dependency_check.py` |
| **WP39** | Cap pattern length and input size before `new RegExp` in both `.mjs` scripts; reject a pattern over the cap with a named error rather than hanging. Cover with `tests/js/` (the suite Wave 5 created). | the two `.mjs` scripts, `tests/js/` |
| **WP40** | `0600` on the three user-scope state files at creation, size caps on the two append-only logs, and the matching `.gitignore` entries. | `awm.py`, `awm_gate.py`, `prompt-markers/scripts/user_prompt_hook.py`, `tracker_lib.py` |
| **WP41** | **`project.name` containment.** `scaffold.py:163` builds `Path.home() / ".hermes" / "skills" / project_name`, and `config.schema.json` constrains `project.name` to nothing but `type: string, minLength: 1`. A name of `../../.ssh` resolves outside the namespace directory. Add a pattern to the schema **and** a containment assert at the join — the schema alone is not enough, because a hand-edited `config.json` reaches `scaffold.py` through `den-refresh` without re-validation. | `schemas/config.schema.json`, `.../scaffold.py`, `tests/test_scaffold.py` |
| **WP41b** | **Manifest `target` containment.** `drift.py:181` computes `target / target_rel` straight from the manifest. `pathlib` lets an absolute right-hand side win outright (`Path("/a") / "/etc"` → `/etc`), so a hand-edited or corrupted manifest points the hasher anywhere on disk. Read-only today, but `refresh.py` re-scaffolds from the same entries. Resolve and assert containment under `target`, skip with a note otherwise — the pattern `learned_skills_sync` already uses. | `.../drift.py`, `.../refresh.py`, `tests/test_drift.py` |

### TDD entry point

`tests/test_install_plugins.py::test_a_command_with_a_shell_metacharacter_is_not_interpreted`
— declare a skill whose name contains `; touch pwned`, assert the file is not created and the
command is passed as a single argv element. **Fails today: `shell=True` interprets it.**

### Constraints

- WP38 changes default behaviour: dependencies stop auto-installing. That is a **breaking
  change for anyone relying on the silent install** — it belongs in `BREAKING_VERSIONS`, and the
  scaffold must print what to run.
- Do not add gitleaks/trufflehog here (security suggestion 6). It is a new CI dependency with
  its own finding backlog — separate task, as originally scoped.

**Release:** `VERSION` → `0.27.0`, `docs/changelog/0.27.0-hardening.md`. Add `0.27.0` to
`BREAKING_VERSIONS` if WP38 lands as specified.

---

## Wave 10 — the path that publishes

**Original reason for deferral:** *"Genuinely important — it is the path that publishes — but
the fix depends on extracting `scan_for_unsafe_literals` into a shared module, which WP5 and
WP13 both touch. Schedule immediately after Wave 3."* (security I4)

**Still true?** The dependency is now clear: WP5 and WP13 have landed, and
`scan_for_unsafe_literals` sits in `features/common/hooks/learned_skills_sync.py:279` with its
`UNSAFE_LITERAL_PATTERNS` / `UNSAFE_LITERAL_LABELS` / `LITERAL_SCAN_MAX_BYTES` constants. It is
ready to extract. **This wave is overdue relative to its own stated schedule** ("immediately
after Wave 3") — hence the recommendation to run it first.

### What is actually there

`feed-badger`'s `open_pr.py:71` runs **`git add -A`** in the ai-badger checkout, then commits
and pushes to a branch and opens a PR. Whatever is in that working tree at that moment is
published. Nothing scans the outgoing content, and nothing constrains *which* paths are staged —
`-A` stages every modification present, including any the user did not intend to contribute.

The inbound path (`learned_skills_sync`) already refuses a skill whose content matches an
unsafe-literal pattern. The **outbound** path has no equivalent.

### Work packages

| WP | Work | Files owned |
|---|---|---|
| **WP42** | Extract `scan_for_unsafe_literals` + its constants into a shared module both paths import (`features/common/hooks/` is the wrong home for something `feed-badger` needs). Behaviour-preserving; `learned_skills_sync` keeps working through the new import. | new shared module, `learned_skills_sync.py`, `tests/test_learned_skills_sync.py` |
| **WP43** | `open_pr.py` scans everything it is about to stage and **refuses** on a finding, naming the file and the pattern label (never the matched text — the existing closed-vocabulary rule). Replace `git add -A` with an explicit pathspec derived from what `detect_additions.py` proposed, so an unrelated dirty file in the checkout cannot ride along. | `.../feed-badger/scripts/open_pr.py`, `tests/test_open_pr.py` |

### TDD entry point

`tests/test_open_pr.py::test_a_secret_shaped_literal_blocks_the_pr` — stage a contribution
containing an obviously-fake token matching a known pattern, run `open_pr.py --dry-run`, assert
a non-zero exit, the file named, and **no** `git push` in the printed command list.
**Fails today: nothing scans, so the PR command list is printed unchanged.**

A second entry point worth writing at the same time:
`test_an_unrelated_dirty_file_is_not_staged` — dirty an unrelated file in the checkout, assert
it does not appear in the staged pathspec. **Fails today: `git add -A` takes everything.**

### Constraints

- The scanner is *"a guard, not proof"* (its own docstring). Do not let WP43's messaging imply
  it certifies the diff is clean — say what it checked.
- Findings must keep travelling as `{file, label}` pairs. No scanned byte reaches stdout,
  the PR body, or a log line. This is the CodeQL `py/clear-text-logging` rule the inbound path
  already respects.

**Release:** `VERSION` → `0.28.0`, `docs/changelog/0.28.0-outbound-scan.md`.

---

## Still deferred after these waves

From the same §7, deliberately **not** scheduled here, with the reason each is still parked:

| Item | Why still parked |
|---|---|
| Package `badger_lib` as an installable `ai_badger` distribution | Needs its own ADR. Would retire Wave 7's shim work entirely — decide before Wave 7, not after. |
| Collapse the 3+1 MCP config writers into one table-driven writer | ~215 → ~90 lines, but the `.mcp.json` command-splitting heuristic must be preserved verbatim or deliberately unified. Own PR. |
| Derive `DEFAULT_SKILLS`/`COMMON_SKILLS` from catalog metadata; decide `code-review-checklist`'s status | A **product decision**, not a refactor: that skill is in the catalog, indexed, tested, and reachable by neither default path. Somebody has to decide. |
| Pick one extension mechanism | Removing a schema field is a compatibility decision. Small PR, own changelog. |
| Split `test_drift.py` / `test_scaffold.py` | Purely mechanical; do it when no wave is touching them. Wave 6 touches both — schedule after. |
| Rename `scripts/` to a domain name | Renames every entry point and `_bootstrap_lib` path. Own PR, own ADR, after packaging is decided. |
| Split `badger_lib.py` into `catalog.py`/`fingerprint.py`/`versioning.py` | Waves 7 and 8 both touch it. Schedule after both. |
| gitleaks/trufflehog in CI | New external CI dependency plus an initial finding backlog. Separate task. |

## Definition of done, per wave

1. The wave's TDD entry-point test was written first and observed failing.
2. All gates green: `pytest -q`, `node --test "tests/js/*.test.mjs"`, `pylint` (scripts) at
   10.00, `index_build --check`, `validate --all`, `version_sync --check`,
   `sync_plugin_skills --check`, `release_guard`, `tdd_guard`.
3. `VERSION` bumped and a changelog entry added (`.ai-badger/invariants/`, non-negotiable).
4. One PR, merged, **then tagged** `ai-badger--v{version}` — the step whose 32 consecutive
   omissions are recorded in `docs/incidents/2026-07-27-untagged-releases.md`.
