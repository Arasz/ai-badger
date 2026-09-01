"""Red tests for the user-DB message bus store surface (P1, aib-user-db-message-bus).

``engine/badger_store.py`` gains the bus families and their API — born in SQLite (D2), no
legacy source, carried to every consumer by the vendored-copy discipline (D16):

    SCHEMA_VERSION = 2                   # the bus is the first migration (D1)
    UPGRADE_HOOKS[1]                     # the bus tables' DDL: idempotent, DDL-only
    USER_FAMILIES += messages, cursors   # db="user", no legacy_path (born in SQLite)

    Store.send_message(*, sender_session, sender_project, content,
                       target_session=None, target_project=None) -> int
    Store.deliver_for_session(session_id, project_id=None) -> list[dict]
    Store.delete_cursor(session_id) -> bool

Test map (plan aib-user-db-message-bus §3 P1 · spec rules in parentheses):
  1. Bus tables + stamp 2 (fresh open) .......... test_open_user_creates_the_bus_tables_and_stamps_version_two
  2. DDL conventions (the DDL gate, D6/D17c) .... test_bus_ddl_follows_the_store_conventions
  3. Upgrade path (Rule 9 machinery, A1) ........ test_pre_bus_user_db_runs_upgrade_hook_one_and_re_stamps,
                                                   test_failing_upgrade_hook_rolls_back_to_stamped_and_tableless
  4. Fail closed (Rule 9) ....................... test_stamped2_db_refuses_old_code_naming_den_refresh,
                                                   test_pre_bus_db_without_bus_tables_opens_unchanged_under_old_code
  5. Send identity (Rule 1, D3/A2) .............. test_send_stamps_sender_identity_and_defaults_to_broadcast,
                                                   test_send_without_project_id_is_refused_and_writes_no_row,
                                                   test_send_without_session_id_is_refused_and_writes_no_row,
                                                   test_send_with_both_targets_stores_one_to_one_with_null_project,
                                                   test_send_project_target_stores_null_session
  6. Delivery shapes + suppression (Rules 1-2) .. test_deliver_addressing_shapes_reach_their_recipients,
                                                   test_deliver_suppresses_the_senders_own_messages,
                                                   test_deliver_without_project_id_delivers_one_to_one_only
  7. History gate (Rule 4, D5) .................. test_first_delivery_gates_to_the_30_minute_window,
                                                   test_a_message_exactly_30_minutes_old_is_included,
                                                   test_a_message_just_past_30_minutes_is_excluded,
                                                   test_cursorless_live_read_applies_the_gate_once
  8. Cap 16 (Rule 5) ............................ test_small_inbox_delivers_whole_in_chronological_order,
                                                   test_sixteen_messages_hold_the_boundary,
                                                   test_overflow_beyond_sixteen_is_dropped_and_never_redelivered
  9. Exactly once (Rule 3, F5) .................. test_concurrent_deliveries_inject_exactly_once,
                                                   test_hook_crash_between_read_and_commit_rolls_back,
                                                   test_cursor_upsert_advances_ts
 10. Cursor lifecycle + retention (Rules 6+10) .. test_delete_cursor_removes_the_row,
                                                   test_open_user_prunes_cursors_older_than_four_days,
                                                   test_open_user_prunes_messages_older_than_four_days,
                                                   test_a_message_exactly_four_days_old_survives_until_the_window_closes
 11. Index gate (D6) ............................ test_every_delivery_shape_is_index_bounded

Deterministic mechanisms (plan review F5/§D): the race and crash tests drive the
module-level seams (``_TEST_HOLDS`` / ``AI_BADGER_TEST_HOLD``) at the delivery path's two
named fault points, and the boundary tests freeze ``badger_store.datetime`` so fixture
timestamps and store cutoffs share one instant — no sleeps, no clock assumptions.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import badger_store

GATE_MINUTES = 30
START_CAP = 16
RETENTION_DAYS = 4


# ---------------------------------------------------------------------------
# helpers — env redirect, fixtures, clock freeze, race seams
# ---------------------------------------------------------------------------


def _user_env(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "user-root"
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(root))
    return root


def _schema_version(conn) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert row is not None, "meta must carry a schema_version row"
    return row[0]


def _tables(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _pre_bus_user_db(root: Path) -> Path:
    """A user DB exactly as the pre-bus store leaves it: meta stamped 1, no bus tables."""
    db_path = root / "ai-badger.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
        conn.commit()
    finally:
        conn.close()
    return db_path


class _FrozenDatetime:
    """Stands in for the datetime class inside badger_store: now() frozen, rest delegates.

    The module calls datetime.now (row stamps, gate cutoff, prune cutoff), fromisoformat
    (the prune's parseability sweep) and fromtimestamp (the status rendering); everything
    else is real. Freezing the one reference makes fixture timestamps and store cutoffs
    share an instant, which is what lets a boundary test write the exact boundary ts.
    """

    frozen = None  # class attribute: the moment every now() returns

    @classmethod
    def now(cls, tz=None):
        moment = cls.frozen
        return moment if tz is None else moment.astimezone(tz)

    fromisoformat = staticmethod(datetime.fromisoformat)
    fromtimestamp = staticmethod(datetime.fromtimestamp)


@pytest.fixture
def frozen_clock(monkeypatch) -> datetime:
    """Freeze badger_store's clock at one UTC instant and hand the instant back."""
    moment = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _FrozenDatetime.frozen = moment
    monkeypatch.setattr(badger_store, "datetime", _FrozenDatetime)
    return moment


def _seed_message(store, *, ts: str, sender_session: str, sender_project: str,
                  target_session: str = None, target_project: str = None,
                  content: str = "m") -> int:
    """Insert one message row with an exact ts — send_message stamps now, fixtures age."""
    cursor = store.conn.execute(
        "INSERT INTO messages(ts, sender_session, sender_project, target_session, "
        "target_project, content) VALUES (?, ?, ?, ?, ?, ?)",
        (ts, sender_session, sender_project, target_session, target_project, content),
    )
    store.conn.commit()
    return cursor.lastrowid


def _seed_cursor(store, session_id: str, cursor_id: int, ts: str) -> None:
    store.conn.execute(
        "INSERT INTO cursors(session_id, cursor_id, ts) VALUES (?, ?, ?)",
        (session_id, cursor_id, ts),
    )
    store.conn.commit()


def _clear_prune_stamps(store) -> None:
    """Clear the pruned_at.* meta stamps: the 3600 s throttle would no-op the next prune (F7)."""
    store.conn.execute("DELETE FROM meta WHERE key LIKE 'pruned_at.%'")
    store.conn.commit()


def _cursor_row(store, session_id: str):
    return store.conn.execute(
        "SELECT cursor_id, ts FROM cursors WHERE session_id = ?", (session_id,)).fetchone()


def _documents(rows) -> list:
    """(id, ts, sender_session, sender_project, content) rows as the delivered documents."""
    return [{"sender": {"sessionId": row[2], "projectId": row[3]},
             "content": row[4], "timestamp": row[1]} for row in rows]


# ---------------------------------------------------------------------------
# 1–4. schema, migration machinery, fail closed
# ---------------------------------------------------------------------------


def test_open_user_creates_the_bus_tables_and_stamps_version_two(tmp_path, monkeypatch):
    """A fresh user store is born with the bus tables and stamped 2 — the bus's own stamp (D1/D2)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        assert {"messages", "cursors"} <= _tables(store.conn)
        assert int(_schema_version(store.conn)) == 2
    finally:
        store.close()


def test_bus_ddl_follows_the_store_conventions(tmp_path, monkeypatch):
    """The DDL gate on the bus tables (P0.6a pattern, D6/D17c): messages is an append-log
    whose queried fields are real NOT NULL columns with a ts index and both target indexes;
    cursors carries NOT NULL ts under its own ts index so the 4-day prune is a seek."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        messages = {row[1]: row[3] for row in store.conn.execute("PRAGMA table_info(messages)")}
        assert messages["ts"] == 1 and messages["content"] == 1
        assert messages["sender_session"] == 1 and messages["sender_project"] == 1
        assert "target_session" in messages and "target_project" in messages
        message_indexes = " ".join(
            row[0] for row in store.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'messages'"
                " AND sql IS NOT NULL"))
        assert "idx_messages_ts" in message_indexes
        assert "idx_messages_target_session" in message_indexes
        assert "idx_messages_target_project" in message_indexes
        cursors = {row[1]: row[3] for row in store.conn.execute("PRAGMA table_info(cursors)")}
        assert cursors["ts"] == 1 and cursors["cursor_id"] == 1
        cursor_indexes = " ".join(
            row[0] for row in store.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'cursors'"
                " AND sql IS NOT NULL"))
        assert "idx_cursors_ts" in cursor_indexes
    finally:
        store.close()


