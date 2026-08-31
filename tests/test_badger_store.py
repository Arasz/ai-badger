"""Red tests for engine/badger_store.py (P0.2a) — this file is the contract P0.2b implements.

Intended API (module ``badger_store``, stdlib-only, imports nothing from the engine):

    SCHEMA_VERSION: int                                        # in the stub (= 1)
    UPGRADE_HOOKS: dict[int, Callable[[sqlite3.Connection], None]]
    tracking_db_path() -> Path                                 # in the stub
    user_db_path() -> Path                                     # in the stub
    audit_db_path() -> Path                                    # in the stub
    open_tracking() -> Store
    open_user() -> Store

    class Store:
        conn: sqlite3.Connection                               # raw access: pragmas, meta, DML
        def kv_get(self, table: str, key: str, default=None)
        def kv_all(self, table: str) -> dict                   # per-key LWW dual-read (legacy + DB)
        def kv_set(self, table: str, key: str, value) -> None  # first write lazy-migrates the family
        def close(self) -> None

Roots resolve from the environment at CALL time, never at import (D9):
``AI_BADGER_TRACKING_ROOT`` replaces ``<project>/.ai-badger/task-tracking/``,
``AI_BADGER_USER_ROOT`` replaces ``~/.ai-badger/``, and ``AI_BADGER_DEBUG_DIR``
moves the audit sink (its own DB file, D21). Defaults: the nearest existing
``.ai-badger`` directory above the module file (the tracker_lib/hook convention),
``~/.ai-badger/ai-badger.db``, and ``~/.ai-badger/debug/`` respectively.

Test map (plan aib-sqlite-storage-migration-phased-rollout rev 2 · ADR-0024):
  1. D9 call-time env path resolution ............ test_env_roots_set_after_import_*,
                                                   test_default_paths_resolve_under_real_roots_*
  2. open pragmas WAL / busy_timeout / NORMAL .... test_open_sets_wal_busy_timeout_and_synchronous_pragmas
  3. meta(schema_version) + fail-closed (D27) .... test_created_store_stamps_schema_version_in_meta,
                                                   test_older_schema_version_runs_upgrade_hook_and_re_stamps,
                                                   test_newer_schema_version_fails_closed_naming_den_refresh
  4. lazy migration COMMIT-then-rename (D6) ...... test_first_write_imports_legacy_rows_then_renames_legacy_file,
                                                   test_crash_between_commit_and_rename_does_not_double_import
  5. per-key LWW dual-read, resurrection (D5) .... test_dual_read_merges_legacy_rows_before_first_write,
                                                   test_dual_read_prefers_db_row_when_both_sources_non_empty,
                                                   test_resurrected_legacy_map_file_fails_closed
  6. perms 0600/0700 incl. sidecars (D17) ........ test_db_and_wal_shm_sidecars_are_0600_after_write,
                                                   test_existing_user_root_is_not_chmodded,
                                                   test_store_created_root_gets_0700
  7. fail-open reads (D31) ....................... test_read_errors_return_defaults_instead_of_raising
  8. partial unique index on tasks (D14) ......... test_tasks_partial_unique_index_exists_*,
                                                   test_second_active_task_for_session_raises_integrity_error,
                                                   test_reactivating_finished_task_while_active_exists_raises,
                                                   test_finished_task_rows_do_not_block
  9. migration takes the legacy .write.lock ...... test_migration_blocks_while_legacy_write_lock_is_held

The map-like family used throughout is ``marker_state`` (legacy
``<.ai-badger>/prompt-markers/marker-state.json``, a top-level dict; its legacy
dir is a sibling of the tracking root). Crash state (table populated, legacy
file still present) is constructed by migrating once, renaming the
``*.migrated.json`` file back, and reopening — the exact on-disk state a crash
between COMMIT and rename produces.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

import badger_store
from conftest import REAL_HOME, ROOT


def _make_tracking_layout(tmp_path: Path) -> Path:
    """A realistic .ai-badger layout: task-tracking root + prompt-markers sibling."""
    badger_root = tmp_path / ".ai-badger"
    (badger_root / "task-tracking").mkdir(parents=True)
    return badger_root


def _seed_marker_state(badger_root: Path, state: dict) -> Path:
    state_dir = badger_root / "prompt-markers"
    state_dir.mkdir(exist_ok=True)
    state_file = state_dir / "marker-state.json"
    state_file.write_text(json.dumps(state, indent=2) + "\n")
    return state_file


# ---------------------------------------------------------------------------
# 1. D9 — call-time env path resolution
# ---------------------------------------------------------------------------


def test_env_roots_set_after_import_move_db_paths(tmp_path, monkeypatch):
    """Env set *after* the module was imported must move every resolved DB path (D9)."""
    tracking = tmp_path / "tracking"
    user = tmp_path / "user"
    debug = tmp_path / "debug"
    for directory in (tracking, user, debug):
        directory.mkdir()

    before_tracking = badger_store.tracking_db_path()
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(tracking))
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(user))
    monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(debug))

    assert badger_store.tracking_db_path() != before_tracking
    assert badger_store.tracking_db_path() == tracking / "tracking.db"
    assert badger_store.user_db_path() == user / "ai-badger.db"
    audit = badger_store.audit_db_path()
    assert audit.parent == debug
    assert audit.suffix == ".db"  # own DB file — the sink moves whole (D21)
    assert audit != badger_store.user_db_path()


def test_default_paths_resolve_under_real_roots_when_env_unset(monkeypatch):
    """With no env override: tracking under this checkout's .ai-badger, user under ~, audit in the debug sink."""
    monkeypatch.delenv("AI_BADGER_TRACKING_ROOT", raising=False)
    monkeypatch.delenv("AI_BADGER_USER_ROOT", raising=False)
    monkeypatch.delenv("AI_BADGER_DEBUG_DIR", raising=False)

    assert badger_store.tracking_db_path() == (
        ROOT / ".ai-badger" / "task-tracking" / "tracking.db"
    )
    assert badger_store.user_db_path() == REAL_HOME / ".ai-badger" / "ai-badger.db"
    audit = badger_store.audit_db_path()
    assert audit.parent == REAL_HOME / ".ai-badger" / "debug"
    assert audit.suffix == ".db"


