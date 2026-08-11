"""Tests for skills/task/scripts/statusline_capture.py.

Ported from the originating job-search-ai-assistant repo's test_statusline_capture.py to this
repo's pytest + load_script pattern.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from unittest.mock import patch
from conftest import _test_write

REALISTIC_PAYLOAD = {
    "session_id": "ff836f92-f769-4a31-ae00-ff0585e741b1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/repo",
    "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
    "workspace": {"current_dir": "/repo", "project_dir": "/repo", "added_dirs": []},
    "version": "2.1.220",
    "context_window": {"context_window_size": 1000000, "used_percentage": 12},
    "rate_limits": {
        "five_hour": {"used_percentage": 91, "resets_at": 2000000000},
        "seven_day": {"used_percentage": 20},
    },
}


def test_end_to_end_capture_writes_state_and_delegates_to_the_recorded_renderer(tmp_path, root):
    """The wired command, run as Claude Code runs it: state persisted, renderer output relayed."""
    data_dir = tmp_path / ".ai-badger" / "task-tracking"
    data_dir.mkdir(parents=True)
    _test_write(tmp_path / ".ai-badger" / "config.json", "{}", encoding="utf-8")
    renderer = tmp_path / "renderer.sh"
    _test_write(renderer, "#!/bin/sh\nprintf 'rendered:'\ncat\n", encoding="utf-8")
    renderer.chmod(0o755)
    _test_write(data_dir / "statusline-delegate.json", json.dumps({"command": str(renderer)}), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
    env.pop("CLAUDE_USER_STATUSLINE", None)

    result = subprocess.run(
        [sys.executable,
         str(root / "features/common/skills/task/scripts/statusline_capture.py")],
        input=json.dumps(REALISTIC_PAYLOAD), text=True, capture_output=True,
        env=env, timeout=30, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("rendered:"), result.stdout
    assert json.loads(result.stdout[len("rendered:"):]) == REALISTIC_PAYLOAD
    state = json.loads((data_dir / "statusline-state.json").read_text(encoding="utf-8"))
    assert state["rateLimits"]["five_hour"]["resets_at"] == 2000000000
    assert state["sessionId"] == REALISTIC_PAYLOAD["session_id"]


def test_capture_persists_rate_limit_metadata(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    state_path = tmp_path / "statusline-state.json"
    payload = {
        "session_id": "sid-1",
        "transcript_path": "/tmp/transcript.jsonl",
        "rate_limits": {
            "five_hour": {"used_percentage": 91, "resets_at": 2000000000},
            "seven_day": {"used_percentage": 20},
        },
        "context_window": {"used_percentage": 12},
        "model": {"display_name": "Claude"},
    }

    with patch.object(statusline_capture, "STATUSLINE_STATE", state_path):
        statusline_capture.capture_statusline(json.dumps(payload))

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["sessionId"] == "sid-1"
    assert state["rateLimits"]["five_hour"]["resets_at"] == 2000000000
    assert state["rateLimits"]["five_hour"]["used_percentage"] == 91
    assert state["contextWindow"] == {"used_percentage": 12}
    assert state["model"] == {"display_name": "Claude"}


def test_capture_falls_back_to_workspace_current_dir_for_cwd(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    state_path = tmp_path / "statusline-state.json"
    payload = {"workspace": {"current_dir": "/repo"}}

    with patch.object(statusline_capture, "STATUSLINE_STATE", state_path):
        statusline_capture.capture_statusline(json.dumps(payload))

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["cwd"] == "/repo"


def test_capture_silently_ignores_invalid_json(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    state_path = tmp_path / "statusline-state.json"

    with patch.object(statusline_capture, "STATUSLINE_STATE", state_path):
        statusline_capture.capture_statusline("not json")

    assert not state_path.exists()


def _record(module, tmp_path, command):
    """Point the module at a delegate record holding *command*."""
    path = tmp_path / "statusline-delegate.json"
    _test_write(path, json.dumps({"command": command}), encoding="utf-8")
    return patch.object(module, "DELEGATE_RECORD", path)


def test_render_user_statusline_returns_zero_when_the_delegate_is_missing(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")

    with _record(statusline_capture, tmp_path, str(tmp_path / "missing.sh")):
        rc = statusline_capture.render_user_statusline("{}")

    assert rc == 0


def test_render_user_statusline_prints_user_script_stdout(tmp_path, load_script, capsys):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    script = tmp_path / "statusline.sh"
    _test_write(script, "#!/bin/sh\ncat\n", encoding="utf-8")
    script.chmod(0o755)

    with _record(statusline_capture, tmp_path, str(script)):
        rc = statusline_capture.render_user_statusline("hello-input")

    assert rc == 0
    assert capsys.readouterr().out == "hello-input"


def test_main_reads_stdin_captures_and_renders(tmp_path, load_script, monkeypatch):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    state_path = tmp_path / "statusline-state.json"
    payload = {"session_id": "sid-1"}

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with patch.object(statusline_capture, "STATUSLINE_STATE", state_path), \
         _record(statusline_capture, tmp_path, None):
        rc = statusline_capture.main()

    assert rc == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["sessionId"] == "sid-1"


def test_no_maintainer_path_is_shipped_as_the_default(load_script, tmp_path):
    """A personal absolute path as the default made the feature dead for everyone else (F-20)."""
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")

    with patch.object(statusline_capture, "DELEGATE_RECORD", tmp_path / "absent.json"):
        assert statusline_capture.resolve_delegate() is None


def test_env_var_wins_over_the_scaffolded_record(load_script, monkeypatch, tmp_path):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    monkeypatch.setenv("CLAUDE_USER_STATUSLINE", "/from/env.sh")

    with _record(statusline_capture, tmp_path, "/from/record.sh"):
        assert statusline_capture.resolve_delegate() == "/from/env.sh"


def test_the_scaffolded_record_supplies_the_delegate_without_the_env_var(load_script,
                                                                        monkeypatch, tmp_path):
    """The env block reaching a statusLine command is undocumented, so the record must stand alone."""
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    monkeypatch.delenv("CLAUDE_USER_STATUSLINE", raising=False)

    with _record(statusline_capture, tmp_path, "/from/record.sh"):
        assert statusline_capture.resolve_delegate() == "/from/record.sh"


def test_an_unreadable_record_yields_no_delegate(load_script, monkeypatch, tmp_path):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    monkeypatch.delenv("CLAUDE_USER_STATUSLINE", raising=False)
    path = tmp_path / "statusline-delegate.json"
    _test_write(path, "{ not json", encoding="utf-8")

    with patch.object(statusline_capture, "DELEGATE_RECORD", path):
        assert statusline_capture.resolve_delegate() is None


def test_a_recorded_shell_command_is_run_through_a_shell(tmp_path, load_script, capsys,
                                                         monkeypatch):
    """A preserved renderer is a settings command string, not always a bare path."""
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    script = tmp_path / "statusline.sh"
    _test_write(script, "#!/bin/sh\ncat\n", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_USER_STATUSLINE", raising=False)

    with _record(statusline_capture, tmp_path, f'sh "{script}"'):
        rc = statusline_capture.render_user_statusline("shell-input")

    assert rc == 0
    assert capsys.readouterr().out == "shell-input"


def test_a_tilde_in_the_recorded_command_is_expanded(tmp_path, load_script, capsys, monkeypatch):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_USER_STATUSLINE", raising=False)
    script = tmp_path / "statusline.sh"
    _test_write(script, "#!/bin/sh\ncat\n", encoding="utf-8")
    script.chmod(0o755)

    with _record(statusline_capture, tmp_path, "~/statusline.sh"):
        rc = statusline_capture.render_user_statusline("tilde-input")

    assert rc == 0
    assert capsys.readouterr().out == "tilde-input"


def test_render_is_a_no_op_when_no_delegate_is_recorded(load_script, capsys, monkeypatch,
                                                        tmp_path):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    monkeypatch.delenv("CLAUDE_USER_STATUSLINE", raising=False)

    with _record(statusline_capture, tmp_path, None):
        rc = statusline_capture.render_user_statusline("{}")

    assert rc == 0
    assert capsys.readouterr().out == ""
