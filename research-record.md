# Research record — consolidate-stack-skills

Every finding cites its source. Unverified claims are marked HYPOTHESIS.

## How skills are routed today

- Routing is the filesystem: a skill lives in `features/<stack>/skills/<name>/SKILL.md`;
  presence in a stack directory = owned by that stack. Source: `docs/adr/0010-stack-local-skill-discovery.md`, ratified by ADR-0018.
- Scope (`default`/`optIn`) is declared in each common-stack skill's own frontmatter
  (`scope:` key); `skills_lint` rule 12 refuses a common-stack skill declaring neither.
  Stack-local skills do NOT declare scope — ADR-0018 explicitly declined to require it
  ("ceremony rots"). Source: `docs/adr/0018-where-the-skill-routing-declaration-lives.md`.
- Delivery walks every configured stack except `DEFAULT_COMMON_STACKS`
  (`SkillDelivery.discover_stack_local`); common-stack optIn skills are filtered by scope.
  Source: ADR-0018 Implementation section.
- A skills directory registers exactly ONE nesting level: a subdirectory without a
  `SKILL.md` at level 1 is silently ignored by every agent. Nested dirs therefore cannot
  be registered skills. Source: `docs/skills.md` (SKILL_GROUPS section).
- Existing grouping precedent: `badger_lib.SKILL_GROUPS` groups skills **in configuration
  only** (`"skills": ["documentation"]` delivers scaffold+update+migrate-documentation);
  delivery stays flat. Source: `docs/skills.md`.
- Hook-backed skills exist (wired at scaffold time, fire on events): e.g. prompt-markers,
  auto-wm, task's dispatch-gate. These must not be restructured blindly. Source:
  `docs/skills.md` intro; HYPOTHESIS on exact list until checked.

## Current inventory

| Stack | Skills |
|---|---|
| dotnet | 11: bdd-testing, domain-modeling, flaky-test-diagnosis, hosted-service-review, hosted-service-testing, logger-message-design, mcp-server, sqlcipher-encryption, system-commandline, tool-publishing, observability-contract-review |
| common | 42 (20 default, 22 optIn) incl. documentation trio (scaffold-, update-, migrate-documentation) already grouped as `"documentation"` |
| hermes | 2 (cron-watchdog-authoring, hermes-plugin-development) |
| mcp | 1 (mcp-tool-surface-testing) |
| ai-raccoon | 1 (ai-raccoon-manual-checklist) |
| claude | 1 (auto-wm, hook-backed, claude-only) |

Source: `ls features/*/skills` on main @ 982df8c9; counts cross-checked against `docs/skills.md`.

## Gates/tests that watch this surface (will go red under consolidation — by design)

- `gates/skills_lint.py` — parses ALL `features/*/skills/*/SKILL.md`; rule 10 (eight
  required frontmatter keys), rule 2 (name == parent dir), rule 12 (common scope).
  Glob is depth-limited (`features/*/skills/*/SKILL.md`) so moving skills one level deeper
  removes them from lint reach — ADR-0018 revisit condition 2 warns exactly about this
  (narrowing the glob once left 15/51 unlinted).
- `tests/test_docs_match_the_catalog.py` — docs/skills.md numbers + rows must match catalog
  (common + claude stacks).
- `tests/test_sync_plugin_skills.py::test_every_catalog_skill_is_reachable_by_a_declared_route`.
- Duplicate-name test: no skill name in two stack dirs (ADR-0018).
- `index_build.py --check` freshness; `drift.py` consumes `index.json`.

## Constraints from prior decisions

- ADR-0018: declaration travels WITH the skill; no hand-maintained parallel lists
  ("derive the list or delete it" invariant agrees).
- ADR-0015: prose doesn't change behaviour; mechanisms do. A gateway skill whose
  description aggregates trigger keywords IS such a mechanism for skill discovery.
- docs/skills.md generated table + bidirectional test is the one-glance view.

## Findings from orchestrator verification

- No hook wiring touches any absorbed skill: grep of hooks/ and features/*/adjustments/
  for the 11 dotnet names + docs trio returned nothing. All 13 are plain invoked-by-name
  skills. Safe to move.
- `SKILL_GROUPS` lives at engine/badger_lib.py:112 ("documentation" trio, plus a
  "testing" group). expand_skill_groups() (line ~127) and inclusion_notes() (~789) read it.
  Decision needed: does "documentation" group become the gateway dir name, or is the group
  deleted once the gateway IS the skill named "documentation"? (Naming the gateway
  `documentation` makes the group redundant — config `"skills": ["documentation"]` then
  names the gateway directly.)
- Cross-reference survival: update-/migrate-/scaffold-documentation cite each other via
  `../<skill>/references/<file>.md` (SIBLING_REFERENCE_RE, badger_lib.py:106). After the
  move all three sit as siblings under documentation/references/<skill>/, so the SAME
  relative paths still resolve. Links need no rewrite — but any lint/test asserting the old
  layout must be found and updated.
  Source: grep of features/common/skills/{update,migrate}-documentation + engine/badger_lib.py.

## Open design decisions (owner input needed)

1. Fate of inner skills' directories: move under `<gateway>/references/<skill>/`
   (drops out of registration AND out of skills_lint glob) vs keep registered.
2. Machine-readable descriptor: JSON manifest inside gateway dir vs inline markdown only.
3. Scope of first conversion: dotnet only / dotnet + common docs trio / all stacks.
4. Frontmatter marker for gateway kind: new frontmatter key vs separate manifest file.
