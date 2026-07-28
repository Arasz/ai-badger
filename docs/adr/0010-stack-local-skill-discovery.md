# ADR-0010 — Stack-local skill discovery

**Date:** 2026-07-28
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent
**Supersedes:** None

## Context

ADR-0005 established `badger_lib.SKILL_SCOPES` as the single declaration for which skills
ship. Every catalogued skill must appear in that dictionary as either `default` (ships
everywhere) or `optIn` (installed only when named).

`auto-wm` was declared `default`, but it lives under `features/claude/skills/` — a
claude-specific directory. Three problems resulted:

1. **scaffold_skills() hardcoded `"common"`** — searched only
   `feature_items(self.index, "common", "skills")`, so even if auto-wm were in the skill
   list, the index lookup would never find it in the claude stack.

2. **DEFAULT_SKILLS and re_scaffold scanned only common/** — both used
   `default_skills_in(features/common/skills/)`, so auto-wm was never discovered.

3. **The scope declaration lied** — `default` means "ships to every stack", but auto-wm
   only works with claude. A dotnet project would see it offered and then skipped.

The failure mode is a skill that is declared universal but only works for one stack — the
scaffold silently skips it, the manifest disagrees with the scope, and the user sees a
confusing warning.

## Decision

**`SKILL_SCOPES` is for universal skills only. Stack-specific skills are discovered from
their stack directory.**

1. Remove auto-wm from `SKILL_SCOPES`. Universal defaults live here; stack-local skills
   do not.

2. Add `badger_lib.stack_local_skills(skills_dir)` — the shared helper that finds skills
   in a directory that are NOT in `SKILL_SCOPES`. Used by both `scaffold.py` and
   `sync_plugin_skills.py` so the discovery logic lives in one place.

3. `Scaffolder.scaffold_skills()` searches ALL configured stacks in the index, not just
   `"common"`. Records the correct `item_stack` provenance in the manifest.

4. `Scaffolder.run()` discovers stack-local skills from configured stacks before calling
   `scaffold_skills()`. Respects `config.exclude`.

5. `sync_plugin_skills.py` uses `bl.stack_local_skills()` for the claude skills list.

## Alternatives considered

**Keep auto-wm in SKILL_SCOPES as optIn.** Rejected: `optIn` means "available but not
auto-installed", but auto-wm SHOULD auto-install for claude projects. The scope system
doesn't model "default for one stack".

**Scan all stacks in DEFAULT_SKILLS.** Rejected: `DEFAULT_SKILLS` is the universal default
list. Making it stack-aware would require passing config at module load time and would
confuse the meaning of "default".

**Keep the inline discovery logic in scaffold.py.** Rejected: sync_plugin_skills.py needs
the same logic. A shared helper in `badger_lib.py` keeps the two in agreement.

## Consequences

- `auto-wm` is no longer in `SKILL_SCOPES`. It is discovered from `features/claude/skills/`
  when the project has `claude` in its stacks.
- `scaffold_skills()` now searches all configured stacks and records the correct stack
  provenance in the manifest.
- `stack_local_skills()` is the single source of truth for "which skills in a directory
  are stack-local". Both scaffold.py and sync_plugin_skills.py derive from it.
- The catalog routing test (`test_every_catalog_skill_is_reachable_by_a_declared_route`)
  now checks only common-stack skills against `SKILL_SCOPES`. Stack-local skills are
  reachable via their stack's directory.
