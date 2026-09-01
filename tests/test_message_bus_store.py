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
import time
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


# ---------------------------------------------------------------------------
# 5. send identity (Rule 1, D3/A2)
# ---------------------------------------------------------------------------


def test_send_stamps_sender_identity_and_defaults_to_broadcast(tmp_path, monkeypatch):
    """A send with both identities stores the content verbatim under a UTC ts; with no
    target it is a machine broadcast — both target columns NULL (D3 read predicates)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        row_id = store.send_message(sender_session="S", sender_project="P",
                                    content="found it, see src/bus.py")
        row = store.conn.execute(
            "SELECT ts, sender_session, sender_project, target_session, target_project, "
            "content FROM messages WHERE id = ?", (row_id,)).fetchone()
        assert row[1:3] == ("S", "P")
        assert row[3] is None and row[4] is None  # broadcast: both targets NULL
        assert row[5] == "found it, see src/bus.py"  # verbatim, never re-encoded
        datetime.fromisoformat(row[0])  # a parseable ISO-8601 ts (retention feeds on it)
        assert row[0].endswith("+00:00")  # UTC, the store's ts convention
    finally:
        store.close()


def test_send_without_project_id_is_refused_and_writes_no_row(tmp_path, monkeypatch):
    """Rule 1 scenario 2: a sender without a projectId is refused with the missing-identity
    error, and no message row is written (R10 — identity is REQUIRED at send)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        with pytest.raises(ValueError, match="projectId"):
            store.send_message(sender_session="S", sender_project="", content="x")
        assert store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    finally:
        store.close()


def test_send_without_session_id_is_refused_and_writes_no_row(tmp_path, monkeypatch):
    """The session half of the identity is equally required: no sessionId, no row (R10)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        with pytest.raises(ValueError, match="sessionId"):
            store.send_message(sender_session="", sender_project="P", content="x")
        assert store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    finally:
        store.close()


def test_send_with_both_targets_stores_one_to_one_with_null_project(tmp_path, monkeypatch):
    """D3/A2: when both targets are given the session target wins and the row is
    normalised AT WRITE — target_project is stored NULL, not kept alongside (A2's
    secondary observable: the normalisation must be observable in the row itself)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        row_id = store.send_message(sender_session="S", sender_project="P", content="x",
                                    target_session="T", target_project="Q")
        row = store.conn.execute(
            "SELECT target_session, target_project FROM messages WHERE id = ?",
            (row_id,)).fetchone()
        assert row == ("T", None)
    finally:
        store.close()


def test_send_project_target_stores_null_session(tmp_path, monkeypatch):
    """The project shape is the mirror image: target_session NULL, target_project set —
    every read predicate stays single-shape (D3)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        row_id = store.send_message(sender_session="S", sender_project="P", content="x",
                                    target_project="Q")
        row = store.conn.execute(
            "SELECT target_session, target_project FROM messages WHERE id = ?",
            (row_id,)).fetchone()
        assert row == (None, "Q")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 6–8. delivery shapes, suppression (Rules 1–2), history gate (Rule 4), cap (Rule 5)
# ---------------------------------------------------------------------------


def test_deliver_addressing_shapes_reach_their_recipients(tmp_path, monkeypatch):
    """Every D3 shape reaches exactly its recipient set, in chronological order: a 1:1
    only its session, a project message its project's sessions, a broadcast everyone."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S1", sender_project="P", content="direct",
                           target_session="S2")
        store.send_message(sender_session="S1", sender_project="P", content="for P",
                           target_project="P")
        store.send_message(sender_session="S1", sender_project="P", content="everyone")

        s2 = store.deliver_for_session("S2", "P")
        assert [m["content"] for m in s2] == ["direct", "for P", "everyone"]
        assert s2[0]["sender"] == {"sessionId": "S1", "projectId": "P"}
        assert s2[0]["timestamp"] == store.conn.execute(
            "SELECT ts FROM messages WHERE content = 'direct'").fetchone()[0]
        # S3 sits in another project: the broadcast still reaches it, the project message not
        s3 = store.deliver_for_session("S3", "OTHER")
        assert [m["content"] for m in s3] == ["everyone"]
    finally:
        store.close()


