# ADR-0024 — Runtime state moves to SQLite: one vendored store module, two databases, and a named exclusion list that stays JSON

**Date:** 2026-08-31
**Status:** Accepted (2026-08-31, plan `aib-sqlite-storage-migration-phased-rollout` rev 2; G0 owner approval. The P0.6a schema-review gate rules the concrete DDL and its verdict amends this ADR.)
**Author:** Rafał Araszkiewicz (Arasz), with the MoE plan-review panel (architect, test-engineer, code-reviewer); ADR text by the architect lane (P0.1)
**Extends:** ADR-0009 (one framework root, resolved rather than searched; the verbatim-vendoring discipline), ADR-0017 (memory-first gate; its marker store migrates here)
**Scope:** `engine/badger_store.py` (new) and its vendored copies; `.ai-badger/task-tracking/tracking.db` and `~/.ai-badger/ai-badger.db` (new artifacts); the runtime stores inventoried below; the scaffold's managed `.gitignore` block. This file records the decision; implementation follows the plan's packages P0–P4. Out of scope by owner decision: Windows-specific tests (support is taken for granted) and `pr-monitor/` / `run-suite/` (plain logs).

## Context

The project's runtime state lives as roughly two dozen JSON and JSONL files across three scopes: project state under `.ai-badger/task-tracking/` and `.ai-badger/prompt-markers/`, user state under `~/.ai-badger/`, and away-mode state under `~/.claude/awm/`. The tracker CLI and per-prompt hooks write them under hand-rolled locking: `fcntl.flock` plus tmp-file plus `os.replace` in `tracker_lib.py`'s `locked_store()`, re-invented per store. Atomicity is per-file only. Where data is appended, growth is unbounded: `~/.claude/awm/decisions.jsonl` measured 6.95 MB on 2026-08-31, and `debug/audit.jsonl` 1.15 MB.

The research record (`docs/work/2026-08-31-sqlite-storage-migration-preview.md`, 2026-08-31) measured the alternative on this machine and stack. Python's stdlib `sqlite3` carries full JSON1 support everywhere ai-badger runs (SQLite 3.53.4 observed on Python 3.14.7), so no dependency is added for hooks, skills, or scaffolded projects. Under WAL, a concurrent reader sees the last committed snapshot in 0.06 ms while a writer holds `BEGIN IMMEDIATE`; a second writer blocks for exactly its `busy_timeout` (measured 334 ms against a 300 ms timeout) and then gets a clean, waitable `database is locked`; a process killed mid-transaction leaves the database intact with the transaction discarded. Throughput is a wash at hook scale: 500 appends cost 0.8 ms as JSONL and 1.3 ms as batched SQLite inserts. The stack already trusts the pattern. Two hooks write the ai-raccoon server's SQLite `search_quality` table directly, and the project ships a `sqlite-schema-review` skill.

Two deployment facts constrain the shape. First, scaffolded projects receive whole skill directories via `copytree` and cannot import the framework engine, so a shared store module must be vendored verbatim into each consumer skill's scripts directory, the discipline the bootstrap shim and `tracker_lib.py` already follow under ADR-0009. Eleven copies of `debug_log.py` exist today, and planning verified no test watches them for skew (`test_copy_skew.py` is Hermes-tree staleness; `framework_copies.py` is tree ownership). Second, deployed surfaces (Claude Code snapshots under `${CLAUDE_PROJECT_DIR}/.ai-badger/`, the Hermes plugin copy) update only on den-refresh, and multiple checkouts and worktrees on one machine share a single `~/.ai-badger/`. Old code and new code hitting the same store is the steady state, not a window between releases. Any design that assumes one version owns the files will silently lose the other's writes.

The plan (rev 2; three MoE review lanes; twelve MUST findings folded; G0 owner approval 2026-08-31) fixed the invariants below. Owner decisions taken in that plan are binding here and are restated where they shape the decision.

## Decision

**SQLite replaces the runtime JSON/JSONL stores listed below, behind one store module, in two databases, with an explicit exclusion list.** Thirteen decisions:

