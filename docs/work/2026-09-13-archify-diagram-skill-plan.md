# archify diagram skill — plan (0.171.0)

Task `aib-archify-diagram-skill-default-integration`. Effort: high. Target version: **0.171.0**
(minor: a new default skill changes scaffold output; precedent 0.147.0 / 0.154.0 / 0.166.0).

Inputs: `docs/work/2026-09-13-archify-diagram-skill-research.md` and the three lane proposals
(`-plan-proposal-architect.md`, `-plan-proposal-test-engineer.md`, `-plan-proposal-api-engineer.md`).
Where the lanes disagreed, the ruling is stated in the package.

## Rulings on the research record's six open questions

1. **Packet contents — full upstream packet.** Vendor the canonical v2.16.0 release packet:
   76 files, 5.88 MB, including the five rendered `examples/*.html` (3.59 MB, 61%). Owner said
   "full packet"; the trim would live in the re-vendor tool forever. Accepted cost: copied three
   times (`features/`, plugin `skills/`, `.ai-badger/` mirror) ≈ 17.6 MB working tree.
2. **Provenance — release asset pinned by sha256.** v2.16.0 publishes `archify.zip`
   (1,318,273 bytes, sha256 `4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46`,
   MEASURED via `gh release download` + `shasum`; the API `digest` agrees, and staging the tag with
   upstream's own `scripts/stage-clean-skill.mjs` produces a byte-identical tree — MEASURED
   `diff -r`). `vendor.json` pins repo, tag, commit `c826e6c3…`, asset sha256, and per-file sha256.
   The architect's claim that "the tag has no stager" is wrong — the tag carries it; corrected here.
3. **SKILL.md adaptation — one file, guarded.** Replace only the frontmatter with ai-badger's
   required keys; keep the upstream body byte-identical except for added `## When NOT to Use`,
   `## Gotchas`, and the Mermaid-fallback statement. `vendor.json` records `SKILL.md` as adapted
   with `upstream_body_sha256` + adapted-frontmatter hash so `--check` still verifies it. A thin
   wrapper around a second byte-identical `SKILL.md` was rejected (splits the procedure).
4. **Node dependency — detect-only `system` ecosystem.** Implement `ecosystem: system` in
   `dependency_check.py`: detect with `shutil.which(package)` (plus `node --version` major ≥ 18 for
   the archify entry's floor), report `already_present` in report-only mode too, install only when
   `allow_install` **and** a declared `command` are both present, and never run anything for archify
   (no universal Node installer belongs in catalog data). No schema change — the enum and `command`
   already exist. A node-ecosystem entry was rejected: it would run `npm install -g node`.
5. **Lint as-is — measured clean.** `references_without_conditions` returns `[]` on the upstream
   body; body 127 lines / 15,215 chars (proxy 3,804). One adjacency accident is pinned anyway
   (line ~82: add "when you need field enums or spacing math"). Added text must not create a
   conditionless `references/` mention.
6. **Docs/task integration — invariant + documentation gateway + one clamped task line.**
   New common invariant `archify-diagrams.md`; `scaffold-documentation` and `update-documentation`
   member edits. `differential-feature-refactor` keeps its Mermaid mandate: committed Markdown is
   the documented inline fallback case. `complete-project-scope-code-review` already says "the
   repo's own diagram convention" and needs no edit. The task skill gets one clause (its body is at
   proxy 4,964.5/5,000, so ≤ ~140 chars of net addition; `gates/skills_lint.py` rule 7 is the gate).
   If even that cannot be added safely, the invariant carries the rule and the fallback is
   recorded in the PR — but the clause is attempted first, because the owner named `task`.

**Owner-surfaced decisions, resolved:** full packet stays (Q1); upstream's opt-out update check is
kept as-is and documented in `## Gotchas` (`ARCHIFY_UPDATE_CHECK_DISABLED=1`), rather than
diverging from upstream behaviour (R5).

