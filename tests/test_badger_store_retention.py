"""P2.3 retention gate (D36) — the prune's edge cases beyond the P1.1b seam tests.

``Store.prune_expired`` landed with P1.1b (throttle + BEGIN IMMEDIATE + fail-open, D30);
this file pins the behaviours the P2.3 gate demands of it before the on-write callers go
live: the empty-table no-op, garbage ``ts`` values that must neither crash nor live
forever, clock-skewed future rows that must survive, concurrent prunes that serialize,
and time-based (never count-based) retention. The hook_audit on-write caller is pinned
in ``test_debug_log.py``; the ``prune --status`` verb in ``test_badger_store_cli.py``.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import badger_store


def _user_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))


def _ts(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _rows(store, table: str) -> list[str]:
    return [row[0] for row in store.conn.execute(f"SELECT ts FROM {table} ORDER BY id")]


def _seed(store, table: str, ts: str, marker: str) -> str:
    payload = json.dumps({"marker": marker})
    store.conn.execute(f"INSERT INTO {table}(ts, payload) VALUES (?, ?)", (ts, payload))
    store.conn.commit()
    return ts


def test_log_tables_declares_only_tables_the_ddl_can_retain(tmp_path, monkeypatch):
    """LOG_TABLES is the retention scope declared by hand beside the DDL it mirrors —
    an unasserted twin drifts silently (join-review finding): a typo'd name or a table
    without a NOT NULL ts column and a ts index would promise retention the schema cannot
    deliver. Every declared table must exist in the schema with both properties (D17c)."""
    _user_env(tmp_path, monkeypatch)
    assert badger_store.LOG_TABLES, "the scope must name at least one DB"
    conn = sqlite3.connect(str(tmp_path / "ddl-twin.db"))
    try:
        badger_store._create_schema(conn)
        # The bus tables (P1) arrive through UPGRADE_HOOKS[1], not the v1 base DDL (D1) —
        # replay the hooks exactly as a real open does before checking the declared twins.
        for version in range(1, badger_store.SCHEMA_VERSION):
            hook = badger_store.UPGRADE_HOOKS.get(version)
            if hook is not None:
                hook(conn)
        for db_kind, tables in badger_store.LOG_TABLES.items():
            assert db_kind in ("user", "audit"), f"unknown DB kind: {db_kind}"
            for table in tables:
                columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
                assert columns, f"LOG_TABLES names {table!r}: no such table in the DDL"
                ts = [row for row in columns if row[1] == "ts"]
                assert ts and ts[0][3] == 1, (
                    f"{table}: retention needs a NOT NULL ts column")
                indexed = any(
                    col[2] == "ts"
                    for idx in conn.execute(f"PRAGMA index_list({table})").fetchall()
                    for col in conn.execute(f"PRAGMA index_info({idx[1]})").fetchall())
                assert indexed, f"{table}: the cutoff must be served by a ts index (D17c)"
    finally:
        conn.close()


def test_prune_sweeps_rows_with_unparseable_ts(tmp_path, monkeypatch):
    """A ts that never parses (empty, words, an ISO-looking month 13) can never satisfy
    any future cutoff, so string comparison alone leaves it immortal — the prune must
    sweep such rows rather than let them accumulate behind the retention promise (D36)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed(store, "awm_decisions", _ts(90), "ancient")
        fresh = _seed(store, "awm_decisions", _ts(1), "fresh")
        for garbage in ("", "banana", "2026-13-45T99:99:99+00:00"):
            _seed(store, "awm_decisions", garbage, f"garbage:{garbage}")

        pruned = store.prune_expired("awm_decisions", max_age_days=60)

        assert _rows(store, "awm_decisions") == [fresh], (
            "only the fresh, parseable row survives; garbage and expired rows are gone"
        )
        assert pruned == 4
    finally:
        store.close()


