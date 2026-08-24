All context gathered. Here is the plan.

---

# Implementation Plan — consolidate-stack-skills

**Repo:** `/Users/arasz/RiderProjects/ai-badger`, worktree `.ai-badger/worktrees/consolidate-stack-skills`, branch `task/consolidate-stack-skills`.
**Basis:** research record at that worktree root; ADR-0010/0015/0018; current source read directly (`gates/skills_lint.py`, `engine/badger_lib.py` `SKILL_GROUPS`/`expand_skill_groups`/`index_build.py` scope derivation, `tests/test_sync_plugin_skills.py::TestCatalogRouting`, `tests/test_skill_groups.py`, `tests/test_docs_match_the_catalog.py`).

## 0. Verified pre-flight facts (evidence, cited)

These were checked, not assumed; the implementing lanes may rely on them but should re-run the two greps as step 0 acceptance.

| Fact | Evidence |
|---|---|
| None of the 14 absorbed skills is hook-backed | `find features/dotnet/skills … -iname "*hook*"` → no hook dirs/scripts; the only "hook" hits in dotnet SKILL.mds are prose about .NET hook pipelines (`dotnet-bdd-testing:107,124`, `dotnet-mcp-server:248`, `dotnet-system-commandline:47,97`). Docs trio have no `hooks/` and appear in `docs/skills.md`'s "Invoked how" column as "by name". Hook-backed set remains prompt-markers, commit-reminder, auto-wm, mcp-index — none absorbed. **Gate:** re-run the two greps; paste output in the task notes. |
| `SKILL_GROUPS` has two entries | `engine/badger_lib.py:111-116`: `"documentation"` (the trio) and `"testing"` (design-tests + review-tests). Only `documentation` is affected; `testing` is untouched. |
| Routing test reads index.json, not the tree | `tests/test_sync_plugin_skills.py:287-301` checks every *indexed* common skill declares a valid scope. Moving inner skills out of index reach does not fail it; the gateway must declare `scope:` like any common skill. |
| Duplicate-name test | `tests/test_skill_scope_declarations.py:52` walks level-1 stack dirs. `dotnet-workload` and `documentation` collide with nothing today. |
| docs/skills.md pinned numbers | Regexes at `tests/test_docs_match_the_catalog.py:20-23` pin: catalog total, common total, default count, optIn count. Today 43 / 42 / 20 / 22; 58 total `SKILL.md` files. |
| drift.py scope consumer | `features/common/skills/welcome-ai-badger/scripts/drift.py` reads `item.get("scope")` from `index.json`; `tooling/index_build.py:62-64` writes `scope` only when `skill_scope_in()` returns one. Shape unchanged → consumer survives untouched. |
| Plugin shipping surface | `sync_plugin_skills.py` ships **default**-scope common skills + claude stack. The trio are `optIn`; dotnet skills are stack-local. Neither is in the plugin copy today, so `--check` breaks only via the index/catalog derivations, not the copied tree. |
| Sibling citations survive the move | The docs trio cite each other via `../<sibling>/…`. Inside `references/` they remain siblings (`references/scaffold-documentation/`, `references/update-documentation/`, …), so relative links still resolve. |

## 1. Design decisions this plan implements (owner-ruled, restated for the lanes)

1. **Move is whole-directory**: `git mv features/dotnet/skills/<skill> features/dotnet/skills/dotnet-workload/references/<skill>` (11×), and likewise the docs trio into `features/common/skills/documentation/references/<skill>` (3×). Inner `SKILL.md` files are edited **only** where they contain relative paths that break (expected: none — see fact above; verify with a link check).
2. **Manifest**: `<gateway>/manifest.json`, `{ "kind": "gateway", "members": [ { "name", "purpose", "triggers": [], "paths": { "skill", "scripts?", "references?" } } ] }`. Gateway `SKILL.md` is short: routing table of *when to open which member* lives in the manifest, not the body; body explains how to read `manifest.json` and carries the mandatory `## Gotchas` section (lint rule 9 applies to the gateway too).
3. **Two gateways only**: `dotnet-workload` (already exists as a registered dotnet skill — verify: it is listed in `docs/skills.md` prose as one of the 15; confirm on disk) absorbs the 11; `documentation` absorbs the trio and keeps the name.
4. **Gateway kind lives in manifest.json**, not frontmatter. `skills_lint` derives gateway-ness from the presence of a parseable `manifest.json` in a level-1 skill dir — no new frontmatter key, no second registry (ADR-0018).

