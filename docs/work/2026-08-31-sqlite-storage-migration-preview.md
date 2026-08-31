# Research: Replacing ai-badger's JSON/JSONL stores with SQLite (project and user level)

**Date:** 2026-08-31
**Question:** Can ai-badger replace its project-level and user-level JSON/JSONL file stores with SQLite (JSON1 extension for semi-structured data), what exactly would have to change, and what does the project gain or lose?

## Findings

### F1 — Python's stdlib sqlite3 with full JSON1 support is available everywhere ai-badger runs [MEASURED]

Python 3.14.7 ships SQLite 3.53.4; `json()`, `json_extract()`, `json_patch()`, `json_each()`, the `->>' path operator, and `jsonb()` (binary JSON, 3.45+) all work. `sqlite3` is stdlib — no new dependency for hooks, skills, or scaffolded projects.

**Evidence:** `python3 -c` on this machine (macOS, local Python): `SELECT json_extract('{"a":{"b":2}}','$.a.b')` → `2`; `typeof(jsonb('{"a":1}'))` → `blob`; `SELECT count(*) FROM json_each('[1,2,3]')` → `3`. Also `import sqlite3; sqlite3.sqlite_version` → `3.53.4`.

### F2 — SQLite WAL gives hook-grade concurrency with none of the hand-rolled locking [MEASURED]

While one process holds an uncommitted `BEGIN IMMEDIATE` write transaction, a concurrent reader sees the last committed snapshot in 0.06 ms (no block); a second writer blocks for exactly its `busy_timeout` (measured 334 ms with a 300 ms timeout) and then raises `database is locked` — a clean, waitable error. A process killed mid-transaction leaves the DB intact with the uncommitted transaction discarded (0 rows after simulated crash).

This is the semantics the current code hand-builds with `fcntl.flock` + tmp-file + `os.replace` (tracker_lib.py:280-355, `locked_store()`), except SQLite also gives per-row concurrency and multi-file atomicity in one transaction.

**Evidence:** Local test: WAL-mode temp DB, three connections (one writer inside `BEGIN IMMEDIATE`, one reader, one writer with `busy_timeout=300`), timing each; then `os.kill(os.getpid(), 9)` inside an open write transaction and re-opening the DB from a new process.

### F3 — Throughput is a wash at hook scale [MEASURED]

500 append-events: JSONL appends 0.8 ms; SQLite WAL 500 inserts + one commit 1.3 ms. Hooks fire per user prompt / tool call / stop event — sub-millisecond per fire either way. Per-connection open cost (~0.1 ms) is invisible next to the Python interpreter startup every hook already pays.

**Evidence:** Local timing loop, temp dir, same machine and Python as F1: `open(...,'a')` writes vs `sqlite3.connect` + `INSERT` × 500 + single `commit()`, `time.perf_counter()`.

### F4 — The runtime data stores split into four families, with very different migration verdicts [READ]

1. **Project runtime state** (gitignored, `.ai-badger/task-tracking/`): `executed-tasks.json`, `token-usage.json`, `current-session.json`, `statusline-state.json`, `statusline-delegate.json`, `prompt-markers/marker-state.json` — written by tracker CLI and hooks under flock. Migrate.
2. **User runtime state** (`~/.ai-badger/`): `commit-reminder/state.json` + `pending.json`, `pending-feedback.json`, `memory-grade/memory-quality.jsonl` + `pending.json`, `dirty-sweep/*.json`, `dispatch-lanes/*`, `memory-first/*` (573 files), `semantica-nudge/*` (712 dirs) — Migrate.
3. **Append-only logs**: `~/.claude/awm/decisions.jsonl` (6.95 MB, unbounded), `~/.ai-badger/debug/audit.jsonl` (1.15 MB), plus 7 vendored copies of `debug_log.py` writing it. Migrate.
4. **Deliberately NOT migrated** (stay JSON): `.ai-badger/config.json` (hand-edited, schema-validated, git-diffed by humans), the committed knowledge log `.ai-badger/state.json` + `status-notes.json` + `status-history.json` (git-TRACKED, and "edited by the main agent as ordinary repo content" via plain Read/Write — file-schemas.md), `.ai-badger/mcp-tools.json` (generated catalog validated against `schemas/mcp-tools.schema.json`, read by agents as context), `markers-context.json` (static skill content), harness settings (`hooks.json`, `.claude/settings.json`, `package.json` — owned by the agent host, not us), `schemas/*.schema.json`, `plans/*.md`, session transcripts (Claude Code's own files).

**Evidence:** `skills/task/references/file-schemas.md` (all four schemas + the "plain Read/Write" note); `ls ~/.ai-badger/` and `ls ~/.claude/awm/` (sizes measured 2026-08-31: decisions.jsonl 6,950,025 B; audit.jsonl 1,152,376 B; memory-first 573 entries; semantica-nudge 712 entries); `features/common/skills/welcome-ai-badger/scripts/skill_delivery.py:287` (skill dirs ship via `copytree` — code must be vendored, framework `engine/badger_lib.py` is not reachable from projects, ADR-0009 duplication pattern).

### F5 — The change surface is dominated by tests and docs, not code [MEASURED]

Grep counts across the repo (files mentioning each artifact): `executed-tasks.json` code 4 / tests 49 / docs 9; `token-usage.json` 4/36/10; `current-session.json` 14/28/16; `audit.jsonl` 12/31/10; `decisions.jsonl` 6/11/4; `mcp-tools.json` 11/63/23 (mostly untouched — excluded); `state.json` 41/106/53 (mostly the excluded committed log + awm/debug state); `config.json` 36/147/160 (excluded). The four migration families touch roughly 25–30 Python modules (writers/readers) and ~120 test files that construct JSON fixtures, plus `skills/task/references/file-schemas.md` and a dozen SKILL.md path references.

**Evidence:** `grep -rl` loops over `features skills tooling gates engine` (code), `tests/` (tests), and `*.md` under docs/skills/features (docs), run 2026-08-31; counts are file counts, not occurrences. Caveat: `state.json` and `config.json` counts conflate several same-named files (awm state, debug state, committed log) — the excluded share is the large one.

### F6 — SQLite is already a proven pattern in this stack [READ]

Two hooks already write to the ai-raccoon memory server's SQLite DB (`search_quality` table) directly via stdlib `sqlite3`: follow-through attribution and memory grading. The project even carries review skills for SQLite-backed stores (`features/common/skills/sqlite-schema-review/SKILL.md`, `sqlite-bank-space-diagnosis`). A migration standardizes on what the codebase already trusts.

**Evidence:** `features/common/hooks/follow_through.py:14,118-127`; `features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py:18,123`; skill manifests.

### F7 — The schema shape: normal columns for queried fields, JSON columns for payloads [INFERRED]

Tasks (`task_id` PK, state, session_id, branch, timestamps, flags as columns; `resume_attempts` as JSON column), token usage (1:1 with tasks; `checkpoints`/`subagents`/`usage` as JSON columns — they are read/written whole, never filtered), sessions (`session_id` PK, pid, cwd, recorded_at), hook audit (`ts`, `hook`, `project`, `event` JSON), awm decisions (`ts`, `project`, `tool`, decision JSON). JSON columns via Python-side `json.dumps` on write / `json.loads` on read, with SQL `json_extract` only where a query actually needs to filter — the "store json native data as json columns" requirement. From: F4's read/write patterns (whole-document access dominates; only `state`, `session_id`, `pid`, timestamps are ever filtered) and F1's confirmed JSON1 availability.

### F8 — Deployment constraint: the store module must be vendored per skill, like tracker_lib [READ]

Scaffolded projects get whole skill directories via copytree and have no `engine/badger_lib.py`; shared constants are already "repeated verbatim" per entry point (ADR-0009 pattern, and 7 existing copies of `debug_log.py`). So the migration ships one canonical `badger_store.py` (open-with-PRAGMAs, migrate-from-JSON, typed accessors) maintained in `engine/` and vendored verbatim into each skill/scripts dir that needs it — the same discipline tracker_lib.py already follows for the task skill.

**Evidence:** `features/common/skills/welcome-ai-badger/scripts/skill_delivery.py:287` (copytree deployment); `features/common/skills/commit-reminder/scripts/commit_reminder.py:111` and `den-refresh/scripts/refresh.py:29-32` (documented verbatim-duplication pattern); `features/common/skills/task/scripts/claude_md_compact.py:22` (`import tracker_lib as lib` from sibling scripts dir).

### F9 — Migration mechanics: lazy import on first write, JSON renamed, dual-read during one release [INFERRED]

Each store module, on first open: if legacy JSON exists and DB has no rows, import it (same field mapping as today's `save_json`/`load_json`), rename the file to `*.migrated.json` (never delete — the rollback story), and proceed DB-only. Writers migrate eagerly; readers accept both during the transition window. From: the codebase's existing atomic-replace + flock discipline (never clobber), the gitignored nature of every migrated file (no merge conflicts to worry about), and ai-badger's multi-agent habit (worktrees share `~/.ai-badger` user state across versions).

### F10 — What this change costs in agent ergonomics — and what keeps it small [INFERRED]

Lost: agents can no longer `Read`/`Grep` migrated stores directly; debugging shifts to `sqlite3` CLI or helper verbs; the audit-log skills (`call-behaviorist`, commit-reminder's `ensure_committed.py`) gain new query verbs. Kept small because: (a) most stores are already mediated by CLI commands (`task_tracker.py`, `awm.py`, `status_report.py`) rather than direct file reads by agents; (b) the stores agents DO read directly — the committed knowledge log, config, plans, notes — are exactly the ones excluded in F4; (c) one DB per scope means one `.gitignore` line each (`*.db`, `*.db-wal`, `*.db-shm`) replaces ~8 per-directory ignores.

## Still open

- Whether `token-usage.json`'s `subagents` list should become its own table (queryable per-subagent) or stay a JSON column — deferred BY DECISION (2026-08-31, owner) to the schema-review gate; the project's own `sqlite-schema-review` skill runs on the P0 schema before it ships.

## Decisions taken 2026-08-31 (owner, via f: feedback)

- **Windows support:** taken for granted; no Windows tests in this migration.
- **Away mode (auto-wm):** the per-project-keyed table design pass for `~/.claude/awm/state.json` + `decisions.jsonl` is part of the task plan (P1), not a separate investigation.
- **`debug_log.py` collapse:** the 7 vendored copies fold into the store module's audit table as part of P2 (plan default held).
- **Retention:** log-data tables (audit, decisions) carry a 2-month limit — rows older than 60 days are deleted; the JSONL files' unbounded growth (decisions.jsonl at 6.95 MB) is the failure this fixes.
- **Execution:** one task covering P0–P3 registered as `aib-sqlite-storage-migration-phased-rollout` (high-effort loop derived from scope: ~30 modules, ~120 test files, schema design).
