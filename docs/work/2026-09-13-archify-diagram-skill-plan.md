# archify diagram skill — plan rev 2 (0.171.0)

Task `aib-archify-diagram-skill-default-integration`. Effort: high. Target version: **0.171.0**
(minor: a new default skill changes scaffold output; precedents 0.147.0 / 0.166.0).

Inputs: `docs/work/2026-09-13-archify-diagram-skill-research.md`, the three MoE proposals, and
the three plan reviews (`-plan-review-code-reviewer.md`, `-plan-review-qa.md`,
`-plan-review-hermes-agent-author.md`). Rev 2 folds every MUST and SHOULD finding; the fold table
at the end maps each review id to its change. Execution model: implementation lanes edit
**disjoint source paths and do not run git write commands**; the orchestrator owns all commits and
the single join (index → plugin sync → self-scaffold → release ritual), which is why no package
claims an intermediate self-scaffold any more (code-reviewer F1).

## Rulings on the six research questions (rev 2)

1. **Packet contents — full upstream packet.** 76 files / 5,888,015 B, including the five rendered
   `examples/*.html` (3.59 MB). Copied three times (`features/`, plugin `skills/`, `.ai-badger/`)
   ≈ 17.7 MB working tree; **pack growth ≈ 1.1–1.5 MB**, because the three copies are
   byte-identical and git stores one blob set (zlib(6) over the unique content = 1,144,408 B;
   measured by the code-reviewer). `.claude/skills/*` and `.github/skills/*` are symlinks, not
   copies.
2. **Provenance — release asset pinned outside the file it protects.** v2.16.0 publishes
   `archify.zip` (1,318,273 B, sha256 `4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46`).
   The tool carries that literal is **not** stored in `vendor.json`; `--revendor` takes
   `--expect-sha256` from the command line and never reads the expected value from
   `vendor.json` (QA-3). The tag *does* carry `scripts/stage-clean-skill.mjs` (correcting the
   architect's proposal); staging the tag reproduces the release tree byte-for-byte (measured
   `diff -r`).
3. **SKILL.md adaptation.** Frontmatter replaced with the ai-badger keys; body byte-identical to
   upstream except added `## When NOT to Use`, `## Gotchas`, and the Mermaid-fallback statement.
   The adapted **description must name the Mermaid fallback** (plugin-only consumers see only
   frontmatter before reading — hermes F3). `vendor.json` records `SKILL.md` as adapted with
   `upstream_body_sha256` + adapted-frontmatter hash.
4. **Node dependency — presence-only `system` ecosystem.** No version probe and no schema change.
   Detection is `shutil.which(package)` in both report and execute modes; a missing binary yields
   a hint (never an error) naming Node 18+ and the Mermaid fallback; an install command runs only
   with `allow_install` and a declared `command`; the archify entry declares **no** `command`, so
   it can never auto-install. Residual, accepted and recorded in ADR-0030: a Node older than 18
   that exists on PATH reports `already_present`; the version floor is enforced at use time by
   `node bin/archify.mjs doctor`, whose failure routes to the documented Mermaid fallback. This
   closes QA-7/8/9 by removing the unsupported floor claim and the schema question, rather than
   adding a probe whose floor no field could express.
5. **Lint as-is — measured clean.** `references_without_conditions` returns `[]`; body 127 lines /
   ~15.2 KB (proxy 3,804). One adjacency accident is pinned with an explicit condition
   (line ~82: "when you need field enums or spacing math").
6. **Docs/task integration.** New common invariant `archify-diagrams.md`; edits to
   `scaffold-documentation` and `update-documentation` members; `differential-feature-refactor`
   and `complete-project-scope-code-review` unchanged (committed-Markdown Mermaid is the
   fallback and the latter already says "the repo's own diagram convention"). The task skill gets
   one clause of **≤142 chars net** (body 19,858 chars → proxy 4,964.5); if wording runs longer,
   trim `Parallelism has to be designed in; it does not arrive on its own.` (66 chars). The
   invariant is scaffold-only by design; the plugin-only path keeps the degradation policy in the
   SKILL body + description (hermes F4).

**Owner-surfaced decisions:** full packet stays (Q1); upstream's opt-out update check is kept and
documented in `## Gotchas` (`ARCHIFY_UPDATE_CHECK_DISABLED=1`) rather than diverging.

## Deliverables

### PKG-1 — vendored packet, provenance, catalog wiring

