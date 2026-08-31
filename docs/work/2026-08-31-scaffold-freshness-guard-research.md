# Research record — scaffold freshness guard blind spots (F2 + `--skills ''` trap)

Task: `aib-scaffold-freshness-guard-blindspot-proof` · Target: main @ `19e28a7b` (v0.149.1) · Date: 2026-08-31

Every finding carries its source. Unverified claims are labelled **hypothesis**.

## 1. The witnessed incidents (evidence)

**d-16 review record** (`~/.pi/agent/subagent-logs/d-16.jsonl`, review of aib-delegation-usage-parser-migration-note ee2625bb..f92e91de):

- **F1 (MUST):** two full-suite runs on one tree: `5 failed, 4707 passed` — `tests/test_scaffold_freshness_guard.py` ×4 + its `test_every_check_can_fail` provocation ×1. The same file passes 13/13 in isolation and at base ee2625bb. → the flake is **test-order/environment-dependent**.
- **F2 (MUST):** "The freshness guard can silently pass a hand-edited tree. Observed failure mode: a hand edit to a skill mirror survives the guard's own re-scaffold, so the gate prints `only version stamps differ — PASS`. Reproduced twice outside pytest: a scaffold run on an **extracted f92e91de tree** reused **11 of 32** manifest-recorded skills (128 vs 212 entries) and left the edit in place; identical reruns (gp3/gp4/gs0–3, four PYTHONHASHSEED values) reuse 32 and correctly remove it."
- **Eliminated hypotheses (d-16):** PYTHONHASHSEED randomization, plugin-cache catalog sourcing ("no cache has 11 skills"), config/manifest drift ("byte-identical across probes"), root env overrides.
- **d-16 verdict:** "Investigate as a framework defect (likely test-order/env-dependent under-production of the skill set); until pinned, do not treat a single green `scaffold` lane as proof."

**0.147.0 changelog** (`docs/changelog/0.147.0-status-report-skill.md`, "Discovered en route"): "With the stale index the scaffold silently skipped the new skill ('not in any configured stack') while still passing the freshness guard, because the guard re-scaffolds with `--skills ""` (reuse-manifest) and **cannot notice a skill the manifest never gained**." — independent, earlier documentation of the same blindness class.

**In-session incidents (spec):** `d6e7975f` (a parser edit required an in-commit mirror regen for the guard to pass), `50f09b11` (0.148.0 merge repair — the under-production had already happened in-repo), PR #455 disposition comment (F2 filing).

## 2. Mechanism map (verified in source @ 19e28a7b)

### The guard (`gates/scaffold_freshness_guard.py`, 352 lines)

- `rescaffold_argv()` **L128–133**: returns `[python, scaffold, --config, …, --target, …, --root, …, --no-install, --skills, ""]` — carries `--skills ""`.
- `remediation()` **L135–137**: "The command that makes a stale tree fresh" — prints `AI_BADGER_MCP_AVAILABILITY=all python3 … --no-install --skills ''`. **The docstring's claim is false for skill-mirror staleness whenever the manifest is narrowed** (it advises the exact recovery-from-manifest mode).
- `rescaffold(work)` **L139–155**: runs the SAME `rescaffold_argv` against a throwaway copy of the tree → **the guard's internal re-scaffold also uses `--skills ""`** → inherits the manifest's own skill set. Shared builder is a deliberate property: "printed advice is what the guard ran".
- `collect()` **L272–301**: copies tracked+untracked-unignored tree to temp, re-scaffolds there, `differences()` diffs path sets + content (`before` vs `after`). Comparison is **tree-vs-tree**; the manifest is used only by `classify()` (**L246–264**) for stale/hand-edited verdicts.
- `check()` **L302–317**: exit 0 "PASS" when no findings; else prints findings + remediation.

### The scaffolder (`features/common/skills/welcome-ai-badger/scripts/scaffold.py`, 850 lines)

