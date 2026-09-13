# archify implementation review — architect lane

Task `aib-archify-diagram-skill-default-integration` (0.171.0). Reviewed tip `c757b858` (as
briefed), base `f9c6f287`. **The branch advanced mid-review to `7695092b`** ("docs(vendor,test):
name the verified anchor and fix a fixture note's wording", 14:39) — gate results below are
marked where they were re-run at the new tip. Read-only lane: no git write commands; one file
written (this report).

**Verdict: conforms on every architectural axis — with two MUST fixes.** ADR-0030 describes
what shipped (provenance, scope, fallback policy, dependency semantics, consequences), the
delivery surfaces and catalog wiring are consistent, and the pack-growth arithmetic reproduces.
Outstanding: (F1) PKG-4's `actions/setup-node` CI step was never added and the omission is
unrecorded; (F2) current HEAD is red in CI-only pytest because the first impl-review record was
committed without its `docs/work/README.md` row.

## 1. Gate ledger — every PKG-1..PKG-4 gate, actually re-run

| PKG | Criterion / gate | Observed output | Status |
|---|---|---|---|
| 1a | `tooling/vendor_archify.py --check` | `ok archify vendor v2.16.0 76 files` rc=0 (ran at both tips) | PASS |
| 1a | `node …/archify/bin/archify.mjs doctor` (feature dir) | rc=0; 15 `[ok]` lines incl. `[ok] Node.js v26.8.2 (requires >=18)`, "Archify is ready." | PASS |
| 1a | file set / exclusions / package.json | 79 files = 76 upstream (incl. adapted `SKILL.md`) + 3 extras; 75 manifest hashes + `SKILL.md` = 76; no `test/`, `package-lock.json`, `scripts/generate-*.mjs`; `scripts`/`devDependencies` absent, `engines.node >=18` kept | PASS |
| 1b | `pytest tests/test_archify_vendor.py` | green in the 177-pass focused run; forged-zip-refused, disk-`rglob`, literal-split, lint-subject and exemption tests all present | PASS |
| 1b | meta-gate provocation for the vendor check | `REGISTRY` entry present (`_vendor_archify_check`, signal exit 1 + `CHANGED`); `pytest tests/test_every_check_can_fail.py` → **80 passed, 1 teardown error** (environmental, see F4) | PASS (with F4) |
| 1c | `validate --all` | every block `ok` (incl. `feature json schema coverage`, `skills lint`), rc=0 | PASS |
| 1c | six `validate.py` exemptions | each matches ≥1 archify file; I deleted each of the six individually → archify gaps 6/14/1/1/1/1, so all six are load-bearing for this packet | PASS (test proves one; independent check proves all) |
| 2 | `pytest tests/test_dependency_check.py` | 58 passed together with the claims test at the new tip; shipped-entry test asserts `system`, `node`, no `command`, note names Node/18/Mermaid | PASS |
| 2 | presence-only semantics | `shutil.which` in report+execute, zero subprocesses when present; no-command+`--execute` stays a hint; shlex/shell=False only when a command is declared | PASS |
| 3 | `pytest tests/test_invariant_catalog.py` + `skills_lint.py` | invariant is 3 lines; title+link present in CLAUDE.md/copilot/HERMES assembled files; lint `54 SKILL.md checked` rc=0 | PASS |
| 3 | `tests/test_archify_integration.py::test_documentation_members_put_archify_before_mermaid` | green; member mandates name archify before Mermaid; frontmatter untouched | PASS |
| 4a | `pytest tests/test_archify_integration.py` | 7 items green (scaffold file-by-file, invariant link, dependency presence, docs members ×2, doctor rc==0 exactly, 9/9 showcase deliver + non-empty HTML) | PASS |
| 4a | `node --test tests/js/archify_packet.test.mjs` | `tests 3 / pass 3 / fail 0` (delivered-vs-catalog comparison, doctor, deliver receipt) | PASS |
| 4a | CI `actions/setup-node` (pinned SHA, node 20) | **absent**: `git diff f9c6f287...HEAD --name-only -- .github/` = `copilot-instructions.md` + `skills/archify` only; no workflow mentions `setup-node`; `pylint.yml:142` runs `verify.sh pytest` with `setup-python` only | **FAIL (F1)** |
| 4b | join gates | `index_build --check` rc=0; `sync_plugin_skills --check` "46 skill(s) in sync"; `scaffold_freshness_guard` "2609 path(s)… PASS"; `version_sync --check`, `changelog_index --check`, `docs_guard`, `deps_guard`, `release_guard`, `shipped_paths_guard`, `workflow_lint` all rc=0 | PASS |
| 4b | `docs/work/README.md` rows | 9 rows for the research/plan/proposal/review records (rows arrived in `3786759c`); **current HEAD red**: `pytest tests/test_docs_tree_is_canonical.py` → `1 failed, 74 passed`, assertion names `2026-09-13-archify-impl-review-api-engineer.md` | **FAIL (F2)** |

Focused suite as the plan's 4b list: `pytest tests/test_archify_vendor.py tests/test_archify_integration.py tests/test_dependency_check.py tests/test_docs_match_the_catalog.py tests/test_expected_skill_names.py tests/test_invariant_catalog.py tests/test_every_check_can_fail.py -q` → **177 passed, 1 error** (the F4 teardown artefact). CI itself was not observed: the branch has no upstream here, so "push and read CI" remains for the orchestrator.

## 2. Findings

| ID | Sev | Claim | Evidence | Proposed fix |
|---|---|---|---|---|
| F1 | MUST | PKG-4's CI leg is missing: no `actions/setup-node` was added to the pytest job | no workflow diff under `.github/workflows/`; `awk` for `setup-node` finds none in the 7 workflows; `pylint.yml:142` = `bash .lefthook/pre-push/verify.sh pytest` on a `setup-python`-only job | Add the pinned step (full commit SHA, `node-version: 20`) to the pytest job, or amend plan/ADR with the rationale that hosted runners preinstall Node and `_require_node` fails rather than skips under `CI` (it does) — decide and record; don't leave the plan item silently dropped |
| F2 | MUST | Current HEAD is red on the docs/work index | `pytest tests/test_docs_tree_is_canonical.py` → 1 failed (file named in the assertion); `git ls-tree HEAD docs/work/` shows the api-engineer record committed in `7695092b`; `git show HEAD:docs/work/README.md` has 9 archify rows, none for it | Add a README row per impl-review record as it lands (this report, code-reviewer, qa, hermes), then re-run the test; plan 4b already requires this |
| F3 | NOTE | Plan ruling 2 said the v2.16.0 literal lives in VENDOR.md **and the tool's usage text**; the tool embeds neither | `'4c59fa…' in tooling/vendor_archify.py` → False (python check); the literal is in `VENDOR.md`, `docs/scripts.md`, `vendor.json` | Put the literal in the `--revendor` usage example (it is an expected input, not a manifest read), or drop that clause from the plan |
| F4 | NOTE | The meta-gate file errors only under concurrent sessions | `pytest tests/test_every_check_can_fail.py` twice → 80 passed + 1 teardown error naming `~/.ai-badger/hook-errors.log` appends by `commit_reminder_hook`/`test_economy_hook`; the named test passes alone (`1 passed in 3.33s`); FS observer flagged concurrent writes | Environmental; re-run the lane when no parallel agent session is firing hooks. No code change |
| F5 | NOTE | The reviewed tip `c757b858` carried a fixture typo ("the architect skill" where the shipped note says "the Archify skill") | `git show c757b858:tests/test_dependency_check.py` line 432 vs `features/common/dependencies.json`; fixed in `7695092b` after the review snapshot | Already fixed; note for reviewers comparing the briefed SHA to today's branch |
| F6 | NOTE | `vendor_archify.py --check` is invoked by no `verify.sh` lane or pre-commit hook — only inside the pytest lane | `awk vendor .lefthook/pre-push/verify.sh` → no match; `tests/test_archify_vendor.py` calls the tool; `dispatched_gates` only requires `gates/*.py` | Acceptable (pytest lane is CI and runs it) but if a pre-push signal is wanted, call it from `lane_validate` |
| F7 | NOTE | ADR-0030 phrasing "byte-identical for the 76 upstream files, with `LICENSE` and `THIRD_PARTY_NOTICES.md`" reads as if the notice were one of the 76 | `vendor.json` `extra_files` = `THIRD_PARTY_NOTICES.md`, `VENDOR.md`, `vendor.json`; notice is an ai-badger backfill (tests assert exactly that) | Reword to "…plus LICENSE (one of the 76) and the ai-badger extras `THIRD_PARTY_NOTICES.md`/`VENDOR.md`/`vendor.json`" |

## 3. ADR-0030 vs the tree — no contradictions found

- Provenance: `vendor.json` pins repo/tag/commit/asset sha + per-file hashes; `--check` is
  offline-only and never compares the asset sha; `--revendor` verifies the **command-line**
  literal before any write and refuses a dirty target — all as decided (QA-3 honoured).
- Scope `default`; delivered to plugin copy + scaffold (integration test) + self-scaffold.
- Fallback policy matches the invariant, the adapted body, the description, and `docs/skills.md`.
- `system` dependency: detect-only, no `command` on the archify entry, Node<18 residual recorded.
- Consequences arithmetic reproduced independently: 238 tracked entries across the three trees =
  **80 unique blobs** (dedup), zlib(6) over unique content = **1,154,616 B ≈ 1.10 MiB** (ADR
  ~1.1–1.5 MB measured 1,144,408 B); working tree ≈3 × 5.94 MB ≈ 17.8 MB (ADR ~17.7 MB).
- Plugin copy is pointer `SKILL.md` + `SKILL.full.md` (byte-identical to the catalog SKILL.md);
  only the three bootstrap skills lack `SKILL.full.md`, as the ADR says. Pointer body names the
  project copy `.ai-badger/skills/archify/SKILL.md`; the description names the Mermaid fallback.
- Delivery surfaces: `git ls-files skills/archify | wc -l` = **80**; feature and `.ai-badger`
  mirrors 79 each; both symlinks are mode 120000 → `../../.ai-badger/skills/archify`; agent files
  (CLAUDE.md, copilot-instructions, HERMES.md, `.hermes.md`, `.ai-badger/*`, `.github/*`) carry
  the title + link.
- Catalog wiring: docs counts 48/47/45/54 pass the new derived assertions; expected names 49;
  docs/scripts row documents `--check` vs `--revendor` with the literal; changelog+index, ADR
  README row, `VERSION`/plugin/marketplace 0.171.0, model-groups stamped in both copies.

## 4. Commit sequence and per-commit greenness

`2911519b → 66b73a4d → 3786759c → c757b858 → 7695092b`.

- `2911519b`, `66b73a4d` (docs records): all pre-commit hooks and pre-push lanes pass in
  principle — no code changed (tdd_guard scans `engine|tooling|features|gates` `.py/.mjs`), no
  broken relative links (checked every link target of every added file against that commit),
  changelog/index unchanged. **But the CI-only pytest lane would be red at each**: the work-index
  test reads the committed tree and README had **0** archify rows until `3786759c` (rows added
  then: 9).
- `3786759c` (everything but integration tests): the whole join in one commit, so
  version-sync/index/plugin-skills/scaffold-freshness are self-consistent; pre-commit pylint with
  the hook's exact args on the changed Python scores 9.99/10, rc=0 (fail-under 9.5). Green.
- `c757b858` (integration tests + mjs backstop): green; the same 177-pass focused run covers it.
- `7695092b` (VENDOR.md anchor note in all three trees + manifest + fixture fix + first review
  record): hooks green, pytest red on F2.
- Matters only if CI ran per commit; branches are normally gated at the pushed tip, so only F2 is
  live for the PR. Fix F2, re-push, then the remaining work is mechanical (F1 decision, optional
  F3 wording, F7 ADR phrasing).
