"""Red tests for the plans table in the tracking store (S3, DR4) — the contract the store implements.

The table is born in SQLite like the message bus: no legacy source, no ``Family`` entry,
``SCHEMA_VERSION`` 2 -> 3, ``UPGRADE_HOOKS[2] = _upgrade_v2_to_v3`` lands ``_PLANS_DDL`` on
a stamped-2 DB, and a fresh DB replays the hooks before stamping. Accessors live beside
``tasks_all``/``task_upsert`` so no other module touches the SQL:

    Store.plan_row(task_id) -> dict | None        # payload verbatim, revision, timestamps
    Store.plan_upsert(task_id, payload, expected_revision=None) -> int
        # INSERT -> revision 0 (no expected_revision needed); UPDATE ... WHERE
        # task_id=? AND revision=? -> revision+1; 0 rows updated -> PlanConflict
        # (current_revision); created_at preserved; revision/updated_at server-stamped.

Test map:
  1. lifecycle ................. test_schema_version_is_three_and_the_hooks_chain,
                                 test_fresh_tracking_db_lands_plans_and_stamps_three,
                                 test_stamped_two_db_runs_the_plans_hook_and_re_stamps,
                                 test_newer_schema_stamp_fails_closed_naming_den_refresh
  2. CAS matrix ................ test_plan_row_returns_none_for_an_absent_plan,
                                 test_insert_seeds_revision_zero_and_returns_it,
                                 test_cas_update_increments_revision_and_preserves_created_at,
                                 test_stale_expected_revision_conflicts_carrying_the_current_revision,
                                 test_missing_expected_revision_on_a_present_row_conflicts,
                                 test_two_readers_from_one_revision_leave_exactly_one_winner,
                                 test_held_write_lock_makes_the_cas_fail_cleanly
  3. payload + CHECK guards .... test_payload_is_returned_verbatim,
                                 test_json_valid_check_rejects_a_garbage_payload_on_insert_and_update,
                                 test_revision_check_rejects_a_negative_direct_insert
  4. vendoring + root routing .. test_vendored_copies_report_is_empty,
                                 test_every_test_routes_the_store_under_tmp_path,
                                 test_the_default_root_tripwire_is_armed

Mutation witnesses: remove ``CHECK (json_valid(payload))`` from the imported module's
``_PLANS_DDL`` and this file's garbage-payload test is the only failure (scoped run);
disarm the ``_default_badger_root`` tripwire and the routing test proves the leak it refuses.
"""
from __future__ import annotations

import sqlite3

import pytest

import badger_store
from conftest import ROOT

TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"


@pytest.fixture(autouse=True)
def _default_root_is_a_tripwire(monkeypatch):
    """Every test here routes the store at tmp_path; resolving through the module's default
    root would reach the developer's real checkout, so it trips at the call site instead of
    writing. A test passing is the assertion that it never took that path."""
    def tripwire():
        raise AssertionError(
            "test path reached _default_badger_root(); set AI_BADGER_TRACKING_ROOT instead")

    monkeypatch.setattr(badger_store, "_default_badger_root", tripwire)
    yield


def _open_store(tmp_path, monkeypatch) -> "badger_store.Store":
    """Open the tracking store against this test's tmp_path and pin the routing."""
    root = tmp_path / "task-tracking"
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(root))
    store = badger_store.open_tracking()
    assert badger_store.tracking_db_path() == root / "tracking.db", \
        "the env root must win over the default root"
    return store


def _schema_version(conn) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert row is not None, "meta must carry a schema_version row"
    return row[0]


def _plans_columns(conn) -> dict:
    """pragma table_info rows keyed by column name: (cid, name, type, notnull, dflt, pk)."""
    return {row[1]: row for row in conn.execute("PRAGMA table_info(plans)")}


def _tables(conn) -> set:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ---------------------------------------------------------------------------
# 1. lifecycle: version contract, fresh DB, stamped-2 upgrade, newer stamp
# ---------------------------------------------------------------------------


def test_schema_version_is_three_and_the_hooks_chain():
    """The store's public version contract for S3: 2 -> 3 with both upgrade hooks registered."""
    assert badger_store.SCHEMA_VERSION == 3
    assert sorted(badger_store.UPGRADE_HOOKS) == [1, 2]


