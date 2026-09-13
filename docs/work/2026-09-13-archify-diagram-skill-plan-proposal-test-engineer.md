# Archify diagram skill — test plan (test-engineer lane)

Task `aib-archify-diagram-skill-default-integration`, target `0.171.0`.
Read-only plan. Sources: `docs/work/2026-09-13-archify-diagram-skill-research.md`
(all facts below inherit its MEASURED/READ provenance), plus the test/gate files named
in the brief. Ordering invariant (from `docs/changelog/0.147.0-status-report-skill.md`):
**index first, then self-scaffold** — a stale `index.json` makes the scaffold silently
skip the new skill while the freshness guard still passes.

## Test table (deliverable → test → command → RED → GREEN)

| # | Deliverable | Test file + case | Command | Expected RED (before change) | Expected GREEN (after) |
|---|-------------|------------------|---------|------------------------------|------------------------|
| 1 | Vendored packet integrity + provenance | `tests/test_archify_vendor.py::test_manifest_hashes_match_disk`, `::test_file_set_equals_staged_packet`, `::test_revendor_check_is_clean` | `.venv/bin/python3 -m pytest -q tests/test_archify_vendor.py` | `FileNotFoundError: features/common/skills/archify/vendor.json` / `assert manifest['upstream']['commit'] == 'c826e6c…'`. Independent re-hash with `hashlib`, never the generator's own hash fn | `vendor.json` (`upstream:{repo,tag:v2.16.0,commit:c826e6c…}`, `files:[{path,sha256}]`, `adapted:["SKILL.md"]`, `staged_by`) matches disk; `tooling/vendor_archify.py --check` exit 0 |
| 2 | Adapted SKILL.md passes lint 1–13 | `tests/test_archify_vendor.py::test_skill_md_passes_lint` — calls `gates/skills_lint.py::skills_lint(root)`, filters `archify` | `.venv/bin/python3 -m pytest -q tests/test_archify_vendor.py -k lint` + `python3 gates/skills_lint.py` | `rule 5: description must start with 'Use when'` / `rule 9: no '## Gotchas'` / `rule 10: missing frontmatter keys` / `rule 8: references/ mention … has no … condition` | lint returns `[]` for archify; gate prints `ok skills lint — N SKILL.md checked` |
| 3 | Exemptions necessary + well-formed | Reuse `tests/test_catalog_claims_checkable.py::test_every_feature_json_exemption_matches_a_file_that_exists`, `::test_every_feature_json_exemption_states_a_reason`, `::test_a_new_unschemad_json_under_features_is_a_violation` + new `test_each_archify_exemption_is_necessary` (delete-one-pattern → `unschemad_feature_json` non-empty) | `.venv/bin/python3 -m pytest -q tests/test_catalog_claims_checkable.py tests/test_archify_vendor.py -k "exemption or unschemad"` | `unschemad_feature_json == ['…/archify/examples/….json', …]` (no exemption) / `thin == {pattern: reason<30}` / `inert == [overbroad pattern]` | `unschemad_feature_json(root) == []`; every new pattern matches ≥1 file, reason ≥30 chars, and deleting any one pattern re-reddens |
| 4 | `system` ecosystem in dependency_check | Extend `tests/test_dependency_check.py`: `TestSystemEcosystem::test_present_detected_via_which`, `::test_absent_without_consent_hints_mermaid_fallback`, `::test_absent_with_consent_and_command_runs_command`, `::test_absent_with_consent_and_no_command_never_installs`, `::test_node_regression_npm_g_node_untouched`, `::test_nothing_runs_without_consent` (matrix below) | `.venv/bin/python3 -m pytest -q tests/test_dependency_check.py -k system` | `unknown ecosystem 'system'` (current `run_dependency_check` else-branch, `dependency_check.py`) | Matrix GREEN; `shutil.which` is the only detector; no `npm install -g node` path |
| 5 | E2E scaffolded copy runs | `tests/test_archify_scaffold.py::test_fixture_receives_archify_and_doctor_passes` — scaffold minimal fixture (index-then-scaffold), assert `.ai-badger/skills/archify/bin/archify.mjs` present, run `node bin/archify.mjs doctor` from the **delivered copy** | `.venv/bin/python3 -m pytest -q tests/test_archify_scaffold.py` (needs `node>=18`; skip — not pass — when absent) | `AssertionError: archify/ not scaffolded` / `doctor rc != 0` on a stub copy | scaffolded `archify/` present; `doctor` rc 0 (rc 2 = visual-skipped-no-Chrome still GREEN, asserted explicitly) |
| 6 | Docs + count drift | Existing `tests/test_docs_match_the_catalog.py` (row, Ships cell, 4 counts), `::TestScriptsDocCoversTheScripts` (new `tooling/vendor_archify.py` row in `docs/scripts.md`), `tests/test_expected_skill_names.py::test_derived_set_equals_the_manifest_rows_on_this_repo` (48→49) | `.venv/bin/python3 -m pytest -q tests/test_docs_match_the_catalog.py tests/test_expected_skill_names.py` | `undocumented: archify` / `catalogs 47 skills != 48` / `default 44 != 45` / `len(derived) == 48 != 49` / `docs/scripts.md omits tooling/: vendor_archify.py` | Row `\| [archify](#archify) \| … \| default \|` + counts +1 (catalog/common/default; optIn unchanged); scripts row; count 49 |
| 7 | Invariant lands within budget | `tests/test_archify_invariant.py::test_invariant_in_assembled_claude_md`, `::test_agent_docs_budget_holds` — read `features/common/invariants/*.md`, assert the sentence in assembled `CLAUDE.md`, assert `lines ≤ 260` and `chars ≤ 17500` from `.ai-badger/config.json agentDocs` | `.venv/bin/python3 -m pytest -q tests/test_archify_invariant.py` | `assert 'archify' in claude_md` fails (invariant written but never assembled) | Line present in `CLAUDE.md` (+ `HERMES.md`/copilot as routed); `224+1 lines`, chars under cap |