def test_deliver_suppresses_the_senders_own_messages(tmp_path, monkeypatch):
    """Rule 2: a session never receives its own broadcast or its own project message —
    and the suppression is not the write being missing: another session still gets them."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S", sender_project="P", content="own broadcast")
        store.send_message(sender_session="S", sender_project="P", content="own project",
                           target_project="P")
        store.send_message(sender_session="S", sender_project="P", content="own 1:1",
                           target_session="S")

        assert store.deliver_for_session("S", "P") == []
        # The same messages reach everyone else — only the sender is blind to them.
        assert [m["content"] for m in store.deliver_for_session("T", "P")] == \
            ["own broadcast", "own project"]
    finally:
        store.close()


def test_deliver_without_project_id_delivers_one_to_one_only(tmp_path, monkeypatch):
    """A session whose project id could not be resolved still receives its 1:1 mail,
    but the project and broadcast legs are skipped (the P2 fail-open contract, D7)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S1", sender_project="P", content="direct",
                           target_session="S2")
        store.send_message(sender_session="S1", sender_project="P", content="for P",
                           target_project="P")
        store.send_message(sender_session="S1", sender_project="P", content="everyone")

        delivered = store.deliver_for_session("S2", None)
        assert [m["content"] for m in delivered] == ["direct"]
    finally:
        store.close()


def test_first_delivery_gates_to_the_30_minute_window(tmp_path, monkeypatch, frozen_clock):
    """Rule 4: a fresh session's first delivery sees recent history (5 minutes old) and
    never anything older (2 days) — the gate is applied by the store, not the harness."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_message(store, ts=(frozen_clock - timedelta(days=2)).isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="ancient")
        _seed_message(store, ts=(frozen_clock - timedelta(minutes=5)).isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="recent")

        delivered = store.deliver_for_session("S2", "P")
        assert [m["content"] for m in delivered] == ["recent"]
    finally:
        store.close()


def test_a_message_exactly_30_minutes_old_is_included(tmp_path, monkeypatch, frozen_clock):
    """Rule 4 scenario 2: the gate boundary is INCLUSIVE — a message whose ts equals the
    cutoff exactly (now − 30 min) counts as inside; only strictly older ones are gated."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_message(store, ts=(frozen_clock - timedelta(minutes=GATE_MINUTES)).isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="boundary")

        assert [m["content"] for m in store.deliver_for_session("S2", "P")] == ["boundary"]
    finally:
        store.close()


def test_a_message_just_past_30_minutes_is_excluded(tmp_path, monkeypatch, frozen_clock):
    """The window is exactly 30 minutes: one microsecond past the boundary is outside —
    this pins the magnitude, which the 2-day and boundary tests alone cannot."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_message(store,
                      ts=(frozen_clock - timedelta(minutes=GATE_MINUTES, microseconds=1))
                      .isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="just past")

        assert store.deliver_for_session("S2", "P") == []
    finally:
        store.close()


def test_cursorless_live_read_applies_the_gate_once(tmp_path, monkeypatch, frozen_clock):
    """Rule 4 scenario 4 (D5): a per-turn delivery for a session whose start event never
    fired gates once — the old backlog is skipped, the cursor lands past the gated window,
    and a message sent afterwards is still delivered on the next read."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        old_id = _seed_message(store, ts=(frozen_clock - timedelta(days=2)).isoformat(),
                               sender_session="S1", sender_project="P", target_project="P",
                               content="ancient")

        assert store.deliver_for_session("S2", "P") == []  # the gate, not an empty store
        cursor_id, _ = _cursor_row(store, "S2")
        assert cursor_id >= old_id, "the cursor must land past the gated window"

        store.send_message(sender_session="S1", sender_project="P", content="fresh",
                           target_project="P")
        assert [m["content"] for m in store.deliver_for_session("S2", "P")] == ["fresh"]
    finally:
        store.close()


def test_small_inbox_delivers_whole_in_chronological_order(tmp_path, monkeypatch):
    """Rule 5 scenario 1: an inbox under the cap delivers whole, oldest first."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        for i in range(5):
            store.send_message(sender_session="S1", sender_project="P", content=f"m{i}",
                               target_project="P")

        delivered = store.deliver_for_session("S2", "P")
        assert [m["content"] for m in delivered] == [f"m{i}" for i in range(5)]
    finally:
        store.close()


def test_sixteen_messages_hold_the_boundary(tmp_path, monkeypatch):
    """Rule 5 scenario 2: exactly 16 messages in the window all deliver — the cap is
    'more than 16 drops', not '16 is already too many'."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        for i in range(START_CAP):
            store.send_message(sender_session="S1", sender_project="P", content=f"m{i}",
                               target_project="P")

        delivered = store.deliver_for_session("S2", "P")
        assert [m["content"] for m in delivered] == [f"m{i}" for i in range(START_CAP)]
    finally:
        store.close()


