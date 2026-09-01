"""Red tests for the user-DB schema families (P1.1a) — this file is the contract P1.1b implements.

Extends ``badger_store`` with the user database's five families (ADR-0024 §awm/commit-reminder/
pending-feedback/searches): ``~/.ai-badger/ai-badger.db`` gains

    USER_FAMILIES: dict[str, Family]     # open_user() defaults to this registry

    awm_state         KV  (key = resolved project root, value = the project's awm entry —
                           mirrors ~/.claude/awm/state.json's ``{"projects": {root: entry}}``)
    awm_decisions     append-log (id INTEGER PK AUTOINCREMENT, ts TEXT NOT NULL,
                           payload TEXT NOT NULL — the decisions.jsonl line verbatim)
    commit_reminder   KV  (key = project root — mirrors commit-reminder/state.json)
    pending_feedback  KV  (single document under row key "pending" — pending-feedback.json)
    searches          append-log (id/ts/payload — memory-grade search telemetry)

plus ``Store.prune_expired(table, *, max_age_days=60) -> int``: the retention seam P2.3
implements — deletes rows whose ``ts`` predates the cutoff, returns the row count, and
stamps ``pruned_at.<table>`` in meta; a second call inside the throttle window is a no-op
(returns 0, deletes nothing) even when expired rows exist.

P0.6b-gate carries pinned here (binding): (1) the user DB file pre-exists at 0600 BEFORE
``sqlite3.connect`` runs — verified by spying on connect under a hostile umask 000;
(2) the ``_DDL`` block carries the ts-index convention comment naming the three log tables
(hook_audit lands P2.1, searches' index lands P1.4) and ``awm_decisions.ts`` is actually
indexed. D21: ``audit_db_path()`` derives from ``AI_BADGER_DEBUG_DIR`` at call time (its
own DB file), defaulting under the real home.

Test map (plan aib-sqlite-storage-migration-phased-rollout rev 2 · ADR-0024 · P0.6b carries):
  1. USER_FAMILIES registry ..................... test_user_families_registry_pins_tables_and_legacy_paths,
                                                   test_user_family_legacy_paths_follow_user_root_env
  2. DDL shape + accessor behavior .............. test_open_user_creates_all_five_family_tables,
                                                   test_awm_state_round_trips_per_project_entries,
                                                   test_commit_reminder_round_trips_independent_per_project_keys,
                                                   test_pending_feedback_round_trips_as_single_replaced_document,
                                                   test_awm_decisions_schema_is_append_log_with_ts,
                                                   test_awm_decisions_rows_read_back_in_append_order,
                                                   test_log_rows_since_returns_only_rows_at_or_after_the_cutoff,
                                                   test_log_rows_since_is_served_by_the_ts_index,
                                                   test_log_rows_since_fails_open_as_empty,
                                                   test_searches_schema_is_telemetry_log_with_ts
  3. P0.6b carry 1: pre-create 0600 pre-connect . test_user_db_file_is_0600_before_sqlite3_connect
  4. P0.6b carry 2: ts-index convention ......... test_ddl_block_carries_ts_index_convention_comment,
                                                   test_awm_decisions_ts_index_exists
  5. D21 audit sink path ........................ test_audit_db_follows_debug_dir_and_defaults_under_home
  6. Retention seam + throttle (P2.3 prereq) .... test_prune_expired_deletes_only_rows_older_than_max_age,
                                                   test_prune_expired_second_call_within_window_is_noop
  7. Perms 0600/0700 on every open/write ........ test_user_db_sidecars_0600_on_every_open_and_write,
                                                   test_user_write_does_not_chmod_existing_root
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import badger_store
from conftest import REAL_HOME


def _user_env(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "user-root"
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(root))
    return root


def _ts(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# 1. USER_FAMILIES registry
# ---------------------------------------------------------------------------


def test_user_families_registry_pins_tables_and_legacy_paths():
    """The registry carries the P1 families and the P2 session families, all user-DB.

    P2.0b grew the registry with the six session families (plan P2.0) — the pin extends
    rather than replaces: every P1 family keeps its exact table + legacy path.
    """
    families = badger_store.USER_FAMILIES
    assert set(families) == {
        "awm_state", "awm_decisions", "commit_reminder", "commit_reminder_pending",
        "pending_feedback", "searches",
        "memory_first", "semantica_nudge", "dispatch_lanes", "dirty_sweeps",
        "blast_radius_denials", "hook_audit", "hook_state",
        "messages", "cursors",
    }
    assert {name: family.table for name, family in families.items()} == {
        "awm_state": "awm_state",
        "awm_decisions": "awm_decisions",
        "commit_reminder": "commit_reminder",
        "commit_reminder_pending": "commit_reminder",
        "pending_feedback": "pending_feedback",
        "searches": "searches",
        "memory_first": "memory_first",
        "semantica_nudge": "semantica_nudge",
        "dispatch_lanes": "dispatch_lanes",
        "dirty_sweeps": "dirty_sweeps",
        "blast_radius_denials": "blast_radius_denials",
        "hook_audit": "hook_audit",
        "hook_state": "hook_state",
        "messages": "messages",
        "cursors": "cursors",
    }
    for family in families.values():
        assert family.db == "user"
    # The bus families (P1, D2) are born in SQLite: no legacy source anywhere — no
    # legacy_path callable and no import kind. The DDL arrives via UPGRADE_HOOKS[1].
    for name in ("messages", "cursors"):
        assert families[name].legacy_path is None, name
        assert families[name].legacy_kind == "store", name
    home = REAL_HOME
    assert families["awm_state"].legacy_path() == home / ".claude" / "awm" / "state.json"
    assert families["awm_decisions"].legacy_path() == home / ".claude" / "awm" / "decisions.jsonl"
    assert families["commit_reminder"].legacy_path() == (
        home / ".ai-badger" / "commit-reminder" / "state.json")
    assert families["commit_reminder_pending"].legacy_path() == (
        home / ".ai-badger" / "commit-reminder" / "pending.json")
    # The kvdoc convention: the pending stash document lands under this row key.
    assert families["commit_reminder_pending"].row_key == "pending"
    assert families["pending_feedback"].legacy_path() == home / ".ai-badger" / "pending-feedback.json"
    assert families["searches"].legacy_path() == (
        home / ".ai-badger" / "memory-grade" / "searches.json")
    # The kvdoc convention: the single pending-feedback document lands under this row key.
    assert families["pending_feedback"].row_key == "pending"


def test_user_family_legacy_paths_follow_user_root_env(tmp_path, monkeypatch):
    """USER_ROOT redirect moves the .ai-badger-artifact legacy paths; awm stays under ~/.claude."""
    root = _user_env(tmp_path, monkeypatch)
    families = badger_store.USER_FAMILIES
    assert families["commit_reminder"].legacy_path() == root / "commit-reminder" / "state.json"
    assert families["commit_reminder_pending"].legacy_path() == (
        root / "commit-reminder" / "pending.json")
    assert families["pending_feedback"].legacy_path() == root / "pending-feedback.json"
    assert families["searches"].legacy_path() == root / "memory-grade" / "searches.json"
    assert families["awm_state"].legacy_path() == (
        REAL_HOME / ".claude" / "awm" / "state.json")  # not a .ai-badger artifact: never moves


# ---------------------------------------------------------------------------
# 2. DDL shape + accessor behavior
# ---------------------------------------------------------------------------


def test_open_user_creates_all_five_family_tables(tmp_path, monkeypatch):
    """open_user() creates every user-family table (and open_tracking never needs them)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        tables = {row[0] for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("awm_state", "awm_decisions", "commit_reminder",
                      "pending_feedback", "searches"):
            assert table in tables
    finally:
        store.close()


def test_awm_state_round_trips_per_project_entries(tmp_path, monkeypatch):
    """awm_state keys are resolved project roots; one project's entry never answers for another."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        main = {"enabled": True, "since": "2026-08-31T00:00:00+00:00"}
        worktree = {"enabled": False}
        store.kv_set("awm_state", "/repo/main", main)
        store.kv_set("awm_state", "/repo/main/worktrees/alpha", worktree)

        assert store.kv_get("awm_state", "/repo/main") == main
        assert store.kv_get("awm_state", "/repo/main/worktrees/alpha") == worktree
        assert store.kv_get("awm_state", "/repo/other", None) is None
        # write-back of one project leaves the sibling untouched (save_entry semantics)
        store.kv_set("awm_state", "/repo/main", {**main, "enabled": False})
        assert store.kv_get("awm_state", "/repo/main/worktrees/alpha") == worktree
    finally:
        store.close()


def test_commit_reminder_round_trips_independent_per_project_keys(tmp_path, monkeypatch):
    """commit_reminder is per-project: two roots hold independent state entries."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/a", {"count": 3, "marker": 1, "fires": 0})
        store.kv_set("commit_reminder", "/repo/b", {"count": 7, "marker": 4, "fires": 2})

        assert store.kv_get("commit_reminder", "/repo/a") == {"count": 3, "marker": 1, "fires": 0}
        assert store.kv_get("commit_reminder", "/repo/b") == {"count": 7, "marker": 4, "fires": 2}
        store.kv_set("commit_reminder", "/repo/a", {"count": 4, "marker": 1, "fires": 1})
        assert store.kv_get("commit_reminder", "/repo/b") == {"count": 7, "marker": 4, "fires": 2}
    finally:
        store.close()