- `main()` **L~780**: `--skills` defaults to `",".join(DEFAULT_SKILLS)`. `skills = [s for s in args.skills.split(",") if s]`. **If empty**: "An explicitly empty --skills means 'the set already scaffolded', not 'none' (#129)" → `skills = bl.scaffolded_skill_names(bl.load_json(manifest_path))` and prints `--skills was empty — reused {N} skill(s) already scaffolded`. **This recovery note is the only place the word "reused" appears** — strong candidate match for d-16's "reused 11 of 32" wording. **Hypothesis:** the under-produced run took the recovery path with a manifest that yielded only 11 skills, OR `DEFAULT_SKILLS` evaluated empty at import.
- `Scaffolder.__init__` **L~270**: `offered = list(dict.fromkeys(list(skills) + asked_for))` where `asked_for` = sorted config-include skills present in `addable_skills`; filtered by `excluded["skills"]`. `self.prune_discovery = bool(skills)`.
- `discover_stack_local()` (skill_delivery.py **L~216**): appends stack-local (non-common-stack) skills missing from the list.
- `scaffold_skills()` (skill_delivery.py **L~230**): for each delivered skill: `find_skill_in_stacks(index, stacks, name)` → **`None` ⇒ note "skill 'X' not in any configured stack — skipped"** (silent under-production when the index is stale relative to features/ — the 0.147.0 discovery). Delivered skills are ALWAYS `rmtree` + `copytree` (no per-skill fingerprint-reuse branch in delivery itself; the spec's "reuse/fingerprint path" wording maps to the list-recovery + record()-time fingerprints).
- `record()` **L~360**: per-skill dir fingerprint = `bl.dir_content_hash(target, exclude=SKILL_EXCLUDE_PATTERNS + ["extensions"], exclude_rel=projectOwned)` + `sourceHash` of the framework source.
- `DEFAULT_SKILLS` module-level: `bl.default_skills_in(root/features/common/skills)` — scope-frontmatter walk at import time (badger_lib **L782–784**), sorted.
- `bl.scaffolded_skill_names()` (badger_lib **L868–880**): manifest entries where `feature=="skills"` and name has no `/`.

### The blindness chain (verified reasoning from the above)

1. Anything that makes a scaffold run deliver fewer skills (index staleness, recovery from a narrowed manifest, an under-produced default set) writes a manifest whose `entries` omit those skills — while the **files remain on disk** (nothing deletes them; `prune_discovery`/`SupersededPrune` only act in specific paths).
2. The guard's re-scaffold, run with `--skills ""`, recovers the SAME narrowed list → does not regenerate the omitted mirrors → they are byte-identical in `before` and `after` → **no finding**.
3. Therefore a hand edit to (or upstream staleness of) any omitted mirror is invisible. Compounding: once entries lose a path, no later guard run regains it (d-16: "the blindness compounds").

### What the existing tests cover and miss (`tests/test_scaffold_freshness_guard.py`, 327 lines)

- Fixture `_freshen()` scaffolds a full git-copy of the repo with `--skills ""` (L48–61) — **the fixture itself trusts manifest recovery**, so a narrowed manifest produces a "fresh by construction" fixture that is blind the same way.
- Covered: fresh pass, source-gains-file, stale classify, hand-edited classify, stamp exemption, refusals, no-mutation, hermes-home containment, remediation-executes-to-green (`test_the_printed_remediation_produces_a_tree_the_gate_then_passes` — **executes the `--skills ''`-carrying advice verbatim and asserts green**; AC3 will need this inverted/extended), argv/hermes-home mechanism.
- Missing: under-produced-manifest scenario (AC2), remediation-executed-then-hand-edit-still-fails (AC3), remediation message audit (AC4), consecutive-run determinism (AC1).
- `tests/test_scaffold_empty_skills.py` (95 lines) pins the LEGITIMATE `--skills ''` reuse mode — must keep passing.

## 3. R4 status probe (verified, 2026-08-31, main @ 19e28a7b)

Manifest `.ai-badger/manifest.json`: 212 entries; skill-dir entries **32/32** vs `.ai-badger/skills/` on disk (33 dirs incl. `learned/`, which is Hermes-authored and correctly absent); 17 per-file extension rows. **The 42-path loss from the 0.148.0 era appears already repaired at 0.149.1** — AC0's double-scaffold protocol must confirm rather than repair. (One caveat: `frameworkDirty: true` in the committed manifest — the tree was dirty at last stamp; note for the lanes.)

## 4. Leads for R1 (root cause of nondeterministic under-production) — hypotheses, unverified

1. **Recovery-path match:** "reused 11 of 32" matches the `--skills was empty — reused N` note verbatim in shape. How could `scaffolded_skill_names` return 11 of a 32-skill manifest? Not obvious from source — needs empirical repro + note capture.
2. **Import-time `DEFAULT_SKILLS` walk:** if `default_skills_in` returned empty/partial at import (exception path? `_skills_scoped` internals unread), `--skills` default collapses to empty → recovery path engages. Needs `_skills_scoped` read + repro.
3. **Index staleness:** `find_skill_in_stacks` returning None silently skips ("not in any configured stack"). Verified mechanism for under-production, but not yet for NONdeterminism on an unchanged tree.
4. **Test-order/environment dependence (F1):** guard test file fails ×4 only inside full-suite runs — some state (env var, cwd, HOME, hermes home, plugin cache, `$AI_BADGER`, index cache) differs under pytest. d-16 eliminated PYTHONHASHSEED + plugin cache + config drift + env overrides for the *out-of-pytest* repro, but the in-suite flake may have a separate trigger.
5. **Extracted-tree factor:** d-16's out-of-pytest repro ran on an **extracted tree** (no `.git`). The guard's own temp-copy is also a no-`.git` copy. `git_provenance()` returns (None, False) there — could any downstream branch differ? **Hypothesis.**

**Repro recipe for lanes:** extract f92e91de (or current main) to a scratch dir, run the spec's command (`AI_BADGER_MCP_AVAILABILITY=all python3 …/scaffold.py --config … --target . --root . --no-install`) N times, capture stdout notes + manifest entry counts per run, diff. Do NOT run against the task worktree itself (would mutate it) — scratch copies only, `/tmp`.

## 5. Proposed shapes (dispatcher's — lanes evaluate, don't execute)

- **R2 (guard detects narrowing):** derive the expected skill set from `config.json` independently of the manifest (replicating the config-driven part of `Scaffolder.__init__`: defaults by scope + include-expansion − exclusions + stack-local discovery), fail fast with a named message when the manifest's `scaffolded_skill_names()` ⊊ that set, and re-scaffold the **union**(manifest-recovered, config-derived) so mirrors regenerate even when the manifest lost them. Trade-offs to evaluate: config names a catalog-dropped skill (inert-exclusion semantics), consumer repos' legitimate narrower configs, #129 semantics preservation.
- **R3 (remediation):** emit the union form — no `--skills ''` in `rescaffold_argv`/`remediation`; keep one builder so printed advice = what the guard ran. AC4 greps the rendered output. Existing remediation test needs rework, not deletion.
- **Version:** current 0.149.1. `gates/` is shipped surface + guard failure-mode change → **0.150.0** proposed (assigned at dispatch, lanes don't pick).
- **R5 target:** welcome-ai-badger skill (source of truth `features/common/skills/welcome-ai-badger/SKILL.md`, mirror regenerates) + guard failure output already carries the fix via R3.

## 6. Constraints & gates

- Red-first: AC2–AC4 witnessed failing pre-fix, RED output pasted into the task record.
- Don't break `--skills ''` legit mode (`test_scaffold_empty_skills.py`), #129 recovery semantics, or consumer-repo scaffolding.
- Full pytest + pylint 10.00 (`python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`) + `python3 tooling/index_build.py --check` + `verify.sh pre-push`; CI is the pass condition.
- Changelog entry + version bump (release gate) since `gates/` is shipped surface.