1. **Two databases, split by scope.** Project runtime state goes to `.ai-badger/task-tracking/tracking.db` (gitignored). User-level runtime state goes to `~/.ai-badger/ai-badger.db`. The debug/audit sink is always its own DB file: under `AI_BADGER_DEBUG_DIR` when that variable is set, else under `$HOME`. This preserves `debug_log.py`'s documented contract that the variable moves the whole sink.

2. **One store module, vendored verbatim.** `engine/badger_store.py` is stdlib-only, imports nothing from the engine, and is maintained in `engine/` and copied verbatim into each consumer skill's scripts directory, per ADR-0009's duplication-with-a-test discipline. P0.2 establishes an explicit vendored-path manifest (about 9 to 12 copies: task, prompt-markers, welcome-ai-badger, the hooks directory, auto-wm, commit-reminder, ai-raccoon-memory twice, worktree-agent-isolation twice, mcp-index) with a byte-equality and scaffold-delivery test; P2.2's mirror sync reuses the manifest.

3. **Paths resolve at call time, never at import.** The store reads its database roots from `AI_BADGER_TRACKING_ROOT`, `AI_BADGER_USER_ROOT`, and `AI_BADGER_DEBUG_DIR` when a call is made, not when the module is imported. Conftest freezes path constants at import, before fixtures run, and a session-fixture-only design was measured leaking 76 records across tests. Call-time resolution keeps the fixtures and the monkeypatched globals both working.

4. **Open pragmas and a version gate that fails closed.** Every open sets `journal_mode=WAL`, `busy_timeout=5000`, and `synchronous=NORMAL`. The worst case is accepted and documented rather than tuned away: under contention a per-prompt hook can block up to five seconds. The database carries `meta(schema_version)`. A store opening a database with a newer schema version than it knows fails closed with an actionable error naming the upgrade path (the den-refresh pointer). It never writes in an old shape silently and never dies in a `no such column` crash loop.

5. **Migration commits first and renames after, idempotently per family.** Import runs lazily, inside a transaction. The `*.migrated.json` rename happens only after COMMIT, so a crash mid-migration leaves both artifacts: the next writer's empty-table re-check re-imports, readers keep a fallback, and a concurrent first-write migration produces exactly one import, no duplicates, and one rename. Each family's migration spec pins a natural key per table and imports with `INSERT OR IGNORE` on that key, resumable after a crash mid-import; the 586-file and 711-dir families require this per-file story. Migration takes the legacy `.write.lock` flock that old writers use, so a legacy writer cannot be mid-write during an import. One keying choice is inherited, not changed: `dirty_sweeps` keys by sha1 of the main checkout root, because all worktrees of a repo deliberately share one record (the warning is repo-wide).

6. **Version skew is the steady state, so dual-read is per-key last-write-wins, not a fallback.** Readers merge the legacy file and the database per key with last-write-wins for map-like stores; an empty-database fallback would silently lose old-surface writes. On open, a legacy file whose mtime postdates the recorded migration stamp triggers re-import (append-only stores) or fail-closed with an upgrade pointer (map stores). Silent divergence is never an option. One residual is accepted and named: a stale surface's own new writes to map stores are not seen by current code until that surface refreshes. This is safety-relevant for the away-mode armed state, and the fail-closed error message says so.

7. **Permissions are re-asserted on every open and write, at store level.** `0600` on files and `0700` on directories, explicitly including `*.db-wal` and `*.db-shm` sidecars. P0.6a scratch-verified (macOS, SQLite 3.53.4): sidecars inherit the main DB's mode **only at sidecar-creation time** — chmod'ing the main DB never re-perms existing sidecars, so the re-assert design is load-bearing, not belt-and-braces. SQLite clamps creation modes at 0644 regardless of umask; the residual first-open window (a new DB is readable at 0644 until the end-of-open chmod, or after a crash in that window) is closed by pre-creating the DB file at 0600 before `sqlite3.connect` (P1.1 carrier; sidecars then inherit 0600). The `~/.ai-badger/` root itself is not chmod'd; it is an existing shared root, and leaving it alone is an explicit no, not an oversight.

8. **Store failures never block a hook.** Failures fail open and are logged, matching the project's hook convention. The recovery runbook is part of the contract: delete the database, restore the `*.migrated.json` names, and the lazy import redoes the work. Suite-write attribution (`AI_BADGER_REAL_WRITE_LOG`, `AI_BADGER_REAL_ROOT`) moves into the store write path so the conftest leak-guards keep working.

