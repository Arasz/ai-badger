# ADR-0005 — One Declaration of Which Skills Ship

**Date:** 2026-07-27
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent
**Supersedes:** None

## Context

Two hand-maintained lists decided which skills a user actually gets:

- `scaffold.DEFAULT_SKILLS` — what `welcome-ai-badger` writes into a project's `.ai-badger/skills/`
- `sync_plugin_skills.COMMON_SKILLS` / `CLAUDE_SKILLS` — what the plugin copy in `.claude/skills/` exposes

Nothing tied them to each other or to the catalog. They were two copies of the same product
decision, kept in agreement by hand.

`code-review-checklist` is what that cost us. It has been in the catalog since it was written,
is indexed by `index_build.py`, has tests and six stack extensions — and appeared in **neither**
list. It shipped to nobody by either route, for its entire life, and nothing failed. A skill
could be complete, correct, and unreachable, and the only way to notice was to read both lists
and diff them against the tree by eye.

The failure mode is omission. Any fix that still lets a skill be absent from a list reproduces it.

## Decision

**One declaration, and omission is an error.**

`badger_lib.SKILL_SCOPES` maps every catalog skill to a scope:

- `default` — ships without being asked for: scaffolded into projects *and* copied into the plugin
- `optIn` — stays in the catalog; installed only when named

Both consumers derive from it. `DEFAULT_SKILLS` is `bl.default_skill_names()`;
the plugin's per-stack lists are `bl.default_skills_in(<stack>/skills)`, which is the same
decision filtered by which directory holds the skill. `index_build.py` stamps the scope onto
each skill entry, so the generated catalog carries the decision where readers already look.

`skill_scope()` raises `UnknownSkillScope` rather than assuming a default, and
`test_every_catalog_skill_is_reachable_by_a_declared_route` fails on any catalogued skill with
no declaration. A new skill cannot repeat `code-review-checklist`'s history: it either declares
a route or CI stops.

**`code-review-checklist` is scoped `default`** — it ships everywhere.

## Alternatives considered

**Declare the scope in SKILL.md frontmatter.** The most natural home, and rejected on cost: no
script in `scripts/` parses YAML frontmatter today, and pyyaml is a guarded optional import that
degrades to a note. Adding a parser — or hand-rolling one — to read a single scalar buys a
worse failure mode than the constant it replaces. Worth revisiting if anything else ever needs
frontmatter at build time.

**Derive from directory layout** (e.g. a `default/` subtree). Behaviour becomes invisible in
`git mv` and couples the decision to paths that other tooling resolves.

**Leave the lists, add a parity test.** Fixes the drift between the two lists but not the
omission that caused this — both lists can still miss a skill in agreement.

## Consequences

- The default skill set grows by one; `code-review-checklist` now reaches every project.
- Adding a skill is a two-step act: create the directory, declare its scope. CI enforces the second.
- `SKILL_SCOPES` is still hand-maintained. It is one list instead of two, checked against the
  catalog in both directions, which is the property that matters.
- The scope is now part of `index.json` and `index.schema.json`; consumers may read it.