## 2. Section breakdown

### S-A — Test design (before any production change)

See §3 below. Deliverable of this section: the failing-test list committed as test files (red), reviewed by `review-tests`.

### S-B — `engine/badger_lib.py`: gateway-aware inclusion resolution

- Add `gateway_aliases(features_root) -> Dict[str, str]` (member name → gateway name), **derived by walking `features/*/skills/*/manifest.json`** — never a literal.
- Apply it in the inclusion pipeline right after `expand_skill_groups`: a config naming `update-documentation` resolves to `documentation`. `SKILL_GROUPS["documentation"]` is **deleted**; `"testing"` stays.
- Rationale for alias-over-migration-note: deleting the group means `"documentation"` now names a *real registered skill*, so that config needs no machinery at all. Only stale member names need help, and a silent no-delivery of a named skill is precisely the ADR-0005 failure mode. The alias map costs one directory walk and cannot drift because it is derived. The simpler alternative (migration note + `drift.orphaned` report only) was weighed and rejected; note it in the ADR.
- **Files:** `engine/badger_lib.py`, callers in scaffold/refresh that consume `inclusions()`. **Serialise with S-C** (both are engine-side; small surface, do sequentially to avoid merge noise).

Acceptance: config `{"include":{"skills":["update-documentation"]}}` scaffolds the documentation gateway once (not twice, not zero times); `{"skills":["documentation"]}` scaffolds the same tree byte-for-byte modulo timestamps. Gate: pytest e2e scaffold tests (§3 rows T8–T9) via `.venv/bin/python3 -m pytest -q`.

### S-C — `gates/skills_lint.py`: rule 13 (gateway manifest validation)

New rule, derived purely from disk state:

