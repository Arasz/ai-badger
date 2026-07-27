# ADR-0006 — One Skill Extension Mechanism

**Date:** 2026-07-27
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Hermes Agent
**Supersedes:** None

## Context

The framework carried two ways to extend a skill with stack-specific content.

**A — inside the skill:** `features/<stack>/skills/<skill>/extensions/<name>/`, holding
`extension.md` and an optional `extension.json` with `requires`. Content is copied with the
skill, pruned when its requirements aren't met (`_prune_inline_extensions`), and merged into
`SKILL.md` at `<!-- EXT:name -->` markers (`_merge_extensions`).

**B — beside the skill:** `features/<stack>/skills/<skill>-extensions/<name>/`. `index_build.py`
scanned for these and attached the names to the skill's index entry as an `extensions` array;
`_embed_extensions` then resolved each name back to a directory and copied it.

Mechanism A is in real use: `task` has four extensions (claude, github, hermes, copilot) and
`code-review-checklist` has six (azure, cosmos, dotnet, mcp, react, ts).

Mechanism B had **zero instances** — no `*-extensions` directory existed anywhere in the
catalog, and `index.json` contained no `extensions` key. It had been dead code, a schema field,
and a documented feature, all describing something no content used.

Two mechanisms for one job is a cost paid on every read: a contributor adding an extension had
to pick, and the wrong pick produced content that never shipped.

## Decision

**Mechanism A is the only mechanism.** B is removed: `_embed_extensions`, the `index_build.py`
scan block, and the `extensions` field in `schemas/index.schema.json`.

Removing it creates a new failure mode: a `<skill>-extensions/` directory would now be entirely
inert — `_skill_items` already skips anything ending in `-extensions`, so the content would
neither ship nor be reported. That is worse than the situation we started from.

So deletion is paired with detection. `index_build.legacy_extension_dirs()` finds any surviving
`<skill>-extensions/` directory, and `main()` **refuses to build the index**, naming each
offender and the path its contents belong at. A mistaken port fails immediately with the fix in
the message, rather than silently producing nothing.

## Alternatives considered

**Keep both.** The status quo. Rejected — the cost is paid by every contributor deciding
between them, forever, to preserve a mechanism nothing uses.

**Delete B silently.** Cheapest, and the plan's original scope. Rejected once it became clear
`-extensions` directories are already skipped by the indexer: the removal would convert a
working-but-unused path into an invisible no-op.

**Warn instead of refusing.** Rejected. A warning printed by a tool that then succeeds is a
warning nobody reads. `-extensions` is not a name anyone types accidentally, so false positives
are effectively zero and a hard failure costs nothing.

**Keep `extensions` in the schema as deprecated** so a stale `index.json` still validates.
Rejected — `index.json` is generated from, and validated against, the same checkout, so a
version-skewed pair does not arise. Keeping the field would advertise the mechanism we are
deleting.

## Consequences

- One documented way to extend a skill; `extensions.py` describes only that one.
- `index.json` entries no longer carry `extensions`; the schema rejects it (`additionalProperties:
  false`), so a stale index is a loud failure rather than a silent acceptance.
- Anyone porting a catalog that used mechanism B gets a build failure naming the target path.
- `adjust_task.py`'s comment, which credited `_embed_extensions` for the Hermes task extension,
  was wrong before this change — that extension has always used mechanism A. Corrected here.
