# Plan proposal — vendor Archify as the default diagram skill (0.171.0)

**Task:** `aib-archify-diagram-skill-default-integration` · **Version (assigned centrally):** 0.171.0
**Lane:** architect (blueprint only; no production edit in this deliverable) · **Date:** 2026-09-13
**Read:** `docs/work/2026-09-13-archify-diagram-skill-research.md`, `docs/authoring-a-feature.md`,
`gates/skills_lint.py`, `tooling/validate.py` (`FEATURE_JSON_WITHOUT_SCHEMA`, `unschemad_feature_json`),
`docs/skills.md`, `tests/test_docs_match_the_catalog.py`, `tests/test_expected_skill_names.py`,
`git show --stat 7a751008`, the staged packet at `/tmp/archify-staged/archify` (v2.16.0).

Evidence grades are per the research record: MEASURED / READ / INFERRED / HYPOTHESIS. New measurements
made for this proposal are marked MEASURED and carry the command that produced them.

## 1. Rulings on the six open questions

**Q1 — packet contents: AGREE, with a measured size caveat.** Vendor the canonical v2.16.0 release
packet unchanged (76 files / 5.88 MB uncompressed). MEASURED: `examples/*.html` is 3.59 MB of that
(61%, `unzip -l`); the packet is copied three times (`features/`, plugin `skills/`, `.ai-badger/`
mirror) → ~17.6 MB working tree. Keep the full packet: the owner ruled "full packet", and a trim
list would live in the re-vendor tool forever. Escape hatch if size bites: drop only
`examples/*.html` (generator output, regenerable via `scripts/render-examples.mjs`) as a
`vendor.json` exception.

**Q2 — provenance: AGREE with the tool; correct the pin target.** MEASURED: the staged packet is
the **release asset**, not the tag tree — v2.16.0 publishes `archify.zip` (`gh release view`), the
tag has no `scripts/stage-clean-skill.mjs`, and the local zip's sha256 `4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46`
equals the GitHub asset `digest` (`gh api repos/tt-a1i/archify/releases/tags/v2.16.0 --jq '.assets[0].digest'`).
`vendor.json` pins repo, tag, commit, asset URL, zip sha256, per-file sha256, adapted list.
`tooling/vendor_archify.py --check` is offline (`--revendor <zip>` verifies the zip sha first).
Keep the tool in `tooling/` (repo-only; `docs/scripts.md` row), not in the shipped payload.

**Q3 — SKILL.md adaptation: AGREE, one addition.** Replace frontmatter with the ai-badger keys
(rule 5 "Use when", `scope: default`, version/author/license/platforms/hermes metadata), keep the
upstream body verbatim, add `## When NOT to Use` and `## Gotchas`. Addition: the Mermaid fallback
must live in the SKILL.md body itself — plugin-only consumers never receive the invariant.
MEASURED: upstream description 652 chars (rewrite < 1024); body 127 lines / chars-4 proxy 3,804;
`references_without_conditions` returns 0. Record `SKILL.md` in the `adapted` list so `--check`
does not flag it.

**Q4 — Node dependency: AGREE on `system`, DISAGREE with install-on-command.** Implement
`ecosystem: system` in `dependency_check.py`: detect via `shutil.which(package)` in **report-only
mode too** (today a required dep without `--execute` always prints a would-install hint; for a
system binary already on PATH that is noise), and never run a global install for Node — declare no
`command`, so a missing node yields a hint naming the Mermaid fallback. Node's install is
OS-specific and the skill degrades by design. Note the pre-existing dead entry
`feature: code-review-graph` (no catalog skill has that name) as a follow-up issue, not a
drive-by fix.

**Q5 — lint as-is: AGREE (measured).** Rules 6–8 pass unmodified. Only the description rewrite
(rule 5) and `## Gotchas` (rule 9) are additions. Constraint on added text: no evidence table
(`tests/test_skill_bodies_carry_procedure_not_evidence.py`) and no `references/` mention without a
when/if/before/after/only-when condition in its 3-line window.

**Q6 — docs/task integration: AGREE on invariant + documentation gateway; DISAGREE on two edits.**
Home is a new common invariant `features/common/invariants/archify-diagrams.md` (renders as a
bullet in every assembled agent file). Edit
`documentation/references/scaffold-documentation/SKILL.md` (root-README diagram) and
`.../update-documentation/SKILL.md` (visual-first bullet). Do **not** touch
`differential-feature-refactor` — committed Markdown needs the inline Mermaid render, the
documented fallback case — and do **not** touch `task/SKILL.md`: MEASURED body proxy 4,965/5,000
leaves 141 chars, and the invariant reaches the task workflow through the assembled agent file.
`complete-project-scope-code-review` already says "the repo's own diagram convention".

