# MoE reviewer lane — R3 remediation semantics, R4 risk, R5 placement + release (sections 3–5 of the plan)

Task: `aib-scaffold-freshness-guard-blindspot-proof` · Target: main @ `19e28a7b` (v0.149.1) · Date: 2026-08-31

Companion to `docs/work/2026-08-31-scaffold-freshness-guard-research.md`. Every behavior claim cites file:line read in this worktree; unverified statements are labelled **hypothesis**.

## 1. R3 — remediation semantics (the exact post-fix form)

### 1.1 The defect, restated at line level

`rescaffold_argv()` (gates/scaffold_freshness_guard.py:128–133) returns `… --no-install --skills ""`, and `remediation()` (L135–137) renders that same argv as the printed advice — so the guard's internal re-scaffold (`rescaffold()`, L142–159) and the operator's repair share one builder. The empty `--skills` engages the scaffolder's #129 recovery path (features/common/skills/welcome-ai-badger/scripts/scaffold.py:806–821): `skills = bl.scaffolded_skill_names(bl.load_json(manifest_path))` (L814) — the set comes **from the manifest being audited**. A manifest that under-reports the managed set therefore makes both the guard's verdict and the printed repair reproduce the narrowing. That is the trap: following the guard's own advice regenerates the same narrowed set (research record §2, 0.147.0 changelog witness).

### 1.2 Decided form: explicit config-derived list, no recovery mode in the guard's argv

**`rescaffold_argv` returns `--skills <sorted-expected-set>` — never `--skills ""`, never a bare omission.** (The task's "union" framing is deliberately answered in the negative: the manifest contributes nothing to the list.) The set is `expected_skill_names(root, config)`, computed once and threaded into both `rescaffold()` and `remediation()` through the same builder, preserving the printed-advice-is-what-the-guard-ran property by construction.

> **SUPERSEDED by rev-2 D1 (API-F1):** "sorted" is wrong at the order level — the expected
> set must carry `Scaffolder`'s delivery BLOCK order (defaults block, include-derived block,
> stack-local in `resolve_stacks` order); a flat-sorted list reorders manifest rows, which
> the guard's `normalized()` preserves, and fails healthy trees. Everything else in this
> section stands (config-derived, front-door-trap argument, shared helper).

The set is **config-derived, not manifest-recovered and not manifest∪config**: it is exactly what the scaffolder delivers when `--skills` is omitted — `DEFAULT_SKILLS` (scope:`default` walk, scaffold.py:157, bl.default_skills_in badger_lib.py:782–784) ∪ config-include-expanded skills (scaffold.py:262–270) ∪ stack-local discovery (skill_delivery.py:254–270, called unconditionally in run() at scaffold.py:711) − `excluded["skills"]` (scaffold.py:263, 278).

**Where the union/expected set is computed:** not re-derived a second time inside the guard. The derivation above is spread across `Scaffolder.__init__` (scaffold.py:262–273) and `SkillDelivery.discover_stack_local` (skill_delivery.py:254–270); the fix extracts it into one helper (engine/badger_lib.py, next to `default_skills_in`/`scaffolded_skill_names` at L782/L868) that both `Scaffolder.__init__` and the guard call. This is the same helper R2 needs to compare the manifest against the config — R3's list and R2's fail-fast share one oracle, so they cannot drift. The guard additionally **refuses loudly (Refusal, exit 2) if the computed set is empty** — an empty expected set is a broken derivation, never a licence to fall back to recovery.

**Why config-derived and not manifest∪config:** a skill removed from `config.json include` but still present in the manifest must surface as a finding ("the re-scaffold no longer writes it") — the union would keep regenerating it forever, silently preserving a config the project declined. Config-derived is also the honest definition of "fresh": what an unattended scaffold of this config produces.

**Why not drop the flag (catalog defaults):** with `--skills` omitted, the default is `",".join(DEFAULT_SKILLS)` (scaffold.py:774); if the import-time catalog walk ever returns empty, the default is `""`, `skills` (L806) is `[]`, and **the recovery path engages silently again** (L807–821) — the exact trap R3 removes, back through the front door. The explicit form's degenerate case is a loud Refusal; the omission form's degenerate case is the blindness itself. That asymmetry is decisive.

**Why not change #129 semantics in the scaffolder:** the empty-value reuse mode is legitimate for consumers (pinned by tests/test_scaffold_empty_skills.py; scaffold.py:809–812 documents the fresh-target branch — module docstring L17–19 states the recovery rule). The guard is the only caller that must never use it; fixing it there keeps the scaffolder contract untouched.