**1a — Packet.** `features/common/skills/archify/` holds the 76 upstream files byte-identical
(from the v2.16.0 release asset), `LICENSE` included, plus: `THIRD_PARTY_NOTICES.md` (backfilled
from upstream `main`; `brand-marks/catalog.json` is byte-identical between v2.16.0 and main —
measured `shasum`, so the notice applies exactly), `VENDOR.md` (provenance + the documented
re-vendor command), `vendor.json`, adapted `SKILL.md` (frontmatter + When NOT to Use + Gotchas +
fallback; description names Mermaid).
**AC:** file set = 76 upstream files + the ai-badger additions; `test/`, `package-lock.json`,
`scripts/generate-*.mjs` absent; staged `package.json` without `scripts`/`devDependencies`;
`node bin/archify.mjs doctor` exits 0 from the feature dir.
**Gate:** `python3 tooling/vendor_archify.py --check`;
`node features/common/skills/archify/bin/archify.mjs doctor`.

**1b — Provenance tool + tests.** `tooling/vendor_archify.py`:
- `--check [--root DIR]` — offline; exit 0 clean / 1 on `MISSING|EXTRA|CHANGED <relpath>`; also
  fails if any vendored path segment matches `badger_lib.SKILL_EXCLUDE_PATTERNS` (a future
  re-vendor must not ship files the scaffold would silently drop); never reads the expected asset
  sha from `vendor.json`.
- `--revendor <zip> --expect-sha256 <sha>` — verifies the zip against the **command-line**
  literal first, then stages to a temp dir, applies upstream exclusion rules + `package.json`
  cleaning + frontmatter adaptation, replaces the tree, regenerates `vendor.json`; refuses a
  dirty target; exit 2 on network/argument failure, tree untouched.
- The v2.16.0 literal `4c59fa65…` lives in `VENDOR.md` and the tool's usage text; `vendor.json`
  stores it as information only and no code path compares it against itself (QA-3).
`tests/test_archify_vendor.py` (red first): disk tree enumerated with `Path.rglob`, not derived
from the manifest; adapted `SKILL.md` split with a literal delimiter and hashed with `hashlib`;
literal file count 76 and literal forbidden paths; planted drift/missing/extra; forged zip +
forged manifest rejected even when they agree
(`test_revendor_refuses_a_forged_packet_even_when_the_manifest_agrees`); lint test asserts the
subject exists before filtering (`skill_files` contains `archify`); exemption necessity test
(delete one added pattern → `unschemad_feature_json` non-empty).
**Gate:** `python3 -m pytest tests/test_archify_vendor.py -q`;
`python3 tooling/vendor_archify.py --check`.
**New meta-gate:** `tests/test_every_check_can_fail.py` gains a `REGISTRY` provocation for
`tooling/vendor_archify.py --check` (a tmp tree with one corrupted hash → exit 1 `CHANGED`; the
clean fixture → exit 0), or the suite fails once the tool is tracked (code-reviewer F3).

**1c — Catalog wiring.** `tooling/validate.py` exemptions with exact, mutually disjoint globs:
`features/*/skills/*/schemas/*.json`, `.../examples/*.json`, `.../brand-marks/*.json`,
`.../package.json`, `.../skill-release.json`, `.../vendor.json` (each reason ≥30 chars, each
pattern matching ≥1 file; the necessity test rides in `tests/test_archify_vendor.py`).
`docs/scripts.md` row for `vendor_archify.py` naming the `--check` (offline) vs `--revendor`
(origin) split and the exact maintainer commands. `docs/skills.md`: at-a-glance row, the four
gated counts 47→48 / 46→47 / 44→45, "These 43"→48, tree "53"→54, plus a new section.
`tests/test_docs_match_the_catalog.py` gains derived assertions for the tree-glob numeral and the
"These N" sentence. `tests/test_expected_skill_names.py` 48→49.
`docs/adr/0030-vendored-archify-and-diagram-default.md` + ADR README row. ADR consequences:
working tree ≈17.7 MB; pack growth ≈1.1–1.5 MB; the routing invariant is scaffold-only while
plugin-only consumers keep the degradation policy in SKILL body + description; existing consumers
receive archify on next `den-refresh` (drift-new), declining via
`config.exclude.skills: ["archify"]`; Node <18 residual (ruling 4); Copilot-cloud symlink/Node
hypothesis.
`VERSION` 0.171.0; `docs/changelog/0.171.0-archify-diagram-skill.md`; changelog index;
`features/common/data/model-groups.json` stamp; run `tooling/version_sync.py` (writer, not just
`--check`). The generated mirrors (`index.json`, `skills/archify/`, `.ai-badger/**`, root agent
docs, `.claude-plugin/*`) belong to the join, not this package.

### PKG-2 — Node ≥18 declared as a presence-checked system dependency

