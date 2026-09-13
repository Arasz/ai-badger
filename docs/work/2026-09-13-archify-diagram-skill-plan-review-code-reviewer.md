# archify diagram skill — plan review (code-reviewer lane)

Task `aib-archify-diagram-skill-default-integration`, version 0.171.0. Read-only review of
`docs/work/2026-09-13-archify-diagram-skill-plan.md` against the tree; every claim below carries
the command that produced its output. All Python ran through the main checkout's `.venv/bin/python3`
from this worktree; the git worktree is clean (`git status --porcelain` shows only other lanes'
untracked review files).

## Question verdicts

1. **Counts, paths, ownership.** The arithmetic is right: `features/common` holds 46 skills
   (44 `default`, 2 `optIn`), the catalog totals 47, `features/*/skills/*/SKILL.md` matches 53, and
   `tests/test_expected_skill_names.py` pins `len(derived) == 48`. So 47→48 / 46→47 / 44→45,
   48→49, 53→54 are all correct. Gateway members are indeed below `skills_lint`'s reach
   (`SKILLS_GLOB = "features/*/skills/*/SKILL.md"`, one level). The `FEATURE_JSON_WITHOUT_SCHEMA`
   necessity-test claim is a valid strengthening (mechanism verified) but under-specified — F8.
   The ownership claim has a real hole: PKG-2 owns a delivered script and no mirror step — F1.
2. **Package split.** PKG-1 and PKG-3 touch no shared source file and both self-scaffold; in the
   parallel wave PKG-2 and PKG-3 touch disjoint sources as written. But PKG-2 edits
   `dependency_check.py`, which ships byte-identically into `skills/` and `.ai-badger/skills/`;
   with no sync/scaffold step, two repo gates go red on the merged tree — F1 (MUST). PKG-1's and
   PKG-3's self-scaffold steps are sufficient for their own paths.
3. **Vacuous criteria.** 3a's `grep -c "Archify"` gate is the clear one — F6 (SHOULD); 2b's
   "scaffold note names the fallback" and 3b's "name archify first" have no named gate — F7
   (SHOULD); 4a's "watched red" is a process claim, acceptable per the repo's TDD invariant.
   2a's "no `subprocess.run` call without consent" is not vacuous but contradicts its own node<18
   probe — F5 (SHOULD).
4. **Task clause.** `engine/frontmatter.py` measures the task body at 19,858 chars → proxy 4,964.5,
   headroom 142 chars to the 5,000 cap. A 120–130-char clause fits without trimming; if wording
   runs longer, trim `Parallelism has to be designed in; it does not arrive on its own.` (66 chars,
   line 224) — a flourish, not a procedure. The clause is possible; the invariant-only fallback
   need not be used.
5. **Budget.** The three-copy working-tree claim holds (two full copies from scaffold/sync plus the
   plugin copy ≈ 3 × 5,888,015 B ≈ 17.7 MB; `.claude/skills` and `.github/skills` are symlinks,
   not copies). The 5–6 MB pack-growth claim is wrong: the copies are byte-identical, git stores
   one blob set, and zlib(6) over the 76 unique files is 1,144,408 B (asset zip 1,318,273 B) —
   F4 (SHOULD). Manifest cost is one skill entry, negligible; the freshness guard already re-hashes
   this tree in 1.3 s at 2,358 paths.
