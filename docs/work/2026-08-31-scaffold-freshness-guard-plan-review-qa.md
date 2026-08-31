# QA plan review — scaffold freshness guard test strategy

Reviewer: QA persona (lens: test honesty, gate honesty, red-first discipline)
Target: `docs/work/2026-08-31-scaffold-freshness-guard-plan.md` (Packages 1–2, 4, 7; D5/D6/D9) + `docs/work/2026-08-31-scaffold-freshness-guard-moe-test-engineer.md`
Verified against: `tests/test_scaffold_freshness_guard.py`, `tests/test_scaffold_empty_skills.py`, `gates/scaffold_freshness_guard.py` in worktree `aib-scaffold-freshness-guard-blindspot-proof`.
Status: COMPLETE — verdict REQUEST-CHANGES (5 MUST, 3 SHOULD, 2 MAY, verified-clean list at bottom).

## Scope & out-of-scope declaration

- In scope: the six attack lenses in the brief (AC1–AC4 failability, AC4 regex vs real remediation output, red-first integrity, Package 7 gate honesty vs d-16, suite budget + fixture isolation, D5 ruling).
- Out of scope: production-code correctness of D1–D4 design (code-reviewer's artifact), release/versioning policy (reviewer lane), docs prose quality.

## Findings

### F-QA1 — MUST — RED-witness runbook §6 step 1 produces refusals, not artifacts

`docs/work/2026-08-31-scaffold-freshness-guard-moe-test-engineer.md:## 6` step 1:
`rsync -a --exclude .git <worktree>/ /tmp/aib-red-base/`, then step 2 runs the guard on that
copy. Applied verbatim (probe 1): the guard exits 2 with `SCAFFOLD FRESHNESS GUARD COULD NOT
RUN: GIT COMMAND FAILED … fatal: not a git repository` — `tracked_and_untracked`
(guard L33–45) requires a git repo, and the runbook stripped it. None of the four RED
artifacts can be produced by the runbook as written; Package 1's gate ("orchestrator eyeballs
each against the expected pre-fix shape", plan Package 1) would receive four refusal dumps, or
an implementer would improvise a fix and the record would diverge from the runbook.
**Fix:** scratch must replicate the fixture's repo setup (harness L66–72: git init + config +
add + commit, then optionally `_freshen`), or rsync WITH `.git`. `run?`: applied (exit 2
witnessed) — the expected-PASS artifact is impossible under the written command.

### F-QA2 — MUST — Package 7 pass condition is weaker than the repo's own d-16 MUST ruling

Plan Package 7: "push; **CI green = pass condition**" — one green run. The d-16 review record
(research doc L11, verdict quoted at L14; d-16.jsonl F2, severity MUST) rules for this exact
flake class: "Re-run the full suite to **two consecutive green runs before merge**; root-cause
the flake (see F2) or file it as a blocking known-flake." The file at issue —
`tests/test_scaffold_freshness_guard.py` — is the file Packages 1/4 extend, and its ×4
in-suite flake is unresolved (F1 open; plan §7 Q3 only time-boxes a probe whose stop condition
leaves it "documented as open"). The plan therefore satisfies neither branch of d-16's ruling
(root-cause, nor blocking-known-flake filing) and weakens the gate below the standard the
repo already set for this file. **Fix:** Package 7 AC = two consecutive green full-suite runs
(or a recorded, explicit supersession of d-16 in the plan). `run?`: verified against the
d-16 record text (research L11/L14) vs plan Package 7 wording — source-read, no run needed.

## Probes run (all in /tmp scratch copies, never the worktree)

Scratch built fixture-style: copy tracked+untracked tree → `git init` + commit → `_freshen`-equivalent scaffold+commit. Baseline guard on a clean clone: exit 0 PASS, 1945 paths, `reused 32`.

