# archify diagram skill — QA test-quality lane (0.171.0, HEAD b4cea01d)

Target: the new/changed tests in `git diff f9c6f287...HEAD -- tests/ tests/js/`:
`tests/test_archify_vendor.py` (17), `tests/test_archify_integration.py` (7),
`tests/js/archify_packet.test.mjs` (3), `tests/test_dependency_check.py` (+9),
`tests/test_every_check_can_fail.py` (+1 REGISTRY entry = +2 runs),
`tests/test_docs_match_the_catalog.py` (+3), `tests/test_invariant_catalog.py` (+2),
`tests/test_expected_skill_names.py` (count edit). Method: `review-tests` walk, pass 0→8.
Out of scope: production security, layering and performance — only test quality is judged.

## What I ran (all commands from the worktree, `.venv/bin/python3` = main checkout venv)

| command | result |
|---|---|
| `pytest tests/test_archify_vendor.py -q` | `17 passed in 1.64s` |
| `pytest tests/test_archify_integration.py -q` | `7 passed in 4.94s` |
| `pytest tests/test_dependency_check.py tests/test_docs_match_the_catalog.py tests/test_invariant_catalog.py tests/test_expected_skill_names.py -q` | `74 passed in 10.94s` |
| `pytest tests/test_every_check_can_fail.py -k vendor -q` | `2 passed` |
| `node --test tests/js/archify_packet.test.mjs` | `pass 3, fail 0` (475 ms) |
| `CI=1 PATH=/usr/bin:/bin pytest tests/test_archify_integration.py -q` (no node) | `3 failed, 4 passed` — the CI-fail branch behaves; **no test asserts it** (F6) |
| `PATH=/usr/bin:/bin pytest tests/test_archify_integration.py -q` (no node, no CI) | `4 passed, 3 skipped` |

## What the suite does well

- The vendor oracles are independent: disk `rglob`, literal counts (76/75), `hashlib`, literal
  split — not the manifest or the tool recomputing themselves. The QA-1/QA-2/QA-3 findings were
  genuinely folded.
- The forged zip + forged manifest test is the strongest assertion on the branch; the sha anchor
  is proven, not asserted (P1 below).
- The meta-gate provocation makes `--check` fail for real, and the clean-fixture half rejects a
  degenerate provocation.
- Determinism is clean: pinned `GENERATED_AT`, tmp paths, no sleeps, no wall-clock, no retries.

## Findings

Severity: blocker = suite gives false confidence / major = a real regression will be missed /
minor = diagnosis cost or drift. `run?` = mutation applied and reverted, suite re-run.