6. **Gates left out.** Two gates fail on this branch as planned: `tests/test_docs_tree_is_canonical.py`
   (the plan's own five work records are unindexed — F2, MUST) and, once
   `tooling/vendor_archify.py` is tracked, `tests/test_every_check_can_fail.py` (F3, MUST). Also
   unstated: the six-line cap on common invariants (`tests/test_invariant_catalog.py`, F6) and the
   `version_sync.py` write step (F11, NOTE).

## Findings

| id | severity | claim | evidence (command → output) | proposed plan patch |
|----|----------|-------|-----------------------------|---------------------|
| F1 | MUST | PKG-2 edits the delivered `features/common/skills/welcome-ai-badger/scripts/dependency_check.py` but neither syncs the plugin copy nor re-scaffolds `.ai-badger/`; the plan's per-package self-scaffold list names only PKG-1 1c and PKG-3 3d, so the merged tree fails repo gates until PKG-4's join. | `cmp` of the three copies → all byte-identical; `git ls-tree HEAD features/... skills/... .ai-badger/...` → same blob `f0a0fe7ad820b4a56946d7ba6e3ba18f0974621e`; `check_skill(<features copy>, skills/welcome-ai-badger)` → `None` (in sync), `check_skill(<same copy + one appended line>, dest)` → `diverged`; `sync_plugin_skills.py --check` now → `45 skill(s) in sync`. `scaffold_freshness_guard` re-runs the real scaffolder and would classify the stale mirror as `stale`. | In 2a add: after the script edit, run `tooling/index_build.py`, `tooling/sync_plugin_skills.py`, then the self-scaffold, and list `gates/scaffold_freshness_guard.py` + `sync_plugin_skills.py --check` in PKG-2's gates; serialise PKG-2 after PKG-3 so only one lane writes the mirrors. (Alternative: keep PKG-2 parallel and make PKG-4 4b's final sync+scaffold the explicit owner of this mirror, dropping any “every package leaves the tree green” claim.) |
| F2 | MUST | The plan's own five `docs/work/2026-09-13-archify-*` records are not named in `docs/work/README.md`; no package includes that file, so the branch is red now and stays red after implementation. | `.venv/bin/python3 -m pytest "tests/test_docs_tree_is_canonical.py::TestEveryMapIsComplete::test_a_directory_readme_names_every_file_beside_it[work]" -q` → `AssertionError: docs/work/README.md omits: 2026-09-13-archify-diagram-skill-plan-proposal-api-engineer.md, …-proposal-architect.md, …-proposal-test-engineer.md, …-plan.md, …-research.md`; `1 failed`. | In PKG-1 1c (or a pre-step) add rows to `docs/work/README.md` for every `2026-09-13-archify-*` record committed by the PR — including this review and the other lanes' reviews — and add `tests/test_docs_tree_is_canonical.py` to the local test list. |
| F3 | MUST | `tooling/vendor_archify.py --check` is mechanically discovered by `tests/test_every_check_can_fail.py`; without a `REGISTRY` provocation the suite fails once the file is tracked. The plan never mentions the meta-test. | Loaded the module and simulated: `_declares_check_flag('ap.add_argument("--check", …)')` → `True`; `discovered_checks(root)` → 23 checks, `unproven == []` today; adding `tooling/vendor_archify.py --check` to the set → `unproven == ['tooling/vendor_archify.py --check']`; `test_every_check_has_a_provocation` asserts `unproven == []`. | In 1b add a `Provocation("tooling/vendor_archify.py --check", …)` to `tests/test_every_check_can_fail.py` (tmp vendored tree: one corrupted hash → exit 1 with `CHANGED`; the same fixture clean → exit 0) and list that test file in PKG-1's owns and gate list. |
| F4 | SHOULD | The ADR/risk arithmetic overstates pack growth at ~5–6 MB. The three copies are byte-identical, so git stores one blob set; growth is ≈ one compressed copy. | `git ls-tree HEAD` for the three `dependency_check.py` copies → one blob SHA; `zlib.compress` at level 6 over the 76 packet files → 1,144,408 B; v2.16.0 release asset → 1,318,273 B; uncompressed packet → 5,888,015 B; `working tree` count of full copies → 3. `.claude/skills/*` and `.github/skills/*` are mode-`120000` symlinks (e.g. blob `e3564d5c…`), so they add no copy. | Reword the ADR consequence/risk: “~17.7 MB working tree; pack growth ≈ the packet's compressed size (~1.1–1.5 MB) because `features/`, `skills/` and `.ai-badger/` share blobs.” Keep the 17.6 MB working-tree number. |
| F5 | SHOULD | 2a's AC is internally unsatisfiable: it demands `node <18` detection (a `node --version` probe) and “no `subprocess.run` call without consent” in the same report-mode matrix; the test-engineer matrix even says “zero `subprocess.run` calls”. | Plan Ruling 4 / 2a: “plus `node --version` major ≥ 18 for the archify entry's floor” vs “no `subprocess.run` call without consent”; current `dependency_check.py` does `if not allow_install: hints.append(...); continue` (no detection at all today); the api-engineer acceptance runs `node --version` in report mode. | Pin the probe: report mode may exec only the fixed `[package, "--version"]` argv (`shell=False`, read-only) and must run no install command; reword the AC to “no install command (npm/pip/declared `command`) runs without `allow_install`” and align the case matrix. Stub the probe in tests so they do not depend on a host node. |
| F6 | SHOULD | 3a's acceptance is not a check: `grep -c "Archify"` cannot prove the default/fallback rule landed, cannot prove “once”, and inspects only 2 of the assembled agent files. The architect proposal's “≤ ~8 lines” would also break the repo's six-line cap. | `tests/test_invariant_catalog.py` defines the real contract: `title` + `→ .ai-badger/invariants/<name>.md` inside `## Non-negotiable invariants`, `test_every_common_invariant_is_at_most_six_lines` (>6 lines fails), one heading on line 1. Measured: 31 invariants today; `CLAUDE.md` = 224 lines, budget 260/17500. | Replace the grep gate with a test (extend `tests/test_archify_invariant.py`): assert the invariant's first body sentence and the Mermaid fallback phrase appear in the invariants section of every assembled agent file (`CLAUDE.md`, `.ai-badger/CLAUDE.md`, `HERMES.md`, `.hermes.md`, `.github/copilot-instructions.md`, `.pi/AGENTS.override.md`), plus the ≤6-line/one-heading caps. |
| F7 | SHOULD | 2b's “scaffold note names the fallback” and 3b's “both name archify first and Mermaid as the fallback” have no named gate; the only named commands are a direct `dependency_check` run and a `git diff --stat`. | Plan 2b/3b ACs (lines ~103, ~124); `tests/test_dependency_check.py` has no hint-text assertion for a system entry; no test reads the two member bodies' ordering. (Members are outside `skills_lint`'s glob and outside `tests/test_skill_docs.py`'s `*/SKILL.md`, confirmed by reading both.) | Name the tests: in `tests/test_dependency_check.py` assert the report-mode hint contains `Node` + `Mermaid`; in the planned `tests/test_archify_integration.py` assert `archify` precedes `Mermaid` in the edited member bodies (e.g. the mandate sentence). |
| F8 | SHOULD | The necessity-test requirement is right in intent but under-specified: no existing test checks necessity, and a delete-one-pattern test passes vacuously if patterns overlap; the plan's shorthand patterns (`schemas/*.json`) are not the actual roots. | `tests/test_catalog_claims_checkable.py` only checks “matches ≥1 file” and “reason ≥30 chars”. In-memory demo: `v.unschemad_feature_json(root)` → `[]`; after `pop('features/*/skills/review-tests/rules.json')` → `['features/common/skills/review-tests/rules.json: matched by no schema …']`, so the mechanism works. Packet scan: 23 JSON files, none matched by an existing pattern, all covered by the six proposed families (+ `vendor.json`). | In 1c state the exact globs (`features/*/skills/*/{schemas,examples,brand-marks}/*.json`, `…/package.json`, `…/skill-release.json`, `…/vendor.json`), name the test file that carries the delete-one-pattern test (e.g. `tests/test_archify_vendor.py`), and require one narrow, mutually disjoint pattern per family. |
| F9 | NOTE | The “These 43”/“53 files” corrections have no stated targets. Right values after the change: the page total becomes 48 and the glob 54 (pre-change 47/53), consistent with the plan's own count list; the docs test enforces only 47→48, 46→47, 44→45. | `docs/skills.md` lines 3–19; `test_docs_match_the_catalog.py` regexes `catalogs (\d+) skills`, `(\d+) live under…`, `\*\*(\d+) are \`default\`\*\*`, `\*\*(\d+) are \`optIn\`\*\*`; measured 53 glob matches with `Counter({'common': 46, 'hermes': 2, …})`. | Spell the targets in 1c: “These 43” → 48 and the tree sentence 53 → 54 (as the architect proposal already does). |
| F10 | SHOULD | The plan's task-clause claim is correct but the budget is stated as “~140”; the exact cap headroom is 142 chars, and the fallback trim is unnamed. | `frontmatter.split(task/SKILL.md).body` → 19,858 chars, proxy 4,964.5, headroom `20000 − 19858 = 142`; rule 7 fails only on `proxy > 5000`. | State the exact cap (≤142 chars net) and name the trim: `Parallelism has to be designed in; it does not arrive on its own.` (66 chars, Phase 2 step 1) if a longer clause is preferred. |
| F11 | NOTE | `version_sync.py --check` is gated, but the writer that bumps `.claude-plugin/plugin.json` / `marketplace.json` is never named in 1c; the 0.166.0 precedent ran it explicitly. Also, `scaffold.py` labels every hint “optional dependency:”, now false for a required `system` dep; relabelling would make `scaffold.py` another delivered script subject to F1. | `git show 7a751008 --stat` lists `VERSION`, `.claude-plugin/plugin.json`, `marketplace.json`, model-groups, mirrors; `grep version_sync` finds no caller in the scaffolder; `scaffold.py:569` appends `f"optional dependency: {hint}"` for hints. | In 1c add “run `python3 tooling/version_sync.py` after bumping `VERSION`”; decide the label in 2b and, if changed, fold the `scaffold.py` edit into the F1 sync/scaffold step. |

## Verdict

Implementation may **not** start on the plan as written: three MUST findings are repo-gate
breakers — F2 is red on the current branch already, and F3 turns red the moment the new tool is
tracked.
F2 is a one-table-row fix, F3 is one `REGISTRY` entry, and F1 is a two-line addition to PKG-2's
steps plus a serialisation edge; none changes the feature or its shape. The SHOULD findings
(F4–F8, F10) are wording and test-definition corrections that can be folded into the plan in one
edit pass — notably the pack-growth number, the consent/probe contradiction, and replacing three
unbacked acceptance strings with named tests. The feature itself is feasible and well-evidenced:
the packet/sha/doctor/deliver chain, the count arithmetic, the lint headroom, and the members'
lint blindness were all re-measured and hold. Fold F1–F3 into the plan (and F4–F8, F10 while the
file is open), then dispatch.