def test_pending_feedback_round_trips_as_single_replaced_document(tmp_path, monkeypatch):
    """pending_feedback holds one document under the "pending" row key; a new write replaces it."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        first = {"marker": "f:commit message", "project": "/repo/a", "files": 3}
        store.kv_set("pending_feedback", "pending", first)
        assert store.kv_get("pending_feedback", "pending") == first

        second = {"marker": "f:other correction", "project": "/repo/b", "files": 1}
        store.kv_set("pending_feedback", "pending", second)  # pop path replaces, never appends
        assert store.kv_get("pending_feedback", "pending") == second
    finally:
        store.close()


def _columns(conn, table) -> dict:
    return {row[1]: row[3] for row in conn.execute(f"PRAGMA table_info({table})")}  # name -> notnull


def test_awm_decisions_schema_is_append_log_with_ts(tmp_path, monkeypatch):
    """awm_decisions is an append-log: autoincrement id, NOT NULL ts, JSON payload (D9 ts convention)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        columns = _columns(store.conn, "awm_decisions")
        assert set(columns) == {"id", "ts", "payload"}
        assert columns["ts"] == 1  # NOT NULL: retention ranges query it lexicographically
        assert columns["payload"] == 1
    finally:
        store.close()


def test_awm_decisions_rows_read_back_in_append_order(tmp_path, monkeypatch):
    """Rows come back in insertion order (the decisions.jsonl line sequence), payload verbatim."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        entries = [
            {"ts": _ts(3), "type": "enabled", "detail": "away 4h"},
            {"ts": _ts(2), "type": "registered", "detail": "decision X"},
            {"ts": _ts(1), "type": "disabled", "detail": "awm off"},
        ]
        for entry in entries:
            store.conn.execute(
                "INSERT INTO awm_decisions(ts, payload) VALUES (?, ?)",
                (entry["ts"], json.dumps(entry)),
            )
        store.conn.commit()

        rows = store.conn.execute(
            "SELECT ts, payload FROM awm_decisions ORDER BY id").fetchall()
        assert [json.loads(payload) for _, payload in rows] == entries
    finally:
        store.close()


def test_log_rows_since_returns_only_rows_at_or_after_the_cutoff(tmp_path, monkeypatch):
    """The windowed read side of log_append (join-review finding: the memory-grade hook
    decoded the whole 60-day table to answer a 60-second window): rows older than the
    cutoff never come back, the cutoff row itself does (>=, matching the caller's own
    window edge), and append order is preserved."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        stale = _ts(2)
        edge = _ts(1)
        fresh = _ts(1 / 86400)  # one second ago
        for ts, marker in ((stale, "stale"), (edge, "edge"), (fresh, "fresh")):
            store.log_append("searches", ts, {"marker": marker})

        rows = store.log_rows_since("searches", edge)

        assert [json.loads(payload)["marker"] for _, payload in rows] == ["edge", "fresh"]
        assert store.log_rows_since("searches", _ts(0) + "x") == []  # future cutoff: empty
    finally:
        store.close()