def test_pre_bus_user_db_runs_upgrade_hook_one_and_re_stamps(tmp_path, monkeypatch):
    """A DB stamped 1 (pre-bus) upgrades on open: hook 1 lands the bus DDL inside its
    BEGIN IMMEDIATE and the stamp moves to 2 — the first exercise of UPGRADE_HOOKS (A1)."""
    root = _user_env(tmp_path, monkeypatch)
    _pre_bus_user_db(root)
    real_hook = badger_store.UPGRADE_HOOKS[1]
    calls = []

    def recording_hook(conn):
        calls.append(1)
        real_hook(conn)

    monkeypatch.setitem(badger_store.UPGRADE_HOOKS, 1, recording_hook)

    store = badger_store.open_user()
    try:
        assert calls == [1], "the 1 -> 2 upgrade hook must run on open"
        assert int(_schema_version(store.conn)) == 2
        assert {"messages", "cursors"} <= _tables(store.conn)
    finally:
        store.close()


def test_failing_upgrade_hook_rolls_back_to_stamped_and_tableless(tmp_path, monkeypatch):
    """A hook that writes DDL then dies must leave the DB exactly as it was — stamped 1,
    table-less — so the next open re-runs the migration instead of half-having it (D1)."""
    root = _user_env(tmp_path, monkeypatch)
    db_path = _pre_bus_user_db(root)

    def writes_then_dies(conn):
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
        raise RuntimeError("hook died mid-migration")

    monkeypatch.setitem(badger_store.UPGRADE_HOOKS, 1, writes_then_dies)
    with pytest.raises(RuntimeError):
        badger_store.open_user()

    conn = sqlite3.connect(db_path)  # raw: inspect what actually survived on disk
    try:
        assert _schema_version(conn) == "1"
        assert "messages" not in _tables(conn) and "cursors" not in _tables(conn)
    finally:
        conn.close()