def test_fresh_tracking_db_lands_plans_and_stamps_three(tmp_path, monkeypatch):
    """A fresh DB replays the hooks before stamping: the pinned DDL is present at stamp 3."""
    store = _open_store(tmp_path, monkeypatch)
    try:
        assert _schema_version(store.conn) == "3"
        columns = _plans_columns(store.conn)
        assert set(columns) == {"task_id", "revision", "payload", "created_at", "updated_at"}
        assert columns["task_id"][2] == "TEXT" and columns["task_id"][5] == 1
        assert columns["revision"][2] == "INTEGER" and columns["revision"][3] == 1
        for name in ("payload", "created_at", "updated_at"):
            assert columns[name][2] == "TEXT" and columns[name][3] == 1
        ddl = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'plans'"
        ).fetchone()[0]
        assert "json_valid(payload)" in ddl
        assert "revision >= 0" in ddl
        index = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'idx_plans_updated_at'"
        ).fetchone()
        assert index is not None and "plans(updated_at)" in index[0]
    finally:
        store.close()


def test_stamped_two_db_runs_the_plans_hook_and_re_stamps(tmp_path, monkeypatch):
    """A pre-S3 DB (all v1/v2 DDL, no plans, stamped 2) gets the table from the hook."""
    store = _open_store(tmp_path, monkeypatch)
    try:
        store.conn.execute("DROP TABLE plans")  # the stamped-2 shape: no plans yet
        store.conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        store.conn.commit()
    finally:
        store.close()

    calls = []
    real_hook = badger_store.UPGRADE_HOOKS[2]

    def recording_hook(conn):
        calls.append(1)
        real_hook(conn)

    monkeypatch.setitem(badger_store.UPGRADE_HOOKS, 2, recording_hook)
    reopened = badger_store.open_tracking()
    try:
        assert calls == [1], "the 2 -> 3 hook must run for a stamped-2 DB"
        assert _schema_version(reopened.conn) == "3"
        assert _plans_columns(reopened.conn), "the hook must land the plans table"
    finally:
        reopened.close()


def test_open_user_never_lands_plans_and_stays_at_the_user_version(tmp_path, monkeypatch):
    """R-D root cause: the plans upgrade is tracking-only. The machine-wide user DB keeps
    its v2-era stamp and gains no plans table, so pre-0.179 copies still open it."""
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    store = badger_store.open_user()
    try:
        assert _schema_version(store.conn) == str(badger_store.NON_TRACKING_SCHEMA_VERSION)
        assert _schema_version(store.conn) == "2"
        assert "plans" not in _tables(store.conn)
    finally:
        store.close()


def test_open_audit_never_lands_plans(tmp_path):
    """The audit sink is the second non-tracking DB; it must stay plan-free too."""
    store = badger_store.open_audit(tmp_path / "debug")
    try:
        assert _schema_version(store.conn) == str(badger_store.NON_TRACKING_SCHEMA_VERSION)
        assert "plans" not in _tables(store.conn)
    finally:
        store.close()


def test_a_user_db_leaked_to_stamp_three_still_opens(tmp_path, monkeypatch):
    """Pre-fix code re-stamped the user DB 3; new code tolerates that state instead of
    failing closed into a recovery dead end, and still never lands plans there."""
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    first = badger_store.open_user()
    first.conn.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
    first.conn.commit()
    first.close()

    reopened = badger_store.open_user()
    try:
        assert _schema_version(reopened.conn) == "3"
        assert "plans" not in _tables(reopened.conn)
    finally:
        reopened.close()


def test_newer_schema_stamp_fails_closed_naming_den_refresh(tmp_path, monkeypatch):
    """A DB newer than known is still never written in an old shape: open fails closed (D27)."""
    store = _open_store(tmp_path, monkeypatch)
    try:
        store.conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
        store.conn.commit()
    finally:
        store.close()

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        badger_store.open_tracking()
    message = str(excinfo.value)
    assert "den-refresh" in message
    assert str(badger_store.tracking_db_path()) in message


