"""Tests for the memory-follow-through hook (passive implicit-feedback measurement)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def fresh_hook_state(monkeypatch):
    """Reset the hook's in-memory state before each test."""
    import sys as _sys
    import features.common.hooks.ai_badger_hooks as hooks
    import features.common.hooks.follow_through as ft
    # Seed sys.modules so _load_follow_through() finds the same instance
    _sys.modules.setdefault("ai_badger_follow_through", ft)
    ft._RECENT_SEARCHES.clear()
    monkeypatch.setattr(ft, "_record_follow_through_sql", lambda cid, fp: None)
    monkeypatch.setattr(hooks, "_debug", lambda *a, **kw: None)
    return hooks, ft


class TestStashSearchSources:
    MEMORY_SEARCH_RESULT = json.dumps({
        "meta": {"correlationId": "abc-123"},
        "results": [
            {"sourceFile": "/project/docs/adr/0001.md", "ranking": 0.95},
            {"sourceFile": "/project/src/Program.cs", "ranking": 0.80},
            {"sourceFile": "/project/docs/adr/0001.md", "ranking": 0.75},
        ]
    })

    def test_stashes_correlation_id_and_source_files(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        hooks._stash_search_sources("memory_search", self.MEMORY_SEARCH_RESULT, str(tmp_path))
        assert str(tmp_path) in ft._RECENT_SEARCHES
        entries = ft._RECENT_SEARCHES[str(tmp_path)]
        assert len(entries) == 1
        assert entries[0]["correlationId"] == "abc-123"
        assert entries[0]["sourceFiles"] == [
            "/project/docs/adr/0001.md", "/project/src/Program.cs"]

    def test_ignores_non_memory_search_tools(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        hooks._stash_search_sources("read_file", self.MEMORY_SEARCH_RESULT, str(tmp_path))
        assert str(tmp_path) not in ft._RECENT_SEARCHES

    def test_ignores_result_without_correlation_id(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        result = json.dumps({"meta": {}, "results": [{"sourceFile": "/x.md"}]})
        hooks._stash_search_sources("memory_search", result, str(tmp_path))
        assert str(tmp_path) not in ft._RECENT_SEARCHES

    def test_ignores_result_without_source_files(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        result = json.dumps({"meta": {"correlationId": "abc"}, "results": [{}]})
        hooks._stash_search_sources("memory_search", result, str(tmp_path))
        assert str(tmp_path) not in ft._RECENT_SEARCHES

    def test_handles_mcp_prefixed_tool_name(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        hooks._stash_search_sources(
            "mcp__ai_raccoon__memory_search", self.MEMORY_SEARCH_RESULT, str(tmp_path))
        assert str(tmp_path) in ft._RECENT_SEARCHES

    def test_handles_non_json_result(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        hooks._stash_search_sources("memory_search", "not json", str(tmp_path))
        assert str(tmp_path) not in ft._RECENT_SEARCHES

    def test_prunes_old_entries(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        stale = {"correlationId": "stale", "sourceFiles": ["/old.md"],
                 "ts": time.time() - 200}
        ft._RECENT_SEARCHES[str(tmp_path)] = [stale]
        hooks._stash_search_sources("memory_search", self.MEMORY_SEARCH_RESULT, str(tmp_path))
        entries = ft._RECENT_SEARCHES[str(tmp_path)]
        assert len(entries) == 1
        assert entries[0]["correlationId"] == "abc-123"

    def test_multiple_searches_accumulate(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        hooks._stash_search_sources("memory_search", self.MEMORY_SEARCH_RESULT, str(tmp_path))
        hooks._stash_search_sources(
            "memory_search", json.dumps({
                "meta": {"correlationId": "def"},
                "results": [{"sourceFile": "/other.md"}]}), str(tmp_path))
        entries = ft._RECENT_SEARCHES[str(tmp_path)]
        assert len(entries) == 2


class TestRecordFollowThrough:
    # pylint: disable=attribute-defined-outside-init
    def _setup(self, hooks, ft, tmp_path):
        ft._RECENT_SEARCHES[str(tmp_path)] = [{
            "correlationId": "abc-123",
            "sourceFiles": ["/project/docs/adr/0001.md"],
            "ts": time.time(),
        }]
        recorded = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(ft, "_record_follow_through_sql",
                            lambda cid, fp: recorded.append((cid, fp)))
        self.recorded = recorded
        self.hooks = hooks
        self.project = str(tmp_path)

    def test_matches_exact_path(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        self._setup(hooks, ft, tmp_path)
        self.hooks._maybe_record_follow_through(
            "read_file", json.dumps({"path": "/project/docs/adr/0001.md"}), self.project)
        assert len(self.recorded) == 1
        assert self.recorded[0] == ("abc-123", "/project/docs/adr/0001.md")

    def test_ignores_non_read_tools(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        self._setup(hooks, ft, tmp_path)
        self.hooks._maybe_record_follow_through(
            "write_file", json.dumps({"path": "/project/docs/adr/0001.md"}), self.project)
        assert len(self.recorded) == 0

    def test_ignores_stale_search_results(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        ft._RECENT_SEARCHES[str(tmp_path)] = [{
            "correlationId": "abc-123",
            "sourceFiles": ["/project/docs/adr/0001.md"],
            "ts": time.time() - 120,
        }]
        recorded = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(ft, "_record_follow_through_sql",
                            lambda cid, fp: recorded.append((cid, fp)))
        hooks._maybe_record_follow_through(
            "read_file", json.dumps({"path": "/project/docs/adr/0001.md"}), str(tmp_path))
        assert len(recorded) == 0

    def test_first_match_wins(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        ft._RECENT_SEARCHES[str(tmp_path)] = [
            {"correlationId": "first", "sourceFiles": ["/project/docs/adr/0001.md"],
             "ts": time.time()},
            {"correlationId": "second", "sourceFiles": ["/project/docs/adr/0001.md"],
             "ts": time.time()},
        ]
        recorded = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(ft, "_record_follow_through_sql",
                            lambda cid, fp: recorded.append((cid, fp)))
        hooks._maybe_record_follow_through(
            "read_file", json.dumps({"path": "/project/docs/adr/0001.md"}), str(tmp_path))
        assert len(recorded) == 1
        assert recorded[0][0] == "first"

    def test_handles_non_json_result(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        self._setup(hooks, ft, tmp_path)
        self.hooks._maybe_record_follow_through("read_file", "not json", self.project)
        assert len(self.recorded) == 0

    def test_handles_result_without_path(self, fresh_hook_state, tmp_path):
        hooks, ft = fresh_hook_state
        self._setup(hooks, ft, tmp_path)
        self.hooks._maybe_record_follow_through(
            "read_file", json.dumps({"content": "no path"}), self.project)
        assert len(self.recorded) == 0


class TestIsReadFile:
    def test_hermes_read_file(self, fresh_hook_state):
        _hooks, ft = fresh_hook_state
        assert ft._is_read_file("read_file") is True

    def test_claude_read(self, fresh_hook_state):
        _hooks, ft = fresh_hook_state
        assert ft._is_read_file("Read") is True

    def test_mcp_prefixed(self, fresh_hook_state):
        _hooks, ft = fresh_hook_state
        assert ft._is_read_file("mcp__hermes__read_file") is True

    def test_non_read_tool(self, fresh_hook_state):
        _hooks, ft = fresh_hook_state
        assert ft._is_read_file("write_file") is False

    def test_non_string(self, fresh_hook_state):
        _hooks, ft = fresh_hook_state
        assert ft._is_read_file(None) is False


# ---------------------------------------------------------------------------
# File-based variant (memory_grade_hook.py shell hook)
# ---------------------------------------------------------------------------

MEMORY_GRADE_HOOK = (
    Path(__file__).resolve().parent.parent
    / "features" / "common" / "skills" / "ai-raccoon-memory"
    / "scripts" / "memory_grade_hook.py"
)


def _load_memory_grade_hook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("memory_grade_hook", MEMORY_GRADE_HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMemoryGradeHook:
    # pylint: disable=attribute-defined-outside-init
    @pytest.fixture(autouse=True)
    def clean_searches_file(self, tmp_path, monkeypatch):
        searches_file = tmp_path / "searches.json"
        mgh = _load_memory_grade_hook()
        monkeypatch.setattr(mgh, "SEARCHES_FILE", searches_file)
        monkeypatch.setattr(mgh, "_record_follow_through_sql", lambda cid, fp: None)
        self.mgh = mgh
        return searches_file

    def test_memory_search_stashes_sources(self, clean_searches_file):
        mgh = self.mgh
        payload = {"tool_name": "memory_search", "result": json.dumps({
            "meta": {"correlationId": "abc-123"},
            "results": [{"sourceFile": "/project/docs/adr/0001.md"}]})}
        import io
        old = mgh.sys.stdin
        mgh.sys.stdin = io.StringIO(json.dumps(payload))
        try:
            mgh.main([])
        finally:
            mgh.sys.stdin = old
        stash = mgh._load_searches()
        assert "recent" in stash
        assert stash["recent"][0]["correlationId"] == "abc-123"

    def test_read_file_matches_and_records(self, clean_searches_file, monkeypatch):
        mgh = self.mgh
        mgh._save_searches({"recent": [{
            "correlationId": "abc-123", "sourceFiles": ["/project/docs/adr/0001.md"],
            "ts": time.time()}]})
        recorded = []
        monkeypatch.setattr(mgh, "_record_follow_through_sql",
                            lambda cid, fp: recorded.append((cid, fp)))
        payload = {"tool_name": "Read",
                   "result": json.dumps({"path": "/project/docs/adr/0001.md"})}
        import io
        old = mgh.sys.stdin
        mgh.sys.stdin = io.StringIO(json.dumps(payload))
        try:
            mgh.main([])
        finally:
            mgh.sys.stdin = old
        assert len(recorded) == 1

    def test_ignores_non_memory_or_read_tools(self, clean_searches_file):
        mgh = self.mgh
        payload = {"tool_name": "write_file", "result": json.dumps({"path": "/x.md"})}
        import io
        old = mgh.sys.stdin
        mgh.sys.stdin = io.StringIO(json.dumps(payload))
        try:
            assert mgh.main([]) == 0
        finally:
            mgh.sys.stdin = old

    def test_handles_invalid_json_stdin(self, clean_searches_file):
        import io
        old = self.mgh.sys.stdin
        self.mgh.sys.stdin = io.StringIO("not json")
        try:
            assert self.mgh.main([]) == 0
        finally:
            self.mgh.sys.stdin = old


# ---------------------------------------------------------------------------
# SQLite write function
# ---------------------------------------------------------------------------

class TestRecordFollowThroughSql:
    @pytest.fixture
    def db(self, tmp_path):
        db_dir = tmp_path / ".ai-raccoon"
        db_dir.mkdir()
        db_path = db_dir / "memory.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS search_quality ("
                     "correlation_id TEXT PRIMARY KEY, "
                     "follow_through_count INTEGER DEFAULT 0, "
                     "follow_through_files TEXT DEFAULT '[]')")
        conn.execute("INSERT INTO search_quality (correlation_id) VALUES (?)", ("abc-123",))
        conn.commit()
        conn.close()
        return db_path

    def test_records_first_follow_through(self, db, monkeypatch):
        import features.common.hooks.follow_through as ft
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        ft._record_follow_through_sql("abc-123", "/project/docs/adr/0001.md")
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT follow_through_count, follow_through_files "
            "FROM search_quality WHERE correlation_id = ?", ("abc-123",)).fetchone()
        conn.close()
        assert row[0] == 1
        assert json.loads(row[1]) == ["/project/docs/adr/0001.md"]

    def test_appends_to_existing_files(self, db, monkeypatch):
        import features.common.hooks.follow_through as ft
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE search_quality SET follow_through_count=1, "
                     "follow_through_files=? WHERE correlation_id=?",
                     (json.dumps(["/first.md"]), "abc-123"))
        conn.commit()
        conn.close()
        ft._record_follow_through_sql("abc-123", "/second.md")
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT follow_through_count, follow_through_files "
            "FROM search_quality WHERE correlation_id = ?", ("abc-123",)).fetchone()
        conn.close()
        assert row[0] == 2
        assert json.loads(row[1]) == ["/first.md", "/second.md"]

    def test_deduplicates_same_file(self, db, monkeypatch):
        import features.common.hooks.follow_through as ft
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        ft._record_follow_through_sql("abc-123", "/same.md")
        ft._record_follow_through_sql("abc-123", "/same.md")
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT follow_through_count, follow_through_files "
            "FROM search_quality WHERE correlation_id = ?", ("abc-123",)).fetchone()
        conn.close()
        assert row[0] == 1

    def test_noop_when_db_missing(self, monkeypatch):
        import features.common.hooks.follow_through as ft
        monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
        ft._record_follow_through_sql("abc-123", "/file.md")

    def test_noop_when_correlation_id_not_found(self, db, monkeypatch):
        import features.common.hooks.follow_through as ft
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        ft._record_follow_through_sql("nonexistent", "/file.md")
