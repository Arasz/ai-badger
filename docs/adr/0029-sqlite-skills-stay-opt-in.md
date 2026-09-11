# ADR-0029 — The sqlite pair stays opt-in; ADR-0028 otherwise stands

**Date:** 2026-09-11
**Status:** Accepted (2026-09-11, 0.170.0) — owner-ruled
**Author:** Rafał Araszkiewicz (Arasz) with pi
**Scope:** `features/common/skills/sqlite-bank-space-diagnosis/SKILL.md`,
`features/common/skills/sqlite-schema-review/SKILL.md`, the delivery pins, the docs counts
**Supersedes:** ADR-0028 **in part** — its "every common-stack skill" clause and its sqlite
paragraph; the rest of ADR-0028 (the empty rationale for everything else, the retained
`include`/`availableOptIn` mechanism, `config.exclude` as the decline) stands unchanged

## Context

ADR-0028 moved the whole common catalog to `scope: default`, including the sqlite pair, on the
reading that a project can decline by name what it does not want. The owner's ruling is the
opposite for those two: `sqlite-bank-space-diagnosis` and `sqlite-schema-review` are specific to
a SQLite-backed project, and a repo with no SQLite database should not receive them unasked.
That was the original carve-out — "exclude the sqlite skills" — and this ADR records it after
0.169.0 shipped the pair in the default set for a day.

## Decision — owner-ruled

**The sqlite pair declares `scope: optIn`. Every other common skill stays `default` (ADR-0028).**

- The two skills arrive only when a project names one in `config.include.skills`; a project that
  wants to be explicit may also keep them in `config.exclude.skills`.
- They are not copied into the plugin `skills/` directory (`sync_plugin_skills.py` ships by
  scope), and `den-refresh`'s `availableOptIn` section lists them to every project that has not
  installed them.
- ADR-0028's mechanism survives intact: `scope: optIn`, `config.include.skills`,
  `availableOptIn` and the inclusion notes were never in question — this ADR moves two skills
  back into the tier, it does not remove the tier.

## Consequences

- **0.170.0 is a minor release**: it changes what scaffolding does to a consumer repo — the pair
  stops arriving unasked. A project that refreshed to 0.169.0 and received the two skills keeps
  its copies; the next refresh delivers nothing new for them and leaves the mirrors in place
  (a skill that is still in the catalog is not pruned by scope change, only by exclusion or
  removal).
- **The shipped plugin copy and the framework's own mirror drop the pair.** `sync_plugin_skills`
  prunes the plugin copies; the framework's `.ai-badger/skills/` mirrors are removed in the same
  commit, because the freshness guard compares the tree against a re-scaffold that no longer
  produces them.
- **The delivery pins move with the contract**, named in the PR: `test_the_opt_in_tier_is_empty`
  became `test_the_opt_in_tier_is_the_sqlite_pair`, the fed-back-workflows test drops the two
  names, `TestPluginCopyFollowsScope` keeps its default-presence expectation for everything else,
  and the manifest pin moves 50 → 48.
- **The include path no longer needs a simulation for the pair**: a real `optIn` exemplar is back,
  though `simulated_opt_in` remains the fixture for tests that need `documentation` opt-in.

## Revisit condition

The pair is opt-in because SQLite specificity, not price or maturity, is the reason. If a skill
in the default set starts shipping SQLite-specific guidance, or a SQLite-backed stack is added
that should deliver them unasked, revisit: either declare them `default` again (a new ADR) or
route them by stack directory if a SQLite stack ever exists.