| # | Probe | Result |
|---|-------|--------|
| 1 | Runbook §6 step-1 command verbatim (`rsync --exclude .git`) + guard run | exit **2**, `SCAFFOLD FRESHNESS GUARD COULD NOT RUN: GIT COMMAND FAILED … not a git repository` |
| 2 | AC2 recipe verbatim (victim = recipe's deterministic pick = `ai-raccoon-memory`) | guard exit **1**, finding `.ai-badger/manifest.json  (content differs, regenerates differently)` — NOT the claimed PASS |
| 2b | Victim-row census | 30/32 skills have out-of-mirror rows (`feature: adjustments` → `.claude/skills/<name>`, `.github/skills/<name>`); the 2 without are **stack-local hermes skills** (`cron-watchdog-authoring`, `hermes-plugin-development`) |
| 2c | Both clean-row victims | guard exit **1** pre-fix: victim mirror SKILL.md regenerated (stack-local walk re-adds the skill regardless of manifest rows) + manifest row regenerated |
| 3 | AC3 full 8-step sequence, pre-fix | guard#1 exit 1 (2 findings: staleness + manifest drift); remediation exit 0 with `reused 31 skill(s)`; assertion 6 FALSE (victim entry absent, 209 entries) → RED; guard#2 exit 0 PASS → assertion 8 RED. Matches the doc's claimed RED shape |
| 4 | AC4 regex vs real output | rendered remediation ends `--skills ''` — matches (span 165–176); mechanism-tier joined argv ends `--skills ` trailing-space unquoted — matches via `$` |
| 5 | D6b transports pre-fix | list-form `["--skills", "''"]` → exit 0, **128 entries** (the ea17ae60 under-production shape); shell `--skills ''` → exit 0, **212 entries** |
| 6 | AC1 second scaffold (`--generated-at` pinned) digest diff | exactly 2 differing paths; the only one outside `.ai-badger/` is **`.git/index`**; `__pycache__` clean in this run |

### F-QA3 — MUST — AC2's recipe cannot produce its claimed pre-fix PASS on this tree; the viable-victim set is empty

`moe-test-engineer.md:152-158` claims pre-fix step 5 returns 0 ending `… only version stamps differ — PASS` because "the tree-vs-tree diff sees nothing." Applied verbatim (probes 2/2b/2c): **every possible victim produces exit 1 pre-fix.** Three measured mechanisms:
1. The recipe's pick (L118–120, first `feature=="skills"` /-free entry) is `ai-raccoon-memory`, which carries out-of-mirror **adjustment rows** (`.claude/skills/ai-raccoon-memory`, `.github/skills/ai-raccoon-memory`). The recipe strips only rows under `.ai-badger/skills/<name>` (L130–137), so the root manifest keeps them while the regenerated manifest drops them (skill not re-delivered) → `differences()` (guard L302) reports the manifest → exit 1.
2. 30/32 skills carry such rows → same poisoning for any of them.
3. The 2 adjustment-free skills are stack-local — `stack_local_skills` (badger_lib.py L884–893, via skill_delivery.py L255–274) re-adds them to delivery regardless of manifest rows, so the mirror regenerates and the hand-edit is clobbered → exit 1.

The intersection the recipe needs — scope-default ∧ no out-of-mirror rows — is **empty** on this tree. Consequences: (a) Package 1's gate (plan L75–82, "orchestrator eyeballs each against the expected pre-fix shape") cannot match its AC2 expectation; (b) the test's `"manifest" in done.stdout` discriminator (moe-test-engineer.md:147–149) passes pre-fix too (the pre-fix finding line contains `manifest.json`) — zero discriminating power; pre-fix RED survives only via the mirror-path assertion, for a different mechanism than documented. The real-world blindness (ea17ae60's wholesale-narrowed manifest) is real — probe 5's 128-entry shape — but the recipe models the wrong tree state. **Fix:** pick a pure scope-default victim (exclude `config.include.skills` ∪ stack-local), strip every row naming the victim (any target containing the skill name), re-baseline the RED expectation against the observed shape, and re-scope the `"manifest"` assertion to the D2 narrowing message. `run?`: applied+reverted (probes 2–2c).

### F-QA4 — MUST — D6b transport-invariance is unsatisfiable under D3 as designed (plan-internal contradiction)

Plan L62 (D6b): the two transports "produce the same outcome (both recover 32, or both refuse)." Under D3 (plan L59): list-form `["--skills", "''"]` delivers the literal two-char name → quoting-artifact → **refused, exit 2**; shell `--skills ''` collapses to true-empty → recovery preserved → **32 skills, exit 0**. The outcomes differ by construction; the planned assertion can never go green post-fix. The pre-fix RED is genuine (probe 5: 128 vs 212 entries — exactly the ea17ae60 shape), so keep the test, but restate the invariant per-transport: list-form ⇒ exit 2 with the quoting-artifact message; shell ⇒ recovery to 32; and neither transport silently under-delivers. `run?`: applied+reverted (probe 5) for the RED side; the post-fix contradiction is D3×D6b spec analysis (static reasoning).

### F-QA5 — MUST — AC1's assertion 2 fails on `.git/index` noise; the control is broken as specified

`moe-test-engineer.md:55-60` (assertion 2): `_tree_digest` both clones, then `normalized()` "applied to both copies of every differing path; assert the set of normalized differences is empty." `_tree_digest` (harness L179–194) `os.walk`s **everything including `.git`** — no filter. Probe 6 (second scaffold, `--generated-at` pinned): exactly one differing path outside `.ai-badger/` — `.git/index` (the scaffold's `frameworkDirty` `git status` refreshes the index in clone B post-copytree; clone A keeps inherited bytes). `normalized()` passes non-JSON bytes through raw → non-empty difference set → the "control" reports RED pre-fix for purely environmental reasons (T0-06: a test that samples the machine, not the code). Package 1's expected-GREEN control record is then either false, or the implementer silently adds exclusions the plan never named. **Fix:** scope the digest/comparison to the managed tree — exclude `.git` explicitly and reuse the guard's `is_noise` semantics for `__pycache__`/`.pyc` (clean in this probe, but environment-fragile). `run?`: applied+reverted (probe 6).

### F-QA6 — SHOULD — AC3's step-3 rationale is false on this tree; its post-fix GREEN depends on an unpinned D2 output shape

(a) `moe-test-engineer.md:305-307` (§2 property 2): "A merely narrowed tree pre-fix PASSES (that is AC2's blindness), so there would be no remediation to capture." Probe 2 falsifies this — the narrowed tree alone exits 1 pre-fix (manifest-drift finding) and a remediation is capturable without the staleness provocation. The 8-step sequence still works (probe 3: RED at assertion 6, guard#2 PASS, `reused 31` — the doc's claimed RED shape holds), but the documented rationale and guard#1 stdout shape are wrong; §2's ordering argument must be re-baselined against the observed two-finding guard#1 output.
(b) Post-fix, D2's fail-fast (plan L58: "message names the narrowing + lists missing skills + counts") does not specify printing the `Re-scaffold this repo` block. AC3 step 5 extracts via `_printed_remediation`, whose `next(...)` (harness L226–227) **raises StopIteration** if the header is absent → the test errors post-fix instead of going GREEN. Pin in D2: the fail-fast path prints the standard findings + remediation block (or AC3 tolerates its absence explicitly). `run?`: (a) applied+reverted (probes 2, 3); (b) static reasoning on harness L225–231 + plan L58.

### F-QA7 — SHOULD — AC2's proposed message shape contradicts its own path assertion

`moe-test-engineer.md:145-149` proposes the R2 message `SKILL MIRROR LOST FROM MANIFEST: {name} (re-scaffold recovered {N} of {M} skills)` — the skill **name** — while the assertion set (moe-test-engineer.md:143) requires `f"{mirror}/SKILL.md" in done.stdout` — the full **path**. An implementer following the message shape ships a test that fails post-fix; one following the assertion ships a message the doc itself calls over-pinned. Pin one (the path form is the stronger observable; the message bullet should then name paths, not names). `run?`: unverified (static reasoning) — internal doc contradiction.

### F-QA8 — SHOULD — D7's rationale clause has an unpinned print position that can break two tests

`_printed_remediation` (harness L225–231) joins **every** line after the `Re-scaffold this repo` header to end of stdout — faithful today because the command is check()'s last print (guard L329–330; verified in probe 3: the extracted line executes clean, exit 0). D7 (plan L63) adds "one rationale clause" to the guard failure output with no position. Printed **after** the command, the clause is swallowed into the extracted "command" → AC3 step 5 executes prose as shell → scaffolder argparse failure → false post-fix RED; the kept remediation-executes test (harness L233) breaks the same way. Pin: print the clause **before** the remediation block. `run?`: unverified (static reasoning) — hazard, not an observed failure.

### F-QA9 — MAY — AC4 regex is sound but the match table omits the mechanism tier's actual pre-fix shape

Verified against both real shapes (probe 4): rendered remediation ends `--skills ''` (`shlex.quote("")`, guard L136) — matches; the mechanism tier's `" ".join(argv)` ends `--skills ` + end-of-string, **unquoted** — matches via the `$` alternative. The match table (moe-test-engineer.md:355-368) lists only quoted/`=` shapes; add the trailing-space row so the pasted RED artifact is recognizable against it. The positive regex correctly rejects the pre-fix line (lookahead `(?!""|''|$)` blocks `''`). `run?`: applied+reverted (probe 4).

### F-QA10 — MAY — D5 ruling: acceptable, with a named diagnosis cost

The canary is real but post-fix-only (pre-fix the guard is blind to the fixture inheriting a narrowed manifest — that is the defect under repair, and D2 lands in the same change, so there is no unprotected interim). Two caveats: (1) the canary fires as `test_a_fresh_tree_passes` red with a D2 narrowing message on a tree the test calls fresh — diagnosis cost; note it in that test's docstring; (2) the deferred `reused N` fixture check (moe-test-engineer.md:127–131) was declined on a wording-coupling hypothesis, but the note format proved stable across all probes (`--skills was empty — reused {N} skill(s)`, N tracking the narrowed manifest exactly: 31/32 observed) — cheaper insurance than the hypothesis implies. Accept D5; take (1) as mandatory, (2) optional. `run?`: applied+reverted (reused-31 observed in probe 3).

### Verified-clean claims (no finding)

- **Suite budget (+6, §5)**: arithmetic holds per probe — AC1 1 scaffold, AC2 1 gate run, AC3 3, AC4 outcome 1, mechanism 0. Baseline ≈12 recounted from the 13 tests (10 gate-run re-scaffolds + fixture scaffold + remediation execution) — matches.
- **Fixture isolation**: `mutable_repo` is a plain `shutil.copytree` into the per-test `tmp_path` (harness L79–83); `fresh_repo` is module-scoped, scaffolded once (L66–75). Narrowing one clone cannot leak into another test's clone. Isolation claims hold.
- **D2's detection predicate**: `scaffolded_skill_names` (badger_lib.py L868–880) returns 32 on the healthy manifest and ignores per-file provenance rows — the `⊊` math is sound.
- **AC4's two-tier structure**: mechanism + outcome tiers both bind the real pre-fix output; the positive/disjunction layer is correctly structured (flagless argv delegates the behavioural proof to AC3's manifest pin, as documented).

## Verdict

**REQUEST-CHANGES.**

What survived verification: the detection design (D2's `⊊` check, `scaffolded_skill_names`), AC3's sequence, AC4's regex and two-tier structure, the fixture-isolation and +6-budget claims.

What did not: the red-first protocol itself — the thing this plan hangs its honesty on — rests on a pre-fix behavior model that is false on this tree in three places. AC2's claimed blindness PASS is unobtainable for every possible victim (F-QA3: adjustment rows poison 30/32 victims; stack-local re-delivery poisons the other 2). AC1's control fails on `.git/index` noise (F-QA5). D6b's post-fix invariant contradicts D3 (F-QA4). The runbook that produces the witnesses cannot run the guard at all as written (F-QA1), and Package 7's merge gate is weaker than the repo's own d-16 MUST ruling for this exact flake class (F-QA2). All five MUST defects are fixable at plan level: re-baseline the RED expectations against observed shapes, scope the AC1 digest to the managed tree, restate D6b per-transport, repair the runbook's scratch setup, and require two consecutive green full-suite runs.