# ---------------------------------------------------------------------------
# 2. CAS matrix
# ---------------------------------------------------------------------------


def test_plan_row_returns_none_for_an_absent_plan(tmp_path, monkeypatch):
    store = _open_store(tmp_path, monkeypatch)
    try:
        assert store.plan_row("never-written") is None
    finally:
        store.close()


def test_insert_seeds_revision_zero_and_returns_it(tmp_path, monkeypatch):
    store = _open_store(tmp_path, monkeypatch)
    payload = '{"task_id": "demo", "revision": 0}'
    try:
        assert store.plan_upsert("demo", payload) == 0
        row = store.plan_row("demo")
        assert row["task_id"] == "demo"
        assert row["revision"] == 0
        assert row["payload"] == payload
        assert row["created_at"] == row["updated_at"] != ""
        assert row["created_at"].endswith("+00:00")
    finally:
        store.close()


def test_cas_update_increments_revision_and_preserves_created_at(tmp_path, monkeypatch):
    store = _open_store(tmp_path, monkeypatch)
    try:
        store.plan_upsert("demo", '{"v": 1}')
        created = store.plan_row("demo")["created_at"]
        assert store.plan_upsert("demo", '{"v": 2}', expected_revision=0) == 1
        row = store.plan_row("demo")
        assert row["revision"] == 1
        assert row["payload"] == '{"v": 2}'
        assert row["created_at"] == created, "created_at belongs to the row, not the write"
        assert store.plan_upsert("demo", '{"v": 3}', expected_revision=1) == 2
    finally:
        store.close()


def test_stale_expected_revision_conflicts_carrying_the_current_revision(tmp_path, monkeypatch):
    store = _open_store(tmp_path, monkeypatch)
    try:
        store.plan_upsert("demo", '{"v": 1}')
        store.plan_upsert("demo", '{"v": 2}', expected_revision=0)
        before = store.plan_row("demo")
        with pytest.raises(badger_store.PlanConflict) as excinfo:
            store.plan_upsert("demo", '{"v": 3}', expected_revision=0)
        assert excinfo.value.current_revision == 1
        assert "demo" in str(excinfo.value)
        assert store.plan_row("demo") == before, "a refused CAS must not touch the row"
    finally:
        store.close()


def test_missing_expected_revision_on_a_present_row_conflicts(tmp_path, monkeypatch):
    """None never matches ``revision = ?``: an update without a read revision is exactly the
    stale-writer case CAS exists to refuse, and the refusal says what to re-read."""
    store = _open_store(tmp_path, monkeypatch)
    try:
        store.plan_upsert("demo", '{"v": 1}')
        with pytest.raises(badger_store.PlanConflict) as excinfo:
            store.plan_upsert("demo", '{"v": 2}')
        assert excinfo.value.current_revision == 0
        assert store.plan_row("demo")["payload"] == '{"v": 1}'
    finally:
        store.close()


def test_two_readers_from_one_revision_leave_exactly_one_winner(tmp_path, monkeypatch):
    """The scheduled CAS: both writers read revision 0 before either writes, then write in a
    fixed order — the loser's CAS is refused against the winner's stamp, no timing involved."""
    store_a = _open_store(tmp_path, monkeypatch)
    store_b = badger_store.open_tracking()
    try:
        store_a.plan_upsert("demo", '{"writer": "seed"}')
        seen_by_a = store_a.plan_row("demo")["revision"]
        seen_by_b = store_b.plan_row("demo")["revision"]
        assert seen_by_a == seen_by_b == 0

        assert store_a.plan_upsert("demo", '{"writer": "a"}', expected_revision=seen_by_a) == 1
        with pytest.raises(badger_store.PlanConflict) as excinfo:
            store_b.plan_upsert("demo", '{"writer": "b"}', expected_revision=seen_by_b)
        assert excinfo.value.current_revision == 1
        assert store_a.plan_row("demo")["payload"] == '{"writer": "a"}'
    finally:
        store_a.close()
        store_b.close()


