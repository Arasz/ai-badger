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