9. **Retention: 60 days on the three log tables.** `hook_audit`, `awm_decisions`, and `searches` delete rows older than 60 days (owner decision, 2026-08-31; the `searches` extension was approved at G0-Q2). This replaces awm's `MAX_DECISION_LINES=5000` line trim and ends the unbounded growth the research measured. The prune runs on open, throttled, with the timestamp check, the DELETE, and the stamp update inside one `BEGIN IMMEDIATE` (no check-then-act); the whole prune fails open; a read-only open degrades to a logged no-op. Every log table carries an index on its `ts` column at creation (P0.6a/D17c confirmed): `hook_audit.ts` indexed in P2.0's DDL, enforced by the P2.3 gate. All store timestamps are `datetime.now(timezone.utc).isoformat()` — +00:00 only, since mixed offsets break lexicographic range queries (P0.6a verified).

10. **The database is created only where the scaffold already exists.** The store opens or creates `tracking.db` only when `.ai-badger/` is already present, matching today's directory guard: the prompt-markers hook never creates tracking structure.

11. **Column shape: normal columns for what is queried, JSON columns for payloads.** Fields that are filtered or sorted become columns; whole-document payloads (read and written as one block, never filtered) become JSON columns via Python-side `json.dumps`/`json.loads`. The concrete DDL is ruled by the P0.6a schema-review gate on the full P0 DDL with a scratch database, and its verdict amends this ADR. **`token_usage.subagents` stays a JSON column (P0.6a, 2026-08-31)**: the access pattern is whole-document (every write loads the entry, mutates, saves the block; the `subagentTokens` aggregate is computed at write time), per-subagent SQL filtering is speculative with zero current consumers, and the revisit seam is cheap. Revisit trigger: promote `subagents` to a child table keyed `(task_id, seq)` when an accessor needs per-row predicates or SQL aggregation (P2.2 query verbs, the queued message-bus work), per-record uniqueness becomes a correctness need (delegationId dedup), or subagent volume makes whole-document rewrite measurably expensive. For `tasks`, a partial unique index (`CREATE UNIQUE INDEX ... ON tasks(session_id) WHERE state <> 'FINISHED'`) exists as defense in depth, while the FINISHED-terminal and attach-refusal (exit 2) checks stay application-level: the rationale for the app check is the exit-2 contract, not index impossibility. Task-family writes must use plain INSERT plus the app-level check — `INSERT OR REPLACE` against `tasks` silently deletes the other active task (P0.6a scratch-verified).

12. **The CLI contract does not change.** `task_tracker.py` and `awm.py` verbs and exit codes are identical before and after.

13. **What stays JSON, and why.** The exclusion list is part of the decision, not a leftover:

| Stays as-is | Why |
|---|---|
| `.ai-badger/config.json` | Hand-edited, schema-validated, and git-diffed by humans. |
| `.ai-badger/state.json`, `status-notes.json`, `status-history.json` (the committed knowledge log) | Git-tracked repo content that the main agent edits as ordinary files with plain Read/Write; database rows would take it out of review. |
| `.ai-badger/mcp-tools.json` | Generated catalog, validated against its schema and read by agents as context. |
| `markers-context.json` | Static skill content. |
| Harness settings (`hooks.json`, `.claude/settings.json`, `package.json`) | Owned by the agent host, not by ai-badger. |
| `schemas/*.schema.json`, `plans/*.md` | Repo content with its own review flow. |
| Claude session transcripts | The harness's own files. |
| `pr-monitor/`, `run-suite/` | Plain logs, not runtime state; out of scope. |

### Store inventory

Every runtime store, where it goes, and when it moves (writer facts the implementer must respect are inline):