**2a — `system` ecosystem** in `dependency_check.py`: `shutil.which(package)` in both modes
(present → `already_present`, no hint, **zero** subprocess calls — no version probe); missing +
no declared `command` → hint built from `name`/`note`, never an error; install runs only with
`allow_install` + declared `command`, via `shlex.split` + `subprocess.run(shell=False)`, failure →
`errors`; no `command` text ever reaches a shell.
**Tests** (red first, `tests/test_dependency_check.py`): present (path stubbed) → `already_present`
and `subprocess.run` uncalled; absent → exactly one hint containing `Node`, `18`, `Mermaid` and no
subprocess call; absent + `--execute` + no command → still a hint, never `npm install -g node`;
command-declared system dep + `--execute` → argv equals `shlex.split(command)`, `shell` not passed;
command-declared + no `--execute` → uncalled; declared-command failure → `errors`; and a test
loading the shipped `features/common/dependencies.json` asserting the archify entry has no
`command`, `ecosystem: system`, and a note naming Node 18+ and Mermaid. The scaffold-note label
("optional dependency:" in `scaffold.py`) is left unchanged and recorded as a follow-up (F11).

**2b — Entry.** `features/common/dependencies.json`:
`{feature: archify, path: features/common/skills/archify, dependencies: [{name: "Node.js 18+ (Archify diagram renderer)", ecosystem: system, package: node, note: "...Mermaid fallback..."}]}`.
**Gate:** `python3 -m pytest tests/test_dependency_check.py -q`;
`python3 tooling/validate.py --all`.

### PKG-3 — default-with-fallback policy

**3a — Invariant** `features/common/invariants/archify-diagrams.md`: H1 title + **≤6 lines total**
(the repo cap, `tests/test_invariant_catalog.py`), one sentence: author
architecture/workflow/sequence/data-flow/lifecycle diagrams with `archify` when installed; fall
back to Mermaid when Node 18+ or the skill is unavailable, the diagram must render inline in
committed Markdown, or the user asks for text. Add `archify-diagrams` to
`tests/test_invariant_catalog.py::NEW_INVARIANTS` (or its derived equivalent) so the title + link
are asserted inside the `## Non-negotiable invariants` section of every assembled agent file.
**Gate:** `python3 -m pytest tests/test_invariant_catalog.py -q`.

**3b — Documentation members.** Replace the Mermaid-only mandates with default + fallback in
`documentation/references/scaffold-documentation/SKILL.md` (root-README diagram bullet) and
`.../update-documentation/SKILL.md` (visual-first bullet). Frontmatter descriptions untouched
(gateway rule 13 byte-equality).
**Gate:** `tests/test_archify_integration.py::test_documentation_members_put_archify_before_mermaid`.

**3c — Task clause.** One ≤142-char net addition to Phase 2 (design/architecture presentation
routed to `archify`; Mermaid only when the runtime is missing); trim the named 66-char flourish if
needed.
**Gate:** `python3 gates/skills_lint.py` (rule 7 is the cap).

**3d — model.json intentionally untouched** (seed-once project data; no gate reads catalog
invariants from it) — recorded so no lane "fixes" it (hermes F8).

### PKG-4 — integration package (last)

**4a — `tests/test_archify_integration.py`** scaffolds a scratch consumer with the real
scaffolder (`conftest.make_scaffolder`) and asserts, with no production helpers reused for the
expected values: (i) delivered `.ai-badger/skills/archify` matches the catalog tree file-by-file
via `hashlib`/`filecmp`; (ii) the scaffolded agent file carries the invariant title + link and
`.ai-badger/invariants/archify-diagrams.md` exists; (iii) `dependency_check --features archify`
reports node present with no missing hint, cross-checked against the test's own
`shutil.which("node")`; (iv) `node .ai-badger/skills/archify/bin/archify.mjs doctor` exits 0
exactly (no rc-2 assertion — `doctor` never returns 2, QA-13); (v) `deliver architecture
<example> <out.html> --quality showcase --json` exits 0 with `ok`, 9 artifact checks,
`compositionProfile == "showcase"`, and a non-empty HTML. Node legs skip with a stated re-enable
condition, and **fail** (not skip) when `CI` is set and node is missing (QA-6). Hermes links
require an install run — asserted or named in the test docstring (hermes F5).
Companion `tests/js/archify_packet.test.mjs` (the `js` lane is **pre-push**, not CI-only)
compares `.ai-badger/skills/archify` (the delivered copy in this repo) against
`features/common/skills/archify` with stdlib `crypto`, then runs `doctor` and `deliver` from the
**delivered** path (QA-5).
**CI:** add `actions/setup-node` (pinned to a full commit SHA per the `github` stack invariant,
node-version 20) to the pytest job so the node legs are never vacuous in CI.
**Gate:** `python3 -m pytest tests/test_archify_integration.py -q`;
`node --test tests/js/archify_packet.test.mjs`.

