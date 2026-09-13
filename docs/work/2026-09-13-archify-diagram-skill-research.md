# archify diagram skill — research record

Dated 2026-09-13. Task `aib-archify-diagram-skill-default-integration`. Every finding carries
how it is known. MEASURED = command run and output read; READ = source read in this session;
INFERRED = derived from read/measured facts; HYPOTHESIS = unverified.

## 1. What the user asked for

- Add and integrate <https://github.com/tt-a1i/archify> as an ai-badger skill.
- Full packet, installation dependencies, integration into other skills (documentation, task)
  for design / architecture presentation.
- Used by default to generate diagram / flow / architecture, with a fallback to Mermaid.
- Effort: high. Delivery mechanism: option A — vendored catalog skill, `scope: default`,
  essential packet, pinned upstream commit, re-vendor procedure. (Owner answered directly.)

## 2. Upstream archify (MEASURED via GitHub API + a v2.16.0 sparse clone in /tmp/archify-clone)

- MIT. `LICENSE` carries two copyrights: `tt-a1i (Archify)` and `Cocoon AI (original
  "architecture-diagram-generator")` (READ, `/tmp/archify-clone/archify/LICENSE`).
- Node.js `>=18`, zero runtime npm dependencies: `package.json` is `private: true` and carries
  `devDependencies` only (READ, `/tmp/archify-clone/archify/package.json`).
- Latest stable tag is **v2.16.0** at commit `c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de`; main is
  at 2.17.0-dev.1 (MEASURED, GitHub tags API + `git ls-remote`). Pin to v2.16.0 (stable).
- No npm install is required to run it: `node bin/archify.mjs doctor` self-checks (READ,
  upstream SKILL.md "Setup and fallback"). `visual-check` finds Chrome/Chromium via
  `ARCHIFY_CHROME` or well-known paths and exits 2 (skipped) when absent (READ,
  `bin/visual-check.mjs:107-130`).
- Upstream ships a canonical staged packet: `scripts/build-zip.sh` → `scripts/stage-clean-skill.mjs`.
  At v2.16.0 the packet excludes `archify/test/`, `archify/package-lock.json`,
  `archify/scripts/generate-brand-marks.mjs`, `archify/scripts/generate-validators.mjs`, and
  cleans `package.json` (drops `scripts` + `devDependencies`). (READ,
  `https://raw.githubusercontent.com/tt-a1i/archify/v2.16.0/scripts/build-zip.sh` and
  `.../main/scripts/stage-clean-skill.mjs`; the staged main zip lists 79 files / 6.49 MB.)
- The packet's runtime file reads are all relative to `skillRoot` (`bin/..`): `assets/template.html`,
  `recipes/scenarios.mjs`, `delta/architecture-delta.mjs`, `migrations/workflow-v2.mjs`,
  `schemas/<type>.schema.json`, `examples/*.json` (MEASURED, grep of `bin/archify.mjs`
  lines 1221, 1256, 1275-1278, 1317, 1374, 1463, 1651). Renderers import each other relatively.
- `scripts/check-update.mjs` performs an opt-out network check (`ARCHIFY_UPDATE_CHECK_DISABLED=1`)
  (READ, `scripts/check-update.mjs:1637`).
- v2.16.0 has **no** `THIRD_PARTY_NOTICES.md`; main added one covering the embedded Simple Icons
  16.28.0 brand marks (READ, GitHub contents API at the tag vs raw main). `brand-marks/` is
  present at v2.16.0 (MEASURED, tree listing).