# ---------------------------------------------------------------------------
# 2. Open pragmas  ·  3. meta(schema_version) + fail-closed (D27)
# ---------------------------------------------------------------------------


def _open_tracking(tmp_path, monkeypatch):
    badger_root = _make_tracking_layout(tmp_path)
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(badger_root / "task-tracking"))
    return badger_root, badger_store.open_tracking()


def _schema_version(conn) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert row is not None, "meta must carry a schema_version row"
    return row[0]


def _set_schema_version(conn, value: str) -> None:
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (value,))
    conn.commit()


def test_open_sets_wal_busy_timeout_and_synchronous_pragmas(tmp_path, monkeypatch):
    """Every open sets journal_mode=WAL, busy_timeout=5000, synchronous=NORMAL (ADR-0024 #4)."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    try:
        mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = store.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = store.conn.execute("PRAGMA synchronous").fetchone()[0]
        assert mode == "wal"
        assert timeout == 5000
        assert synchronous == 1  # NORMAL
    finally:
        store.close()


def test_created_store_stamps_schema_version_in_meta(tmp_path, monkeypatch):
    """A freshly created DB records SCHEMA_VERSION in meta(schema_version)."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    try:
        assert int(_schema_version(store.conn)) == badger_store.SCHEMA_VERSION
    finally:
        store.close()


def test_older_schema_version_runs_upgrade_hook_and_re_stamps(tmp_path, monkeypatch):
    """A DB stamped older than known runs the registered on-open upgrade hook, then re-stamps."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    _set_schema_version(store.conn, "0")  # simulate a store written by an older schema
    store.close()

    calls = []
    monkeypatch.setitem(badger_store.UPGRADE_HOOKS, 0, calls.append)

    reopened = badger_store.open_tracking()
    try:
        assert calls, "the 0 -> current upgrade hook must run on open"
        assert int(_schema_version(reopened.conn)) == badger_store.SCHEMA_VERSION
    finally:
        reopened.close()


def test_newer_schema_version_fails_closed_naming_den_refresh(tmp_path, monkeypatch):
    """A DB newer than known is never written in an old shape: open fails closed (D27)."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    _set_schema_version(store.conn, str(badger_store.SCHEMA_VERSION + 1))
    store.close()

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        badger_store.open_tracking()
    assert "den-refresh" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Lazy migration COMMIT-then-rename (D6)  ·  5. dual-read + resurrection (D5)
# ---------------------------------------------------------------------------


def _tracking_env(tmp_path, monkeypatch, badger_root):
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(badger_root / "task-tracking"))