### 1.3 Failure-mode table (option × failure mode × verdict)

| Failure mode | A: drop the flag | B: explicit config-derived list (chosen) | C: union at recovery time inside the scaffolder |
|---|---|---|---|
| Operator pastes into a non-POSIX shell (fish/PowerShell) | Env-assignment prefix `VAR=v cmd` already fails there — pre-existing, unchanged (guard L139 renders `AI_BADGER_MCP_AVAILABILITY=all` first). Verdict: accept, note in changelog. | Same prefix; the skill list is one ordinary argv element needing no quoting (commas are shell-inert; remediation() already `shlex.quote`s every arg, L139). Verdict: accept, unchanged risk. | Same as A/B. Verdict: accept. |
| Long command wrapping | Shortest form. | Adds ~32 sorted names (21 scope-default + 10 config-include + 2 stack-local − exclusions; manifest records 32) ≈ +0.5 KB. Guard prints one line (check() L329–334); terminals soft-wrap without inserting newlines, and the test's joiner (tests/test_scaffold_freshness_guard.py:225–231) already tolerates continuations. Verdict: **accept** — copy-paste safety beats brevity; determinism (sorted) keeps the advice stable. | Same length as B. |
| Command regenerates MORE than the project declared | When the default walk breaks, silently regenerates LESS (recovery), not more. If it works, equals B. | The set is by construction what an unattended scaffold delivers; if the derivation ever over-collects, the guard's own tree-vs-tree diff (collect()/differences(), L275–319) turns the surplus into findings — the failure is self-reporting, not silent. Verdict: **accept**. | Union widens recovery to include defaults — a consumer whose narrow manifest was deliberate gets skills it declined. Changes #129 semantics for everyone (breaks test_scaffold_empty_skills.py). Verdict: **reject**. |
| Manifest absent (fresh consumer repo, or manifest deleted) | Defaults to catalog set; okay when the walk works; silent recovery when it does not. | Needs no manifest at all — advice regenerates the declared set and converges. Today the same state yields `skills=[]` (L806–812: no manifest ⇒ nothing recovered) and the guard advice would loop. Verdict: **accept — strictly better than every alternative**. | Recovery of nothing + defaults; okay but couples scaffolder. Verdict: reject (as C above). |

### 1.4 Verification against AC4 and AC3

**AC4 (no `--skills` + empty value in rendered output):** the test parses `_printed_remediation(failed.stdout)` (existing helper, tests/test_scaffold_freshness_guard.py:225–231) and asserts the `--skills` argument, if present, is a non-empty comma-joined name list — i.e. the substring `--skills ''` / `--skills ""` never occurs, and the list is non-empty and sorted. RED-first: this fails on the current output, which contains `--skills ''` verbatim (guard L132 → remediation L135–137 → check() L334).

**AC3 (remediation executed verbatim cannot hide a hand-edited mirror):** construct a tree whose manifest under-reports one skill whose mirror exists on disk and is hand-edited. Pre-fix, the printed advice (`--skills ''`, recovery from the narrowed manifest) leaves the orphan mirror untouched → the follow-up guard run passes with the edit in place — the d-16 incident as a test. Post-fix, the advice carries the config-derived list, the re-scaffold regenerates that mirror from source, and the assertion is: **after running the printed advice verbatim, the mirror's content equals its framework source's content** (`normalized()` equivalence, guard L216–235) — the edit is either overwritten (correct: mirrors are framework-owned) or the guard still fails, never both-green-and-edited. The existing `test_the_printed_remediation_produces_a_tree_the_gate_then_passes` (tests/test_scaffold_freshness_guard.py:233–257) keeps executing the advice on a minimal PATH; the narrowed-manifest variant extends it rather than replacing it.

## 2. Risk inventory (keep / change / watch)

Every item names the file:line evidence read in this worktree. Dispositions: **keep** = no action, protected by existing tests; **change** = the fix must touch it deliberately; **watch** = the fix must not break it, and a named test/probe covers it.

