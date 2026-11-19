"""Tests for the review_flows table in the tracking store: lands without a schema bump."""
from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys

import pytest

import badger_store
from conftest import ROOT

TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"
USER_ROOT_ENV = "AI_BADGER_USER_ROOT"


@pytest.fixture(autouse=True)
def _default_root_is_a_tripwire(monkeypatch):
    """Resolving the default root would reach the real checkout; trip instead of writing."""
    def tripwire():
        raise AssertionError(
            "test path reached _default_badger_root(); set AI_BADGER_TRACKING_ROOT instead")

    monkeypatch.setattr(badger_store, "_default_badger_root", tripwire)
    yield


@pytest.fixture(name="roots")
def _roots(tmp_path, monkeypatch):
    monkeypatch.setenv(TRACKING_ROOT_ENV, str(tmp_path / "task-tracking"))
    monkeypatch.setenv(USER_ROOT_ENV, str(tmp_path / "user"))
    return tmp_path


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _version(conn):
    return conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]


def test_existing_v3_db_without_the_table_gains_it_on_open(roots):
    store = badger_store.open_tracking()
    store.conn.execute("DROP TABLE review_flows")
    store.conn.commit()
    path = badger_store.tracking_db_path()
    store.close()
    raw = sqlite3.connect(path)
    assert "review_flows" not in _tables(raw) and _version(raw) == "3"
    raw.close()

    reopened = badger_store.open_tracking()
    try:
        assert "review_flows" in _tables(reopened.conn)
        assert _version(reopened.conn) == "3"
        index = reopened.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_review_flows_updated_at'"
        ).fetchone()
        assert index is not None and "review_flows(updated_at)" in index[0]
    finally:
        reopened.close()


# The last store release without review_flows; a fixed commit, so the test keeps
# meaning "an older copy" after this change reaches main.
PRE_CHANGE_COMMIT = "04b07924faad5967c94542c82a24d6092e5573a2"


def test_pre_change_store_copy_opens_a_db_that_has_the_table(roots, tmp_path):
    source = subprocess.run(
        ["git", "show", f"{PRE_CHANGE_COMMIT}:engine/badger_store.py"], cwd=ROOT,
        check=True, capture_output=True, text=True).stdout
    assert "review_flows" not in source, "PRE_CHANGE_COMMIT must be the pre-change store"
    old_path = tmp_path / "old_badger_store.py"
    old_path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("old_badger_store", old_path)
    old = importlib.util.module_from_spec(spec)
    sys.modules["old_badger_store"] = old
    try:
        spec.loader.exec_module(old)
        new = badger_store.open_tracking()
        new.flow_upsert("f1", '{"a": 1}')
        new.conn.commit()
        new.close()
        store = old.open_tracking()
        try:
            assert _version(store.conn) == "3"
            assert "review_flows" in _tables(store.conn)
        finally:
            store.close()
    finally:
        del sys.modules["old_badger_store"]


def test_insert_cas_update_and_stale_revision(roots):
    store = badger_store.open_tracking()
    try:
        assert store.flow_row("f1") is None
        assert store.flow_upsert("f1", '{"n": 1}') == 0
        first = store.flow_row("f1")
        assert first["revision"] == 0 and first["payload"] == '{"n": 1}'
        assert store.flow_upsert("f1", '{"n": 2}', expected_revision=0) == 1
        second = store.flow_row("f1")
        assert second["revision"] == 1 and second["payload"] == '{"n": 2}'
        assert second["created_at"] == first["created_at"]
        with pytest.raises(badger_store.FlowConflict) as caught:
            store.flow_upsert("f1", '{"n": 3}', expected_revision=0)
        assert caught.value.current_revision == 1 and caught.value.flow_id == "f1"
        with pytest.raises(badger_store.FlowConflict):
            store.flow_upsert("f1", '{"n": 3}')
        assert store.flow_row("f1")["payload"] == '{"n": 2}'
        assert store.flow_row("f1")["revision"] == 1
    finally:
        store.close()


def test_schema_versions_are_unchanged(roots):
    assert badger_store.SCHEMA_VERSION == 3
    assert badger_store.NON_TRACKING_SCHEMA_VERSION == 2
    tracking = badger_store.open_tracking()
    user = badger_store.open_user()
    try:
        assert _version(tracking.conn) == "3"
        assert _version(user.conn) == "2"
    finally:
        tracking.close()
        user.close()


def test_json_valid_rejects_a_bad_payload_and_negative_revision(roots):
    store = badger_store.open_tracking()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.flow_upsert("f1", "{not json")
        store.flow_upsert("f2", "{}")
        with pytest.raises(sqlite3.IntegrityError):
            store.flow_upsert("f2", "{not json", expected_revision=0)
        assert store.flow_row("f2")["payload"] == "{}"
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO review_flows VALUES ('f3', -1, '{}', 'x', 'x')")
    finally:
        store.close()