def test_overflow_beyond_sixteen_is_dropped_and_never_redelivered(tmp_path, monkeypatch):
    """Rule 5 scenario 3: 100 unread deliver the 16 oldest and drop the rest — the cursor
    lands PAST the gated window, so the 84 are never injected to this session later."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        for i in range(100):
            store.send_message(sender_session="S1", sender_project="P", content=f"m{i}",
                               target_project="P")

        delivered = store.deliver_for_session("S2", "P")
        assert [m["content"] for m in delivered] == [f"m{i}" for i in range(START_CAP)]
        cursor_id, _ = _cursor_row(store, "S2")
        newest = store.conn.execute("SELECT MAX(id) FROM messages").fetchone()[0]
        assert cursor_id >= newest, "the cursor must land past the gated window"
        assert store.deliver_for_session("S2", "P") == []  # the 84 never surface
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 9. exactly once (Rule 3, F5 deterministic mechanisms)
# ---------------------------------------------------------------------------


def test_concurrent_deliveries_inject_exactly_once(tmp_path, monkeypatch):
    """Rule 3 scenario 1: two hooks for one session race on one unread message.

    The race is made deterministic by the F5 seam: hook 1 freezes INSIDE the write
    transaction after its read (``deliver.after_read``), so hook 2 blocks on
    BEGIN IMMEDIATE until hook 1 commits — hook 2's read can only happen after the
    cursor advanced. Both hooks finish at the same cursor and the message is injected
    exactly once. Under the hoist mutation (read moved before the transaction) hook 2's
    read happens while blocked, snapshotting the pre-commit world, and the message is
    injected twice. The one scheduler-dependent step is the short grace after hook 2
    starts: it gives the mutated shape time to run its (unblocked, pre-BEGIN) read.
    """
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S1", sender_project="P", content="once",
                           target_project="P")
    finally:
        store.close()

    reached_hold = threading.Event()
    release = threading.Event()

    def freeze_after_read():
        reached_hold.set()
        assert release.wait(timeout=10), "the race holder was never released"

    monkeypatch.setitem(badger_store._TEST_HOLDS, "deliver.after_read", [freeze_after_read])

    hook1: list = []
    hook2: list = []

    def _hook(target: list):
        session = badger_store.open_user()
        try:
            target.extend(session.deliver_for_session("S2", "P"))
        finally:
            session.close()

    first = threading.Thread(target=_hook, args=(hook1,))
    first.start()
    assert reached_hold.wait(timeout=10), "hook 1 never reached the after-read hold"

    second = threading.Thread(target=_hook, args=(hook2,))
    second.start()
    time.sleep(0.25)  # the documented grace: hook 2 is parked on BEGIN IMMEDIATE by now
    release.set()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive(), "a racing hook never finished"

    delivered = [m["content"] for m in hook1 + hook2]
    assert delivered == ["once"], f"exactly-once violated: {delivered}"

    final = badger_store.open_user()
    try:
        cursor_id, cursor_ts = _cursor_row(final, "S2")
        assert cursor_id == final.conn.execute(
            "SELECT MAX(id) FROM messages").fetchone()[0]
        datetime.fromisoformat(cursor_ts)  # the upsert stamped a real ts (F7 observable)
        assert final.deliver_for_session("S2", "P") == []  # nothing left to re-inject
    finally:
        final.close()


def test_hook_crash_between_read_and_commit_rolls_back(tmp_path, monkeypatch):
    """Rule 3 scenario 2: a hook that dies after reading but before the cursor commit
    injects nothing and leaves no cursor row — the rollback is the transaction's, and
    the next delivery event delivers the message."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S1", sender_project="P", content="survives",
                           target_project="P")
    finally:
        store.close()

    def die_after_read():
        raise RuntimeError("hook died mid-delivery")

    monkeypatch.setitem(badger_store._TEST_HOLDS, "deliver.after_read", [die_after_read])
    crashed = badger_store.open_user()
    try:
        with pytest.raises(RuntimeError):
            crashed.deliver_for_session("S2", "P")
        assert _cursor_row(crashed, "S2") is None, "a rolled-back delivery leaves no cursor"
        assert crashed.conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0] == 0
    finally:
        crashed.close()

    monkeypatch.setitem(badger_store._TEST_HOLDS, "deliver.after_read", [])
    survivor = badger_store.open_user()
    try:
        assert [m["content"] for m in survivor.deliver_for_session("S2", "P")] == ["survives"]
    finally:
        survivor.close()