- Upstream install path for other agents is `npx -y skills add tt-a1i/archify …` for
  codex/cursor/claude-code/opencode (READ, <https://tt-a1i.github.io/archify/start.html>), which
  does not cover pi/hermes/copilot — supporting the vendored-packet choice.

## 3. ai-badger mechanics (MEASURED by reading the tree, `git show 7a751008`)

Adding a default common skill touches, at minimum (from the 0.166.0 `qa` skill commit
`7a751008` — the last skill addition):

1. `features/common/skills/<name>/` (source dir).
2. `index.json` rebuild (`tooling/index_build.py`).
3. Plugin copy `skills/<name>/` (`tooling/sync_plugin_skills.py`, which for non-bootstrap skills
   renders a pointer `SKILL.md` + `SKILL.full.md`).
4. Self-scaffold of this repo: `.ai-badger/skills/<name>/`, `.ai-badger/manifest.json` hashes,
   `.claude/skills/<name>` + `.github/skills/<name>` symlinks, version stamps across
   `.ai-badger/*`, `CLAUDE.md`, `HERMES.md`, `.github/copilot-instructions.md`, `.hermes.md`.
   Order matters: index first, then self-scaffold (READ, docs/changelog/0.147.0).
5. `VERSION` + `docs/changelog/{version}-{slug}.md` + `tooling/changelog_index.py` +
   `tooling/version_sync.py`, and `features/common/data/model-groups.json` +
   `.ai-badger/model-groups.json` version stamps (the 0.166.0 commit missed the latter two and
   CI caught them).
6. `docs/skills.md` at-a-glance row + opening counts, enforced by
   `tests/test_docs_match_the_catalog.py`; `tests/test_expected_skill_names.py` hardcodes
   `assert len(derived) == 48` (44 default common + 4 stack-local).
7. `tooling/validate.py` `FEATURE_JSON_WITHOUT_SCHEMA` patterns for every vendored JSON file
   (`unschemad_feature_json` fails otherwise), each needing a reason ≥30 chars and ≥1 matching
   file (`tests/test_catalog_claims_checkable.py`).
8. `tooling/sync_plugin_skills.py --check` and `gates/scaffold_freshness_guard.py` must pass —
   the guard compares the delivered tree to a re-scaffold and currently reports PASS on main
   (MEASURED, ran it: "2351 path(s) compared … only version stamps differ — PASS").

Local gates run by `.lefthook/pre-push/verify.sh` include: version-sync, index, plugin-skills,
deps, docs, release, paths, workflows, validate, scaffold, journey, tdd, js, pi-ts, pylint,
pytest, mutation (READ, `.lefthook/pre-push/verify.sh` lanes list).

Skill lint (`gates/skills_lint.py`) rules that bind the vendored SKILL.md: name grammar + dir
match; description non-empty, ≤1024 chars, starts with "Use when"; body ≤500 lines and chars/4
≤5000; every `references/` mention carries a when/if/before/after/only-when condition in its
3-line window; a `## Gotchas` section; deterministic frontmatter with keys
`name, description, version, author, license, platforms, metadata.hermes.tags,
metadata.hermes.related_skills`; `scope: default` (rule 12).

Assembled agent files have a budget (`agentDocs.maxLines: 260`, `agentDocs.maxChars: 17500`);
`CLAUDE.md` is 224 lines today (MEASURED), so one invariant line fits.

Dependencies: `features/common/dependencies.json` is consumed by
`features/common/skills/welcome-ai-badger/scripts/dependency_check.py` with
`features = scaffolded skill names` (READ, `scaffold.py:551-570`). The schema allows ecosystems
`python | node | system` and a `command` field, but the implementation handles python and node
only; a `node` dep would run `npm install -g <package>` and `system` is rejected as
`unknown ecosystem` (MEASURED, `dependency_check.py:105-140, 218-235`). Tests live in
`tests/test_dependency_check.py`.

## 4. Integration points for "archify by default, Mermaid fallback"

Diagram/Mermaid authors in the catalog (MEASURED, grep):

- `features/common/skills/documentation/references/scaffold-documentation/SKILL.md:51` — root
  README "high-level architecture/flow Mermaid diagram".
- `features/common/skills/documentation/references/update-documentation/SKILL.md:64` — diagrams
  "Mermaid flowcharts, sequence diagrams, mindmaps"; root README architecture diagram.
- `features/common/skills/differential-feature-refactor/references/differential-template.md:70-74`
  — "Each view is one Mermaid diagram for Have and one for Will have".
- `features/common/skills/complete-project-scope-code-review/SKILL.md:169` — "Two diagrams in the
  repo's own diagram convention".
- `features/common/skills/humanizer/SKILL.md` — one illustrative Mermaid flowchart (content, not a
  generated diagram).
- `docs/retrieval.md` — the framework's own Mermaid diagram (content).

Gateway members are NOT subject to skills_lint rules 1–12 (`skill_files` globs
`features/*/skills/*/SKILL.md`, one level only), so member bodies can be edited freely; rule 13
only pins each member's frontmatter `description` byte-equality to `manifest.json` `purpose`.

`features/common/skills/task/SKILL.md` is 368 lines / 20,880 bytes total; its body is already
close to the 5000-token proxy cap (MEASURED, `wc`), so any task integration must be short or go
through `references/`.

The natural cross-cutting home is a new common invariant
(`features/common/invariants/*.md`, one short rule, copied into every agent file). Roughly 31
invariants exist today; one more fits the agent-doc budget with room to spare.

## 5. Open questions for the planning panel

1. Packet contents: vendor exactly the upstream staged packet at v2.16.0 (79-ish files, ~6.3 MB
   incl. 5 rendered example HTMLs) — "full packet" per the owner — or drop the rendered HTML
   examples? Recommendation: vendor the canonical packet unchanged.
2. Provenance mechanism: `vendor.json` (upstream repo/tag/commit + per-file sha256, SKILL.md
   marked adapted) + `tooling/vendor_archify.py` re-vendor/`--check`, or a lighter documented
   procedure only. Recommendation: include the tooling; integrity tests are cheap and this repo
   already tests byte-equality of vendored copies.
3. SKILL.md adaptation: replace the frontmatter with ai-badger's required keys, keep the upstream
   body verbatim, add `## When NOT to Use` / `## Gotchas` / the Mermaid-fallback note. Alternative
   rejected: a thin wrapper around a byte-identical upstream `SKILL.md`, which splits the
   procedure across two files.
4. Node dependency: implement `ecosystem: system` in `dependency_check.py` (detect via
   `shutil.which`, install only when a `command` is declared and `--execute` was passed) and add
   the archify entry, with a note naming the Mermaid fallback. Alternative rejected: a
   node-ecosystem entry, which would run `npm install -g node`.
5. Does the upstream SKILL.md body pass lint rules 6–8 as-is? Upstream body is ~15.3 KB
   (proxy ~3.8K < 5000) and 137 lines; rule-8 violations, if any, must be fixed by adding
   conditions at the mention sites, not by deleting the references.
6. Where the docs/task integration lands precisely (docs gateway members, invariant wording,
   the one or two lines the task skill can afford).
