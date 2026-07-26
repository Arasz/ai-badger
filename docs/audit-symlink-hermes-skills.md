# Audit: symlink_hermes_skills() — still needed?

**Date:** 2026-07-26
**Status:** Superseded then re-confirmed — see [Reconciliation](#reconciliation-2026-07-26) at
the end. The recommendation below ("keep it as-is") was overridden by `bafb952` (#58), which
made the function a no-op, and is now correct again — for a different reason and with two
mandatory changes. Authoritative record:
[ADR-0003](adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md).

## Question

Do we still need `symlink_hermes_skills()` in scaffold.py, which writes symlinks
to `~/.hermes/skills/<project>/` (user home scope)? Did we solve this with local
skills instead?

## Answer: Yes, still needed. No local alternative exists.

## Evidence

### 1. How the symlinks work

`scaffold.py:772-800` — creates `~/.hermes/skills/<project-name>/` and symlinks
each scaffolded skill into it:

```
~/.hermes/skills/ai-badger/task       -> .ai-badger/skills/task
~/.hermes/skills/ai-badger/den-refresh -> .ai-badger/skills/den-refresh
...8 skills total
```

Hermes discovers skills from `~/.hermes/skills/` (user-scope global directory).
Without these symlinks, ai-badger skills are invisible to Hermes.

### 2. external_dirs is NOT used

The v0.7.1 changelog says symlinks were augmented with `external_dirs` registration
in `~/.hermes/config.yaml`. However:

- The current code explicitly says: `"Does NOT use external_dirs — that's a shared
  global list that causes skill name conflicts across projects."`
- `~/.hermes/config.yaml` has `external_dirs: []` (empty)
- The tests mentioned in 0.7.1 (`test_scaffold_registers_hermes_external_dirs`,
  `test_scaffold_no_external_dirs_without_hermes`) do NOT exist in test_scaffold.py

Conclusion: the external_dirs approach was reverted. Symlinks with project
namespacing replaced it.

### 3. No local skill discovery

- The project has NO `.hermes/skills/` directory
- Hermes only discovers skills from:
  - `~/.hermes/skills/` (user-scope, where symlinks land)
  - `external_dirs` in config (empty)
  - Built-in skills (bundled with hermes-agent)
- There is no "project-local `.hermes/skills/`" discovery mechanism

### 4. The use case is real

`hermes skills list` confirms 8 ai-badger skills are discovered and enabled:

```
auto-wm, den-refresh, feed-badger, maintain-agent-instructions,
mcp-index, prompt-markers, task, welcome-ai-badger
```

All show as `local` source, `local` trust. Without the symlinks, none would appear.

## Alternatives considered

| Approach | Pros | Cons |
|----------|------|------|
| **Current: symlinks in ~/.hermes/skills/** | Namespaced per-project, no config pollution | Writes to user home scope |
| **external_dirs pointing to .ai-badger/skills/** | No symlinks, no home dir writes | Global flat namespace — name conflicts across projects |
| **Project-local .hermes/skills/** | Cleanest, no user scope | Hermes doesn't support this |
| **Copy skills to ~/.hermes/skills/** | Works without symlinks | Duplicates files, drifts on update |

## Recommendation

**Keep `symlink_hermes_skills()` as-is.** It's the correct mechanism given Hermes's
current skill discovery model. The alternatives are worse:

- `external_dirs` causes cross-project name conflicts (the code comment explains why)
- Project-local discovery doesn't exist in Hermes
- Copying is fragile (drifts on update, den-refresh wouldn't refresh the copies)

The only improvement worth considering: if Hermes adds project-local skill discovery
(e.g., `.hermes/skills/` in the project root), the symlinks could be replaced.
Until then, they're necessary.

> **"As-is" no longer applies to the implementation** — see
> [Reconciliation](#reconciliation-2026-07-26). The mechanism is kept; the `rmtree` in the
> original implementation is not.

## Files examined

- `features/common/skills/welcome-ai-badger/scripts/scaffold.py:772-800`
- `features/common/support.json:104-108`
- `docs/changelog/0.7.1-hermes-external-dirs.md`
- `~/.hermes/config.yaml` (external_dirs: [])
- `~/.hermes/skills/ai-badger/` (8 symlinks confirmed)
- `tests/test_scaffold.py:336-406` (symlink tests)
- `schemas/config.schema.json` (skillScope enum)

## Reconciliation (2026-07-26)

This audit's conclusion — "keep `symlink_hermes_skills()` as-is" — was overridden the same day
by `bafb952` ("fix: remove Hermes user-scoped skill symlinks (#58)"), which made the function a
no-op on the premise that "Hermes discovers project skills via the project-local skill
directory." That premise is false: `agent/skill_utils.py` resolves skills from
`~/.hermes/skills/` plus `skills.external_dirs` and nothing else, exactly as §3 of this audit
found. The no-op therefore did not fix #58's staleness — it removed discovery.

The audit was right about the mechanism and wrong about one detail: it treated the
implementation as sound. It was not. The original code called `shutil.rmtree(namespace_dir)`
when the namespace existed as a real directory, which would have destroyed
`agent-skill-discovery/` — the Hermes-authored skill this audit's own file list records as
living there.

**Current state.** The symlinks are restored with two changes: only symlinks resolving into this
project's `.ai-badger/skills/` are ever removed (no `rmtree`, foreign entries preserved), and
den-refresh re-links on every refresh so added/removed skills propagate. The alternatives table
in §"Alternatives considered" above still holds — `external_dirs` collides across projects,
project-local discovery does not exist in Hermes, and copying is what produced #58 in the first
place. Rationale and rejected options:
[ADR-0003](adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md).