def test_cursor_upsert_advances_ts(tmp_path, monkeypatch, frozen_clock):
    """F7's secondary observable: every delivery's cursor upsert advances cursors.ts —
    a session active for days keeps refreshing it and never prunes; a crashed one
    (whose last upsert ages) does (R6)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_cursor(store, "S", 0, (frozen_clock - timedelta(hours=1)).isoformat())
        store.send_message(sender_session="S1", sender_project="P", content="x",
                           target_project="P")

        store.deliver_for_session("S", "P")

        _, cursor_ts = _cursor_row(store, "S")
        assert cursor_ts == frozen_clock.isoformat()  # the upsert's stamp, not the seeded one
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 10. cursor lifecycle + retention (Rules 6 + 10, D10, F7 throttle-aware)
# ---------------------------------------------------------------------------


def test_delete_cursor_removes_the_row(tmp_path, monkeypatch):
    """Rule 6 scenario 1: the close-event cleanup drops the session's cursor row."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_cursor(store, "S", 3, "2026-09-01T11:00:00+00:00")
        assert store.delete_cursor("S") is True
        assert _cursor_row(store, "S") is None
        assert store.delete_cursor("S") is False  # a second close is a harmless no-op
    finally:
        store.close()


def test_open_user_prunes_cursors_older_than_four_days(tmp_path, monkeypatch, frozen_clock):
    """Rule 6 scenario 2: a crashed session's cursor (no close event) dies at the 4-day
    TTL, through the OPEN-time wiring — open_user prunes, not just an explicit call."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_cursor(store, "C", 9,
                     (frozen_clock - timedelta(days=RETENTION_DAYS, hours=1)).isoformat())
        _seed_cursor(store, "LIVE", 1, frozen_clock.isoformat())
        _clear_prune_stamps(store)  # F7: the throttle would no-op the next prune
    finally:
        store.close()

    reopened = badger_store.open_user()
    try:
        assert _cursor_row(reopened, "C") is None
        assert _cursor_row(reopened, "LIVE") is not None  # fresh cursors survive
    finally:
        reopened.close()


def test_open_user_prunes_messages_older_than_four_days(tmp_path, monkeypatch, frozen_clock):
    """Rule 10 scenario 1: retention runs at user-store open — a 5-day-old message row
    is gone, fresh ones stay (mutation docstring: removing the wiring grows the table
    without bound)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed_message(store, ts=(frozen_clock - timedelta(days=RETENTION_DAYS, hours=1))
                      .isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="ancient")
        _seed_message(store, ts=frozen_clock.isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="fresh")
        _clear_prune_stamps(store)  # F7
    finally:
        store.close()

    reopened = badger_store.open_user()
    try:
        rows = [row[0] for row in reopened.conn.execute(
            "SELECT content FROM messages ORDER BY id")]
        assert rows == ["fresh"]
    finally:
        reopened.close()