## Packages

**PKG-1 — vendored packet, provenance, catalog delivery** (serial; blocks PKG-2/3/4; first merge)

- **1a — Vendor the packet.** `features/common/skills/archify/` holds the 76 upstream files
  byte-identical (from the v2.16.0 release asset), `LICENSE` included, plus
  `THIRD_PARTY_NOTICES.md` backfilled from upstream `main` (v2.16.0 ships none; `brand-marks/
  catalog.json` is byte-identical between v2.16.0 and main — MEASURED `shasum`, so the notice
  applies exactly), `VENDOR.md` (human provenance + the stager delta), `vendor.json`, and the
  adapted `SKILL.md`.
  **AC:** file set = 76 upstream files (no `test/`, no `package-lock.json`, no
  `scripts/generate-*.mjs`, staged `package.json` without `scripts`/`devDependencies`) + the
  ai-badger additions; `node bin/archify.mjs doctor` exits 0 from the feature dir.
  **Gate:** `python3 tooling/vendor_archify.py --check`; `node features/common/skills/archify/bin/archify.mjs doctor`.
- **1b — Provenance tool + tests.** `tooling/vendor_archify.py`: `--check` (offline, exit 0 clean /
  1 on `MISSING|EXTRA|CHANGED`, never network) and `--revendor <archify.zip>` (verify sha256 first,
  stage to temp, apply exclusions + `package.json` cleaning + frontmatter adaptation, replace tree,
  regenerate `vendor.json`; refuses to replace a dirty target via `git status --porcelain`).
  `tests/test_archify_vendor.py` written red first: planted drift, missing file, extra file,
  edited adapted file, wrong zip sha. Manifest honesty note: offline `--check` proves internal
  consistency, **not** upstream origin; the origin anchor is the release-asset sha.
  **AC:** every planted defect turns `--check` red with the right `MISSING|EXTRA|CHANGED` label;
  a corrupt zip is refused before any write.
  **Gate:** `python3 -m pytest tests/test_archify_vendor.py -q`; `python3 tooling/vendor_archify.py --check`.
- **1c — Catalog wiring (the join).** `tooling/validate.py` exemptions for the vendored JSON
  families (`schemas/*.json`, `examples/*.json`, `brand-marks/catalog.json`, `package.json`,
  `skill-release.json`, `vendor.json`; each reason ≥ 30 chars, each pattern matching ≥ 1 file, and
  a necessity test proving a removed pattern re-reddens `unschemad_feature_json`); `docs/scripts.md`
  row for the new tool; `index.json` rebuild; plugin copy `skills/archify/`; `docs/skills.md` row +
  counts (47→48, 46→47, 44→45; "These 43" and the 53-file tree sentence corrected);
  `tests/test_expected_skill_names.py` 48→49; `VERSION` 0.171.0; changelog entry + index;
  `features/common/data/model-groups.json` stamp; `docs/adr/0030-*.md` + ADR README row;
  self-scaffold (`index`-then-`scaffold`).
  **AC:** all of these exit 0: `tooling/validate.py --all`, `gates/skills_lint.py`,
  `tooling/index_build.py --check`, `tooling/sync_plugin_skills.py --check`,
  `tooling/version_sync.py --check`, `tooling/changelog_index.py --check`, `gates/release_guard.py`,
  `gates/scaffold_freshness_guard.py`, and `pytest tests/test_docs_match_the_catalog.py
  tests/test_expected_skill_names.py tests/test_catalog_claims_checkable.py -q`.
  **Owns:** as listed. Serial.

**PKG-2 — Node ≥18 as a report-only system dependency** (parallel with PKG-3; owns dependency files)

