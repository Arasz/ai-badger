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
    """The registry names the five families, all user-DB, with their legacy JSON sources."""
    families = badger_store.USER_FAMILIES
    assert set(families) == {
        "awm_state", "awm_decisions", "commit_reminder", "pending_feedback", "searches",
    }
    assert {name: family.table for name, family in families.items()} == {
        "awm_state": "awm_state",
        "awm_decisions": "awm_decisions",
        "commit_reminder": "commit_reminder",
        "pending_feedback": "pending_feedback",
        "searches": "searches",
    }
    for family in families.values():
        assert family.db == "user"
    home = REAL_HOME
    assert families["awm_state"].legacy_path() == home / ".claude" / "awm" / "state.json"
    assert families["awm_decisions"].legacy_path() == home / ".claude" / "awm" / "decisions.jsonl"
    assert families["commit_reminder"].legacy_path() == (
        home / ".ai-badger" / "commit-reminder" / "state.json")
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
