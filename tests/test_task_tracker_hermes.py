"""Hermes session tracking: task_tracker gathers real token data from ~/.hermes/state.db.

The hermes session source is agent-specific and therefore lives in
features/hermes/adjustments/session_sources.py, installed by the hermes adjustment
(adjust_task.py) into the scaffolded .ai-badger/skills/task/scripts/session_sources.py.
These tests pin the hermes data path: session resolution, the state.db parser, the CLI
branches (start/finish/reattach/subagent --delegation), and the generic registry seam the
common tracker uses to reach it. The fake store is a real file-backed sqlite3 db built in
tmp_path with the exact column names Hermes uses, so the mode=ro open path is exercised for
real and no test can touch ~/.hermes.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pytest

TRACKER_RELPATH = "features/common/skills/task/scripts/task_tracker.py"
LIB_RELPATH = "features/common/skills/task/scripts/tracker_lib.py"
HERMES_RELPATH = "features/hermes/adjustments/session_sources.py"


class _GuardedSubprocess:
    """subprocess.run wrapper that forbids real process access (mirrors test_task_tracker)."""

    CalledProcessError = subprocess.CalledProcessError

    @staticmethod
    def run(*args, **kwargs):
        raise AssertionError(
            f"unexpected subprocess.run call (real cron/process access is forbidden in tests): "
            f"args={args!r} kwargs={kwargs!r}"
        )


def _redirect_lib(lib, tmp_path):
    data_dir = tmp_path / ".ai-badger" / "task-tracking"
    lib.PROJECT_ROOT = tmp_path
    lib.DATA_DIR = data_dir
    lib.EXECUTED_TASKS = data_dir / "executed-tasks.json"
    lib.TOKEN_USAGE = data_dir / "token-usage.json"
    lib.CURRENT_SESSION = data_dir / "current-session.json"
    lib.LOCK_FILE = data_dir / ".write.lock"
    lib.STATE_JSON = tmp_path / ".ai-badger" / "state.json"
    lib.CONFIG_JSON = tmp_path / ".ai-badger" / "config.json"
    lib.CLAUDE_MD = tmp_path / "CLAUDE.md"


@pytest.fixture
def tt(load_script, root, monkeypatch, tmp_path):
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    module = load_script(TRACKER_RELPATH)
    _redirect_lib(module.lib, tmp_path)
    # tracker_lib is module-cached: a register() from one test would otherwise persist into
    # the next. Give this test its own registry so hermes tests are isolated from claude-only
    # ones (and each other).
    monkeypatch.setattr(module.lib, "SESSION_SOURCES", {})
    hermes = load_script(HERMES_RELPATH)
    hermes.register(module.lib)
    module._hermes = hermes
    monkeypatch.setattr(module, "subprocess", _GuardedSubprocess())
    return module


@pytest.fixture
def hs(load_script, root, monkeypatch):
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    return load_script(HERMES_RELPATH)


def _run(monkeypatch, module, *args):
    """Call task_tracker's main() in-process (no subprocess) with the given CLI args."""
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", *args])
    return module.main()