def test_log_rows_since_is_served_by_the_ts_index(tmp_path, monkeypatch):
    """The bound must be a seek, not a scan: the whole point of the windowed read is that
    a short recency window never touches the retention-bounded table's full history —
    the ts-index DDL convention (D17c) is what makes the cutoff cheap."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        plan = store.conn.execute(
            "EXPLAIN QUERY PLAN SELECT ts, payload FROM searches WHERE ts >= ?",
            ("2026-01-01T00:00:00+00:00",)).fetchall()
        detail = " ".join(str(column) for row in plan for column in row)
        assert "idx_searches_ts" in detail, f"cutoff not served by the index: {detail}"
    finally:
        store.close()


def test_log_rows_since_fails_open_as_empty(tmp_path, monkeypatch):
    """A broken store degrades to an empty window, never a raise (D31) — same contract
    as log_rows, which the windowed read exists beside."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.log_append("searches", _ts(1), {"marker": "kept"})
        store.conn.execute("DROP TABLE searches")
        store.conn.commit()

        assert store.log_rows_since("searches", _ts(2)) == []
    finally:
        store.close()


def test_searches_schema_is_telemetry_log_with_ts(tmp_path, monkeypatch):
    """searches is a log table like awm_decisions: autoincrement id, NOT NULL ts, payload."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        columns = _columns(store.conn, "searches")
        assert set(columns) == {"id", "ts", "payload"}
        assert columns["ts"] == 1
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2b. P1.4 — the searches family goes active: the memory-grade stash writer's kind
# ---------------------------------------------------------------------------


def _legacy_searches(root: Path, entries: list) -> Path:
    """Seed the legacy memory-grade stash document; return its path."""
    path = root / "memory-grade" / "searches.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"recent": entries}), encoding="utf-8")
    return path


def test_searches_family_kind_is_the_recent_entry_log():
    """P1.4 flips searches from deferred to the wrapper-document entry log kind, so the
    default registry dual-reads and lazy-migrates the memory-grade stash on first write."""
    family = badger_store.USER_FAMILIES["searches"]
    assert family.legacy_kind == "recent"


def test_first_searches_write_imports_legacy_stash_and_renames(tmp_path, monkeypatch):
    """The first searches write lazy-migrates the legacy stash document: one row per
    entry, COMMIT before the searches.migrated.json rename (D6)."""
    root = _user_env(tmp_path, monkeypatch)
    old = time.time() - 120
    _legacy_searches(root, [
        {"correlationId": "c-1", "sourceFiles": ["/p/a.md"], "ts": old},
        {"correlationId": "c-2", "sourceFiles": ["/p/b.md", "/p/c.md"], "ts": old + 30},
    ])
    store = badger_store.open_user()
    try:
        fresh = time.time()
        store.log_append("searches", badger_store.iso_row_ts(fresh),
                         {"correlationId": "c-3", "sourceFiles": ["/p/d.md"], "ts": fresh})

        assert not (root / "memory-grade" / "searches.json").exists()
        assert (root / "memory-grade" / "searches.migrated.json").exists()
        rows = store.conn.execute("SELECT ts, payload FROM searches ORDER BY id").fetchall()
        assert [json.loads(payload)["correlationId"] for _, payload in rows] == \
            ["c-1", "c-2", "c-3"]
    finally:
        store.close()


def test_searches_import_keeps_entry_verbatim_and_row_ts_parseable(tmp_path, monkeypatch):
    """Each stash entry becomes one row: the entry document verbatim as the payload (its
    consumer does float window arithmetic on the embedded ts), and the entry's own ts
    field converted to UTC ISO-8601 for the row's ts column — the prune must parse it."""
    root = _user_env(tmp_path, monkeypatch)
    epoch = time.time() - 3600
    _legacy_searches(root, [{"correlationId": "c-1", "sourceFiles": ["/p/a.md"],
                             "ts": epoch, "extra": {"kept": True}}])
    store = badger_store.open_user()
    try:
        store.migrate("searches")

        row_ts, payload = store.conn.execute(
            "SELECT ts, payload FROM searches ORDER BY id").fetchone()
        assert json.loads(payload) == {"correlationId": "c-1", "sourceFiles": ["/p/a.md"],
                                       "ts": epoch, "extra": {"kept": True}}
        datetime.fromisoformat(row_ts)  # the prune's parseability contract (D36)
        assert row_ts.endswith("+00:00")  # UTC conversion of the epoch, never a local guess
    finally:
        store.close()