| id | sev | location | rule | claim (surviving mutation, where run) | smallest improvement |
|---|---|---|---|---|---|
| F1 | major | `tests/test_archify_vendor.py:369`; `tooling/vendor_archify.py:347-367,445-451` | T1-STR-02, T1-ORC-06 | The clean/committed-target branch and the extras-preservation block are never reached: the happy path (343) uses a *nonexistent* target, the dirty test only dirties one. M13 `return bool(proc.stdout.strip())` → `return True` survived (17 passed); M6 `if target.is_dir() and False` survived (17 passed). A regression that refuses every re-vendor over a clean worktree, or silently drops `VENDOR.md`/`THIRD_PARTY_NOTICES.md`, is invisible. | One test: git-init a target, commit the synthetic packet, pre-write both extra files with sentinel bytes, re-vendor, assert rc 0 and both files byte-preserved. Kills M13 and M6. |
| F2 | major | `tooling/vendor_archify.py:317,330-339`; `tests/test_archify_vendor.py:369` | T1-SCO-05 | The `stage_zip` refusal matrix is unproven — only the symlink refusal is tested. Survivors: M1 (the backslash/colon guard removed), M2 (`".."` check removed), M8 (packet-shape guard), M9 (duplicate entry), M10 (one-top-dir layout) — each 17 passed. Zip-slip and malformed-zip guards can regress silently. | One parametrized test over hostile keys `evil\name.txt`, `C:evil.txt`, `../escape.txt` via `_synthetic_zip`, plus a small table for missing `SKILL.md`/`package.json`, duplicate name, two top dirs; each asserts rc 2 and the tree untouched. |
| F3 | major | `tooling/vendor_archify.py:366-367` | T1-SCO-05 | The git-unavailable `VendorError` is unproven: M3 `except OSError as exc: raise VendorError(...)` → `return False` survived (17 passed). Retained, that mutant skips the dirty check on a git-less host and `replace_tree` can discard uncommitted work — the exact outcome the guard exists to prevent. | Run the CLI with `env` PATH="" against an existing target; assert rc 2 and `git unavailable` in the output. |
| F4 | major | `tooling/vendor_archify.py:389-399,477-484` | T1-ORC-06 | `_staging_parent`'s nearest-existing-ancestor contract and the EXDEV fallback are unreached: M5 (staging parent → `Path(tempfile.gettempdir())`) survived and M4 (`shutil.move` fallback deleted) survived, each 17 passed. Both mechanisms exist only for cross-mount hosts and are the reason staging is not under system tmp. | Unit-test `_staging_parent(deep_nonexistent)` == nearest existing ancestor and `== path` when it exists; in-process `replace_tree` with `os.replace` monkeypatched to raise `OSError(errno.EXDEV)` once, asserting the tree moved and no `*.revendor-prev` remains. |
| F5 | major | `tooling/vendor_archify.py:171-174` | T0-01, T1-SCO-05 | The adaptation-anchor refusal (missing/duplicated `ORIGINAL_TAIL`) is unproven: M7 `if upstream_body.count(...) != 1:` → `if False:` survived (17 passed). A future upstream drift would silently no-op the line-82 fix instead of refusing. | Synthetic zip whose `SKILL.md` omits the anchor; assert rc 2 and the `adaptation anchor` message. |
| F6 | major | `tests/test_archify_integration.py:62-71` | T1-PRF-01 | The CI-fail branch is itself unguarded. M14 (`if os.environ.get("CI"):` → `if False:`) passed 7/7 with node present; the branch is unreachable in any executed configuration. Manual `CI=1` + no-node run fails 3/3, so the code is right and the guard for it is missing. Left unguarded, CI with a broken node provisioning goes green and the node legs vanish. | `monkeypatch.setattr(shutil, "which", lambda _n: None)` + `monkeypatch.setenv("CI", "1")`, `pytest.raises(pytest.fail.Exception)` around `_require_node()`; a CI-unset twin asserting the skip. |
| F7 | minor | `tests/test_archify_vendor.py:435` | T1-SCO-02 | Name says "each is necessary"; the body deletes only `SIX_EXEMPTION_PATTERNS[0]` and proves necessity for 1 of 6 (argued; no mutation). Deleting any pattern still reds via the literal-text loop, so the cost is a lying name. | Loop the in-memory delete/assert over all six patterns. |
| F8 | minor | `tests/test_dependency_check.py:531-556` | T1-ORC-04, T1-STR-01 | `"npm install -g node" not in " ".join(...call_args_list)` runs after `mock_run.assert_not_called()`, so it can only ever read an empty list — a tautological sub-assertion. The strong assertion (`assert_not_called`) is present; no coverage is lost. | Delete the dead string assertion. |
| F9 | minor | `tests/test_docs_match_the_catalog.py:86,149` | T2-UNIT-05 | `_one_count` uses `search` with no uniqueness or anchor; `TREE_TOTAL_RE` (`matches **N** files`) could match a different sentence than the glob one it intends to check. | Anchor the regex to the `` `features/*/skills/*/SKILL.md` matches **N** files `` literal and assert exactly one match. |
| F10 | minor | `tests/test_archify_vendor.py:310`; `tests/test_dependency_check.py:596` | T1-ORC-03 | Exit-code/count-only assertions: the forged-packet test never asserts the sha-mismatch message (another refusal path would satisfy it), and the timeout test never names the timeout. | Assert `refusing: zip sha256` in the forged output and the timeout text in the error message. |
| F11 | minor | `tests/test_archify_integration.py:64-67` | T1-STR-03 | Dev skips carry a reason and a re-enable condition but no tracking id. | Add the task id (`aib-archify-diagram-skill-default-integration`) to the skip reason. |
| F12 | minor | `tests/js/archify_packet.test.mjs:52-65` | T1-CST-02 | The delivered-vs-catalog byte comparison duplicates `gates/scaffold_freshness_guard.py` (same pre-push lane set) — the guard re-scaffolds in a temp copy and diffs, so a stale `.ai-badger/skills/archify` already reds it. The js file's unique value is doctor/deliver from the delivered path, which the guard does not run. | Keep it; document the overlap, or drop the tree-equality test if the guard is the owner of that claim. |

## Load-bearing assertions — red proofs (mutation applied, suite re-run, reverted)

| # | assertion | production edit applied | observed |
|---|---|---|---|
| P1 | forged packet refused (`:310`) | `run_revendor` sha compare → `if False:` | `FAILED test_revendor_refuses_a_forged_packet_even_when_the_manifest_agrees` |
| P2 | exclusions/cleaning applied (`:343`) | `excluded()` first line `return False` | `FAILED test_revendor_happy_path_then_check_is_green` |
| P3 | dirty target refused (`:369`) | `target_is_dirty` first line `return False` | `FAILED test_revendor_refuses_symlinks_and_a_dirty_target` |
| P4 | SKILL.md tamper detected (`:279`) | `check_skill_md` first line `return []` | `FAILED test_check_rejects_an_adapted_body_tamper...` |
| P5 | exemption necessary (`:435`) | `unschemad_feature_json` → `return []` | `FAILED test_validate_py_exempts_the_six_..._necessary` |
| P6 | consent before install (`:566`) | system dep installs without `allow_install` | `FAILED test_with_command_but_no_consent_does_not_run` |
| P7 | meta provocation is real (`test_every_check_can_fail.py`) | `run_check` hash compare off | `FAILED test_check_fails_when_provoked[tooling/vendor_archify.py --check \| ...]` |
| P8 | docs numerals derived (`:149,:156`) | `docs/skills.md` 54→53 and 48→47 | both new tests `FAILED` |