def test_stamped2_db_refuses_old_code_naming_den_refresh(tmp_path, monkeypatch):
    """Rule 9 scenario 1: a DB the bus already stamped 2 fails closed under old code —
    the OperationalError carries the den-refresh pointer and names the exact DB (D27)."""
    _user_env(tmp_path, monkeypatch)
    badger_store.open_user().close()  # a store the bus stamped 2

    monkeypatch.setattr(badger_store, "SCHEMA_VERSION", 1)  # the pre-bus code's world
    with pytest.raises(sqlite3.OperationalError) as excinfo:
        badger_store.open_user()
    message = str(excinfo.value)
    assert "den-refresh" in message
    assert str(badger_store.user_db_path()) in message


def test_pre_bus_db_without_bus_tables_opens_unchanged_under_old_code(tmp_path, monkeypatch):
    """Rule 9 scenario 2: old code on a pre-bus DB is simply a store without the bus —
    the open succeeds, its own operations run, and the absent bus tables never bite (D31)."""
    root = _user_env(tmp_path, monkeypatch)
    _pre_bus_user_db(root)
    monkeypatch.setattr(badger_store, "SCHEMA_VERSION", 1)

    store = badger_store.open_user()
    try:
        assert int(_schema_version(store.conn)) == 1
        store.kv_set("pending_feedback", "pending", {"ok": True})
        assert store.kv_get("pending_feedback", "pending") == {"ok": True}
    finally:
        store.close()