def test_searches_crash_between_commit_and_rename_does_not_double_import(
        tmp_path, monkeypatch):
    """Crash after COMMIT, before rename: the next write re-imports the same entries and
    exact (ts, payload) content keeps the rows unique (D6)."""
    root = _user_env(tmp_path, monkeypatch)
    entries = [
        {"correlationId": "c-1", "sourceFiles": ["/p/a.md"], "ts": time.time() - 60},
        {"correlationId": "c-2", "sourceFiles": ["/p/b.md"], "ts": time.time() - 30},
    ]
    legacy = _legacy_searches(root, entries)
    time.sleep(0.05)  # legacy mtime must strictly predate the migration stamp
    store = badger_store.open_user()
    try:
        store.migrate("searches")  # commits and renames
        # Restore the exact on-disk state a crash between COMMIT and rename leaves behind.
        legacy.with_name("searches.migrated.json").rename(legacy)

        store.migrate("searches")  # the next write's import re-runs in that state
        count = store.conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        assert count == 2  # duplicate-free: a re-import must not add rows
        assert not legacy.exists()  # and the rename completes this time
    finally:
        store.close()


def test_searches_retention_sweeps_migrated_rows_older_than_60_days(tmp_path, monkeypatch):
    """G0-Q2 made operative: rows imported from the legacy stash prune on the same 60-day
    rule — an entry stashed 61 days ago is gone, a fresh one survives, because the import
    converted the entries' epoch ts into parseable row ts (D36)."""
    root = _user_env(tmp_path, monkeypatch)
    _legacy_searches(root, [
        {"correlationId": "old", "sourceFiles": ["/p/old.md"],
         "ts": time.time() - 61 * 86400},
        {"correlationId": "fresh", "sourceFiles": ["/p/new.md"],
         "ts": time.time() - 120},
    ])
    store = badger_store.open_user()
    try:
        store.migrate("searches")
        pruned = store.prune_expired("searches", max_age_days=60)

        assert pruned == 1
        kept = [json.loads(payload)["correlationId"] for _, payload in store.conn.execute(
            "SELECT ts, payload FROM searches ORDER BY id").fetchall()]
        assert kept == ["fresh"]
    finally:
        store.close()