- **2a — `system` ecosystem.** `dependency_check.py` detects `shutil.which(package)` in both
  report and execute modes (a present binary reports `already_present`, never a would-install
  hint); missing binary without a declared `command` → hint, never error; install runs only with
  `allow_install` + declared `command`, via `shlex.split` + `subprocess.run(shell=False)`. The
  archify entry declares no `command`, so it can never auto-install.
  **AC:** case matrix green in `tests/test_dependency_check.py` (present/absent × report/execute ×
  command declared/not; node `<18` → hint naming the floor and the Mermaid fallback; no
  `subprocess.run` call without consent); `pylint` clean on the changed script.
  **Gate:** `python3 -m pytest tests/test_dependency_check.py -q`.
- **2b — Archify entry.** `features/common/dependencies.json` gains
  `{feature: archify, ecosystem: system, package: node, note: "…Mermaid fallback…"}`, no `command`.
  **AC:** validates against `dependencies.schema.json`; the scaffold note names the fallback.
  **Gate:** `python3 tooling/validate.py --all`;
  `python3 features/common/skills/welcome-ai-badger/scripts/dependency_check.py --root . --target . --features archify`.
  Wave: PKG-2 ∥ PKG-3. (The pre-existing dead `code-review-graph` dependency entry is noted as a
  follow-up, not fixed here.)

**PKG-3 — default-with-fallback policy** (parallel with PKG-2; owns invariant + docs members + task)

- **3a — Invariant.** `features/common/invariants/archify-diagrams.md`: author
  architecture/workflow/sequence/data-flow/lifecycle diagrams with `archify` when installed; fall
  back to Mermaid when Node 18+ or the skill is unavailable, the diagram must render inline in
  committed Markdown, or the user asks for text. H1 + one paragraph, no links, no evidence table.
  **AC:** the rule appears in the assembled agent files once; agent-doc budgets hold
  (`agentDocs.maxLines` 260 / `maxChars` 17500).
  **Gate:** `gates/scaffold_freshness_guard.py` after self-scaffold;
  `grep -c "Archify" CLAUDE.md .ai-badger/CLAUDE.md`.
- **3b — Documentation members.** Replace the Mermaid-only mandates with default + fallback in
  `documentation/references/scaffold-documentation/SKILL.md` (root-README diagram bullet) and
  `documentation/references/update-documentation/SKILL.md` (visual-first bullet). Members are
  below skills_lint's reach; `manifest.json` purposes stay byte-equal (frontmatter descriptions
  unchanged).
  **AC:** both name archify first and Mermaid as the inline/unavailable fallback;
  `git diff --stat features/common/skills/documentation` shows exactly two files.
- **3c — Task skill clause.** One ≤140-char net addition to Phase 2 (design/arch presentation
  routed to `archify`, Mermaid only when the runtime is missing), with `skills_lint` rule 7 as the
  hard gate; trim within the paragraph if needed rather than breaching the cap.
  **AC:** `python3 gates/skills_lint.py` exit 0; body chars/4 ≤ 5000.
- **3d — Self-scaffold.** `index`-then-`scaffold` so the invariant and member edits reach
  `.ai-badger/**`, the plugin copy, and the agent files.
  **Gate:** `gates/scaffold_freshness_guard.py` PASS; `tooling/sync_plugin_skills.py --check` 0.

**PKG-4 — integration package** (serial; last merge; cross-package tests)

- **4a — Integration tests.** `tests/test_archify_integration.py` scaffolds a scratch consumer with
  the real scaffolder (`conftest.make_scaffolder`) and asserts: the delivered
  `.ai-badger/skills/archify/` tree hashes match the catalog (PKG-1); the scaffolded `CLAUDE.md`
  carries the diagram rule and `.ai-badger/invariants/archify-diagrams.md` exists (PKG-3);
  `dependency_check --features archify` reports node present with no missing hint (PKG-2);
  `node .ai-badger/skills/archify/bin/archify.mjs doctor` exits 0; `deliver architecture
  <example> <out.html> --quality showcase --json` exits 0 with 9/9 artifact checks and writes the
  HTML. Node legs `skipif` without node, with a companion `tests/js/archify_packet.test.mjs`
  running doctor + deliver against the catalog copy unconditionally in the `js` lane.
  **AC:** file green; each assertion watched red on the pre-change base before it is made green.
  **Gate:** `python3 -m pytest tests/test_archify_integration.py -q`; `node --test tests/js/archify_packet.test.mjs`.