def test_held_write_lock_makes_the_cas_fail_cleanly(tmp_path, monkeypatch):
    """The scheduled interleave, never the race: a second connection holds BEGIN IMMEDIATE
    while the store attempts its CAS — the write fails with a clean ``database is locked``
    and the row is untouched; releasing the lock lets the same CAS land."""
    store = _open_store(tmp_path, monkeypatch)
    blocker = None
    try:
        store.plan_upsert("demo", '{"v": 1}')
        store.conn.execute("PRAGMA busy_timeout = 50")  # the lock is held, not raced
        blocker = sqlite3.connect(str(badger_store.tracking_db_path()), timeout=0.05,
                                  isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute("UPDATE plans SET revision = revision + 1 WHERE task_id = 'demo'")
        before = store.plan_row("demo")
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            store.plan_upsert("demo", '{"v": 2}', expected_revision=0)
        assert "database is locked" in str(excinfo.value).lower()
        assert store.plan_row("demo") == before, "a refused write must not touch the row"
        blocker.rollback()
        blocker.close()
        blocker = None
        assert store.plan_upsert("demo", '{"v": 2}', expected_revision=0) == 1
    finally:
        if blocker is not None:
            blocker.close()
        store.close()


# ---------------------------------------------------------------------------
# 3. payload bytes + the DDL's own guards
# ---------------------------------------------------------------------------


def test_payload_is_returned_verbatim(tmp_path, monkeypatch):
    """No decode/re-encode in the store: the exact UTF-8 the caller wrote comes back,
    unicode, spacing and all — document validation belongs to the model layer."""
    payload = '{\n  "note": "caf\u00e9 \u2603",  "spaced":  [1,  2]\n}\n'
    store = _open_store(tmp_path, monkeypatch)
    try:
        store.plan_upsert("verbatim", payload)
        row = store.plan_row("verbatim")
        assert row["payload"] == payload
        assert row["payload"].encode("utf-8") == payload.encode("utf-8")
    finally:
        store.close()


def test_json_valid_check_rejects_a_garbage_payload_on_insert_and_update(tmp_path, monkeypatch):
    """The row's own guard is the last line of defence: garbage must never land through
    either path, and a refused update must leave the old payload in place."""
    store = _open_store(tmp_path, monkeypatch)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.plan_upsert("garbage", "not json at all")
        assert store.plan_row("garbage") is None

        store.plan_upsert("good", '{"ok": true}')
        with pytest.raises(sqlite3.IntegrityError):
            store.plan_upsert("good", "still not json", expected_revision=0)
        assert store.plan_row("good")["payload"] == '{"ok": true}'
    finally:
        store.close()


def test_revision_check_rejects_a_negative_direct_insert(tmp_path, monkeypatch):
    """The second CHECK in the pinned DDL: revision is a non-negative CAS token, so even a
    direct INSERT that bypasses plan_upsert cannot seed a negative revision."""
    store = _open_store(tmp_path, monkeypatch)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO plans(task_id, revision, payload, created_at, updated_at)"
                " VALUES ('negative', -1, '{}', '2026-01-01T00:00:00+00:00',"
                " '2026-01-01T00:00:00+00:00')")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 4. vendoring + root routing
# ---------------------------------------------------------------------------


def test_vendored_copies_report_is_empty():
    """Canonical and every globbed copy agree byte for byte (D16). Explicit ROOT so the
    assertion never resolves the default root the tripwire refuses."""
    assert badger_store.vendored_copies_report(ROOT) == []


def test_every_test_routes_the_store_under_tmp_path(tmp_path, monkeypatch):
    store = _open_store(tmp_path, monkeypatch)
    try:
        assert badger_store.tracking_db_path() == tmp_path / "task-tracking" / "tracking.db"
        assert str(tmp_path) in str(store.db_path)
    finally:
        store.close()


def test_the_default_root_tripwire_is_armed(tmp_path, monkeypatch):
    """AC (5)'s own break-it witness: unset the env and resolving the path must reach the
    tripwire — proving the guard can fail, the property every other test here leans on."""
    monkeypatch.delenv(TRACKING_ROOT_ENV, raising=False)
    with pytest.raises(AssertionError, match="_default_badger_root"):
        badger_store.tracking_db_path()