- Any level-1 skill dir containing `manifest.json` is a gateway candidate. Manifest must parse as JSON, carry `kind: "gateway"`, and validate structurally: non-empty `members`, each with `name`, `purpose`, non-empty `triggers`, `paths.skill` pointing at an existing `references/<name>/SKILL.md`; optional `paths.scripts`/`paths.references` must exist if declared.
- Every directory under `<gateway>/references/` must be named by exactly one member entry (**orphan detection**).
- Member `name` values must be unique within the manifest and must match their directory name under `references/` (reuses rule 2's spirit).
- The gateway's own `SKILL.md` stays under all eight existing rules — assert this explicitly in a test (remove a frontmatter key from the gateway in a fixture → rule 10 fires), pinning ADR-0018's revisit-condition-2 concern.
- Numbering: append as **rule 13**; update the module docstring ("twelve conventions" → thirteen).

**Files:** `gates/skills_lint.py` only (self-contained; reads manifest.json directly, no badger_lib dependency → **parallel-safe with S-B** despite both being Python; different files).

Acceptance: fixture-based tests red→green per §3 T1–T4; `python3 gates/skills_lint.py` exits 0 on the converted catalog and prints the new checked-file count.

### S-D — Move the 11 dotnet skills (mechanical)

- Write `dotnet-workload/manifest.json` (11 members; purpose = one line distilled from each member's frontmatter description; triggers = keywords from each description — this is the ADR-0015 mechanism: the *gateway's aggregated trigger surface* is what discovery matches on).
- Rewrite `dotnet-workload/SKILL.md` to short router form (must satisfy rules 1–12: `Use when…` description ≤1024 chars, gotchas section, references/-mention conditions per rule 8).
- `git mv` the 11 dirs under `references/`. Delete nothing else.

**Parallel-safe with S-E's file moves**; shares docs/index edits with S-E → the *doc-and-index tail* is done once, in S-F.

Acceptance: `ls features/dotnet/skills` shows exactly `dotnet-workload`; `python3 gates/skills_lint.py` green; `git status` shows renames (history preserved). Gate: skills_lint + pytest subset.

### S-E — Move the docs trio + SKILL_GROUPS disposition

- `git mv` the three dirs into `features/common/skills/documentation/references/`.
- Rewrite `documentation/SKILL.md` (router form), `scope: optIn` preserved (the trio were opt-in; keeping optIn means the default-shipped set is unchanged — 20 defaults stay 20).
- Delete `SKILL_GROUPS["documentation"]` (done in S-B; this section is its on-catalog counterpart).
- Update `tests/test_skill_groups.py`: the documentation-group classes lose their subject; replace with gateway-alias tests. The sibling-citation test's `_catalog_skills` walks level-1 only — inner skills leave its reach; accept and note in the ADR (their mutual citations are instead covered by manifest validation: every member exists).

**Serialise with S-B** (same conceptual unit; S-B's tests reference this layout).

### S-F — Shared tail: index regeneration, tooling, plugin sync

Serialised after S-D **and** S-E (single owner):

1. Regenerate `index.json`: `.venv/bin/python3 tooling/index_build.py` — expect dotnet stack to list 1 skill, common to list 39.
2. Run `.venv/bin/python3 tooling/sync_plugin_skills.py --check` — expected clean (neither trio nor dotnet skills ship in the plugin copy); if not, diagnose before proceeding.
3. Confirm `drift.py` untouched; its `item.get("scope")` contract is shape-stable. Existing scaffolded projects will next `den-refresh` report the moved skills under `drift.changed`/`removed` and offer the new config — this is correct behaviour and gets a line in the changelog.

Acceptance: `index_build --check` exit 0; routing test, index-scope test green.

### S-G — Docs + ADR

- **New ADR `docs/adr/0021-gateway-skills.md`**: records the four owner rulings, the alias-vs-note trade-off, the accepted lint-reach narrowing for members and its compensating control (rule 13 orphan detection = the declaration still travels with the bundle), and a revisit condition (if gateway bodies accrete member detail again, the manifest is rotting).
- **`docs/skills.md`**: update the four pinned numbers (43→40 cataloged; 42→39 common; 20 default unchanged; 22→19 optIn; 58→45 total files: 40 + 5 stack-local) and rewrite the SKILL_GROUPS paragraph: groups now exist only for `testing`; `documentation` is a gateway skill, with a worked example of `"skills": ["documentation"]` and of stale-name aliasing. Remove trio rows from the at-a-glance table, add one `documentation` row and (optionally, since the page covers common+claude only) a pointer sentence for `dotnet-workload`.
- **`docs/authoring-a-feature.md`**: add "authoring a gateway" section (manifest schema, when to gateway vs flat).
- Gate: `.venv/bin/python3 -m pytest tests/test_docs_match_the_catalog.py -q` green; docs_guard/link checks green.

### S-H — Version + changelog (repo invariant)

- Bump `VERSION` → **0.137.0** (minor: new capability, breaking to none — configs keep working).
- `docs/changelog/0.137.0-consolidate-stack-skills.md`: what consolidated, the alias behaviour, what a consumer project sees on next `den-refresh`, token win.
- Check `version_sync.py` / plugin manifest version consistency; gate: `changelog_index.py` + full pytest.

## 3. Design-tests (derived from acceptance criteria, BEFORE implementation)

Runner for all: `.venv/bin/python3 -m pytest <file> -q`. Fixtures use synthetic roots (pattern already established by `test_check_mode_ignores_managed_externally`). Oracles: hand-derived from the manifest schema spec'd in §1; red-proof mutations are single mechanical edits.

| # | Test | Targets failure mode | Red-proof mutation |
|---|---|---|---|
| T1 | `test_gateway_without_valid_manifest_fails_lint` (new `tests/test_skills_lint_gateways.py`) | malformed/`kind`-less manifest.json read as a pass | delete `"kind"` key in fixture |
| T2 | `test_manifest_member_path_must_exist` | ghost member path silently routed | rename referenced `references/<x>/` dir |
| T3 | `test_orphan_member_dir_under_references_fails_lint` | skill moved in, manifest forgotten — the silent-disappearance hazard | add stray dir under `references/` |
| T4 | `test_member_name_must_match_directory_and_be_unique` | manifest/disk name split | rename one member entry |
| T5 | `test_gateway_skill_md_is_fully_linted` | assumed lint exemption for gateways | strip `version:` from gateway fixture frontmatter → rule 10 must fire |
| T6 | `test_config_naming_absorbed_member_delivers_gateway_once` (extend `tests/test_skill_groups.py`) | stale config name silently delivers nothing | remove `gateway_aliases` call from inclusion pipeline |
| T7 | `test_group_name_documentation_is_now_a_real_skill` | deleted SKILL_GROUPS entry broke `"skills":["documentation"]` | revert deletion of the group entry → double-delivery/shadowing assertion fails |
| T8 | `test_dotnet_stack_scaffolds_exactly_the_gateway` (e2e, mirrors ADR-0018's three-config proof) | partial move leaves strays or loses references | move one skill back to level 1 |
| T9 | `test_docs_numbers_match_consolidated_catalog` (update `test_docs_match_the_catalog.py` expectations implicitly — it derives from disk; the *mutation* is on the prose side) | stale prose counts | put old number 43 back in docs/skills.md → test red |
| T10 | existing `test_no_skill_name_appears_in_two_stack_directories` must stay green post-move | gateway/member name collision across stacks | plant `documentation/` dir in another stack |
| T11 | existing `test_every_catalog_skill_is_reachable_by_a_declared_route` green with gateway indexed | gateway indexed without valid scope | remove `scope:` from documentation SKILL.md → lint rule 12 + this test both red |

**TDD order:** T1 is written first and watched failing against a fixture gateway (no production rule yet — RED is "rule missing", the right reason). Then T2, T3, T4 drive rule 13 one behaviour at a time (Stage 5: one test, pasted RED, then green). T5 pins the exemption-absence before S-D/E move anything. T6/T7 drive S-B. Only after rules and helpers are green do S-D/S-E perform the moves, turning T8–T11 from red to green on the real catalog.

## 4. Serialization / parallelism map

- **Lane 1 (serial chain):** S-B → S-E → (with S-C done) S-F.
- **Lane 2 (parallel-safe with Lane 1 until S-F):** S-C → S-D.
- **Shared files forcing serialisation:** `docs/skills.md` numbers, `index.json`, `tests/test_skill_groups.py` — all owned by Lane 1 / S-F. `engine/badger_lib.py` touched only by Lane 1; `gates/skills_lint.py` only by Lane 2.
- S-G and S-H strictly last, single commit series (small commits, early draft PR per repo invariant).

## 5. Honest cost accounting

**What breaks (and is fixed in-plan):**
- `tests/test_skill_groups.py` documentation classes (rewritten, T6/T7); `docs/skills.md` four pinned numbers + trio rows; `index.json` regenerated; any external project config naming `scaffold-/update-/migrate-documentation` or expecting 11 flat dotnet skill dirs (handled by derived aliasing + `den-refresh` drift report).
- Lint/citation reach narrows for 14 inner skills: their SKILL.mds leave `skills_lint`'s glob and the sibling-citation scan. Accepted by owner; compensating controls: rule 13's existence+orphan checks (nothing under `references/` can be unaccounted), and the gateway itself remains fully linted (T5).

**What gets simpler:** one registered skill per specialization instead of 11/3; `SKILL_GROUPS` loses its only delivery-shaped entry; consuming agents' discovery surface drops from 14 entries to 2; authoring guidance collapses to "flat skill or gateway".

**Token/context win (estimate, stated as estimate):** the win is on **registration/discovery surfaces**, not body loading — bodies were already lazy. A dotnet-stack scaffold advertises ~11 skill descriptions (~120–180 tokens each) where it will advertise 1 (~150 tokens): roughly **1.2–2k tokens off every consuming agent's system/discovery context**, plus reduced matcher ambiguity among 11 similarly-named dotnet skills. Members' full bodies now load only after the gateway routes to them, which also converts accidental multi-skill loading into deliberate single-member loading.

**Costs that stay:** manifests are one more artifact to keep truthful — mitigated only by rule 13 making lies loud, not by making them impossible; two formats (frontmatter for gateways, manifest for members) is a real duality, justified here because members are deliberately *un*-registered.

---

---

# Revision 2 — post adversarial review (2026-08-24)

Reviewer verdict was needs-revision. All MUST-FIX and accepted SHOULD items are folded in
here; this section amends the sections above where they conflict.

## Amended decisions

R1 (fixes #1). `dotnet-workload` does NOT exist today — S-D CREATES
`features/dotnet/skills/dotnet-workload/` from scratch (SKILL.md router + manifest.json +
11 git-mv'd members). §1.3's existence claim is withdrawn.

R2 (fixes #2). Correct target numbers: common level-1 skills 42 → **40** (−3 trio, +1
gateway); cataloged page scope 43 → **41**; default **20** unchanged; optIn 22 → **20**;
total SKILL.md files 58 → **46** (40 common + 6 stack-local: dotnet-workload, hermes×2,
mcp, ai-raccoon, claude). index.json: common lists 40, dotnet lists 1.

R3 (fixes #3). Extensions travel and stay live: the trio's `extensions/ledger/` fragments
move WITH their member dirs (`documentation/references/<skill>/extensions/`). S-B extends
extension discovery (skill_delivery.py / extensions.py) to additionally enumerate member
extension dirs DERIVED FROM the gateway manifest's member paths — no parallel list. Tests:
one red-first test that a docs.tool project still gets the ledger fragment merged after the
move, and that an unset docs.tool prunes it.

R4 (fixes #4). `inclusion_notes()` becomes alias-aware: takes the alias map as an argument
(same pattern as its existing `defaults` parameter) and reports stale names as
`included 'update-documentation' — resolved to gateway 'documentation'`. Test added: a
config naming a stale member produces that note, never "matches no optIn catalog skill"
(#275 regression guard).

R5 (fixes #13 asymmetry). `exclusions()` applies the same alias map: excluding a stale
member name suppresses the gateway. One test pins it.

R6 (fixes #5). Remove the `REFERENCES_EXEMPT` entry keyed on scaffold-documentation
(gates/skills_lint.py:50-54) in S-E's change set; update
`test_every_references_exemption_still_names_a_line_that_exists` accordingly.

R7 (fixes #6). Update `HARVEST_SAMPLES` paths in tests/test_catalog_has_no_harvest_artifacts.py
to the new `features/dotnet/skills/dotnet-workload/references/<skill>/…` locations.

R8 (fixes #7). Rewrite tests/test_stack_skill_discovery.py's canonical stack-local skill:
`dotnet-mcp-server` → `dotnet-workload`.

R9 (fixes #8, partial). Manifest `purpose` MUST equal the member's frontmatter
`description:` verbatim — rule 13 enforces byte equality (derive-or-delete). `triggers`
stay curated in the manifest (that aggregation is the gateway's reason to exist); rule 13
requires non-empty triggers but does not second-guess their wording.

R10 (fixes #9). T7 re-specified: assert `expand_skill_groups(["documentation"]) ==
{"documentation"}` (group passthrough gone) and that no stale member name survives
expansion. The old mutation-based red proof was unachievable (set-dedup made it green).

R11 (#10). New T12: direct unit test for `gateway_aliases()` — fixture root with two
gateways; a member name claimed by TWO manifests must raise/report loudly (ambiguity is
never silent); manifest-less dirs are ignored.

R12 (fixes #11). Replacement sibling-citation scan: port
`test_each_referenced_sibling_exists` to walk `features/common/skills/documentation/references/*/*/SKILL.md`
so migrate-documentation's file-level citations (`../update-documentation/references/placement.md` etc.)
stay checked. Directory-existence in rule 13 is NOT sufficient compensation.

R13 (fixes #12). tests/test_config_include.py: `OPT_IN_SKILL = "update-documentation"`
→ `"documentation"`.

R14 (#14, serialization safety). The two lanes are SERIALISED into one implementation
sequence in this single worktree — order: TDD red tests (T1–T5, T12) → S-C rule 13 →
S-D moves → S-B+S-E engine/alias/moves → S-F tail → S-G/S-H. No concurrent lanes; the
worktree-agent-isolation concern is moot at concurrency 1.

R15 (fixes #15). Docs policy: S-G runs a repo-wide grep for the 14 moved names; every hit
that carries a PATH is updated; pure-prose mentions in other skills' bodies get updated
only where they would now mislead (naming a skill that no longer registers); the rest are
accepted and listed in the changelog entry. docs/README index files refreshed if they
name the trio rows.

R16 (nits). skills_lint docstring: "twelve conventions" → thirteen (rules), distinct from
rule 10's eight frontmatter keys — wording fixed. research-record line cites corrected to
badger_lib.py:111/119. test_scaffold_empty_skills.py:66 comment refreshed.
test_docs_tree_is_canonical.py docstring sentence refreshed while touching docs.

## Revised acceptance gates

Unchanged from §3 plus: R3's extension merge/prune test, R4's note test, R5's exclusion
test, T12. Final gate remains: full `.venv/bin/python3 -m pytest -q` green in the
worktree, `index_build --check` exit 0, `skills_lint` exit 0 printing the new count,
docs catalog test green against R2's numbers.

## Revised verified facts

None of the 14 absorbed skills is hook-backed; `SKILL_GROUPS` deletion for `documentation`
is safe because the gateway keeps the name as a real registered skill (with R4/R5 making
delivery reporting and exclusions alias-aware); stale member names get manifest-derived
alias resolution (no second registry, per ADR-0018); lint rule 13 derives everything from
disk with R9 pinning purpose to frontmatter description byte-for-byte; pinned docs numbers
land at 41/40/20/20 and 46 files per R2; TDD starts with the gateway-manifest lint test on
a fixture; execution is fully serialised in one worktree per R14 (version 0.137.0,
changelog, ADR-0021 last).