def test_first_write_imports_legacy_rows_then_renames_legacy_file(tmp_path, monkeypatch):
    """Legacy JSON + empty table: the first write imports rows, then renames to *.migrated.json (D6)."""
    badger_root = _make_tracking_layout(tmp_path)
    legacy = _seed_marker_state(badger_root, {"alpha": "legacy-alpha", "beta": {"n": 1}})
    _tracking_env(tmp_path, monkeypatch, badger_root)

    store = badger_store.open_tracking()
    try:
        store.kv_set("marker_state", "gamma", "db-gamma")

        count = store.conn.execute("SELECT COUNT(*) FROM marker_state").fetchone()[0]
        assert count == 3  # two imported + one written
        assert not legacy.exists()
        migrated = legacy.with_name("marker-state.migrated.json")
        assert migrated.exists()
        assert json.loads(migrated.read_text()) == {"alpha": "legacy-alpha", "beta": {"n": 1}}
        assert store.kv_get("marker_state", "alpha") == "legacy-alpha"  # import committed before rename
    finally:
        store.close()


def test_crash_between_commit_and_rename_does_not_double_import(tmp_path, monkeypatch):
    """Crash after COMMIT, before rename: next open reuses the imported rows — no dupes, idempotent."""
    badger_root = _make_tracking_layout(tmp_path)
    legacy = _seed_marker_state(badger_root, {"alpha": "legacy-alpha", "beta": "legacy-beta"})
    _tracking_env(tmp_path, monkeypatch, badger_root)
    time.sleep(0.05)  # legacy mtime must strictly predate the migration stamp

    store = badger_store.open_tracking()
    store.kv_set("marker_state", "gamma", "db-gamma")  # migrates and renames
    store.close()

    # Restore the exact on-disk state a crash between COMMIT and rename leaves behind.
    legacy.with_name("marker-state.migrated.json").rename(legacy)

    reopened = badger_store.open_tracking()
    assert reopened.kv_all("marker_state") == {
        "alpha": "legacy-alpha",
        "beta": "legacy-beta",
        "gamma": "db-gamma",
    }
    count = reopened.conn.execute("SELECT COUNT(*) FROM marker_state").fetchone()[0]
    assert count == 3  # duplicate-free: a re-import must not add rows
    reopened.kv_set("marker_state", "delta", "db-delta")  # writing proceeds in crash state
    reopened.close()

    final = badger_store.open_tracking()
    final_count = final.conn.execute("SELECT COUNT(*) FROM marker_state").fetchone()[0]
    assert final_count == 4  # idempotent across reopen cycles: one row per key
    assert final.kv_get("marker_state", "alpha") == "legacy-alpha"
    final.close()


def test_log_append_writes_rows_and_imports_jsonl_legacy(tmp_path, monkeypatch):
    """log_append adds one (ts, payload) row; the first write imports a legacy JSONL (D6, P1.2b).

    The JSONL has no natural key, so the import dedupes on exact (ts, payload) content —
    a crash between COMMIT and rename must not double the rows on re-import.
    """
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    legacy = tmp_path / "awm" / "decisions.jsonl"
    legacy.parent.mkdir()
    lines = [
        {"ts": "2026-01-01T00:00:00+00:00", "type": "decision", "detail": "one"},
        {"ts": "2026-01-02T00:00:00+00:00", "type": "auto_approve", "tool_name": "Bash",
         "session_id": "s1", "detail": "{}"},
    ]
    legacy.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    family = badger_store.Family(
        table="awm_decisions", db="user", legacy_path=lambda: legacy, legacy_kind="jsonl",
    )

    store = badger_store.open_user(families={"awm_decisions": family})
    try:
        store.log_append("awm_decisions", "2026-01-03T00:00:00+00:00",
                         {"ts": "2026-01-03T00:00:00+00:00", "type": "decision",
                          "detail": "three"})

        assert not legacy.exists()
        assert legacy.with_name("decisions.migrated.jsonl").exists()
        rows = store.conn.execute(
            "SELECT ts, payload FROM awm_decisions ORDER BY id").fetchall()
        assert [row[0] for row in rows] == [
            "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00",
            "2026-01-03T00:00:00+00:00",
        ]
        assert json.loads(rows[1][1])["tool_name"] == "Bash"  # fields preserved verbatim
    finally:
        store.close()

    # Crash state: COMMIT landed, rename did not. Re-import adds nothing (D6).
    legacy.with_name("decisions.migrated.jsonl").rename(legacy)
    reopened = badger_store.open_user(families={"awm_decisions": family})
    try:
        expected = reopened._import_legacy(family, legacy)  # pylint: disable=protected-access
        assert len(expected) == 2
        count = reopened.conn.execute("SELECT COUNT(*) FROM awm_decisions").fetchone()[0]
        assert count == 3  # duplicate-free: the content key matched the existing rows
    finally:
        reopened.close()