### Deliverable 4 — case matrix (all with `subprocess.run` patched; `shutil.which` stubbed)

| Case | which(node) | allow_install | declared `command` | Expect |
|------|-------------|---------------|--------------------|--------|
| present | path | either | either | `already_present`, zero `subprocess.run` calls |
| absent, no consent | None | False | either | hint containing `node`, `Mermaid`, `--execute`; zero calls |
| absent, consent + command | None | True | `node bin/archify.mjs doctor` | command runs once, `installed` |
| absent, consent, no command | None | True | — | hint/error, **never** `npm install -g node`; zero install calls |
| node-eco regression | n/a | True | n/a | existing `test_node_ecosystem_uses_npx` still GREEN |
| consent gate | n/a | False | n/a | `TestInstallConsent`-style: `mock_run.assert_not_called()` |

Proposed `dependencies.json` entry shape: `{feature: archify, ecosystem: system,
package: node, command: "node bin/archify.mjs doctor", note: "…Mermaid fallback…"}` —
`system` = detect via `shutil.which`, install **only** when `command` is declared **and**
`--execute` passed. Schema already allows `system` + `command`; only the implementation
and the entry are new.

### Manifest schema (proposed `features/common/skills/archify/vendor.json`)

```jsonc
{"upstream": {"repo": "https://github.com/tt-a1i/archify", "tag": "v2.16.0",
  "commit": "c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de", "staged_by": "scripts/build-zip.sh"},
 "files": [{"path": "bin/archify.mjs", "sha256": "…"}],
 "adapted": ["SKILL.md"], "generator": "tooling/vendor_archify.py"}
```

## Honesty note (1): what the offline test can and cannot prove

- CAN prove: internal consistency — every file on disk matches its recorded sha256;
  file set equals the canonical staged packet minus exactly `adapted`; `SKILL.md` is the
  only adapted file; `--check` is clean; no network touched.
