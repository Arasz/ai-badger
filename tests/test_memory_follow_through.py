"""Tests for the memory-follow-through hook (passive implicit-feedback measurement)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def fresh_hook_state(monkeypatch):
    """Reset the hook's in-memory state before each test."""
    import sys as _sys
    import importlib.util as _ilu

    def _load(name, rel_path):
        spec = _ilu.spec_from_file_location(
            name, Path(__file__).resolve().parent.parent / rel_path)
        assert spec is not None and spec.loader is not None
        module = _ilu.module_from_spec(spec)
        _sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    hooks = _load("aib_hooks_ft_test", "features/common/hooks/ai_badger_hooks.py")
    ft = _load("aib_follow_through_ft_test", "features/common/hooks/follow_through.py")
    # Seed sys.modules so _load_follow_through() finds THIS test's instance
    _sys.modules["ai_badger_follow_through"] = ft
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
# Store-backed variant (memory_grade_hook.py shell hook) — P1.4 rewiring
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
    """The shell hook's searches stash lives in the user store (P1.4): one row per stashed
    search, the legacy file imported + renamed on the first write, never rewritten after.
    """

    # pylint: disable=attribute-defined-outside-init
    @pytest.fixture(autouse=True)
    def hook_env(self, tmp_path, monkeypatch):
        """Redirect every seam: the store under a temp user root, the legacy stash file
        beside it, the raccoon-server write stubbed out."""
        self.user_root = tmp_path / "user-root"
        monkeypatch.setenv("AI_BADGER_USER_ROOT", str(self.user_root))
        self.searches_file = tmp_path / "memory-grade" / "searches.json"
        self.mgh = _load_memory_grade_hook()
        monkeypatch.setattr(self.mgh, "SEARCHES_FILE", self.searches_file)
        self.recorded = []
        monkeypatch.setattr(self.mgh, "_record_follow_through_sql",
                            lambda cid, fp: self.recorded.append((cid, fp)))
        return self.mgh

    def _run(self, payload) -> int:
        import io
        old = self.mgh.sys.stdin
        self.mgh.sys.stdin = io.StringIO(json.dumps(payload))
        try:
            return self.mgh.main([])
        finally:
            self.mgh.sys.stdin = old

    def _stash_payload(self, corr_id, source_file):
        return {"tool_name": "memory_search", "result": json.dumps({
            "meta": {"correlationId": corr_id},
            "results": [{"sourceFile": source_file}]})}

    def _seed_legacy(self, entries):
        self.searches_file.parent.mkdir(parents=True, exist_ok=True)
        self.searches_file.write_text(json.dumps({"recent": entries}), encoding="utf-8")

    def test_memory_search_appends_store_row_and_leaves_no_legacy_file(self, hook_env):
        assert self._run(self._stash_payload("abc-123", "/p/a.md")) == 0

        store = self.mgh.open_store()
        try:
            rows = store.log_rows("searches")
            assert len(rows) == 1
            entry = json.loads(rows[0][1])
            assert entry["correlationId"] == "abc-123"
            assert entry["sourceFiles"] == ["/p/a.md"]
            assert isinstance(entry["ts"], float)  # payload verbatim: window arithmetic
            datetime.fromisoformat(rows[0][0])  # row ts parses: the prune's contract (D36)
        finally:
            store.close()
        assert not self.searches_file.exists()  # the legacy writer is gone, not retained

    def test_first_write_migrates_legacy_file_to_rows(self, hook_env):
        self._seed_legacy([{"correlationId": "old", "sourceFiles": ["/p/old.md"],
                            "ts": time.time() - 120}])
        assert self._run(self._stash_payload("new", "/p/new.md")) == 0

        assert not self.searches_file.exists()
        assert self.searches_file.with_name("searches.migrated.json").exists()
        store = self.mgh.open_store()
        try:
            ids = [json.loads(p)["correlationId"] for _, p in store.log_rows("searches")]
            assert ids == ["old", "new"]
        finally:
            store.close()

    def test_read_matches_a_search_stashed_in_the_store(self, hook_env):
        assert self._run(self._stash_payload("abc-123", "/p/a.md")) == 0
        assert self._run({"tool_name": "Read",
                          "result": json.dumps({"path": "/p/a.md"})}) == 0
        # no legacy file exists here: the match can only have come from the store
        assert self.recorded == [("abc-123", "/p/a.md")]

    def test_read_still_matches_pre_migration_legacy_entries(self, hook_env):
        self._seed_legacy([{"correlationId": "legacy", "sourceFiles": ["/p/old.md"],
                            "ts": time.time()}])
        assert self._run({"tool_name": "read_file",
                          "result": json.dumps({"path": "/p/old.md"})}) == 0
        assert self.recorded == [("legacy", "/p/old.md")]
        assert self.searches_file.exists()  # a read never migrates or rewrites the file

    def test_ignores_non_memory_or_read_tools(self, hook_env):
        assert self._run({"tool_name": "write_file",
                          "result": json.dumps({"path": "/x.md"})}) == 0
        assert self.recorded == []

    def test_handles_invalid_json_stdin(self, hook_env):
        import io
        old = self.mgh.sys.stdin
        self.mgh.sys.stdin = io.StringIO("not json")
        try:
            assert self.mgh.main([]) == 0
        finally:
            self.mgh.sys.stdin = old

    def test_write_path_prunes_expired_rows_and_stamps_retention(self, hook_env):
        """G0-Q2 operative through the hook: the stash write is the prune opportunity —
        a 61-day-old row is swept, the stamp lands, the fresh row survives."""
        store = self.mgh.open_store()
        try:
            store.log_append(
                "searches",
                (datetime.now(timezone.utc) - timedelta(days=61)).isoformat(),
                {"correlationId": "stale", "sourceFiles": ["/p/x.md"],
                 "ts": time.time() - 61 * 86400})
        finally:
            store.close()

        assert self._run(self._stash_payload("fresh", "/p/y.md")) == 0

        store = self.mgh.open_store()
        try:
            ids = [json.loads(p)["correlationId"] for _, p in store.log_rows("searches")]
            assert ids == ["fresh"]
            assert store.meta_get("pruned_at.searches") is not None
        finally:
            store.close()

    def test_a_broken_store_fails_open_on_both_paths(self, hook_env, monkeypatch):
        """An unopenable store never blocks the tool call: the stash write degrades to a
        lost metric, the read degrades to the legacy file's entries (D31/advisory)."""
        def _broken():
            raise sqlite3.OperationalError("no such store")
        monkeypatch.setattr(self.mgh, "open_store", _broken)
        self._seed_legacy([{"correlationId": "legacy", "sourceFiles": ["/p/old.md"],
                            "ts": time.time()}])
        before = self.searches_file.read_text(encoding="utf-8")

        assert self._run(self._stash_payload("x", "/p/x.md")) == 0
        assert self._run({"tool_name": "Read",
                          "result": json.dumps({"path": "/p/old.md"})}) == 0

        assert self.recorded == [("legacy", "/p/old.md")]
        # no failure path may resurrect or rewrite the legacy file
        assert self.searches_file.read_text(encoding="utf-8") == before

    def test_load_searches_returns_only_rows_within_the_follow_through_window(
            self, hook_env):
        """Join-review finding: _load_searches read and decoded the entire 60-day searches
        table on every Read to answer a 60-second window (measured linear: 0.8 ms at 0
        rows, 59.2 ms at 20 000). The store read is bounded by the ts index instead — rows
        older than the window never reach the JSON decoder. The window is the row ts's
        clock (the stash moment, iso_row_ts of the payload ts), so the cutoff maps the
        60-second window onto the column the index serves."""
        bs = self.mgh.badger_store
        fresh_epoch = time.time() - 5
        stale_epoch = time.time() - 3600
        store = self.mgh.open_store()
        try:
            store.log_append("searches", bs.iso_row_ts(stale_epoch),
                             {"correlationId": "stale", "sourceFiles": ["/p/a.md"],
                              "ts": stale_epoch})
            store.log_append("searches", bs.iso_row_ts(fresh_epoch),
                             {"correlationId": "fresh", "sourceFiles": ["/p/a.md"],
                              "ts": fresh_epoch})
        finally:
            store.close()

        entries = self.mgh._load_searches()

        assert [entry["correlationId"] for entry in entries] == ["fresh"], (
            "a row outside the window must not be decoded at all")

    def test_load_searches_window_keeps_the_window_edge_and_legacy_merge(self, hook_env):
        """Boundary + composition: an entry right at the 60-second edge survives the bound
        (the caller's window filter admits it), and the legacy file's entries still merge
        after the store rows (D5a) — the bound must not eat the dual-read window."""
        bs = self.mgh.badger_store
        edge_epoch = time.time() - 30
        store = self.mgh.open_store()
        try:
            store.log_append("searches", bs.iso_row_ts(edge_epoch),
                             {"correlationId": "edge", "sourceFiles": ["/p/edge.md"],
                              "ts": edge_epoch})
        finally:
            store.close()
        self._seed_legacy([{"correlationId": "legacy", "sourceFiles": ["/p/old.md"],
                            "ts": time.time()}])

        entries = self.mgh._load_searches()

        assert [entry["correlationId"] for entry in entries] == ["edge", "legacy"]

    def test_hook_module_survives_a_missing_badger_store(self, hook_env, monkeypatch):
        """Join-review finding: the module-level `import badger_store` was the one consumer
        import that could die at import — a partial deployment without the vendored copy
        made the whole hook crash (exit != 0) instead of degrading. The import is guarded:
        the hook loads, exits 0 on every path, and only the metric is lost (D31/advisory)."""
        import builtins
        import importlib.util
        import io
        real_import = builtins.__import__

        def _no_store(name, *args, **kwargs):
            if name == "badger_store":
                raise ImportError("simulated partial deployment")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_store)
        spec = importlib.util.spec_from_file_location(
            "memory_grade_hook_guarded", MEMORY_GRADE_HOOK)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # the defect dies right here
        assert module.badger_store is None

        old = module.sys.stdin
        module.sys.stdin = io.StringIO(json.dumps(
            {"tool_name": "Read", "result": json.dumps({"path": "/p/a.md"})}))
        try:
            assert module.main([]) == 0
        finally:
            module.sys.stdin = old