## 2. Packages

Terminology: **serial** = merge before the packages it blocks; **parallel** = may share a wave,
naming the files it owns so two lanes never write one file. Every package leaves the tree green:
every package that changes a delivered file ends with a self-scaffold (PKG-1, PKG-3), while PKG-2
changes only dependency metadata, which no scaffold output reads (READ, `scaffold.py::_check_dependencies`
returns notes, writes nothing). Version 0.171.0 is assigned; PKG-1 bumps `VERSION` first so every
later self-scaffold stamps it.

### PKG-1 — vendored packet, provenance, catalog delivery (serial; blocks PKG-2/3; first merge)

**1a — Vendor the release packet.** Goal: `features/common/skills/archify/` holds the 76
byte-identical upstream files plus the adapted SKILL.md, LICENSE kept. AC: file count 76 + no
`test/`, `scripts/generate-*.mjs`, `package-lock.json`; upstream SKILL.md stays in `vendor.json`'s
reference set. Command: `python3 tooling/vendor_archify.py --check`. Owns:
`features/common/skills/archify/**`. Serial.

**1b — Provenance tool + data.** Goal: `vendor.json` (repo/tag/commit/asset URL/zip sha256/per-file
sha256/adapted) and `tooling/vendor_archify.py` with `--check` (offline, exits 1 on drift/extra/
missing) and `--revendor <zip>` (sha gate, then extraction). TDD: `tests/test_vendor_archify.py`
written red first — drift, missing file, extra file, adapted-file edit, bad zip sha. AC: `--check`
0 on the vendored tree; every planted defect turns it 1. Commands:
`python3 tooling/vendor_archify.py --check`; `python3 -m pytest tests/test_vendor_archify.py -q`.
Owns: `tooling/vendor_archify.py`, `tests/test_vendor_archify.py`, the skill's `vendor.json`. Serial.

**1c — Catalog wiring.** Goal: validator exemptions for vendored JSON families
(`features/*/skills/*/{schemas,examples,brand-marks}/*.json`, `.../package.json`,
`.../skill-release.json`, `.../vendor.json`; each with a ≥30-char reason), `docs/scripts.md` row,
`index.json` rebuild, plugin copy, `docs/skills.md` row + counts (47→48, 46→47, 44→45; fix the
stale "These 43" to 48 and tree "53"→"54"), `tests/test_expected_skill_names.py` 48→49,
`VERSION` 0.171.0, changelog `docs/changelog/0.171.0-archify-diagram-skill.md` + index,
`features/common/data/model-groups.json` stamp, self-scaffold. AC: all commands 0, docs test green,
freshness guard PASS. Commands (the ones PKG-4 re-runs are marked):
`python3 tooling/validate.py --all` · `python3 gates/skills_lint.py` ·
`python3 tooling/index_build.py --check` · `python3 tooling/sync_plugin_skills.py --check` ·
`python3 tooling/version_sync.py --check` · `python3 tooling/changelog_index.py --check` ·
`python3 gates/release_guard.py` · `python3 -m pytest tests/test_expected_skill_names.py tests/test_docs_match_the_catalog.py -q` ·
`node features/common/skills/archify/bin/archify.mjs doctor` (exit 0; measured 40 ms) ·
`python3 gates/scaffold_freshness_guard.py`. Owns: `tooling/validate.py`, `docs/scripts.md`,
`docs/skills.md`, `tests/test_expected_skill_names.py`, `VERSION`, changelog pair,
`features/common/data/model-groups.json`, and (via scaffold) `index.json`, `skills/archify/**`,
`.ai-badger/**`, `.claude/skills/archify`, `.github/skills/archify`, root agent docs,
`.claude-plugin/*`. Serial; the self-scaffold is the wave's only `.ai-badger/` writer.

### PKG-2 — Node ≥18 declared as a system dependency (parallel with PKG-3; owns dependency files)

**2a — `system` ecosystem.** Goal: `dependency_check.py` detects `system` deps with
`shutil.which(package)` even when `allow_install=False`; installs only when a `command` is declared
and `--execute` is passed; missing binary + no command → hint, never error. AC: a present binary
reports `already_present` with no hint in both modes; an absent binary hints exactly once and names
the fallback; a declared `command` runs only with `--execute`. TDD red first in
`tests/test_dependency_check.py` (present/absent × report/execute, command-declared, command-absent).
Commands: `python3 -m pytest tests/test_dependency_check.py -q` ·
`python3 -m pylint features/common/skills/welcome-ai-badger/scripts/dependency_check.py`. Owns:
`features/common/skills/welcome-ai-badger/scripts/dependency_check.py`,
`tests/test_dependency_check.py`.