- CANNOT prove offline: that the bytes are upstream v2.16.0 at all. A recorded hash
  re-checked against itself goes green for a forged packet too. The falsifiable half is a
  networked re-vendor (`tooling/vendor_archify.py --refresh`, maintainer-run / CI job with
  network) that re-fetches tag v2.16.0 and diffs; the offline gate pins drift, not origin.
  The plan must ship both, labelled as such — otherwise (1) is tautological.

## Tautology audit (falsifiable alternative for each trap)

- `vendor.json` hashes match disk: TAUTOLOGICAL if the same helper writes and reads.
  Fix: test re-hashes with stdlib `hashlib` directly and asserts the upstream commit pin
  equals the literal `c826e6c…`, not `manifest['upstream']['commit']`.
- Exemption "matches ≥1 file": passes vacuously with `features/common/skills/archify/*`.
  Fix: necessity test (delete each new pattern → `unschemad_feature_json` non-empty) plus
  narrow patterns per family (`examples/*.json`, `schemas/*.schema.json`, `vendor.json`).
- Docs counts: TAUTOLOGICAL if the test imports the same helper production uses to render
  the counts. Fix: existing `test_docs_match_the_catalog.py` derives from `SKILL.md`
  frontmatter via `badger_lib.skill_scope_in` (routing source of truth, ADR-0018) while
  prose numerals are literals — keep that split, never compute expected from the doc.
- `doctor` passes: vacuous when run from the source tree instead of the delivered copy, or
  when node is missing and the test passes on skip. Fix: run from the scaffolded
  `.ai-badger/skills/archify/` copy; `pytest.skip` (not pass) when `node<18`/absent.

## Half-done failure modes (existing tests that go red if the plan stops halfway)

- Skill dir without index rebuild: `test_derived_set_equals_the_manifest_rows_on_this_repo`
  (`48 != 49`), `gates/scaffold_freshness_guard.py` (delivered tree ≠ re-scaffold).
- Index rebuilt, self-scaffold skipped: `test_no_catalog_skill_is_undocumented`,
  `tooling/sync_plugin_skills.py --check` (pointer `SKILL.md` + `SKILL.full.md` missing).
- Vendored JSON without exemption: `test_every_json_under_features_is_schemad_or_exempt_by_name`.
- Exemption added but overbroad/unreasoned: `…_exemption_matches_a_file_that_exists`,
  `…_exemption_states_a_reason` (≥30 chars).
- SKILL.md adapted but lint-blind: `python3 gates/skills_lint.py` rules 2 (dir match),
  5 (`Use when`), 8 (references condition window), 9 (Gotchas), 10 (frontmatter keys +
  `scope: default`), 12 (common scope).
- `system` entry without implementation: every new `TestSystemEcosystem` case +
  `unknown ecosystem 'system'` in errors; without the entry, `detect_new_deps` blind spot.
- Docs/counts untouched: the four `TestSkillsDocCountsAreDerived` cases, `test_the_check_sees_the_whole_table`,
  `TestScriptsDocCoversTheScripts`, `tests/test_expected_skill_names.py` pin.
- Invariant written but not assembled, or budget blown: new invariant tests;
  `tooling/version_sync.py --check`, `gates/release_guard.py` (no `VERSION` bump +
  `docs/changelog/0.171.0-*.md` + `changelog_index --check`), `gates/deps_guard.py`.

## Test-run economy (per `.ai-badger/invariants/test-run-economy.md`)

- LOCALLY in one pass: the three new/extend files + directly consuming suites —
  `test_archify_vendor`, `test_archify_scaffold`, `test_archify_invariant`,
  `test_dependency_check`, `test_catalog_claims_checkable`, `test_docs_match_the_catalog`,
  `test_expected_skill_names` — plus `tooling/validate.py --all`,
  `gates/skills_lint.py`, `sync_plugin_skills.py --check`, `scaffold_freshness_guard.py`.
- CI owns the rest: full `pytest -q`, `pylint`, `journey`/`consumer_journey.py`,
  `tdd`, `js`/`pi-ts` lanes via `.lefthook/pre-push/verify.sh` (`LOCAL_LANES` vs
  `CI_ONLY_LANES=pylint pytest journey`). No local full-suite repeat; no mutation lane
  (retrieval-only, hand-run).
