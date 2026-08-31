# RED witnesses — scaffold freshness guard blind-spot-proof (Package 1)

Task: `aib-scaffold-freshness-guard-blindspot-proof` · Pre-fix code at branch HEAD (docs-only
commits atop base `19e28a7b`; zero code delta from base) · 2026-08-31

Every artifact below was produced inside a `/tmp` scratch copy, never against the task
worktree. Scratch setup is fixture-style per QA-F1 (the rev-1 runbook's `rsync --exclude .git`
produces guard refusals — probe 1): copy the tree, `git init` + user config + `add -A` +
commit (harness L66–72 shape), then a `_freshen`-equivalent self-scaffold with `--skills ""`
+ commit. The `_freshen` step reported `reused 32 skill(s)` on every scratch — healthy
recovery from a complete manifest.

Setup (each scratch):

```
SCRATCH=$(mktemp -d /tmp/aib-red-<tag>-XXXXXX)
git -C <worktree> archive HEAD | tar -x -C "$SCRATCH"
git -C "$SCRATCH" init -q && git -C "$SCRATCH" config user.email witness@example.com
git -C "$SCRATCH" config user.name witness && git -C "$SCRATCH" add -A
git -C "$SCRATCH" commit -qm baseline
cd "$SCRATCH" && AI_BADGER_MCP_AVAILABILITY=all /usr/bin/python3 \
  features/common/skills/welcome-ai-badger/scripts/scaffold.py \
  --config .ai-badger/config.json --target . --root . --no-install --skills ""
# → "--skills was empty — reused 32 skill(s) already scaffolded"
git -C "$SCRATCH" add -A && git -C "$SCRATCH" commit -qm "self-scaffold"
```

Interpreter: `/usr/bin/python3` (3.x with jsonschema; pytest 8.4.2 for the mechanism-tier
snippet). `python3`→`/usr/bin/python3` substitution in executed advice mirrors the harness.

---

## ⚠ Plan-deviation finding (STOP-and-report per dispatch): AC2's rebuilt recipe cannot
## produce its claimed pre-fix PASS

The plan (Package 1, QA-F3 rebuilt recipe) states: victim = pure scope-default skill, strip
**every** manifest row naming the victim (mirror rows AND out-of-mirror adjustment rows),
pre-fix expectation = guard exit 0 PASS. **Applied verbatim, this yields exit 1, not 0.**

Reason (traced to source): stripping the rows makes the manifest self-consistent, but the
TREE still holds the victim's out-of-mirror host links (`.claude/skills/<v>`,
`.github/skills/<v>`), and the pre-fix guard's internal re-scaffold — recovering the narrowed
31-skill set — **itself removes those links**:

```
note: adjustment 'skills' for 'claude': Symlinked 29 skill(s) into .claude/skills/; removed .claude/skills/ai-raccoon-memory — no longer delivered to this project
```