def _hermes_db(tmp_path):
    """Build a file-backed fake of ~/.hermes/state.db with the four Hermes tables.

    Returns the Path. Tests seed rows through the returned db handle via the helper
    functions below (session_row, model_usage_row, message_row, delegation_row).
    """
    path = tmp_path / "state.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, input_tokens INTEGER, output_tokens INTEGER,
            cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
            api_call_count INTEGER, message_count INTEGER, tool_call_count INTEGER,
            parent_session_id TEXT, started_at REAL, ended_at REAL
        );
        CREATE TABLE session_model_usage (
            session_id TEXT, model TEXT, api_call_count INTEGER, input_tokens INTEGER,
            output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            reasoning_tokens INTEGER, first_seen REAL, last_seen REAL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, token_count INTEGER
        );
        CREATE TABLE async_delegations (
            delegation_id TEXT PRIMARY KEY, origin_session TEXT, origin_session_id TEXT,
            parent_session_id TEXT, state TEXT, dispatched_at REAL, completed_at REAL,
            result_json TEXT
        );
        """
    )
    return path


def _session(db, sid, inp=0, out=0, cr=0, cw=0, parent=None):
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO sessions (id, input_tokens, output_tokens, cache_read_tokens, "
        "cache_write_tokens, reasoning_tokens, api_call_count, message_count, "
        "tool_call_count, parent_session_id, started_at, ended_at) "
        "VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 0, 0)",
        (sid, inp, out, cr, cw, parent),
    )
    con.commit()
    con.close()


def _model_usage(db, sid, model, inp, out, cr, cw, api_calls=1):
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO session_model_usage (session_id, model, api_call_count, input_tokens, "
        "output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, "
        "first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)",
        (sid, model, api_calls, inp, out, cr, cw),
    )
    con.commit()
    con.close()


def _message(db, sid, role):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO messages (session_id, role, token_count) VALUES (?, ?, NULL)",
                (sid, role))
    con.commit()
    con.close()


def _delegation(db, deleg_id, origin, state="completed", result=None):
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO async_delegations (delegation_id, origin_session, origin_session_id, "
        "parent_session_id, state, dispatched_at, completed_at, result_json) "
        "VALUES (?, ?, '', ?, ?, 0, 1, ?)",
        (deleg_id, origin, origin, state, json.dumps(result) if result is not None else None),
    )
    con.commit()
    con.close()


class TestResolveOwnSessionHermes:
    def test_resolve_own_session_uses_hermes_env_var(self, load_script, monkeypatch,
                                                     tmp_path, hs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        hs.register(tl)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")

        resolved = tl.resolve_own_session()

        assert resolved == {"sessionId": "sid-h", "transcriptPath": None, "source": "hermes"}

    def test_resolve_own_session_claude_env_wins_over_hermes(self, load_script, monkeypatch,
                                                             tmp_path, hs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        hs.register(tl)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-c")
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")

        resolved = tl.resolve_own_session()

        assert resolved["sessionId"] == "sid-c"
        assert "source" not in resolved  # Claude shapes stay untouched

    def test_resolve_own_session_hermes_id_ignores_current_sessions_file(self, load_script,
                                                                         monkeypatch,
                                                                         tmp_path, hs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        hs.register(tl)
        # No current-session.json at all — the Hermes path must not consult it.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")

        resolved = tl.resolve_own_session()

        assert resolved["sessionId"] == "sid-h"

    def test_unregistered_lib_ignores_hermes_env_var(self, load_script, monkeypatch, tmp_path):
        """The common tracker has no hermes knowledge until an adjustment registers it."""
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.chdir(tmp_path)
        tl._own_pid_ancestry = lambda max_depth=12: []

        resolved = tl.resolve_own_session()

        assert resolved == {}


class TestHermesStateDbPath:
    def test_hermes_state_db_path_defaults_to_home_hermes(self, load_script, monkeypatch,
                                                          tmp_path, hs):
        monkeypatch.delenv("HERMES_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        assert hs.hermes_state_db_path() == tmp_path / ".hermes" / "state.db"

    def test_hermes_state_db_path_prefers_hermes_home_env(self, load_script, monkeypatch,
                                                          tmp_path, hs):
        custom = tmp_path / "custom"
        monkeypatch.setenv("HERMES_HOME", str(custom))

        assert hs.hermes_state_db_path() == custom / "state.db"


class TestParseHermesSessionUsage:
    def test_parse_hermes_session_usage_missing_db_returns_zeroed_shape(self, load_script,
                                                                        tmp_path, hs):
        zeroed = {
            "contextTokens": 0, "assistantMessages": 0, "byModel": {},
            "dispatches": {"count": 0, "undeclaredModel": 0, "byAgentType": {}},
            "cumulative": {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0,
                           "cacheCreationTokens": 0},
            "transcriptFound": False,
        }
        assert hs.parse_hermes_session_usage("sid", tmp_path / "nope.db") == zeroed

    def test_parse_hermes_session_usage_unknown_session_returns_zeroed_shape(self, load_script,
                                                                             tmp_path, hs):
        db = _hermes_db(tmp_path)
        _session(db, "real-session", inp=100)
        usage = hs.parse_hermes_session_usage("ghost-session", db)
        assert usage["transcriptFound"] is False
        assert usage["cumulative"]["inputTokens"] == 0

    def test_parse_hermes_session_usage_maps_session_and_model_usage(self, load_script,
                                                                     tmp_path, hs):
        db = _hermes_db(tmp_path)
        _session(db, "s1", inp=1000, out=200, cr=500, cw=0)
        _model_usage(db, "s1", "model-a", 1000, 200, 500, 0, api_calls=7)
        _model_usage(db, "s1", "model-b", 300, 50, 100, 0, api_calls=3)

        usage = hs.parse_hermes_session_usage("s1", db)

        assert usage["transcriptFound"] is True
        assert usage["cumulative"] == {
            "inputTokens": 1000, "outputTokens": 200,
            "cacheReadTokens": 500, "cacheCreationTokens": 0,
        }
        assert usage["byModel"]["model-a"]["outputTokens"] == 200
        assert usage["byModel"]["model-a"]["assistantMessages"] == 7  # api_call_count proxy
        assert usage["byModel"]["model-b"]["outputTokens"] == 50

    def test_parse_hermes_session_usage_counts_assistant_messages(self, load_script, tmp_path,
                                                                  hs):
        db = _hermes_db(tmp_path)
        _session(db, "s1", inp=1)
        for role in ("assistant", "assistant", "assistant", "user", "user"):
            _message(db, "s1", role)

        usage = hs.parse_hermes_session_usage("s1", db)

        assert usage["assistantMessages"] == 3
        assert usage["contextTokens"] == 0  # token_count is NULL everywhere; never fabricated

    def test_parse_hermes_session_usage_counts_completed_delegations(self, load_script,
                                                                     tmp_path, hs):
        db = _hermes_db(tmp_path)
        _session(db, "s1", inp=1)
        _delegation(db, "d1", "s1", result={"results": [{"tokens": {"input": 1, "output": 1},
                                                        "model": "m1"}]})
        _delegation(db, "d2", "s1", result={"results": [{"tokens": {"input": 1, "output": 1}}]})
        _delegation(db, "d3", "s1", state="failed", result={})

        usage = hs.parse_hermes_session_usage("s1", db)

        assert usage["dispatches"]["count"] == 2
        assert usage["dispatches"]["undeclaredModel"] == 1
        assert usage["dispatches"]["byAgentType"] == {}

    def test_parse_hermes_session_usage_handles_null_token_columns(self, load_script, tmp_path,
                                                                   hs):
        db = _hermes_db(tmp_path)
        con = sqlite3.connect(db)
        con.execute(
            "INSERT INTO sessions (id, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_tokens, reasoning_tokens, api_call_count, message_count, "
            "tool_call_count, parent_session_id, started_at, ended_at) "
            "VALUES ('null-s', NULL, NULL, NULL, NULL, NULL, 0, 0, 0, NULL, 0, 0)")
        con.commit()
        con.close()

        usage = hs.parse_hermes_session_usage("null-s", db)

        assert usage["cumulative"] == {
            "inputTokens": 0, "outputTokens": 0,
            "cacheReadTokens": 0, "cacheCreationTokens": 0,
        }

    def test_make_hermes_checkpoint_wraps_with_timestamp(self, load_script, tmp_path, hs):
        db = _hermes_db(tmp_path)
        _session(db, "s1", inp=1000, out=200)

        checkpoint = hs.make_hermes_checkpoint("s1", db)

        assert set(checkpoint) == {"timestamp", "contextTokens", "assistantMessages",
                                   "byModel", "cumulative"}
        load_script(LIB_RELPATH).parse_iso(checkpoint["timestamp"])  # must round-trip
        assert checkpoint["cumulative"]["inputTokens"] == 1000

    def test_parse_hermes_session_usage_accumulates_same_model_across_task_rows(
            self, load_script, tmp_path, hs):
        """session_model_usage has a composite key: one (session, model) spans several rows
        split by task. Assigning instead of accumulating corrupts modelMix (review A1)."""
        db = _hermes_db(tmp_path)
        _session(db, "s1", inp=100)
        # Same model, different task rows (the real store splits '' / 'approval' / ...).
        con = sqlite3.connect(db)
        for task, api, inp, out in (("", 10, 1000, 200), ("approval", 2, 300, 50)):
            con.execute(
                "INSERT INTO session_model_usage (session_id, model, api_call_count, "
                "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
                "reasoning_tokens, first_seen, last_seen) "
                "VALUES ('s1', 'model-a', ?, ?, ?, 0, 0, 0, 0, 0)",
                (api, inp, out))
        con.commit()
        con.close()

        usage = hs.parse_hermes_session_usage("s1", db)

        assert usage["byModel"]["model-a"]["inputTokens"] == 1300
        assert usage["byModel"]["model-a"]["outputTokens"] == 250
        assert usage["byModel"]["model-a"]["assistantMessages"] == 12

    def test_parse_hermes_session_usage_folds_child_sessions_into_cumulative(
            self, load_script, tmp_path, hs):
        """The parent sessions row excludes delegated children; fold one level so cumulative
        matches the Claude path, which sums subagents/*.jsonl (review A2)."""
        db = _hermes_db(tmp_path)
        _session(db, "parent", inp=1000, out=200)
        _session(db, "child-1", inp=400, out=100, parent="parent")
        _session(db, "child-2", inp=100, out=25, parent="parent")

        usage = hs.parse_hermes_session_usage("parent", db)

        assert usage["cumulative"]["inputTokens"] == 1500
        assert usage["cumulative"]["outputTokens"] == 325

    def test_parse_hermes_session_usage_non_dict_result_json_degrades_not_crashes(
            self, load_script, tmp_path, hs):
        """result_json that parses to a non-dict (e.g. '[1,2]') must degrade, not raise
        AttributeError (review A3)."""
        db = _hermes_db(tmp_path)
        _session(db, "s1", inp=1)
        _delegation(db, "d1", "s1", result="[1, 2]")

        usage = hs.parse_hermes_session_usage("s1", db)

        assert usage["dispatches"]["count"] == 1
        assert usage["dispatches"]["undeclaredModel"] == 1  # no model -> undeclared

    def test_hermes_delegation_usage_non_dict_result_json_returns_none(
            self, load_script, tmp_path, hs):
        db = _hermes_db(tmp_path)
        _delegation(db, "d1", "s1", result='"just a string"')

        assert hs.hermes_delegation_usage(db, "d1") is None


class TestCliUnderHermes:
    def test_start_under_hermes_records_nonzero_checkpoint_and_hermes_resume(
            self, tt, monkeypatch, tmp_path, capsys):
        db = _hermes_db(tmp_path)
        _session(db, "sid-h", inp=1000, out=200, cr=500)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.setattr(tt._hermes, "hermes_state_db_path", lambda: db)

        code = _run(monkeypatch, tt, "start", "T-H1", "--no-worktree", "--no-cron")

        assert code == 0
        tasks = json.loads((tt.lib.EXECUTED_TASKS).read_text())["tasks"]
        entry = next(t for t in tasks if t["taskId"] == "T-H1")
        assert entry["resumeCommand"] == "hermes --resume sid-h"
        assert entry.get("trackingSource") == "hermes"
        usage = json.loads(tt.lib.TOKEN_USAGE.read_text())["tasks"]
        uentry = next(t for t in usage if t["taskId"] == "T-H1")
        assert uentry["checkpoints"]["start"]["cumulative"]["inputTokens"] == 1000

    def test_finish_under_hermes_computes_usage(self, tt, monkeypatch, tmp_path):
        db = _hermes_db(tmp_path)
        _session(db, "sid-h", inp=1000, out=200, cr=500)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.setattr(tt._hermes, "hermes_state_db_path", lambda: db)
        _run(monkeypatch, tt, "start", "T-H2", "--no-worktree", "--no-cron")
        # Bump the session's numbers to simulate the task's work landing.
        con = sqlite3.connect(db)
        con.execute(
            "UPDATE sessions SET input_tokens=2000, output_tokens=400, cache_read_tokens=1000 "
            "WHERE id='sid-h'")
        con.commit()
        con.close()
        # finish requires state.json updated since start
        state = tmp_path / ".ai-badger" / "state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("{}")
        _run_args(monkeypatch, tt, "finish", "T-H2", "--force")

        usage = json.loads(tt.lib.TOKEN_USAGE.read_text())["tasks"]
        uentry = next(t for t in usage if t["taskId"] == "T-H2")
        assert uentry["usage"]["inputTokens"] == 1000
        assert uentry["usage"]["grandTotal"] > 0
        assert uentry["usage"]["cacheEfficiency"] == 1.0

    def test_reattach_under_hermes_flips_resume_command_and_source(self, tt, monkeypatch,
                                                                   tmp_path):
        db = _hermes_db(tmp_path)
        _session(db, "sid-h", inp=1)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.setattr(tt._hermes, "hermes_state_db_path", lambda: db)
        _run_args(monkeypatch, tt, "start", "T-H3", "--no-worktree", "--no-cron")
        _run_args(monkeypatch, tt, "reattach", "T-H3")

        tasks = json.loads(tt.lib.EXECUTED_TASKS.read_text())["tasks"]
        entry = next(t for t in tasks if t["taskId"] == "T-H3")
        assert entry["resumeCommand"] == "hermes --resume sid-h"

    def test_subagent_delegation_reads_tokens_from_db(self, tt, monkeypatch, tmp_path):
        db = _hermes_db(tmp_path)
        _session(db, "sid-h", inp=100)
        _delegation(db, "deleg_1", "sid-h",
                    result={"results": [{"tokens": {"input": 300, "output": 50},
                                         "model": "m1", "api_calls": 4}]})
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.setattr(tt._hermes, "hermes_state_db_path", lambda: db)
        _run_args(monkeypatch, tt, "start", "T-H4", "--no-worktree", "--no-cron")

        code = _run_args(monkeypatch, tt, "subagent", "T-H4", "--delegation", "deleg_1")

        assert code == 0
        usage = json.loads(tt.lib.TOKEN_USAGE.read_text())["tasks"]
        uentry = next(t for t in usage if t["taskId"] == "T-H4")
        sub = uentry["subagents"][0]
        assert sub["totalTokens"] == 350
        assert sub["delegationId"] == "deleg_1"
        assert sub["model"] == "m1"

    def test_subagent_delegation_and_total_tokens_are_mutually_exclusive(
            self, tt, monkeypatch, tmp_path, capsys):
        _run_args(monkeypatch, tt, "start", "T-H5", "--no-worktree", "--no-cron",
                  "--session-id", "s-x")
        code = _run_args(monkeypatch, tt, "subagent", "T-H5", "100", "--delegation", "d1")
        assert code == 2

    def test_subagent_delegation_without_a_registered_source_is_exit_2(
            self, tt, monkeypatch, tmp_path):
        """--delegation against the built-in claude source (no delegation store) is a clear
        refusal, not a crash — the flag is generic, the source decides."""
        _run_args(monkeypatch, tt, "start", "T-H8", "--no-worktree", "--no-cron",
                  "--session-id", "s-x")
        code = _run_args(monkeypatch, tt, "subagent", "T-H8", "--delegation", "d1")
        assert code == 2

    def test_subagent_unknown_delegation_is_exit_2(self, tt, monkeypatch, tmp_path):
        db = _hermes_db(tmp_path)
        _session(db, "sid-h", inp=100)
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.setattr(tt._hermes, "hermes_state_db_path", lambda: db)
        _run_args(monkeypatch, tt, "start", "T-H6", "--no-worktree", "--no-cron")
        code = _run_args(monkeypatch, tt, "subagent", "T-H6", "--delegation", "nope")
        assert code == 2

    def test_start_under_hermes_with_missing_db_degrades_to_zeros(self, tt, monkeypatch,
                                                                  tmp_path):
        monkeypatch.setenv("HERMES_SESSION_ID", "sid-h")
        monkeypatch.setattr(tt._hermes, "hermes_state_db_path",
                            lambda: tmp_path / "no-hermes" / "state.db")
        code = _run_args(monkeypatch, tt, "start", "T-H7", "--no-worktree", "--no-cron")
        assert code == 0
        tasks = json.loads(tt.lib.EXECUTED_TASKS.read_text())["tasks"]
        entry = next(t for t in tasks if t["taskId"] == "T-H7")
        assert entry["resumeCommand"] == "hermes --resume sid-h"


def _run_args(monkeypatch, module, *args):
    """Run task_tracker's main() in-process with the given CLI args; returns its exit code."""
    import sys
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", *args])
    return module.main()