def test_searches_import_quarantines_malformed_documents(tmp_path, monkeypatch):
    """A shape-less legacy stash never crashes the write path: it imports nothing and
    quarantines with the rename, like the map-kind behavior this module shipped with."""
    root = _user_env(tmp_path, monkeypatch)
    (root / "memory-grade").mkdir(parents=True, exist_ok=True)
    for content in ("not json", json.dumps({"recent": "not-a-list"}),
                    json.dumps({"recent": ["a string", 7, None]}),
                    json.dumps({"other": []})):
        (root / "memory-grade" / "searches.json").write_text(content, encoding="utf-8")
        store = badger_store.open_user()
        try:
            store.log_append("searches", badger_store.iso_row_ts(time.time()),
                             {"correlationId": "c-1", "sourceFiles": ["/p/a.md"],
                              "ts": time.time()})

            rows = store.conn.execute("SELECT payload FROM searches").fetchall()
            assert len(rows) == 1  # only the live write; the legacy doc contributed nothing
            assert not (root / "memory-grade" / "searches.json").exists()
            store.conn.execute("DELETE FROM searches")
            store.conn.execute("DELETE FROM meta")
            store.conn.commit()
        finally:
            store.close()


def test_searches_import_survives_absurd_entry_timestamps(tmp_path, monkeypatch):
    """A corrupt entry's out-of-range epoch is a value problem, not a migration crash:
    the row lands under now (the sweep treats no better option as fresh) and the file
    still renames — quarantine, never a poisoned stash that fails every later write."""
    root = _user_env(tmp_path, monkeypatch)
    _legacy_searches(root, [
        {"correlationId": "huge", "sourceFiles": ["/p/a.md"], "ts": 1e30},
        {"correlationId": "ok", "sourceFiles": ["/p/b.md"], "ts": time.time() - 30},
    ])
    store = badger_store.open_user()
    try:
        store.migrate("searches")

        ids = [json.loads(payload)["correlationId"]
               for _, payload in store.log_rows("searches")]
        assert sorted(ids) == ["huge", "ok"]  # both imported; neither crashed the import
        assert not (root / "memory-grade" / "searches.json").exists()
    finally:
        store.close()