None of these eight stays green. Tautologies found: F8 (dead sub-assertion), F10
(exit-code-only), F1 (fixture cannot exercise the clean half of the dirty/clean distinction).
Expected-value-from-production: the meta fixture (`test_every_check_can_fail.py`) builds its
manifest with `build_manifest`/`adapt_skill_md` — the acceptance precedent for DL/VALIDATE, and
the tool's hashes are independently pinned in `test_archify_vendor.py`, so no finding.

## Criterion → test map (plan `docs/work/2026-09-13-archify-diagram-skill-plan.md`)

| package / criterion | proving test | status |
|---|---|---|
| 1a 76-file set, forbidden paths, cleaned package.json | `test_archify_vendor.py:131,:343`; `test_archify_integration.py:98` | direct |
| 1a `doctor` exits 0 from the feature dir | none runs `features/common/skills/archify/bin/archify.mjs`; doctor runs from the scaffolded copy (`integration:168`) and the repo mirror (`js:68`), which byte-equality makes equivalent | indirect |
| 1a/1b `--check` shape + EXCLUDED + meta-gate | `:243,:257,:403`; meta REGISTRY entry | direct |
| 1b `--expect-sha256` from the CLI, never `vendor.json` | forged test `:310` (P1) | direct |
| 1b refuses dirty; exit 2, tree untouched | symlink half `:369` direct; dirty half direct; **clean-target proceed + extras survival unproven** | partial (F1) |
| 1b v2.16.0 literal in `VENDOR.md` | `:474` | direct |
| 1b literal in "the tool's usage text" | no test; the tool contains 0 occurrences (`grep` count 0) — the plan sentence is false in the artifact | absent |
| 1c six `validate.py` exemptions, necessity | `:435` | partial (F7: 1 of 6) |
| 1c `docs/scripts.md` row | `TestScriptsDocCoversTheScripts::test_every_script_is_named` names the script only; the `--check`/`--revendor` split is unchecked | partial |
| 1c counts 47/48 / 45 / "These 48" / tree 54 | `test_docs_match_the_catalog.py:149,:156` + four existing derived counts | direct |
| 1c `test_expected_skill_names.py` 48→49 | `:57` edit, passes | direct |
| 2a presence-only system ecosystem (all six plan cases) | `tests/test_dependency_check.py:481-611` (present, execute-present, absent, absent+execute, argv/shell, no-consent, failure, timeout) | direct |
| 2b shipped `dependencies.json` entry | `:611` | direct |
| 3a invariant delivered, heading + link, ≤6 lines | `test_invariant_catalog.py` (`NEW_INVARIANTS`) + `test_archify_integration.py:119` | direct |
| 3b member ordering | `test_archify_integration.py:154` | direct |
| 3c task clause ≤142 chars | `skills_lint` gate; the gate itself is provoked in the meta-gate, no new branch test | indirect |
| 4a (i)-(v) delivery/policy/node receipt | `test_archify_integration.py:98,119,139,168,181`; `js:52,68,81` | direct |
| 4a node legs **fail** in CI without node | manual run only (`CI=1`, no node → 3 failed) | absent (F6) |
| 4a `setup-node` in the pytest job | `.github/workflows/pylint.yml:38` present; config, not a test | n/a |
| 4b `docs/work/README.md` rows, ADR index row | existing `tests/test_docs_tree_is_canonical.py` derives rows from the committed tree | direct |

## Economies

Changed suites cost ≈ 19 s all-in (`vendor 1.6 s + integration 4.9 s + deps/docs 10.9 s + js 0.5 s
+ meta 1.1 s`). No test needs to become a unit test: the vendor tests deliberately run the CLI
as it runs (`_run_tool`), and the scaffolded-consumer tests are the only place the real
`Scaffolder` path is proven. The only duplication is F12 (js tree comparison vs the freshness
guard); the integration file re-scaffolds once per test (~4 × 0.6 s) — acceptable.

## Verdict

**0 blocker, 6 major (F1–F6), 6 minor — fold-majors before merge.** The suite is well designed —
the QA fold-back items are real, and the flagship assertions redden under mutation — but six
behavioural branches (a preservation path, a refusal matrix, a safety guard, a cross-device
fallback, a drift refusal, and the CI-fail switch) have surviving mutants today. The two with the
most consequence are **F1** (re-vendor over a committed tree: refusal or silent loss of the
provenance extras) and **F3** (the dirty guard vanishing when git is unavailable); both are ~10
lines of test each, and every listed improvement is table-driven and hermetic. Every
surviving-mutant finding (F1–F6) was applied, run and reverted; F7 and F12 are argued
name/body and duplication claims, not unproven gaps. `git status` is clean.