# ---------------------------------------------------------------------------
# SQLite write function
# ---------------------------------------------------------------------------

class TestRecordFollowThroughSql:
    @pytest.fixture
    def ft(self):
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "aib_follow_through_sql_test",
            Path(__file__).resolve().parent.parent
            / "features" / "common" / "hooks" / "follow_through.py")
        assert spec is not None and spec.loader is not None
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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

    def test_records_first_follow_through(self, db, monkeypatch, ft):
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        ft._record_follow_through_sql("abc-123", "/project/docs/adr/0001.md")
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT follow_through_count, follow_through_files "
            "FROM search_quality WHERE correlation_id = ?", ("abc-123",)).fetchone()
        conn.close()
        assert row[0] == 1
        assert json.loads(row[1]) == ["/project/docs/adr/0001.md"]

    def test_appends_to_existing_files(self, db, monkeypatch, ft):
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

    def test_deduplicates_same_file(self, db, monkeypatch, ft):
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        ft._record_follow_through_sql("abc-123", "/same.md")
        ft._record_follow_through_sql("abc-123", "/same.md")
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT follow_through_count, follow_through_files "
            "FROM search_quality WHERE correlation_id = ?", ("abc-123",)).fetchone()
        conn.close()
        assert row[0] == 1

    def test_noop_when_db_missing(self, monkeypatch, ft):
        monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
        ft._record_follow_through_sql("abc-123", "/file.md")

    def test_noop_when_correlation_id_not_found(self, db, monkeypatch, ft):
        monkeypatch.setattr(Path, "home", lambda: db.parent.parent)
        ft._record_follow_through_sql("nonexistent", "/file.md")