def test_log_rows_reads_append_order_and_fails_open(tmp_path, monkeypatch):
    """log_rows is the read side of log_append: (ts, payload) pairs in append order;
    a broken store reads as empty, never a crash (D31)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.log_append("searches", badger_store.iso_row_ts(time.time() - 30),
                         {"correlationId": "first"})
        store.log_append("searches", badger_store.iso_row_ts(time.time()),
                         {"correlationId": "second"})

        rows = store.log_rows("searches")
        assert [json.loads(payload)["correlationId"] for _, payload in rows] == \
            ["first", "second"]
    finally:
        store.close()
    assert store.log_rows("searches") == []  # broken (closed) store: empty, not raise


# ---------------------------------------------------------------------------
# 3. P0.6b carry 1 — the DB file pre-exists at 0600 BEFORE sqlite3.connect
# ---------------------------------------------------------------------------


def test_user_db_file_is_0600_before_sqlite3_connect(tmp_path, monkeypatch):
    """No first-open 0644 window: the file is created at 0600 before connect runs (P0.6b carry 1).

    Spying on connect catches the window directly; umask 000 makes sqlite's own creation
    land at 0644, so a direct connect cannot pass the mode check.
    """
    _user_env(tmp_path, monkeypatch)
    real_connect = sqlite3.connect
    seen: dict = {}

    def spy(path, *args, **kwargs):
        target = Path(path)
        seen["mode"] = target.stat().st_mode & 0o777 if target.exists() else None
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    old_umask = os.umask(0o000)  # hostile: permissive creation mode for anything sqlite makes
    try:
        store = badger_store.open_user()
        try:
            assert seen["mode"] == 0o600, (
                f"the user DB must pre-exist at 0600 before sqlite3.connect, saw {seen['mode']}"
            )
            db = badger_store.user_db_path()
            assert db.stat().st_mode & 0o777 == 0o600
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{db}{suffix}")
                assert sidecar.exists() and sidecar.stat().st_mode & 0o777 == 0o600
        finally:
            store.close()
    finally:
        os.umask(old_umask)


# ---------------------------------------------------------------------------
# 4. P0.6b carry 2 — ts-index convention in _DDL + the awm_decisions index
# ---------------------------------------------------------------------------


def _ddl_source() -> str:
    source = inspect.getsource(badger_store)
    tree = ast.parse(source)
    assignment = next(node for node in tree.body
                      if isinstance(node, ast.Assign)
                      and getattr(node.targets[0], "id", "") == "_DDL")
    return ast.get_source_segment(source, assignment)


def test_ddl_block_carries_ts_index_convention_comment():
    """The _DDL block names the three log tables and the ts-index convention in a comment,
    so vendored copies carry the pattern (hook_audit's index lands with P2.1, searches'
    with P1.4 — the P2.3 retention gate enforces both)."""
    ddl = _ddl_source()
    comments = "\n".join(line for line in ddl.splitlines() if line.lstrip().startswith("#"))
    for table in ("hook_audit", "awm_decisions", "searches"):
        assert table in comments, f"the ts-index convention comment must name {table}"
    assert "ts" in comments and "index" in comments.lower()


def test_awm_decisions_ts_index_exists(tmp_path, monkeypatch):
    """awm_decisions.ts is indexed at creation — the retention prune's range query (P0.6a/D17c)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        rows = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'awm_decisions'"
            " AND sql IS NOT NULL"
        ).fetchall()
        assert rows, "awm_decisions must carry a ts index"
        assert any("ts" in row[0] for row in rows)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 5. D21 — the audit sink derives from AI_BADGER_DEBUG_DIR, default under the real home
# ---------------------------------------------------------------------------


