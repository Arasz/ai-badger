# ADR-0028 — The whole catalog ships by default; the opt-in tier is empty

**Date:** 2026-09-11
**Status:** Accepted (2026-09-11, 0.169.0) — owner-ruled
**Author:** Rafał Araszkiewicz (Arasz) with pi (den-refresh lane)
**Scope:** every `scope:` declaration under `features/common/skills/`, `config.include` /
`config.exclude`, the delivery tests and the shipped plugin copy
**Related:** ADR-0018 (mechanism — unchanged), ADR-0005 (superseded by 0018), ADR-0021 (gateways)

## Context

ADR-0018 put a `scope: default | optIn` key in each skill's own `SKILL.md` and left the question
of *which* skills are opt-in to authors. Over time 20 common skills declared `optIn`, each for a
local reason of its own:

- the documentation gateway, because a project asks for that workflow rather than having it
  forced into every listing;
- the navigation trio (`review-changes`, `debug-issue`, `refactor-safely`), because their
  workflows derive from templates the third-party `code-review-graph` package auto-installs —
  ai-badger did not want to contend for the same files uninvited;
- the fed-back workflow skills (`artifact-verification`, `code-review-evidence`,
  `complete-project-scope-code-review`, `design-gate-audit`, `documentation-drift-audit`,
  `multi-lane-report-assembly`, `pre-push-gate-debugging`, `research-record-audit`,
  `review-gate-diff-verification`, `scripts-tooling-refactor`, `spec-driven-refactoring`,
  `sqlite-bank-space-diagnosis`, `sqlite-schema-review`, `worktree-agent-isolation`,
  `evidence-first-research`, `explore-codebase`), because a skill contributed from a consumer
  project should not silently ship to every scaffolded project.

The cost of that care landed on the operator: every project that wanted one of them had to name
it in `config.include.skills`, and every project that named a set had to maintain that list. The
feedback it produced was the same at each refresh — the catalogs are held by one owner who wants
a project to get the framework's current best practice by default, and who can decline by name
when a specific skill is wrong for that repo.

## Decision — owner-ruled

**Every common-stack skill declares `scope: default`. The opt-in tier is empty.**

- All 20 formerly-optIn skills ship with every scaffold, into the plugin copy, and into
  `den-refresh`'s delivered set — including the sqlite pair, which an individual project may
  still decline with `config.exclude.skills`.
- `documentation`'s three nested members are `default` with it; they were never catalog items of
  their own (ADR-0021).
- **The mechanism survives the policy change.** `scope: optIn`, `config.include.skills`,
  `availableOptIn` and the inclusion notes all stay. No catalog skill declares `optIn` today; a
  future skill with a real prerequisite can, and then the include path is how a project asks.
- **Declining is the project-level lever.** `config.exclude.skills` removes delivery and the
  discovery links ai-badger placed, for any skill now default. The documentation for both
  mechanisms is `docs/skills.md`; the authoring rule is
  `docs/authoring-a-feature.md#default-or-optin`.

## Consequences

- **Re-scaffolds deliver more.** An existing project that refreshes gains every formerly-optIn
  skill it did not name. This is additive for the project and is the point of the change; a
  project that does not want one declines it by name. No migration step is required, so 0.169.0
  is **not** in `BREAKING_VERSIONS`.
- **The shipped plugin copy grows.** `sync_plugin_skills.py` ships by scope, so the plugin gains
  the whole common catalog — that is the delivery path Claude Code installs from.
- **The navigation trio now ships beside `code-review-graph`'s own copies.** That contention was
  the recorded reason for their `optIn`; it is accepted here, and a project running that tool can
  exclude the three.
- **The sqlite skills ship to projects with no SQLite database.** Their triggers are specific
  enough to stay dormant, and a project that wants them gone excludes them.
- **Three tests that pinned the old policy were rewritten to the new one**, and the PR body names
  them: `test_the_documentation_gateway_is_opt_in` and `test_the_navigation_skills_are_opt_in`
  (now `..._is_default` / `..._are_default`), `test_fed_back_workflow_skills_are_opt_in` (now
  `test_fed_back_workflow_skills_ship_by_default`), and the plugin-copy expectation that an
  opt-in skill is absent from the shipped list (now present).
- **The include path keeps end-to-end coverage through a simulation.** With no real opt-in skill
  left, `tests/conftest.py`'s `simulated_opt_in` fixture makes `documentation` optIn again in the
  entry points' `badger_lib`, so the delivery, discoverability (#261) and refresh tests still
  exercise the mechanism rather than deleting it.

## Revisit condition

This is a policy choice, not a mechanism choice. If a future skill's unasked delivery proves
damaging in practice — the contention the navigation trio's `optIn` was meant to prevent — the
fix is to declare that one skill `optIn` again and update
`tests/test_skill_scope_declarations.py::TestPinnedScopes::test_the_opt_in_tier_is_empty`, which
exists so that quieting a single skill is a visible decision rather than a silent one.