def test_dual_read_merges_legacy_rows_before_first_write(tmp_path, monkeypatch):
    """Empty DB + legacy present: reads surface legacy rows — never an empty fallback (D5a)."""
    badger_root = _make_tracking_layout(tmp_path)
    _seed_marker_state(badger_root, {"alpha": "legacy-alpha"})
    _tracking_env(tmp_path, monkeypatch, badger_root)

    store = badger_store.open_tracking()
    try:
        assert store.kv_all("marker_state") == {"alpha": "legacy-alpha"}
        assert store.kv_get("marker_state", "alpha") == "legacy-alpha"
        assert store.kv_get("marker_state", "missing", "fallback") == "fallback"
    finally:
        store.close()


def test_dual_read_prefers_db_row_when_both_sources_non_empty(tmp_path, monkeypatch):
    """Both sources hold the key: the DB row wins on read (per-key last-write-wins, D5a/D22)."""
    badger_root = _make_tracking_layout(tmp_path)
    legacy = _seed_marker_state(badger_root, {"alpha": "legacy-alpha", "beta": "legacy-beta"})
    _tracking_env(tmp_path, monkeypatch, badger_root)
    time.sleep(0.05)

    store = badger_store.open_tracking()
    store.kv_set("marker_state", "gamma", "db-gamma")  # migrate + rename
    store.close()
    legacy.with_name("marker-state.migrated.json").rename(legacy)  # crash state: both sources live

    reopened = badger_store.open_tracking()
    reopened.kv_set("marker_state", "alpha", "db-alpha")  # DB row now differs from the legacy row
    assert reopened.kv_get("marker_state", "alpha") == "db-alpha"  # DB wins when both are non-empty
    assert reopened.kv_get("marker_state", "beta") == "legacy-beta"  # legacy-only rows still merge
    reopened.close()


def test_resurrected_legacy_map_file_fails_closed(tmp_path, monkeypatch):
    """Legacy map file recreated after the rename (stale surface): fail closed, never diverge (D5c)."""
    badger_root = _make_tracking_layout(tmp_path)
    legacy = _seed_marker_state(badger_root, {"alpha": "legacy-alpha"})
    _tracking_env(tmp_path, monkeypatch, badger_root)

    store = badger_store.open_tracking()
    store.kv_set("marker_state", "gamma", "db-gamma")  # migrate + rename
    store.close()
    time.sleep(0.05)  # the resurrected file must strictly postdate the migration stamp

    legacy.write_text(json.dumps({"alpha": "stale-surface-write"}))

    with pytest.raises(sqlite3.OperationalError):
        badger_store.open_tracking()


# ---------------------------------------------------------------------------
# 6. Perms 0600/0700 incl. sidecars (D17)  ·  7. fail-open reads (D31)
# ---------------------------------------------------------------------------


def _sidecars(db: Path) -> tuple[Path, Path]:
    return (Path(str(db) + "-wal"), Path(str(db) + "-shm"))


def test_db_and_wal_shm_sidecars_are_0600_after_write(tmp_path, monkeypatch):
    """After a write the DB and both WAL sidecars are owner-only (D17, verified on sidecars)."""
    badger_root = _make_tracking_layout(tmp_path)
    _tracking_env(tmp_path, monkeypatch, badger_root)

    store = badger_store.open_tracking()
    try:
        store.kv_set("marker_state", "alpha", "v")
        db = badger_store.tracking_db_path()
        assert db.stat().st_mode & 0o777 == 0o600
        for sidecar in _sidecars(db):
            assert sidecar.exists(), f"{sidecar.name} must exist while the store is open (WAL)"
            assert sidecar.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()


def test_existing_user_root_is_not_chmodded(tmp_path, monkeypatch):
    """The shared ~/.ai-badger root keeps its own mode — the store never chmods it (D17)."""
    user_root = tmp_path / "user-root"
    user_root.mkdir()
    user_root.chmod(0o755)
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(user_root))

    store = badger_store.open_user()
    try:
        db = badger_store.user_db_path()
        assert db.stat().st_mode & 0o777 == 0o600
        for sidecar in _sidecars(db):
            assert sidecar.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()
    assert user_root.stat().st_mode & 0o777 == 0o755  # still the pre-existing mode


def test_store_created_root_gets_0700(tmp_path, monkeypatch):
    """A root directory the store itself creates is owner-only 0700 (D17)."""
    user_root = tmp_path / "created-root"  # deliberately absent
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(user_root))

    store = badger_store.open_user()
    try:
        assert user_root.is_dir()
        assert user_root.stat().st_mode & 0o777 == 0o700
    finally:
        store.close()