**2b — archify entry.** Goal: `features/common/dependencies.json` gains
`{feature: archify, ecosystem: system, package: node, note: "…Mermaid fallback…"}` with no
`command`. AC: entry validates against `dependencies.schema.json` and the scaffold note is
truthful. Commands: `python3 tooling/validate.py --all` ·
`python3 features/common/skills/welcome-ai-badger/scripts/dependency_check.py --root . --target . --features archify`
(prints no missing-node hint on this machine; measured `node --version` = v26.8.2). Owns:
`features/common/dependencies.json`. Wave: PKG-2 ∥ PKG-3 (no shared file; only PKG-3 writes
`.ai-badger/`). Serial within PKG-2: 2a before 2b.

### PKG-3 — default-with-fallback policy surfaces (parallel with PKG-2; owns invariant + 2 members)

**3a — Common invariant.** Goal: `features/common/invariants/archify-diagrams.md`, H1 title plus a
one-sentence opening: author architecture/workflow/sequence/data-flow/lifecycle diagrams with the
`archify` skill **when it is installed**, falling back to Mermaid when Node 18+ is unavailable or
the diagram must render inline in committed Markdown. AC: the rule's first sentence lands in every
assembled agent file; the file is short (≤ ~8 lines) and carries no evidence table. Commands:
`python3 gates/scaffold_freshness_guard.py` ·
`grep -c "Archify" CLAUDE.md .ai-badger/CLAUDE.md .ai-badger/invariants/archify-diagrams.md`. Owns:
`features/common/invariants/archify-diagrams.md`.

**3b — documentation gateway members.** Goal: replace the Mermaid-only mandates with the default +
fallback rule — `scaffold-documentation/SKILL.md` step 4 root-README bullet; `update-documentation/
SKILL.md` step 5 visual-first bullet. Members are below skills_lint's reach, so no rule 8 exposure;
keep the edits to the mandate sentence, not a rewrite. AC: both name archify first and Mermaid as
the inline/unavailable fallback; no other referenced file changes. Command:
`git diff --stat features/common/skills/documentation` (two files) plus the freshness guard after
self-scaffold. Owns: the two member `SKILL.md` files.

**3c — self-scaffold.** Goal: the invariant reaches the committed mirrors. AC: freshness guard
PASS, `.ai-badger/invariants/archify-diagrams.md` present, agent-doc budgets hold (CLAUDE.md 224
lines today; `agentDocs.maxLines` 260 / `maxChars` 17500). Commands:
`python3 gates/scaffold_freshness_guard.py` · `python3 -m pytest tests/test_expected_skill_names.py -q`.
Owns: `.ai-badger/**` mirrors and root agent docs. Wave: PKG-3 ∥ PKG-2; 3a → 3b → 3c.

### PKG-4 — integration package (serial; last merge; cross-package tests)

**4a — integration test file.** Goal: `tests/test_archify_integration.py` scaffolds a scratch
consumer with the real scaffolder (`tests/conftest.py::make_scaffolder`) and asserts: (i) delivered
`.ai-badger/skills/archify` hashes equal `features/common/skills/archify` (PKG-1); (ii) the
scaffolded `.ai-badger/CLAUDE.md` carries the diagram bullet and the invariant file exists (PKG-3);
(iii) `dependency_check --features archify` reports node present with no missing hint (PKG-2);
(iv) `node .ai-badger/skills/archify/bin/archify.mjs doctor` exits 0; (v) `deliver architecture
<example> <out.html> --quality showcase --json` exits 0 with `ok: true`, 9/9 artifact checks, and
writes the HTML (upstream MEASURED 155 ms, 9/9, 724,866 bytes). Node legs are `skipif` without node
— the companion `tests/js/archify_packet.test.mjs` runs the same doctor/deliver against the catalog
copy unconditionally in the `js` lane, so the check is never silently skipped everywhere. AC: file
green; every assertion watched red on the pre-PKG-1 base before it is made green.
Commands: `python3 -m pytest tests/test_archify_integration.py -q` ·
`node --test tests/js/archify_packet.test.mjs`. Owns: `tests/test_archify_integration.py`,
`tests/js/archify_packet.test.mjs`.

**4b — release sweep + cross-checks.** Goal: the whole join is green on one tree. AC: every PKG-1
command re-run plus `python3 gates/consumer_journey.py` (consumer install path delivers the skill)
and `git status --porcelain` clean after the final self-scaffold. Command: the PKG-1 command list,
then `python3 gates/consumer_journey.py`. Owns: nothing new; may regenerate stamps only.

## 3. ADR-0030 outline — vendor Archify, and make diagrams archify-first with a Mermaid fallback