| Legacy store | Location | Table | DB | Phase |
|---|---|---|---|---|
| executed-tasks.json | `.ai-badger/task-tracking/` | `tasks` | project | P0 |
| token-usage.json | `.ai-badger/task-tracking/` | `token_usage` (subagents JSON column per P0.6a) | project | P0 |
| current-session.json | `.ai-badger/task-tracking/` | `sessions` (eight writers) | project | P0 |
| statusline-state.json, statusline-delegate.json | `.ai-badger/task-tracking/` | `statusline` (KV; the delegate record is owned by `statusline_wiring.py`) | project | P0 |
| marker-state.json | `.ai-badger/prompt-markers/` | `marker_state` (shape pinned by `tests/test_user_prompt_hook.py`) | project | P0 |
| awm state.json | `~/.claude/awm/` | `awm_state` (per-project key; writers: `awm.py`, `awm_gate.py`, `awm_context.py`) | user | P1 |
| awm decisions.jsonl | `~/.claude/awm/` | `awm_decisions` | user | P1 |
| commit-reminder state + pending | `~/.ai-badger/commit-reminder/` | `commit_reminder` (per-project key) | user | P1 |
| pending-feedback.json | `~/.ai-badger/` | `pending_feedback` (`grounded_feedback.py` owns the write; `ai_badger_hooks.py:657` is the Hermes pop path) | user | P1 |
| searches.json | `~/.ai-badger/memory-grade/` | `searches` | user | P1 |
| memory-first/* (586 entries) | `~/.ai-badger/memory-first/` | `memory_first` (ADR-0017's consulted markers and denial counters) | user | P2 |
| semantica-nudge/* (711 dirs) | `~/.ai-badger/semantica-nudge/` | `semantica_nudge` (writer is framework-side and imports the engine directly, so no vendoring) | user | P2 |
| dispatch-lanes/* | `~/.ai-badger/` | `dispatch_lanes` | user | P2 |
| dirty-sweep-{hash}.json | `~/.ai-badger/` | `dirty_sweeps` (keyed sha1-of-main-root) | user | P2 |
| blast-radius-guard/*.denials | `~/.ai-badger/` | `blast_radius_denials` | user | P2 |
| debug/audit.jsonl | `~/.ai-badger/debug/` | `hook_audit` (written by 11 copies of `debug_log.py`: 6 canonical, 5 mirrors) | audit | P2 |
| debug/state.json | `~/.ai-badger/debug/` | `hook_state` (KV) | audit | P2 |

One correction inherited from the plan: `searches.json` is the live memory-grade store. The memory-quality JSONL writer was deleted in b83d1909 (2026-08-11, #373); grades already go to the raccoon server's SQLite, and only the file store migrates.

## Consequences

**Positive.** Hook-grade concurrency without hand-rolled locking, with numbers already measured: readers unblocked during a write transaction, contending writers getting a waitable lock error after exactly `busy_timeout`, crashes mid-transaction discarding cleanly. Multi-file atomicity arrives in one transaction, and the dirty-sweep and dispatch families stop being N files. Unbounded growth ends: the three log tables prune at 60 days, retiring a 5000-line cap and fixing the 6.95 MB `decisions.jsonl` trajectory. One managed `.gitignore` block (`*.db`, `*.db-wal`, `*.db-shm`) per scope replaces about eight per-directory ignores; because no gitignore handling exists in the scaffolder today, this arrives as a new capability in P0.5 followed by a re-scaffold of this repo. The change standardizes on what the codebase already trusts (the direct SQLite writes to the raccoon server).

**Negative and accepted.** Agents lose direct Read/Grep access to migrated stores; debugging shifts to the `sqlite3` CLI and helper query verbs (planned for `call-behaviorist` and `ensure_committed.py` in P2.2). This stays small because most stores are already mediated by CLI commands, and the stores agents read directly (the knowledge log, config, plans) are exactly the excluded ones. The five-second worst-case block on a contended per-prompt hook stands. The stale-surface residual from decision 6 stands, with the away-mode armed-state case named in the error message. Dual-read is permanent infrastructure, not a transition shim: surfaces update only on den-refresh and several checkouts share one user DB, so mixed-version access persists as long as the fleet is heterogeneous, and its tests must treat it that way (both-sources-non-empty precedence, legacy resurrection after rename). Vendoring multiplies the module to roughly a dozen copies; skew is governed by the manifest and the byte-equality test, not by hope. The `~/.ai-badger/` root keeps its current permissions, deliberately.

**Scale note.** The bulk of the work is tests and docs, not code. The plan counts roughly 62, 45, and 90 test files to migrate across P0, P1, and P2, with per-file fixture rework rather than sed, and CLI-stdout contract tests left unmodified.

## Open questions

Recorded rather than invented; each traces to a gap the plan leaves open, not to a new claim:

1. **Forward data migration between future schema versions.** Decision 4 fixes behavior when code meets a newer database (fail closed, den-refresh pointer). Nothing yet specifies how a database moves from version N to N+1 once a second version exists. Deferred until then; v1 ships one schema version.
2. **`*.migrated.json` lifecycle.** The rollback story and the recovery runbook both require the renamed files to persist, but no cleanup mechanism is specified, so they accumulate indefinitely. If that becomes a problem it needs its own decision, not a rider.
3. **The recency signal behind per-key last-write-wins.** RESOLVED by P0.6a (2026-08-31), verified against the implemented module and its tests: family-level recency compares the legacy file's mtime against an epoch-float migration stamp in `meta.migrated_at.<table>` (mtime postdates stamp → re-import or fail closed, per kind); per-key recency is DB-row presence — when both sources hold the key, the DB row wins. Clock-skew residue is covered by the P2.3 retention tests (D36).

## Verification anchor

The plan's gates are this decision's proof surface; the tests land with their packages.

- P0.2: `tests/test_badger_store.py` (call-time path resolution, pragmas, schema-version fail-closed, COMMIT-then-rename, per-key last-write-wins dual-read), plus the vendored-path manifest and copy-skew test.
- P4: concurrent first-write migration (two processes, one legacy file: exactly one import, no duplicates, one rename); dual-read with both sources non-empty; legacy resurrection after rename; the recovery-runbook drill; retention across both databases, including rows with missing or unparseable timestamps (neither crash nor immortal) and a growth comparison against the retired 5000-line cap.
- P0.6a: schema-review verdict on the P0 DDL and accessors, scratch-database verified, folded back into this ADR as an amendment.

## Amendment — P0.6a schema-review verdict (2026-08-31)

**VERDICT: CONFIRM-WITH-CHANGES.** Full review with evidence index: `.ai-badger/task-tracking/plans/2026-08-31-aib-sqlite-storage-migration-phased-rollout-gate-p06a.md` (main checkout's tracking space). `token_usage.subagents` stays a JSON column (ruling and revisit trigger in decision 11); D17a semantics folded into decision 7; D17c convention folded into decision 9; open question 3 resolved. Decisions 1–17 otherwise stand.

Carried changes, named precisely:

- **P0.3 (task-family DDL + accessors):** (1) add the live-writer columns the P0 DDL omits — `tasks.tracking_source`, `tasks.state_json_reminder_sent`, `tasks.compaction_reminder_sent`, `token_usage.graded_at`, `token_usage.tracking_source` (writers: task_tracker.py:283/296/442, stop_hook.py:152–164; migration would otherwise silently drop them and the stop-hook reminder flags would reset); (2) `token_usage.task_id` becomes `TEXT NOT NULL` (a TEXT PK otherwise admits distinct NULLs, verified); (3) never use `INSERT OR REPLACE` against `tasks` (it silently deletes the other active task — verified); (4) the per-family import spec pins a post-import count check, because `INSERT OR IGNORE` silently drops rows violating NOT NULL/CHECK (verified — unlike the upsert form, which raises); (5) `tasks.state` default `'ACTIVE'` names a state no writer produces (real vocabulary STARTED/IN_PROGRESS/FINISHED) — change to `'STARTED'` or drop, owner's call.
- **P1.1 (store-file owner):** (1) pre-create the DB file at 0600 (`os.open(O_CREAT|O_RDWR, 0o600)`) before `sqlite3.connect` — closes the verified first-open window where a new DB exists at 0644 until the end-of-open chmod, and sidecars then inherit 0600; (2) the D27 fail-closed error must name the actual `db_path` — it currently hardcodes `tracking_db_path()` and misnames the user DB (verified by running the module); (3) the `_DDL` block gains a comment naming the three log tables (`hook_audit`, `awm_decisions`, `searches`) and the ts-index convention, so vendored copies carry the pattern.
- **Documented drops (no live writer, legacy residue):** `risk` (executed-tasks) and `note` (token-usage).

