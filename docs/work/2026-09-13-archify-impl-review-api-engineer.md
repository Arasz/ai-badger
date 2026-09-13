# Implementation review — archify diagram skill (API-engineer lane)

Task `aib-archify-diagram-skill-default-integration`, v0.171.0, branch `c757b858` vs base `f9c6f287`.
Basis: plan rev 2 (`2026-09-13-archify-diagram-skill-plan.md`), my contract proposal
(`...-plan-proposal-api-engineer.md`), code read + live provocation this session.
Real tree untouched throughout: all mutations ran under `/tmp` throwaway roots.

## Findings

| id | sev | claim | evidence | proposed fix |
|----|-----|-------|----------|--------------|
| F1 | NOTE | `vendor.json` + `--check` deliver the count contract exactly | `files[]`=75, adapted-`SKILL.md` record separate, `extra_files`=3; disk=79 (76 upstream + 3 extras); `--check` → `ok archify vendor v2.16.0 76 files`, exit 0. Provoked on temp roots: byte-flip → `CHANGED bin/archify.mjs` exit 1; deletion → `MISSING LICENSE` exit 1; new file → `EXTRA smuggled.txt` exit 1; `.DS_Store` → `EXTRA` + `EXCLUDED … SKILL_EXCLUDE_PATTERNS` exit 1. No self-referential sha: `asset_sha256` is write-only (`build_manifest` stores the verified digest; `run_check` never references it; comparison at L391 is CLI-literal-first). Holds. | none |
| F2 | NOTE | `--revendor --expect-sha256` is fail-closed on all four paths | Missing flag → argparse `error: --revendor requires --expect-sha256`, exit 2. Wrong sha → `refusing: zip sha256 … != --expect-sha256 …`, exit 2, `diff -r` vs real tree: bytes identical. Two-top-dir zip → `unexpected zip layout`, exit 2, 79 files intact. Symlink zip + dirty-target refusal covered by `test_revendor_refuses_symlinks_and_a_dirty_target` (suite 16/16 green). `--check` rejects stray `--expect-sha256/--tag/--commit` (exit 2) and bare invocation (exit 2). Holds; improvement over my proposal: no network fetch inside the tool, operator fetches via `gh`, so there is no exit-2-network path to test — strictly smaller trust surface. | none |
| F3 | NOTE | Dependency entry: valid, truthful, well-worded, quadrant-covered | `validate.py features/common/dependencies.json --schema …` → ok, exit 0. Note names Node 18+, Mermaid fallback, nodejs.org — truthful under plan ruling 4 (presence-only; `<18` residual enforced at use time by `doctor`, recorded in ADR). Report mode node-absent → exactly one hint, `subprocess` 0 calls; node-present → `already_present==["node"]`, 0 calls; absent + `--execute` + no `command` → hint, 0 calls, never `npm install -g node`. `test_dependency_check.py` 33/33 green incl. shlex-split/`shell=False` and failure→`errors`. Cosmetic only: the test fixture note says "the architect skill" where the shipped entry says "the Archify skill" — fixture drift, user-invisible. | Align fixture wording to shipped (`Archify skill`) — opportunistic, not a gate. |
| F4 | NOTE | SKILL.md adaptation is faithful; lint passes | `recovered == upstream body: True` (strip appendix + reverse one-line fix vs `/tmp/archify-staged2/SKILL.md`); the 54-line diff is exactly frontmatter replacement + line-82 condition pin + `## When NOT to Use` + `## Gotchas` + fallback. Frontmatter carries all plan keys (`name/version/author: tt-a1i/license/platforms/scope: default/metadata.hermes`); description starts `Use when`, names Mermaid. `gates/skills_lint.py` → `ok — 54 SKILL.md checked`, exit 0; `node …/bin/archify.mjs doctor` → exit 0. Holds. | none |
| F5 | NOTE | Plan meta-gate landed | `tests/test_every_check_can_fail.py` REGISTRY contains `tooling/vendor_archify.py --check` / corrupted-hash → `Signal(exit_code=1, contains="CHANGED")` (L918-919), synthetic tree built via the tool's own `adapt_skill_md`/`build_manifest`. Holds (code-reviewer F3 closed). | none |
| F6 | SHOULD | `--commit` is recorded as-given, never verified — the one detail I would change for a year of maintenance | `run_revendor(…, tag, commit)`: zip sha verified against CLI literal, but `commit` flows straight into `vendor.json` provenance with no check against tag or zip. A typo'd or copy-pasted `--commit` today becomes an unauditable "pin" for every later drift investigation. Non-blocking: the security anchor (asset sha) is verified; commit is informational. | Verify when networked (`gh api repos/tt-a1i/archify/commits/<tag>` must equal `--commit`), else record `"commit_verified": false` so audits distinguish pinned from asserted. Follow-up issue, not this merge. |

## Verdict: merge-as-is

Every MUST/SHOULD from the plan reviews that touches this lane's paths holds with witnessed
failure paths, not just green runs: `--check` fails red on CHANGED/MISSING/EXTRA/EXCLUDED,
`--revendor` refuses forged/wrong/malformed inputs with the tree byte-identical, the
dependency quadrant is covered with zero-subprocess proofs, the adapted body round-trips to
upstream bytes, and both suites (16 + 33) plus `validate --all`, `skills_lint`, and `doctor`
are green. F6 is a genuine year-horizon weakness but informational-only and fixable as a
follow-up. No simpler shape was missed: the implementation already shrank my proposal (zip-in
instead of network fetch, presence-only instead of version probe).
