"""Claude session source: the transcript-based tracker data path.

Every agent's session source registers the same way — a module delivered by
features/<agent>/adjustments/ into the scaffolded task skill scripts. Claude's source is the
transcript reader: it resolves the session from CLAUDE_CODE_SESSION_ID (with the pid/cwd
fallbacks against current-session.json), checkpoints from the JSONL transcript, and resumes
with `claude --resume`. These tests pin the claude data path and the equality with other
agents' sources: nothing is built in, everything is registered.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from conftest import _test_write

TRACKER_RELPATH = "features/common/skills/task/scripts/task_tracker.py"
LIB_RELPATH = "features/common/skills/task/scripts/tracker_lib.py"
CLAUDE_RELPATH = "features/claude/adjustments/claude_session_source.py"


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
    claude = load_script(CLAUDE_RELPATH)
    claude.register(module.lib)
    module._claude = claude
    monkeypatch.setattr(module, "subprocess", _GuardedSubprocess())
    return module


@pytest.fixture
def cs(load_script, root, monkeypatch):
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    return load_script(CLAUDE_RELPATH)


def _run(monkeypatch, module, *args):
    """Call task_tracker's main() in-process (no subprocess) with the given CLI args."""
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", *args])
    return module.main()


class TestResolveOwnSessionClaude:
    def test_resolve_own_session_uses_env_var_when_session_is_known(self, load_script,
                                                                    monkeypatch, tmp_path,
                                                                    cs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        cs.register(tl)
        tl.ensure_data_dir()
        _test_write(tl.CURRENT_SESSION, json.dumps({
            "sessions": {"sid-1": {"transcriptPath": "/tmp/a.jsonl", "cwd": "/a",
                                   "pid": 424242}}}), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-1")

        resolved = tl.resolve_own_session()

        assert resolved["sessionId"] == "sid-1"
        assert resolved["source"] == "claude"
        assert resolved["transcriptPath"] == "/tmp/a.jsonl"

    def test_resolve_own_session_env_var_set_but_not_yet_recorded(self, load_script,
                                                                  monkeypatch, tmp_path, cs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        cs.register(tl)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-unrecorded")

        resolved = tl.resolve_own_session()

        assert resolved == {"sessionId": "sid-unrecorded", "transcriptPath": None,
                            "source": "claude"}

    def test_resolve_own_session_matches_via_pid_ancestry(self, load_script, tmp_path,
                                                          monkeypatch, cs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        cs.register(tl)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        tl.ensure_data_dir()
        _test_write(tl.CURRENT_SESSION, json.dumps({
            "sessions": {"anc-sid": {"transcriptPath": "/tmp/a.jsonl", "cwd": "/a",
                                     "pid": 424242}}}), encoding="utf-8")
        tl._own_pid_ancestry = lambda max_depth=12: [1, 424242]

        resolved = tl.resolve_own_session()

        assert resolved["sessionId"] == "anc-sid"
        assert resolved["source"] == "claude"

    def test_resolve_own_session_matches_via_unique_cwd(self, load_script, tmp_path,
                                                        monkeypatch, cs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        cs.register(tl)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.chdir(tmp_path)
        tl._own_pid_ancestry = lambda max_depth=12: []
        tl.ensure_data_dir()
        _test_write(tl.CURRENT_SESSION, json.dumps({
            "sessions": {"cwd-sid": {"transcriptPath": "/tmp/c.jsonl", "cwd": str(tmp_path)}},
        }), encoding="utf-8")

        resolved = tl.resolve_own_session()

        assert resolved["sessionId"] == "cwd-sid"
        assert resolved["source"] == "claude"

    def test_resolve_own_session_ambiguous_cwd_returns_empty(self, load_script, tmp_path,
                                                             monkeypatch, cs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        cs.register(tl)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.chdir(tmp_path)
        tl._own_pid_ancestry = lambda max_depth=12: []
        tl.ensure_data_dir()
        _test_write(tl.CURRENT_SESSION, json.dumps({
            "sessions": {
                "sid-a": {"transcriptPath": "/tmp/a.jsonl", "cwd": str(tmp_path)},
                "sid-b": {"transcriptPath": "/tmp/b.jsonl", "cwd": str(tmp_path)},
            }
        }), encoding="utf-8")

        resolved = tl.resolve_own_session()

        assert resolved == {}

    def test_resolve_own_session_returns_empty_when_nothing_matches(self, load_script,
                                                                    tmp_path, monkeypatch, cs):
        tl = load_script(LIB_RELPATH)
        tl.PROJECT_ROOT = tmp_path
        tl.DATA_DIR = tmp_path / ".ai-badger" / "task-tracking"
        tl.CURRENT_SESSION = tmp_path / ".ai-badger" / "task-tracking" / "current-session.json"
        cs.register(tl)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.chdir(tmp_path)
        tl._own_pid_ancestry = lambda max_depth=12: []

        resolved = tl.resolve_own_session()

        assert resolved == {}


class TestClaudeCli:
    def test_start_under_claude_records_transcript_checkpoint_and_claude_resume(
            self, tt, monkeypatch, tmp_path):
        transcript = tmp_path / "s.jsonl"
        _test_write(transcript, json.dumps({
            "type": "assistant",
            "message": {"usage": {"input_tokens": 900, "output_tokens": 100,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0},
                        "model": "opus-5"},
        }) + "\n", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-c")

        code = _run(monkeypatch, tt, "start", "T-C1", "--no-worktree", "--no-cron",
                    "--transcript-path", str(transcript))

        assert code == 0
        tasks = json.loads((tt.lib.EXECUTED_TASKS).read_text())["tasks"]
        entry = next(t for t in tasks if t["taskId"] == "T-C1")
        assert entry["resumeCommand"] == "claude --resume sid-c"
        assert entry.get("trackingSource") == "claude"
        usage = json.loads(tt.lib.TOKEN_USAGE.read_text())["tasks"]
        uentry = next(t for t in usage if t["taskId"] == "T-C1")
        assert uentry["checkpoints"]["start"]["cumulative"]["inputTokens"] == 900

    def test_start_with_explicit_session_id_and_no_transcript_source_is_a_clear_refusal(
            self, load_script, root, monkeypatch, tmp_path):
        """No transcript source registered: an explicit --session-id has nothing to
        attribute it to — a clear refusal, not a silent claude default."""
        import pytest
        scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
        monkeypatch.syspath_prepend(scripts_dir)
        module = load_script(TRACKER_RELPATH)
        _redirect_lib(module.lib, tmp_path)
        monkeypatch.setattr(module, "subprocess", _GuardedSubprocess())
        # tracker_lib is module-cached: isolate this test's registry so no other test's
        # registered source leaks in.
        monkeypatch.setattr(module.lib, "SESSION_SOURCES", {})

        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, module, "start", "T-C2", "--no-worktree", "--no-cron",
                 "--session-id", "sid-x")

        assert exc.value.code == 2

    def test_finish_under_claude_computes_usage(self, tt, monkeypatch, tmp_path):
        transcript = tmp_path / "s2.jsonl"
        _test_write(transcript, json.dumps({
            "type": "assistant",
            "message": {"usage": {"input_tokens": 900, "output_tokens": 100,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0},
                        "model": "opus-5"},
        }) + "\n", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-c2")
        _run(monkeypatch, tt, "start", "T-C3", "--no-worktree", "--no-cron",
             "--transcript-path", str(transcript))
        # The transcript grows as the task's work lands.
        _test_write(transcript, json.dumps({
            "type": "assistant",
            "message": {"usage": {"input_tokens": 1900, "output_tokens": 300,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0},
                        "model": "opus-5"},
        }) + "\n", encoding="utf-8")
        state = tmp_path / ".ai-badger" / "state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        _test_write(state, "{}")
        _run(monkeypatch, tt, "finish", "T-C3", "--force")

        usage = json.loads(tt.lib.TOKEN_USAGE.read_text())["tasks"]
        uentry = next(t for t in usage if t["taskId"] == "T-C3")
        assert uentry["usage"]["inputTokens"] == 1000
        assert uentry["usage"]["grandTotal"] > 0


def _run_args(monkeypatch, module, *args):
    """Run task_tracker's main() in-process with the given CLI args; returns its exit code."""
    import sys
    monkeypatch.setattr(sys, "argv", ["task_tracker.py", *args])
    return module.main()