**Context.** The catalog has no diagram-authoring capability of its own; five skills and several
templates currently name Mermaid, which is ideal inline in Markdown but cannot produce a standalone
polished artifact. Upstream Archify is MIT (two copyright holders), Node ≥18, **zero runtime npm
dependencies**, and ships a canonical staged packet as a release asset. ai-badger has vendored
byte-equal code before (`engine/badger_store.py`, `VENDORED_PATHS`), and ADR-0028 says a common
skill ships by default unless unasked delivery is a real liability.

**Decision.** (1) Vendor the v2.16.0 release packet under
`features/common/skills/archify/` at a pinned commit, with `vendor.json` provenance and
`tooling/vendor_archify.py --check`; re-vendoring is an explicit PR with a new zip sha. (2) Declare
`scope: default` — the skill reaches every scaffold and the plugin copy. (3) Archify is the
catalog's default diagram authoring tool, stated once as the common invariant
`archify-diagrams.md`; Mermaid is the fallback for a missing Node runtime, an inline-Markdown
render, or a trivial sketch. (4) Node ≥18 is declared as a `system` dependency, detect-only, never
auto-installed.

**Consequences — positive.** Polished, validated, standalone artifacts with no npm install step;
provenance verifiable offline and byte-for-byte; one documented re-vendor procedure; Node absence
degrades cleanly instead of failing a task.

**Consequences — negative.** ~5.88 MB × three copies (~17.6 MB working tree, ~5–6 MB pack growth);
a third-party surface ai-badger does not maintain, pinned until someone re-vendors; Node 18+
becomes a de-facto runtime for a default skill; `scripts/check-update.mjs` makes an opt-out network
call (`ARCHIFY_UPDATE_CHECK_DISABLED=1`); upstream v2.16.0 ships no `THIRD_PARTY_NOTICES.md` though
it embeds Simple Icons brand marks (main added one) — carry that notice beside `vendor.json`.

**Consequences — neutral.** The plugin `skills/archify/` copy is a pointer + `SKILL.full.md` like
every other skill; consumers can decline with `config.exclude.skills: ["archify"]`; re-vendoring
does not change the `scope:` contract.

**Alternatives considered.** External skill source (`skills.json`) — rejected: no Node runtime
installation and uncovered pi/hermes/copilot paths (research §2). Runtime fetch of upstream —
rejected: unpinned and network-dependent at use. First-party Mermaid-only rewrite — rejected:
leaves the owner's ask unmet. `optIn` instead of default — rejected by the owner's ask. Trimmed
packet — deferred, named under Q1.

## 4. Risks and mitigations

- **R1 bundle size** — MEASURED: 5.88 MB packet, 3.59 MB of it rendered HTML; three copies.
  Mitigation: accept the full packet now; the `examples/*.html` trim is the documented, local
  fallback if size bites.
- **R2 vendored content breaks existing tests** — MEASURED: no `plugin:skill` refs, no evidence
  tables, no absolute paths, all four `references/` files named in SKILL.md, rule 8 clean.
  Residual risk low; PKG-4's full sweep is the backstop.
- **R3 upstream drift/regression on re-vendor** — INFERRED: upstream main is 2.17.0-dev.1 and the
  packet is pinned by sha; `--check` catches local drift, and a re-vendor PR diffs file hashes.
- **R4 Node absent in a consumer repo** — DESIGN: dependency hint + invariant fallback + the
  SKILL.md's own `## Gotchas`. Unverified against a node-less machine — HYPOTHESIS until PKG-2's
  tests simulate `which("node")` returning None.
- **R5 update-check network call** — READ: `scripts/check-update.mjs:1637` is opt-out. Mitigation:
  document `ARCHIFY_UPDATE_CHECK_DISABLED=1` in `## Gotchas`; owner may rule "disable by default in
  the adapted body" — surfaced, not decided here.
- **R6 brand-mark licence** — READ: Simple Icons notice absent at the tag, present on main.
  Mitigation: ship the upstream notice text beside `vendor.json`; MIT LICENSE stays in the packet.
- **R7 parallel-lane collisions on `.ai-badger/`** — MEASURED (7a751008): the mirror is
  scaffolder-written. Mitigation: PKG-2 owns no mirror file; PKG-3 is the wave's only mirror
  writer; PKG-4 re-runs the guard on the joined tree.
- **R8 count/stamp drift** — MEASURED (0.166.0 missed model-groups stamps; CI caught it). Mitigation:
  PKG-1's command list includes every derived-count check in the same commit.

## 5. Decisions surfaced for the owner (not blocking PKG-1)

1. Disable Archify's update check by default in the adapted SKILL.md, or keep upstream behaviour
   with the opt-out documented (R5)?
2. Accept ~17.6 MB of working-tree size, or pre-authorise the `examples/*.html` trim (Q1)?