| # | Item | Disposition | Evidence & consequence |
|---|---|---|---|
| 1 | `test_the_printed_remediation_produces_a_tree_the_gate_then_passes` | **change** | tests/test_scaffold_freshness_guard.py:233–257 executes the printed advice verbatim on a minimal PATH (`PATH=/usr/bin:/bin`, L250–251) and asserts the gate then passes. Post-fix it still passes (the explicit list removes the manifest dependency, so the minimal-PATH run is *more* deterministic); it gains the AC4/AC3 sibling assertions (§1.4). The `_printed_remediation` joiner (L225–231) tolerates the longer line. |
| 2 | `test_the_rescaffold_points_hermes_home_away_from_the_operators` | **keep** | tests/test_scaffold_freshness_guard.py:260–277 calls `guard.rescaffold(work)` directly (L268) and asserts `HERMES_HOME` containment. `rescaffold()` (guard L142–159) keeps its env wiring; only the argv builder's payload changes. |
| 3 | Fixture `_freshen()` uses `--skills ""` | **change** | tests/test_scaffold_freshness_guard.py:47–61 scaffolds the fixture with the recovery mode — the fixture itself trusts manifest recovery, so a narrowed real manifest yields a "fresh by construction" fixture that is blind the same way (research record §2). Post-fix the fixture must use the same argv form the guard builds (via the shared helper), or the fixture enshrines a narrowing the guard now rejects. Research §3 says the live manifest is healthy (32/32 skill entries, 212 total), so no fixture-content change is expected. |
| 4 | Operators who scripted the old remediation | **change** | The printed command's shape changes (guard L135–137 renders the new argv). The old command keeps *running* — `--skills ''` recovery stays legitimate (scaffold.py:806–821) — but stays blind on narrowed manifests. Mitigation: changelog upgrade note (§5) + R5 gotcha note (§4). |
| 5 | Pre-push / pre-commit lane runtime | **watch** | The guard runs as a pre-commit hook (.pre-commit-config.yaml:48) and is imported by the consumer-journey gate (gates/consumer_journey.py:38). Same single subprocess, same env — runtime unchanged. Landing cost: if the live manifest were narrowed, the first post-fix run fails loudly and needs a one-time mirror/manifest regen commit; research §3 indicates it is healthy, so landing should be clean (the `frameworkDirty: true` caveat in that manifest is stamp-class, exempt per guard STAMP_KEYS L57–58). |
| 6 | Legitimate `--skills ''` reuse mode (#129) | **keep** | tests/test_scaffold_empty_skills.py pins it; scaffold.py:806–821 is untouched by R3. The guard is the only caller that stops using the mode. |
| 7 | `manifest.json.partial` (F-25) | **keep** | Crash breadcrumb written/removed by the scaffolder itself (scaffold.py:189, 682). With an explicit list the guard's argv no longer reads `manifest.json` at all — a leftover `.partial` cannot influence the guard's repair. den-refresh's flow is unaffected. |
| 8 | Hermes-home containment & `relink_hermes_skills` | **keep** | `relink_hermes_skills` runs only under `if self.install:` (scaffold.py:715) — `--no-install` (guard L132) skips it; the guard additionally points `HERMES_HOME` at a throwaway (guard L152), asserted by test #2. The printed advice also carries `--no-install`, so an operator following it installs nothing. |
| 9 | Consumer repos with legitimately narrow configs | **watch** | The guard cannot meaningfully run on a consumer repo: `rescaffold()` executes `work/features/common/skills/…/scaffold.py` (guard L153–155), which does not exist outside the framework root ⇒ `SCAFFOLDER FAILED` Refusal (L158–159) before any remediation prints; gates/consumer_journey.py:404 documents "A project has no `scaffold_freshness_guard`". The real consumer risk is the shared derivation helper: extracting it must be behavior-neutral for `Scaffolder` (guarded by the full suite + test_scaffold_empty_skills.py). |
| 10 | Index staleness silently skipping a requested skill | **watch** | `find_skill_in_stacks` → None ⇒ note "skill 'X' not in any configured stack — skipped" (skill_delivery.py:278–280): an explicit list does **not** guarantee delivery. R3 removes the manifest-recovery trap; converting this residual silent under-production into a named failure is R2's fail-fast, which shares the derivation helper. Cross-referenced, not duplicated here. |
| 11 | `prune_discovery` / `may_prune` semantics | **watch** | `prune_discovery = bool(skills)` (scaffold.py:271–273) feeding host-skill pruning (features/claude/adjustments/adjust_skills.py:66–68). Today's recovery path already yields a non-empty list on any manifest-bearing tree, so only the manifest-absent case flips False→True — inside the guard's throwaway copy only. The AC0 double-scaffold determinism protocol (§3) is the tripwire for phantom findings. |
| 12 | `SupersededPrune` against a manifest that is a superset of config | **change (intended)** | run() prunes prior-manifest entries not in the delivered list (scaffold.py:706). A config-derived list makes the guard's re-scaffold actively drop skills the config no longer declares → new "no longer writes it" findings where the old guard silently passed. That surfacing is the point; it must be named in the changelog (§5) so a one-time diff is not mistaken for a defect. |
| 13 | Guard's own explanatory comments/docstrings | **change** | The builder docstring (guard L129) and `remediation()` docstring (L135–137, "the command that makes a stale tree fresh") currently document the trap-form; both must describe the config-derived form, or the next reader re-introduces the shortcut. |

## 3. R4 — verification protocol (AC0 confirmation on the fix branch)

Research record §3 measured the live manifest healthy at 0.149.1 (32/32 skill-dir entries vs `.ai-badger/skills/` on disk, 212 total entries): the 42-path loss from the 0.148.0 era appears already repaired. AC0 on the fix branch is therefore a **confirmation**, not a repair — and it doubles as the determinism tripwire for risk #11 (§2): if the double-scaffold is not idempotent on the branch, the branch's own lane is untrusted and must not ship.

### 3.1 The protocol (runnable verbatim; read-only on the repo — scratch copies only)

```bash
WT=/Users/arasz/RiderProjects/ai-badger/.ai-badger/worktrees/aib-scaffold-freshness-guard-blindspot-proof
SCRATCH=$(mktemp -d /tmp/aib-ac0-XXXXXX)
git -C "$WT" archive HEAD | tar -x -C "$SCRATCH"      # read-only export; no git state touched
cd "$SCRATCH" || exit 1
git init -q
git add -A
git -c user.email=ac0@example.com -c user.name=ac0 commit -qm baseline
export AI_BADGER_MCP_AVAILABILITY=all                   # the guard's own env (guard L50)
STAMP=2026-08-31T00:00:00Z                              # fixed clock: scaffold.py --generated-at
python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py \
  --config .ai-badger/config.json --target . --root . \
  --no-install --generated-at "$STAMP" 2>&1 | tee /tmp/ac0-run1.log
git status --porcelain | sort | tee /tmp/ac0-status1.txt
git add -A && git commit -qm "scaffold run 1"
python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py \
  --config .ai-badger/config.json --target . --root . \
  --no-install --generated-at "$STAMP" 2>&1 | tee /tmp/ac0-run2.log
git status --porcelain | tee /tmp/ac0-status2.txt       # MUST be empty
! grep -q "reused" /tmp/ac0-run1.log /tmp/ac0-run2.log  # recovery path (#129) never engaged
! grep -q "not in any configured stack" /tmp/ac0-run1.log /tmp/ac0-run2.log
python3 - <<'PY'
import json
m = json.load(open(".ai-badger/manifest.json"))
skills = [e for e in m["entries"] if e.get("feature") == "skills" and "/" not in e.get("name", "")]
print(f"{len(skills)} skill entries, {len(m['entries'])} total")
PY
python3 gates/scaffold_freshness_guard.py --root "$SCRATCH"   # expect: PASS, exit 0
```

### 3.2 What each step proves

- **`git archive HEAD`** — the branch's committed tree, exported without touching the worktree (research §6 forbids scaffolding the task worktree itself).
- **`--generated-at "$STAMP"`** — without it `generatedAt` churns every run (stamp key, guard L57–58) and "git status clean" would be untestable. With it, run 2's zero-diff is meaningful.
- **Run 1's expected diff (`/tmp/ac0-status1.txt`)** — stamp-class paths only: `.ai-badger/manifest.json` (`frameworkCommit` now names the scratch commit, `frameworkDirty` flips to false, `generatedAt` fixed), possibly `config.json`. All are STAMP_KEYS (guard L57–58) or stamp lines (guard L59). Any *non-stamp* path here is a real repro of narrowing and fails AC0.
- **Run 2's empty status** — the scaffold is idempotent on a clean tree; a second-run diff is the nondeterminism F1 witnessed.
- **No `reused` note** — scaffold.py:816 prints it iff the #129 recovery path engaged; its absence proves the run was driven by the declared set, not the manifest.
- **32/32, 212 total** — the numbers measured at 19e28a7b (research §3); the branch's own output is the baseline to record, and the two runs must print identical counts.
- **Guard PASS** — the guard's internal re-scaffold (a third scaffold, in its own throwaway copy) agrees with the double-scaffold result; this is the AC0 sentence "guard passes".

### 3.3 If narrowing reproduces on the branch

1. **Capture before touching anything:** keep `/tmp/ac0-run*.log` (the `reused N` / `not in any configured stack` notes are the d-16 "reused 11 of 32" shape — research §4 lead 1) plus per-run manifest counts; re-run with several `PYTHONHASHSEED` values and with `.git` removed from the scratch copy (lead 5, extracted-tree factor). That evidence belongs in the research record, not the changelog.
2. **The branch's own lane is then untrusted:** AC2 (under-produced-manifest scenario) stays RED-first in the suite, and R3's Refusal-on-empty derivation plus R2's manifest-vs-config fail-fast become load-bearing rather than belt-and-braces.
3. **AC0 is a ship condition:** the release (§5) is blocked until §3.1 is green on the branch — a guard that can go blind on its own tree must not go out with a changelog claiming the opposite.
4. Root-cause work escalates to R1 (the plan's separate lane); R3/R5 do not depend on R1's answer, which is why this protocol can confirm independently.

## 4. R5 — placement (where the gotcha lives)

**The gotcha, in two sentences:** never remediate a scaffold-freshness-guard failure with `--skills ''` — the empty value recovers the skill list *from the manifest being audited* (scaffold.py:806–821), so on a narrowed manifest it regenerates the same narrowed set and the guard goes green over the very defect it reported. And every regenerated mirror (`.ai-badger/skills/**`, agent files, `.ai-badger/manifest.json`) rides in the **same commit as the source edit that made it stale** — a mirror committed alone is the guard catching up to something that already shipped.

### 4.1 Decided locations (minimal honest set = 2 + the changelog)

1. **The guard's own failure output** (gates/scaffold_freshness_guard.py:333–334). R3 already changes what is printed there; the fix adds one rationale clause to the `Re-scaffold this repo…` line, stating the skill list is explicit **so a narrowed manifest cannot narrow the repair**. This is the only location a person is guaranteed to be reading at the moment of the mistake, and it self-documents why the argv must never be "simplified" back to `--skills ''`. No separate prose block — the advice *is* the fix.
2. **`features/common/skills/welcome-ai-badger/SKILL.md`, Gotchas section (L123)** — the source of truth, adding both sentences above as the fourth bullet. This is where agents and developers go when the guard's message is not enough, and it is the skill whose mirrors are the usual subject of the staleness. Both gotchas belong there: the `--skills ''` trap (it is this skill's own flag whose empty value is dangerous *in this context*) and the same-commit rule (it is this skill's delivery contract).
3. **The changelog entry's upgrade note (§5)** — covers operators who scripted the old remediation and never open either of the above (risk #4, §2).

**Not README.md:** the README names the guard once, in the gates table (README.md:73), and its workflow sections are bootstrap/refresh commands (L119–141) — neither audience is mid-remediation when reading it. Adding remediation prose there violates the minimal-honest-set rule without reaching anyone the two locations above miss.

### 4.2 The mirror question, answered with the guard's own mechanism

Editing `.ai-badger/skills/welcome-ai-badger/SKILL.md` (the mirror) instead of the source would be **hand-editing exactly what the guard now catches**: skill entries are a `hashes_source` feature type (engine/badger_lib.py:50 — `FeatureType("skills", "skills", True)`), so `classify()` compares the mirror against the recorded *source* hash (guard L250–264: `recorded_source = entry.get("sourceHash")`; STALE when the source moved, HAND_EDITED when it did not). The behavior is witnessed by `test_a_hand_edited_mirror_is_reported_as_such` (tests/test_scaffold_freshness_guard.py:123–131), which hand-edits `SKILL_MIRROR/SKILL.md` and asserts the `hand-edited` verdict. Therefore: the R5 edit lands in `features/…/SKILL.md`, the regenerated mirror is committed alongside it in the same commit, and the guard passes on the pair — the placement decision is itself a worked example of gotcha #2. If the mirror edit were made alone, the pre-fix guard would pass it only when the manifest is narrowed — the defect this whole plan removes.

## 5. Release discipline (version bump + changelog)

### 5.1 Version: 0.150.0 — confirmed

RELEASING.md's rule: **0.MINOR** is "anything that changes what scaffolding *does* to a consumer repo: … changed hook contracts, changed detection behavior"; **0.x.PATCH** is "content fixes to existing files that do not alter scaffold output shape"; and "the number tracks blast radius, not intent". This change (a) rewrites the guard's printed remediation contract — an operator-visible command whose shape scripted workflows may embed (risk #4, §2) — and (b) routes the scaffolder's skill-set derivation through a shared helper (§1.2), which is scaffold-adjacent behavior, not a content fix. Minor is correct.

Honest caveat: 0.77.2 shipped a guard-only fix as a patch (`0.77.2-freshness-guard-host-independent.md` — the `=all` env override). That change altered the guard's *internal* determinism without touching its output contract; here the output contract itself changes, so the precedent does not govern. 0.149.1 was a docs-only patch already cut; this is a distinct behavioral unit. **0.150.0 stands** (as assigned at dispatch, research record §5).

### 5.2 Changelog entry

New file `docs/changelog/0.150.0-remediation-cannot-be-narrowed.md` (one file per release, named after the version it ships at — docs/changelog/README.md header; slug style follows e.g. `0.99.0-a-gate-nobody-enumerates.md`). Format per the 0.149.x entries: `# <version> — <title>` headline paragraph, then **What changed** bullets and an **Upgrade notes** section carrying: the printed remediation's new shape (scripts embedding `--skills ''` keep running but stay blind — risk #4), the intended new "no longer writes it" findings when the manifest is a config superset (risk #12), and the two R5 gotchas (§4). Classification: **Minor**.

### 5.3 Every file the bump touches (the version-bump surface)

| File | Why | Mechanism |
|---|---|---|
| `VERSION` | single source of truth (version_sync.py:4; bl.read_version) | hand-edit `0.149.1` → `0.150.0` (RELEASING.md step 1) |
| `docs/changelog/0.150.0-remediation-cannot-be-narrowed.md` | the entry itself | hand-written (step 2) |
| `docs/changelog/README.md` | release table row | `python3 tooling/changelog_index.py` regenerates it — never hand-edited (issue #160; RELEASING.md step 3) |
| `.claude-plugin/plugin.json` | top-level `"version"` | `tooling/version_sync.py` (version_sync.py:38, 63–66; step 4) |
| `.claude-plugin/marketplace.json` | `plugins[]` entry whose name matches plugin.json's, `"version"` | version_sync.py:39, 67–73 |
| `index.json` | `"frameworkVersion"` | version_sync delegates the whole file to `index_build.main` (version_sync.py:76–77) |
| `.ai-badger/manifest.json` + every `Scaffolded by ai-badger <v>` line under `*.md`, `.*.md`, `.ai-badger/*.md`, `.github/*.md` | scaffold stamps | **reported, never rewritten** by version_sync (version_sync.py:87–127; the rule is the docstring at L90; the stamp patterns are L102) — fixed by re-running welcome-ai-badger and committing the regenerated mirrors + stamps in the same commit (RELEASING.md step 5's check enforces it; §4's same-commit rule applies verbatim) |

Must pass before push (RELEASING.md steps 5–6): `version_sync.py --check`, `changelog_index.py --check`, `gates/release_guard.py`, full pytest, pylint — plus the plan's own gates (research record §6: index_build `--check`, `verify.sh pre-push`). CI is the pass condition.

## 6. Acceptance-criteria cross-check

| Doc criterion | Where satisfied |
|---|---|
| R3 form decided with the failure-mode table | §1.2 (form + where computed + why not the alternatives), §1.3 (table) |
| Risk inventory with dispositions and file:line evidence | §2, items 1–13 |
| AC0 protocol runnable verbatim | §3.1 (block), §3.2 (per-step meaning), §3.3 (repro contingency) |
| R5 placement + exact locations | §4.1 (guard output + SKILL.md Gotchas + changelog; README rejected), §4.2 (mirror question resolved by classify()/FeatureType evidence) |
| Release file list complete | §5.3 (all six version_sync surfaces + the stamp surface + entry/index files), §5.1 (version ruling), §5.2 (file name + format) |

Fix-level AC mapping: AC4 and AC3 in §1.4; AC0 in §3; AC1 (consecutive-run determinism) is proven operationally by §3.1's run-2 empty status; AC2 (under-produced-manifest scenario) is R2's red-first test, referenced at §2 item 10 and §3.3 but owned by the R2 lane. Every claim above cites lines read in this worktree at the task branch's checkout of `19e28a7b` descendants; the one forward-looking statement — that the extracted-helper refactor is behavior-neutral — is a **hypothesis** until the full suite runs on the fix branch (§2 item 9).