def test_read_errors_return_defaults_instead_of_raising(tmp_path, monkeypatch):
    """Store-level read failures fail open: defaults return, the caller never sees a raise (D31)."""
    badger_root = _make_tracking_layout(tmp_path)
    _tracking_env(tmp_path, monkeypatch, badger_root)

    store = badger_store.open_tracking()
    store.kv_set("marker_state", "alpha", "v")
    # Force a store error under the live connection: the table vanishes beneath it
    # (the recovery runbook's mid-state).
    outsider = sqlite3.connect(badger_store.tracking_db_path())
    outsider.execute("DROP TABLE marker_state")
    outsider.commit()
    outsider.close()

    assert store.kv_get("marker_state", "alpha", "fallback") == "fallback"
    assert store.kv_all("marker_state") == {}
    store.close()


# ---------------------------------------------------------------------------
# 8. Partial unique index on tasks(session_id) WHERE state <> 'FINISHED' (D14)
# ---------------------------------------------------------------------------


def _insert_task(store, session_id: str, state: str) -> None:
    store.conn.execute(
        "INSERT INTO tasks(session_id, state) VALUES (?, ?)", (session_id, state)
    )
    store.conn.commit()


def test_tasks_partial_unique_index_exists_on_session_id_where_not_finished(tmp_path, monkeypatch):
    """The DDL carries the partial unique index as defense in depth (D14)."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    try:
        rows = store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tasks'"
            " AND sql IS NOT NULL AND UPPER(sql) LIKE 'CREATE UNIQUE%'"
        ).fetchall()
        assert rows, "tasks must have a partial UNIQUE index"
        sql = " ".join(row[0] for row in rows)
        assert "session_id" in sql
        assert "FINISHED" in sql  # the partial predicate spares finished rows
    finally:
        store.close()


def test_second_active_task_for_session_raises_integrity_error(tmp_path, monkeypatch):
    """Two active tasks for one session cannot coexist at the schema level (D14)."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    try:
        _insert_task(store, "s1", "ACTIVE")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_task(store, "s1", "ACTIVE")
    finally:
        store.close()


def test_reactivating_finished_task_while_active_exists_raises(tmp_path, monkeypatch):
    """The partial index also bites on UPDATE: finished -> active collides with a live active row."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    try:
        _insert_task(store, "s1", "ACTIVE")
        _insert_task(store, "s1", "FINISHED")
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "UPDATE tasks SET state = 'ACTIVE' WHERE session_id = ? AND state = 'FINISHED'",
                ("s1",),
            )
            store.conn.commit()
    finally:
        store.close()


def test_finished_task_rows_do_not_block(tmp_path, monkeypatch):
    """The index is partial: FINISHED rows never collide, and a session without an active row can go active."""
    _, store = _open_tracking(tmp_path, monkeypatch)
    try:
        _insert_task(store, "s1", "FINISHED")
        _insert_task(store, "s1", "FINISHED")  # second FINISHED row: fine
        _insert_task(store, "s2", "FINISHED")
        store.conn.execute("UPDATE tasks SET state = 'ACTIVE' WHERE session_id = 's2'")
        store.conn.commit()  # no active row existed for s2: the update goes through
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 9. Migration takes the legacy .write.lock flock (D5b)
# ---------------------------------------------------------------------------


def test_migration_blocks_while_legacy_write_lock_is_held(tmp_path, monkeypatch):
    """Import excludes legacy writers: migration blocks on <legacy-dir>/.write.lock until it frees (D5b)."""
    badger_root = _make_tracking_layout(tmp_path)
    _seed_marker_state(badger_root, {"alpha": "legacy-alpha"})
    _tracking_env(tmp_path, monkeypatch, badger_root)

    lock_path = badger_root / "prompt-markers" / ".write.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # a legacy writer is mid-write

        done = threading.Event()
        worker_error: list[BaseException] = []

        def migrating_writer() -> None:
            try:
                store = badger_store.open_tracking()
                store.kv_set("marker_state", "gamma", "db-gamma")  # triggers the lazy import
                store.close()
                done.set()
            except BaseException as exc:  # pylint: disable=broad-exception-caught
                worker_error.append(exc)  # re-raised in the main thread below

        worker = threading.Thread(target=migrating_writer)
        worker.start()
        try:
            assert not done.wait(0.5), (
                "migration must block while the legacy .write.lock is held exclusively"
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)  # legacy writer finishes
        if not done.wait(5) and worker_error:
            raise worker_error[0]
        assert done.is_set(), "migration must proceed once the lock is released"
        worker.join(5)

        store = badger_store.open_tracking()
        try:
            assert store.kv_get("marker_state", "alpha") == "legacy-alpha"  # import landed
        finally:
            store.close()
    finally:
        os.close(lock_fd)