- **4b — Release sweep.** Re-run every PKG-1 gate on the joined tree plus
  `gates/consumer_journey.py`; `git status --porcelain` clean after the final self-scaffold.
  **AC:** all commands exit 0 on one tree.

## ADR-0030 outline

- **Context:** no diagram-authoring capability in the catalog; five skills/templates name Mermaid,
  which renders inline but produces no standalone artifact. Archify is MIT (two copyright holders),
  Node ≥ 18, zero runtime npm dependencies, distributed as a staged release asset. ai-badger has
  vendored byte-equal code before (`badger_store.py`, ADR-0009/0024); ADR-0028 says common skills
  ship by default.
- **Decision:** (1) vendor the v2.16.0 release packet under `features/common/skills/archify/` with
  `vendor.json` provenance + `tooling/vendor_archify.py --check`, re-vendoring is an explicit PR
  against a new asset sha; (2) `scope: default`; (3) archify is the default diagram authoring tool,
  stated once as the common invariant `archify-diagrams.md`, with Mermaid as the fallback for a
  missing Node runtime, inline-Markdown rendering, or an explicit text request; (4) Node ≥ 18 is a
  detect-only `system` dependency, never auto-installed.
- **Consequences:** positive — polished validated artifacts with no install step, verifiable
  provenance, clean degradation. Negative — ~17.6 MB working tree and ~5–6 MB pack growth; a
  third-party surface pinned until re-vendored; Node becomes a de-facto runtime for one default
  skill; the upstream update check makes an opt-out network call; v2.16.0 lacked a third-party
  notice that must be carried from main. Neutral — plugin copy is a pointer + `SKILL.full.md` like
  every other skill; projects can decline with `config.exclude.skills: ["archify"]`.
- **Alternatives:** external skill source (no runtime install; uncovered pi/hermes/copilot paths);
  runtime fetch (unpinned); first-party Mermaid-only rewrite (leaves the ask unmet); `optIn`
  (contradicts the ask); trimmed packet (deferred, named).

## Risks

- **Bundle size** — measured 5.88 MB × 3; accepted (owner "full packet"); trim of
  `examples/*.html` is the documented escape hatch.
- **Vendored content breaking gates** — measured clean so far (no evidence tables, no absolute
  paths, rule 8 empty); PKG-4's full sweep is the backstop.
- **Count/stamp drift** — the 0.166.0 precedent missed `model-groups` stamps; PKG-1's gate list
  includes every derived-count check in the same commit.
- **`.ai-badger/` collisions across lanes** — only the orchestrator's join writes mirrors; lanes
  own disjoint source paths.
- **Task-skill budget** — rule 7 is the gate; fallback to invariant-only if the clause cannot fit.
- **Node absent in a consumer repo** — hint + invariant + SKILL.md Gotchas; tested by simulating
  `shutil.which → None`.

## Test-run economy

Locally in one pass: `tests/test_archify_vendor.py`, `tests/test_dependency_check.py`,
`tests/test_docs_match_the_catalog.py`, `tests/test_expected_skill_names.py`,
`tests/test_catalog_claims_checkable.py`, `tests/test_archify_integration.py`, plus
`validate.py --all`, `skills_lint.py`, `index_build --check`, `sync_plugin_skills --check`,
`scaffold_freshness_guard.py`, `changelog_index --check`, `version_sync --check`,
`release_guard.py`. CI owns the full `pytest -q`, `pylint`, `journey`, `tdd`, `js`, `pi-ts` lanes.
No local full-suite repetition.