def test_a_message_exactly_four_days_old_survives_until_the_window_closes(
        tmp_path, monkeypatch, frozen_clock):
    """Rule 10 scenario 2: the boundary rule matches the other log tables —
    ``DELETE WHERE ts < cutoff`` — so a message exactly 4 days old survives the prune
    and dies only once the window closes past it (D10)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        boundary = (frozen_clock - timedelta(days=RETENTION_DAYS)).isoformat()
        _seed_message(store, ts=boundary, sender_session="S1", sender_project="P",
                      target_project="P", content="boundary")
        _seed_message(store, ts=(frozen_clock - timedelta(days=RETENTION_DAYS, seconds=1))
                      .isoformat(),
                      sender_session="S1", sender_project="P", target_project="P",
                      content="just past")
        _clear_prune_stamps(store)  # open_user's own prune armed the throttle (F7)

        store.prune_expired("messages", max_age_days=RETENTION_DAYS)
        rows = [row[0] for row in store.conn.execute(
            "SELECT content FROM messages ORDER BY id")]
        assert rows == ["boundary"], "exactly-4-days survives; 1s past dies"

        # The window closes: the clock moves on, the throttle is cleared, the boundary
        # row now sits strictly behind the cutoff and is swept (survives UNTIL then).
        _FrozenDatetime.frozen = frozen_clock + timedelta(hours=1)
        _clear_prune_stamps(store)
        store.prune_expired("messages", max_age_days=RETENTION_DAYS)
        rows = [row[0] for row in store.conn.execute("SELECT content FROM messages")]
        assert rows == [], "once the window closes past the boundary row, it goes"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 11. index gate (D6 — the searches whole-table lesson, as a gate)
# ---------------------------------------------------------------------------


class _RecordingConn:
    """Connection wrapper that records the SQL the store actually runs on the bus tables."""

    def __init__(self, conn):
        self._conn = conn
        self.captured: list = []

    def execute(self, sql, params=()):
        table = "messages" if "messages" in sql else ("cursors" if "cursors" in sql else None)
        if table is not None and sql.lstrip().upper().startswith(
                ("SELECT", "DELETE", "INSERT")):
            if not sql.lstrip().startswith("SELECT rowid, ts FROM"):
                # the D36 unparseable-ts sweep walks the whole table BY DESIGN (it must see
                # every row); it is hour-throttled and retention-bounded — not a delivery read
                self.captured.append((sql, params))
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_every_delivery_shape_is_index_bounded(tmp_path, monkeypatch):
    """D6: every read the delivery and prune paths run on messages/cursors is a seek,
    never a SCAN. The production SQL is captured through a recording connection (the
    same spy pattern the 0600 pre-create test uses) and EXPLAINed with its own params —
    the gate cannot drift from what actually ships."""
    _user_env(tmp_path, monkeypatch)
    real_connect = sqlite3.connect

    def connect(path, *args, **kwargs):
        return _RecordingConn(real_connect(path, *args, **kwargs))

    monkeypatch.setattr(sqlite3, "connect", connect)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S1", sender_project="P", content="direct",
                           target_session="S2")
        store.send_message(sender_session="S1", sender_project="P", content="for P",
                           target_project="P")
        store.send_message(sender_session="S1", sender_project="P", content="everyone")
        store.deliver_for_session("S2", "P")  # gated read + cursor upsert
        store.send_message(sender_session="S3", sender_project="P", content="more",
                           target_project="P")
        store.deliver_for_session("S2", "P")  # live read (id > cursor)
        _clear_prune_stamps(store)
    finally:
        store.close()

    assert store.conn.captured, "the recording connection must have seen the bus SQL"
    raw = real_connect(badger_store.user_db_path())
    try:
        for sql, params in store.conn.captured:
            plan = raw.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
            details = [row[-1] for row in plan]
            assert not any("SCAN" in detail for detail in details), (
                f"unbounded read in the delivery path: {sql.strip()!r} -> {details}"
            )
    finally:
        raw.close()


def test_env_gated_hold_blocks_until_the_release_file_exists(tmp_path, monkeypatch):
    """The F5 seam's cross-process arming path: AI_BADGER_TEST_HOLD="<seam>:<release-path>"
    parks the delivery at the seam until the file appears — the mechanism P9's
    two-process race depends on. In-process this proves the env path; the registry path
    is what the race test above arms."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        store.send_message(sender_session="S1", sender_project="P", content="held",
                           target_project="P")
    finally:
        store.close()

    release = tmp_path / "release-hold"
    monkeypatch.setenv("AI_BADGER_TEST_HOLD", f"deliver.after_read:{release}")

    done = threading.Event()
    error: list = []

    def held_hook():
        session = badger_store.open_user()
        try:
            session.deliver_for_session("S2", "P")
            done.set()
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            error.append(exc)
            done.set()
        finally:
            session.close()

    worker = threading.Thread(target=held_hook)
    worker.start()
    try:
        assert not done.wait(0.5), "the env-gated hold must park the delivery at the seam"
    finally:
        release.touch()  # the parent releases the child by creating the file
    assert done.wait(10), "the delivery never resumed after the release file appeared"
    if error:
        raise error[0]