(`prune_discovery = bool(skills)` is True under recovery with 31 skills, so the adjustments
step prunes undelivered skills' host links.) The tree-vs-tree diff then reports
"the re-scaffold no longer writes it" ×2 → exit 1. Hand-stripping manifest rows cannot make
the tree self-consistent because the host links are files, not rows.

**The true d-16 blindness shape (probe c1: "tree-vs-tree diff clean") is reachable** — but
only when the narrowing is produced *by a narrowed run* (which removes the host links as it
goes and leaves the lost mirrors on disk). That is exactly the D6b list-form transport
(the `ea17ae60` shape). Both artifacts are recorded below: the plan-recipe run (exit 1 — the
plan's expectation falsified) and the narrowed-run recipe (exit 0 PASS — the blindness,
witnessed). Package 4's pytest uses the plan's recipe: post-fix assertions (D2 fail-fast
fires before any re-scaffold) hold under either recipe, and the plan binds the test to the
rebuilt recipe.

---

## AC2 — manifest-narrowing blind spot

### AC2 (a) — plan's rebuilt recipe, applied verbatim (expectation falsified)

Victim picked deterministically: first manifest skill row (block order) that is scope-default,
not config-include-derived, not stack-local → `ai-raccoon-memory`. Hand-edit:
`echo '\nEdited in place.\n' >> .ai-badger/skills/ai-raccoon-memory/SKILL.md`. Narrow: strip
every entry whose target matches `(?:^|/)skills/ai-raccoon-memory(?:/|$)`.

```
victim: ai-raccoon-memory
manifest entries: 212 -> 209 (stripped 3 rows)
```

Command: `AI_BADGER_MCP_AVAILABILITY=all /usr/bin/python3 gates/scaffold_freshness_guard.py --root /tmp/aib-red-ac2-Xwh8cv`
Exit code: **1** (plan expected 0/PASS)

```
SCAFFOLD FRESHNESS GUARD FAILED: re-scaffolding this repo against itself would change 2 of 1946 path(s):
    .claude/skills/ai-raccoon-memory  (the re-scaffold no longer writes it, regenerates differently)
    .github/skills/ai-raccoon-memory  (the re-scaffold no longer writes it, regenerates differently)
Re-scaffold this repo against itself and commit the result:
    AI_BADGER_MCP_AVAILABILITY=all python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root . --no-install --skills ''
```

### AC2 (b) — the d-16 blindness shape (narrowing produced by a narrowed run)

Fresh fixture-style scratch → narrowed RUN via the list-form transport (D6b E1's exact
command) → self-consistent narrowed tree (host links removed by the run itself, mirrors left
on disk) → hand-edit a LOST mirror (`ai-raccoon-memory`, absent from the narrowed manifest's
11 rows, mirror still on disk):

```
narrowed manifest: 11 skill rows, 128 total entries
mirror still on disk: True
host link removed: True
hand-edited a LOST mirror
```

Command: `AI_BADGER_MCP_AVAILABILITY=all /usr/bin/python3 gates/scaffold_freshness_guard.py --root /tmp/aib-red-ac2c-TaHg6B`
Exit code: **0**

```
1904 path(s) compared against a re-scaffold of this tree; only version stamps differ — PASS
```

This is the blindness the fix must remove: a hand-edited mirror whose manifest coverage is
gone passes the guard pre-fix.

---

## AC3 — remediation re-blinding trap (8 steps, RED at assertions 6 + 8)

Scratch `/tmp/aib-red-ac3-nC7OuK`. Step 2: narrow manifest (plan recipe:
212 → 209 entries, 32 → 31 skill rows, victim `ai-raccoon-memory`). Step 3: add
`features/common/skills/welcome-ai-badger/scripts/added_after_scaffold.py`.

**Step 4 — guard#1** (`AI_BADGER_MCP_AVAILABILITY=all /usr/bin/python3 gates/scaffold_freshness_guard.py --root /tmp/aib-red-ac3-nC7OuK`), exit code: **1**

```
SCAFFOLD FRESHNESS GUARD FAILED: re-scaffolding this repo against itself would change 4 of 1948 path(s):
    .ai-badger/skills/welcome-ai-badger/scripts/added_after_scaffold.py  (the re-scaffold writes it; the tree has not got it, stale)
    .claude/skills/ai-raccoon-memory  (the re-scaffold no longer writes it, regenerates differently)
    .github/skills/ai-raccoon-memory  (the re-scaffold no longer writes it, regenerates differently)
    .ai-badger/manifest.json  (content differs, regenerates differently)
Re-scaffold this repo against itself and commit the result:
    AI_BADGER_MCP_AVAILABILITY=all python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root . --no-install --skills ''
```

(guard#1 carries FOUR findings, not probe 3's two — the two host-link prune findings join for
the same adjust-skills reason documented under AC2(a). A remediation is still capturable; the
§2 "no remediation without step 3" rationale stays superseded either way.)

**Step 5 — remediation executed verbatim** (python3→/usr/bin/python3, `PATH=/usr/bin:/bin`,
shell), exit code: **0**. Note captured from its stdout:

```
note: --skills was empty — reused 31 skill(s) already scaffolded, from the manifest at /private/tmp/aib-red-ac3-nC7OuK/.ai-badger/manifest.json
```

**Step 6 — manifest-regeneration pin:** `victim mirror rows in manifest: 0 | total entries: 209`
→ **ASSERTION 6 RED** — the advice re-blinded the tree (recovered the narrowed set; `31 < 32`).

**Step 7 —** mirror file existed (precondition held); appended `\nEdited in place.\n`.

**Step 8 — guard#2** (same command), exit code: **0**

```
1946 path(s) compared against a re-scaffold of this tree; only version stamps differ — PASS
```

→ **ASSERTION 8 RED** — the hand-edit is invisible; the trap sequence is fully witnessed.

---

## AC4 — remediation message audit (no empty `--skills`)

Regexes carried by the test file (test-engineer §3):
`EMPTY_SKILLS_RE = --skills(?:=|\s+)(?:""|''|$)` · `NONEMPTY_SKILLS_RE = --skills(?:=|\s+)(?:""|''|$)[^\s"']+`

**Outcome tier** — AC3 guard#1's rendered remediation line, verbatim:

```
    AI_BADGER_MCP_AVAILABILITY=all python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root . --no-install --skills ''
```

`EMPTY_SKILLS_RE.search` → `match="--skills ''"` at span (663, 674) of the guard stdout;
`NONEMPTY_SKILLS_RE.search` → no match (correctly rejects the pre-fix line).

**Mechanism tier** — pre-fix 5-arg `rescaffold_argv(sys.executable, SCAFFOLD, CONFIG, ".", ".")`,
space-joined tail:

```
joined argv tail: '-root . --no-install --skills '
EMPTY_SKILLS_RE match: match='--skills ' (span (171, 180))    ← the trailing-space + EOS shape (QA-F9)
```

`guard.remediation()` rendered: `EMPTY_SKILLS_RE match="--skills ''"` at span (165, 176).

Both tiers RED pre-fix; the mechanism tier confirms the trailing-space shape matches via the
`$` alternative.

---

## AC1 — consecutive-run idempotence (CONTROL — expected pre-fix GREEN, as designed)

Scratch `/tmp/aib-red-ac1-nzE8gK` (fixture-fresh, committed). Clone B = copytree; second
scaffold driven directly against scaffold.py with explicit env
(`env -i HOME=… PATH=/usr/bin:/bin AI_BADGER_MCP_AVAILABILITY=all HERMES_HOME=<scratch>/hermes-home`)
and pinned clock `--generated-at 2026-01-01T00:00:00Z`. Exit code: **0**; stdout note:
`reused 32 skill(s)`.

Digest comparison scoped to the managed tree (QA-F5: `.git` excluded explicitly; guard
`is_noise` semantics for `__pycache__`/`.pyc`), then the guard's own `normalized()` applied to
every differing path:

```
paths compared: 2415 (clone A) / 2415 (clone B); differing paths: ['.ai-badger/manifest.json']
residual differences after stamp normalization: []
AC1 CONTROL: GREEN — identical modulo stamps
```

Raw cross-check (`diff -rq` incl. `.git`): exactly `manifest.json` + `.git/index` differ —
probe 6's shape. The `.git/index` noise is why the digest is `.git`-scoped.

---

## D6b — transport contract, RED side (per-transport restatement per QA-F4)

**E1 — list-form `["--skills", "''"]` (non-shell transport):** fresh scratch
`/tmp/aib-red-d6b-list-LwWiC9`; command
`AI_BADGER_MCP_AVAILABILITY=all /usr/bin/python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root . --no-install --skills "''"`
— exit code: **0**

```
scaffolded 128 entries into /private/tmp/aib-red-d6b-list-LwWiC9/.ai-badger
  note: skill '''' not in any configured stack — skipped
```

```
manifest: 11 skill rows, 128 total entries
```

The `ea17ae60` under-production shape: literal two-char "name", no recovery (no `reused`
note), silent skip, narrowed manifest. The host links of the 21 lost skills are removed by
the run itself; their mirrors are left on disk.

**E2 — shell transport `--skills ''` (shell strips the quotes → true empty):** fresh scratch
`/tmp/aib-red-d6b-shell-*`; same command with `--skills ''` unquoted-quoted for the shell —
exit code: **0**

```
--skills was empty — reused 32 skill(s) already scaffolded
manifest: 32 skill rows, 212 total entries
```

Neither transport under-delivers *silently-and-wrongly* post-fix: list-form must refuse (exit
2, quoting-artifact message), shell must recover the full set. Pre-fix, the split is total:
128 vs 212 entries from the same printed advice.

---

## Scratch inventory

| Scratch | Artifact |
|---|---|
| `/tmp/aib-red-ac2-Xwh8cv` | AC2(a) plan-recipe run (later reused for a deleter trace — artifacts above predate that) |
| `/tmp/aib-red-ac2c-TaHg6B` | AC2(b) d-16 blindness shape |
| `/tmp/aib-red-ac3-nC7OuK` | AC3 8-step trap + AC4 outcome tier |
| `/tmp/aib-red-ac1-nzE8gK` + `/tmp/aib-ac1-cloneB` | AC1 control |
| `/tmp/aib-red-d6b-list-LwWiC9`, `/tmp/aib-red-d6b-shell-*` | D6b E1/E2 |

---

# Package 4 — guard fail-fast + explicit argv (pytest transitions + post-fix scratch re-runs)

Commit `ab4fa629` (+ `7c785f71` header fix). RED side below = each new test run **against
pre-fix HEAD** (`0602dac6`), one at a time, in the worktree test env
(`/tmp/aib-venv311/bin/python -m pytest`, fixtures are tmp copies — never run against the
worktree itself). GREEN side = same tests at `7c785f71`. Scratch re-runs of the Package 1
recipes post-fix corroborate in `/tmp/aib-green4b-l34PAe` (AC2a), `/tmp/aib-green4c-*`
(AC2b), `/tmp/aib-green4d-I5PqZ9` (AC3), all from `git archive HEAD` of the fix branch,
fixture-style setup.

## AC2 — rebuilt recipe

- **RED** (`test_a_narrowed_manifest_fails_fast_naming_the_lost_mirror` @ `0602dac6`):
  exit **1**, but via host-link findings only — stdout named `.claude/skills/ai-raccoon-memory`
  and `.github/skills/ai-raccoon-memory` ("the re-scaffold no longer writes it"), remediation
  `--skills ''`; **no mirror path, no narrowing cause** — RED exactly at the witnessed
  discriminator (Package 1's plan-deviation finding: the rebuilt recipe cannot produce a
  pre-fix PASS; the pytest binds to the post-fix D2 assertions instead).
- **GREEN** (same test @ `7c785f71`): exit 1; stdout begins
  `SCAFFOLD FRESHNESS GUARD FAILED: the manifest records 31 scaffolded skill(s) but 32 are
  expected from .ai-badger/config.json: 1 skill mirror(s) recorded nowhere…` and names
  `.ai-badger/skills/ai-raccoon-memory/SKILL.md  (recorded in no manifest row, narrowed)`.
- **Scratch re-run** (`/tmp/aib-green4b-*`): same recipe, `exit=1`, header + mirror path +
  rationale + hedge + explicit 32-name `--skills` remediation (block order visible:
  defaults, include-derived, stack-local `auto-wm,cron-watchdog-authoring,hermes-plugin-development`).
- **AC2(b) d-16 shape post-fix** (`/tmp/aib-green4c-*`: narrowed manifest + host links
  removed + hand-edited lost mirror — the tree that PASSED pre-fix): **exit 1**, narrowing
  verdict. The blindness is closed at both reachable shapes.

## AC3 — remediation re-blinding trap

- **RED** (`test_the_remediation_restores_what_the_manifest_lost_…` @ `0602dac6`): failed at
  **assertion 6** — after executing the printed `--skills ''` remediation, the victim's
  mirror row is still absent from the regenerated manifest (`any(...)` False). The trap is
  fully live pre-fix; Package 1's scratch run additionally witnessed assertion 8's PASS.
- **GREEN** (same test @ `7c785f71`): all eight assertions hold — guard#1 exit 1
  (narrowing verdict, remediation still printed — QA-F6b), remediation executes exit 0 on
  bare PATH, manifest-regeneration pin True, guard#2 exit 1 naming
  `.ai-badger/skills/ai-raccoon-memory/SKILL.md` with the ordinary **`hand-edited`** verdict.
- **Scratch re-run** (`/tmp/aib-green4d-I5PqZ9`): guard#1 exit 1 → executed advice exit 0
  with `scaffolded 212 entries` (the FULL set — no `reused` note; pre-fix printed `reused 31`)
  → step-6 pin `victim mirror row present: True | skill rows: 32 | entries: 212` → hand-edit →
  guard#2 `exit=1`, finding `(content differs, hand-edited)`.

## AC4 — remediation message audit

- **RED mechanism** (`test_the_remediation_argv_carries_the_expected_set_explicitly` @
  `0602dac6`): `TypeError: rescaffold_argv() takes 5 positional arguments but 6 were given`
  — the signature is part of the contract (API-F8); the semantic RED is Package 1's
  mechanism-tier artifact (joined argv tail `--skills ` matching EMPTY at span (171, 180)).
- **RED outcome** (`test_the_printed_remediation_never_carries_an_empty_skills_value` @
  `0602dac6`): `EMPTY_SKILLS_RE` matched the rendered advice at **span (165, 176),
  match="--skills ''"**.
- **GREEN** (both @ `7c785f71`): mechanism tier — no EMPTY match, NONEMPTY match, and the
  set itself carried in both `rescaffold_argv(...)` and `remediation(expected)`; outcome
  tier — no EMPTY match anywhere in guard stdout, NONEMPTY matches, and the rationale clause
  indexes BEFORE `Re-scaffold this repo` (QA-F8). Predicate tables (18 rows, incl. the
  trailing-space + EOS shape) pinned both ways.

## D2/D4 refusals + one-oracle pin

- **D4 RED** (`test_an_empty_derived_expected_set_refuses_instead_of_recovering`):
  pre-fix `exit 2` but the message was the late `SCAFFOLDER FAILED … can't open file
  …/work/features/…/scaffold.py` — no derivation named. **GREEN**: `COULD NOT RUN: the
  expected skill set derived from …/config.json is empty: a broken derivation must not fall
  back to manifest recovery`.
- **Parse RED** (`test_an_unparseable_config_refuses_at_the_derivation_site_not_a_traceback`):
  same late SCAFFOLDER FAILED shape pre-fix. **GREEN**: `… could not be parsed as
  config.json: …`, exit 2, no traceback.
- **One-oracle RED** (`test_rescaffold_derives_the_skill_list_from_the_work_copys_own_config`):
  pre-fix the monkeypatched run received `['--skills', '']` — recovery, not the derived set.
  **GREEN**: `['--skills', 'alpha']` derived from the work copy's own config.
- **Meta-suite narrowing provocation** (`the manifest lost a skill row`): provoked lane RED
  at `0602dac6` (gate failed exit 1 but with the wrong story — host-link/manifest findings,
  `--skills ''` advice; signal `contains="expected from .ai-badger/config.json"` unmet);
  GREEN at `7c785f71` both lanes (provoked exit 1 with the narrowing verdict; clean fixture
  exit 0).

## AC1a — idempotence control + canary

- `test_a_second_scaffold_regenerates_the_same_tree_modulo_stamps` GREEN pre- and post-fix
  (control, as designed; Package 1's scratch control concurs). Explicit-env second scaffold
  with `--generated-at` pinned; managed-tree digest (`.git` excluded, `is_noise` applied);
  residual differences after the guard's `normalized()`: **[]**.
- `_freshen` canary (D5 amended): asserts the `reused N skill(s)` note's N == the manifest's
  skill-row count (32); `test_a_fresh_tree_passes` and the kept remediation test carry the
  planned docstring notes.

## Suite gate

`/tmp/aib-venv311/bin/python -m pytest -q` at `7c785f71`: **4763 passed, 17 skipped**
(4735 baseline + 26 new guard-file items + 2 meta-suite lanes; guard file 39/39,
`test_scaffold_empty_skills.py` + `test_expected_skill_names.py` +
`test_scaffold_skills_argv.py` 23/23, pre-commit hooks 10/10 incl. the new guard live
against the worktree).

---

# Package 5 — mirror regen + AC0 (R4/D9)

Self-scaffold of the worktree post-Package-4 (commit `024b5258`): exit 0,
`scaffolded 212 entries`, 62 notes (all inclusion/exclusion/extension-requirement notes),
**no `reused` note, no skill-level skip note**; only `.ai-badger/manifest.json` re-stamped
(Package 4 touched `gates/` + `tests/`, which do not ship as mirrors) — committed
same-commit per the mirror rule.

## AC0 protocol (reviewer §3.1, D9) — scratch `/tmp/aib-ac0-4uMcXQ`, `git archive HEAD` of
## the branch at `024b5258`, fixture-style setup, venv interpreter substituted for `python3`

- **Run 1** (`--generated-at 2026-08-31T00:00:00Z`): exit 0, `scaffolded 212 entries`;
  run-1 diff = ` M .ai-badger/manifest.json` only — stamp-class exactly as §3.2 expects
  (`frameworkCommit` → scratch baseline commit, `frameworkDirty` → false, `generatedAt`
  pinned). Committed.
- **Run 2**: exit 0, `scaffolded 212 entries`.
- **⚠ Protocol deviation finding (report, not a stop):** run-2's `git status` is **not
  verbatim-empty** — it shows exactly ` M .ai-badger/manifest.json`, whose diff is
  **STAMP-KEYS-ONLY** (`frameworkCommit` re-stamps because the protocol's own intermediate
  commit moved HEAD; verified: every `+/-` line in the diff is one of the five
  `STAMP_KEYS`). A second churn source appears when two runs go uncommitted between
  runs: `frameworkDirty` flips false→true because run N starts with run N−1's uncommitted
  manifest — an honest observation of git state at run start, again a STAMP_KEY. The
  verbatim "run-2 status MUST be empty" is unsatisfiable **as written** on any branch: the
  two git-derived stamps (`frameworkCommit`, `frameworkDirty`) record the git state the
  protocol itself changes. The protocol's intent — no CONTENT churn; a second-run diff
  would be F1 nondeterminism — holds: at fixed HEAD, run-to-run manifest diff is exactly
  the two git-state stamp keys, all other 210+ entries byte-identical, pinned
  `generatedAt` stable. **This is not narrowing and not F1 content churn.**
- **Counts ×2**: `32 skill entries, 212 total` in run 2 and run 3 (and the persisted
  run-2 manifest) — 32/32 & 212, matching research §3's healthy baseline.
- **No `reused` note** in run 1/2/3 (recovery never engaged); **no `not in any configured
  stack` skip notes**.
- **Guard PASS**: `1952 path(s) compared against a re-scaffold of this tree; only version
  stamps differ — PASS`, exit 0 — the guard's internal re-scaffold now runs the explicit
  `expected_skill_names` argv, so the PASS also proves the union-form re-scaffold
  reproduces the committed tree byte-stably (AC1a's post-fix claim, at tree level).
- **Contingency not triggered**: no narrowing reproduced; R1 stays repaired on the branch.