def test_audit_db_follows_debug_dir_and_defaults_under_home(tmp_path, monkeypatch):
    """AI_BADGER_DEBUG_DIR moves the audit DB whole (own file, D21); unset, it lands under ~."""
    debug = tmp_path / "debug"
    debug.mkdir()
    monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(debug))
    audit = badger_store.audit_db_path()
    assert audit.parent == debug
    assert audit.suffix == ".db"  # its own DB file, not a table of the user DB
    assert audit != badger_store.user_db_path()

    monkeypatch.delenv("AI_BADGER_DEBUG_DIR")
    assert badger_store.audit_db_path().parent == REAL_HOME / ".ai-badger" / "debug"


# ---------------------------------------------------------------------------
# 6. Retention seam (P2.3 prereq) — prune-by-age per family with the meta-stamp throttle
# ---------------------------------------------------------------------------


def _seed_decision(store, days_ago: float, detail: str) -> str:
    payload = json.dumps({"ts": _ts(days_ago), "type": "t", "detail": detail})
    store.conn.execute(
        "INSERT INTO awm_decisions(ts, payload) VALUES (?, ?)",
        (_ts(days_ago), payload),
    )
    store.conn.commit()
    return payload


def test_prune_expired_deletes_only_rows_older_than_max_age(tmp_path, monkeypatch):
    """prune_expired removes rows older than the cutoff, keeps fresh ones, stamps pruned_at."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_decision(store, 90, "ancient")
        _seed_decision(store, 61, "just-expired")
        fresh_payload = _seed_decision(store, 30, "fresh")
        assert store.meta_get("pruned_at.awm_decisions") is None

        pruned = store.prune_expired("awm_decisions", max_age_days=60)

        assert pruned == 2
        remaining = [row[0] for row in store.conn.execute("SELECT payload FROM awm_decisions")]
        assert remaining == [fresh_payload]
        assert store.meta_get("pruned_at.awm_decisions") is not None
    finally:
        store.close()


def test_prune_expired_second_call_within_window_is_noop(tmp_path, monkeypatch):
    """The meta-stamp throttle: a second prune inside the window deletes nothing (D30) —
    not even rows that expired after the first call."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_decision(store, 90, "ancient")
        assert store.prune_expired("awm_decisions", max_age_days=60) == 1
        stamp = store.conn.execute(
            "SELECT value FROM meta WHERE key = 'pruned_at.awm_decisions'").fetchone()[0]

        _seed_decision(store, 90, "expired-after-first-prune")
        assert store.prune_expired("awm_decisions", max_age_days=60) == 0
        assert store.conn.execute("SELECT COUNT(*) FROM awm_decisions").fetchone()[0] == 1, (
            "the throttled second prune must not delete the newly expired row"
        )
        assert store.conn.execute(
            "SELECT value FROM meta WHERE key = 'pruned_at.awm_decisions'").fetchone()[0] == stamp
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 7. Perms — 0600/0700 on every open and write; the user root keeps its own mode
# ---------------------------------------------------------------------------


def test_user_db_sidecars_0600_on_every_open_and_write(tmp_path, monkeypatch):
    """Every open and every write re-asserts owner-only on the DB and its WAL sidecars (D17)."""
    _user_env(tmp_path, monkeypatch)
    db = badger_store.user_db_path()

    store = badger_store.open_user()
    try:
        store.kv_set("awm_state", "/repo/main", {"enabled": True})
        assert db.stat().st_mode & 0o777 == 0o600
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{db}{suffix}")
            assert sidecar.exists() and sidecar.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()

    reopened = badger_store.open_user()
    try:
        reopened.kv_set("awm_state", "/repo/main", {"enabled": False})
        assert db.stat().st_mode & 0o777 == 0o600
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{db}{suffix}")
            assert sidecar.exists() and sidecar.stat().st_mode & 0o777 == 0o600
    finally:
        reopened.close()


def test_user_write_does_not_chmod_existing_root(tmp_path, monkeypatch):
    """A pre-existing user root keeps its mode through writes — the store never chmods it (D17)."""
    root = _user_env(tmp_path, monkeypatch)
    root.mkdir()
    root.chmod(0o755)

    store = badger_store.open_user()
    try:
        store.kv_set("commit_reminder", "/repo/a", {"count": 1, "marker": 0})
    finally:
        store.close()
    assert root.stat().st_mode & 0o777 == 0o755