def test_prune_on_an_empty_table_is_a_noop_that_stamps(tmp_path, monkeypatch):
    """Pruning a table with no rows (never written, or already swept) neither crashes nor
    skips the stamp — a missing stamp would re-arm the throttle check every open (D30/D36)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        assert store.prune_expired("searches", max_age_days=60) == 0
        assert store.meta_get("pruned_at.searches") is not None
        assert store.prune_expired("searches", max_age_days=60) == 0
    finally:
        store.close()


def test_prune_keeps_parseable_rows_dated_in_the_future(tmp_path, monkeypatch):
    """Clock skew writes future-dated rows; the cutoff is a lower bound only (D36) — a
    future row must survive and age out on its own schedule, never crash the prune."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        _seed(store, "awm_decisions", _ts(90), "ancient")
        future = _seed(store, "awm_decisions",
                       (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), "skewed")
        far_future = _seed(store, "awm_decisions", "9999-12-31T00:00:00+00:00", "far")

        assert store.prune_expired("awm_decisions", max_age_days=60) == 1
        assert set(_rows(store, "awm_decisions")) == {future, far_future}
    finally:
        store.close()


def test_concurrent_prunes_serialize_without_error(tmp_path, monkeypatch):
    """Two writers racing the throttle share one BEGIN IMMEDIATE (D30): both return, no
    exception, every expired row gone, exactly one pruned_at stamp — whoever loses the
    race deletes nothing and leaves the stamp the winner wrote."""
    _user_env(tmp_path, monkeypatch)
    seed_store = badger_store.open_user()
    try:
        for i in range(20):
            _seed(seed_store, "awm_decisions", _ts(90), f"expired-{i}")
        for i in range(5):
            _seed(seed_store, "awm_decisions", _ts(1), f"fresh-{i}")
    finally:
        seed_store.close()

    barrier = threading.Barrier(2)
    results: list[int] = []
    failures: list[Exception] = []

    def _prune() -> None:
        store = badger_store.open_user()
        try:
            barrier.wait(timeout=10)
            results.append(store.prune_expired("awm_decisions", max_age_days=60))
        except Exception as exc:  # pylint: disable=broad-except
            failures.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=_prune) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == [], f"a concurrent prune raised: {failures!r}"
    assert sorted(results) == [0, 20]
    store = badger_store.open_user()
    try:
        assert len(_rows(store, "awm_decisions")) == 5
        stamps = store.conn.execute(
            "SELECT COUNT(*) FROM meta WHERE key = 'pruned_at.awm_decisions'").fetchone()[0]
        assert stamps == 1
    finally:
        store.close()


def test_sixty_day_retention_is_time_based_not_count_based(tmp_path, monkeypatch):
    """The 5000-line trim is retired: volume alone neither keeps old rows nor evicts fresh
    ones — 120 stale rows die and 120 fresh rows survive in one prune (D36)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        for i in range(120):
            _seed(store, "awm_decisions", _ts(90 + i / 1000), f"stale-{i}")
            _seed(store, "awm_decisions", _ts(i / 1000), f"fresh-{i}")

        assert store.prune_expired("awm_decisions", max_age_days=60) == 120
        survivors = [json.loads(row[0])["marker"]
                     for row in store.conn.execute("SELECT payload FROM awm_decisions")]
        assert len(survivors) == 120 and all(m.startswith("fresh-") for m in survivors)
    finally:
        store.close()


def test_a_failing_prune_fails_open_as_zero(tmp_path, monkeypatch):
    """A broken store (locked, corrupt, missing table) returns 0 instead of raising —
    maintenance must never be the thing that breaks a hook (D31/D36)."""
    _user_env(tmp_path, monkeypatch)
    store = badger_store.open_user()
    try:
        seeded = _seed(store, "awm_decisions", _ts(90), "ancient")
        store.conn.execute("DROP TABLE meta")
        store.conn.commit()

        assert store.prune_expired("awm_decisions", max_age_days=60) == 0
        assert _rows(store, "awm_decisions") == [seeded]  # a failed prune deletes nothing
    finally:
        store.close()
