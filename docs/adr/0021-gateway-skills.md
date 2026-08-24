# ADR-0021 — Gateway skills: one registration, members under references/

**Date:** 2026-08-24
**Status:** Accepted (2026-08-24, 0.137.0)
**Author:** Rafał Araszkiewicz (Arasz) with ox-alpha (implementation lane)
**Extends:** ADR-0018 (declaration travels with the skill), ADR-0015 (mechanisms, not prose)
**Scope:** `gates/skills_lint.py` rule 13, `badger_lib.gateway_aliases`/`SKILL_GROUPS`, the
dotnet and documentation catalogs

## Context

A skills directory registers exactly one nesting level (ADR-0010/0018), so every specialized
skill is a registered entry in every consuming agent's discovery surface. The dotnet stack
carried eleven of them and the common catalog three documentation skills; all fourteen were
plain invoked-by-name skills with no hook wiring. A dotnet-stack scaffold advertised ~11 skill
descriptions where one would do, and the matcher had to disambiguate eleven similarly-named
skills. Meanwhile `SKILL_GROUPS["documentation"]` existed purely to deliver the docs trio
together — grouping in configuration because the catalog could not group on disk.

## Decision

Four owner rulings:

1. **Gateway = a level-1 skill dir carrying `manifest.json`.** No new frontmatter key, no
   second registry. Members live at `<gateway>/references/<member>/` — one nesting level below
   registration — and are deliberately *un*-registered.
2. **Two gateways only, for now:** `dotnet-workload` absorbs the eleven dotnet skills;
   `documentation` keeps its name and absorbs the trio.
3. **The manifest is the declaration, and it must be true.** `skills_lint` rule 13 derives
   everything from disk: kind, non-empty members, each member's `paths.skill` existing,
   name/directory agreement, orphan detection for anything under `references/` the manifest
   does not name — and byte equality between a member's `purpose` and that member's own
   frontmatter `description:` (derive-or-delete; the manifest may not paraphrase). `triggers`
   stay curated: their aggregation across members is the gateway's reason to exist.
4. **Stale names resolve through a derived alias map, not a migration note.**
   `badger_lib.gateway_aliases(root)` walks `features/*/skills/*/manifest.json`; inclusion and
   exclusion both apply it, and an ambiguous member name raises rather than winning silently.
   `SKILL_GROUPS["documentation"]` is deleted: the gateway is a real registered skill named
   `documentation`, so config naming it needs no machinery at all.

### Why aliases beat migration notes

Deleting the group means `"skills": ["documentation"]` works with zero machinery. Only stale
*member* names need help, and a silent no-delivery of a named skill is precisely ADR-0005's
failure mode; a note that merely reports it converts working config into dead config the reader
is invited to delete (#275 in reverse). The alias map costs one directory walk per scaffold and
cannot drift from reality because nothing writes it down.

### Accepted narrowings, and what covers them

Lint reach narrows for the fourteen members: their SKILL.mds leave `skills_lint`'s glob and the
sibling-citation scan. Compensating controls:

- rule 13's existence + orphan checks mean nothing under `references/` can be unaccounted;
- the gateway itself stays fully linted (pinned by test — there is no gateway exemption);
- the member-to-member sibling-citation check was ported to walk
  `features/common/skills/documentation/references/*/*/SKILL.md`, so file-level citations stay
  verified — directory existence alone is not sufficient;
- members' extension fragments (`extensions/ledger/`) travel inside their member dirs and stay
  config-gated: extension discovery enumerates member dirs derived from the manifest paths.

### Costs

Manifests are one more artifact to keep truthful — mitigated only by rule 13 making lies loud,
not impossible. Two declaration formats coexist: frontmatter for registered skills (including
gateways), manifests for unregistered members. That duality is accepted because members are
deliberately outside registration.

## Consequences

- Discovery surfaces drop from 14 entries to 2; a dotnet scaffold advertises one skill.
- Members load only after the gateway routes to them, converting accidental multi-skill
  loading into deliberate single-member loading.
- Existing projects naming an absorbed member keep delivering; the next `den-refresh` reports
  moved skills as drift and offers the gateway config.

## Revisit condition

If gateway bodies accrete member detail again — routing tables restating member descriptions,
per-member gotchas — the manifest is rotting: the aggregation should live in `triggers` and the
members' own frontmatter, or the gateway boundary is wrong and should be re-drawn.