**4b — Join + release sweep (orchestrator).** After all source edits: `docs/work/README.md` rows
for every `2026-09-13-archify-*` record (code-reviewer F2, currently red); `tooling/index_build.py`
(index-then-scaffold); `tooling/sync_plugin_skills.py`; self-scaffold
(`welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root .`);
`version_sync.py`, `changelog_index.py`; then focused checks once —
`pytest tests/test_archify_integration.py tests/test_archify_vendor.py tests/test_dependency_check.py
tests/test_docs_match_the_catalog.py tests/test_expected_skill_names.py tests/test_catalog_claims_checkable.py
tests/test_invariant_catalog.py -q`, `gates/scaffold_freshness_guard.py`,
`sync_plugin_skills.py --check` — then push and read CI. `journey`, `pylint`, and the full
`pytest` are **CI-only**; `tdd`, `js`, `pi-ts` run on pre-push (QA-14/15). A full local lane set
runs only if CI is dead.

## Test-run economy (corrected)

Pre-push runs (per `.lefthook/pre-push/verify.sh`): the cheap lanes including `tdd`, `js`,
`pi-ts`. CI-only: `pytest`, `pylint`, `journey`. Local during implementation: each lane's focused
file, once; the join runs the focused list above once; no full-suite repetition locally.

## Fold table (review finding → change)

| Finding | Severity | Folded as |
|---|---|---|
| code-reviewer F1 | MUST | Single orchestrator join owns index/plugin/self-scaffold; lanes are file-disjoint and commit-free |
| code-reviewer F2 | MUST | 4b adds `docs/work/README.md` rows for all work records |
| code-reviewer F3 | MUST | 1b adds the `tests/test_every_check_can_fail.py` provocation |
| code-reviewer F4 | SHOULD | Pack growth corrected to ≈1.1–1.5 MB (blob dedup) |
| code-reviewer F5 | SHOULD | Ruling 4 drops the probe/floor; consent wording is install-only |
| code-reviewer F6 | SHOULD | 3a pins the ≤6-line cap and title+link assertions |
| code-reviewer F7 | SHOULD | Named gates for 2b hint text and 3b member ordering |
| code-reviewer F8 | SHOULD | 1c states exact disjoint globs + necessity test location |
| code-reviewer F9 | NOTE | 1c states targets 48/54 |
| code-reviewer F10 | SHOULD | 3c states the exact 142-char cap and the named trim |
| code-reviewer F11 | NOTE | 1c runs `version_sync.py`; scaffold-note label recorded as follow-up |
| qa QA-1 | major | 1b lint test asserts its subject first |
| qa QA-2 | major | 1b enumerates disk with `rglob`, literal splitter, `--root` for planted defects |
| qa QA-3 | blocker | 1b `--revendor --expect-sha256` never reads the expected value from `vendor.json` |
| qa QA-4 | major | 1b/VENDOR.md/docs/scripts.md settle one command name and wire the human path |
| qa QA-5 | major | 4a mjs backstop runs from the delivered copy and compares trees |
| qa QA-6 | major | 4a fails when CI has no node; setup-node added |
| qa QA-7/8/9 | major | Ruling 4: presence-only, no floor, no schema change; residual documented |
| qa QA-10 | minor | 4a's independence traps named and avoided |
| qa QA-11 | minor | 3a asserts title+link via `test_invariant_catalog.py` |
| qa QA-12 | minor | 1c adds derived assertions for the glob numeral and "These N" |
| qa QA-13 | minor | 4a asserts doctor rc == 0 exactly |
| qa QA-14/15 | minor | Economy section corrected; 4b does not re-run CI-only lanes |
| qa QA-16 | minor | Filenames fixed: `test_archify_vendor.py`, `test_archify_integration.py`, `tests/js/archify_packet.test.mjs` |
| hermes F3 | SHOULD | 1a requires the Mermaid fallback in the description |
| hermes F4 | SHOULD | ADR names scaffold-only invariant vs plugin degradation policy |
| hermes F5 | SHOULD | 4a names the install-run precondition for Hermes links |
| hermes F6 | NOTE | ADR risks list names the unverified Copilot-cloud hop |
| hermes F9 | SHOULD | ADR names den-refresh delivery + `config.exclude` opt-out |
