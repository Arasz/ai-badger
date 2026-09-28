# ADR-0032 — Plan state lives in the project tracking store at schema v3, with upgrades gated per DB kind

**Date:** 2026-09-28
**Status:** Accepted (2026-09-28, shipped 0.179.0 — `docs/changelog/0.179.0-task-decomposition-graph.md`, PR #538). Written at the 0.179.0 Phase-6 documentation-gap audit, which found the decision shipped without its record.
**Author:** Rafał Araszkiewicz (Arasz) with Claude (task `aib-task-decomposition-workflow-graph-mcp`)
**Scope:** `engine/badger_store.py` (`UPGRADE_HOOKS`, `open_store`, `open_user`), `features/common/skills/task-decomposition/scripts/task_plan_store.py`, `tooling/task_plan_schema.py`, and every future store migration.
**Supersedes:** Nothing. **Refines [ADR-0024](0024-sqlite-runtime-store.md):** its "one vendored store module, two databases" stands; this ADR adds which database a feature's tables belong in, and makes DB-kind gating a migration rule.

## Context

0.179.0 gave the task pipeline machine-checkable plan state (a `task-plan` DAG of `step`s, managed
through the local `task-graph` MCP server). That state has to live somewhere durable. ADR-0024 had
already made the project's `.ai-badger/task-tracking/tracking.db` the runtime store and collapsed
the JSON sidecars behind `engine/badger_store.py`; the rendered plan file
(`.ai-badger/task-tracking/plans/<date>-<taskId>.md`) is a human projection, not a queryable
record. Two questions remained open at plan time: which database the plan tables belong in, and
what a schema bump for them is allowed to touch.

The incident that forced the second question is recorded here because it was the evidence: when the
v2→v3 plans DDL was wired as a store upgrade hook without a DB-kind gate, `open_user()` ran it too.
`~/.ai-badger/ai-badger.db` — machine-wide, shared by every scaffolded project's hooks — upgraded
to schema v3 on the first post-merge open. Every pre-0.179 hook on the machine then failed open
against the unexpected version, in a loop, with audit-log churn; two manual recoveries (drop the
leaked table, reset the stamp) were undone within minutes by the next hook firing from a worktree
carrying the new store. The stamp could not be held while any v3 hook could still re-upgrade it.

## Decision

1. **Plan state lives in the project tracking store.** The `plans` table
   (`task_id TEXT PRIMARY KEY, revision, payload, created_at, updated_at`, `CHECK json_valid(payload)`)
   is a tracking.db table at schema v3, written through the plan store module with revision CAS and
   content-hash-idempotent replays. The rendered plan file is derived output; the no-server
   fallback may hand-write one and report at reduced fidelity.
2. **Store upgrades are gated per DB kind.** The plans DDL runs on the tracking store only —
   `open_user()` keeps whatever schema stamp it has and is never migrated as a side effect of a
   project feature. A migration that legitimately concerns the user DB must say so explicitly and
   carry its own decision record; "the hook runs on every store" is no longer the default.
3. **This is a migration rule, not a one-off.** Future schema bumps inherit the gate: name the
   target DB kind in the hook, and treat any hook that would touch the other database as a defect
   the review must catch (the 0.179.0 implementation review caught exactly this as finding R1-5).

## Consequences

- The machine-wide user DB is quiet again: pre-0.179 hooks run against the stamp they expect, and
  the 0.179.0 recovery (leaked table dropped, stamp reset to 2) holds permanently rather than
  until the next hook.
- A feature adding project-scoped state pays one tracking-store migration and nothing else. A
  feature adding user-scoped state must make that scope visible in a new ADR — the gate turns an
  invisible coupling into a decision point.
- Two databases can now be at different schema versions simultaneously, permanently. ADR-0024's
  fail-closed check applies per database: a store refuses a newer version than its code knows, and
  the two stores' versions are not compared to each other.
- The plan file's dual-read role (graph first, file fallback) is unchanged: file-only plans report
  without machine state (manual checkboxes), which is the designed degraded path, not a defect.
