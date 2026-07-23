"""Tests for skills/task/scripts/statusline_capture.py.

Ported from the originating job-search-ai-assistant repo's test_statusline_capture.py to this
repo's pytest + load_script pattern.
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch


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


def test_render_user_statusline_returns_zero_when_no_user_script(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")

    with patch.object(statusline_capture, "USER_STATUSLINE", tmp_path / "missing.sh"):
        rc = statusline_capture.render_user_statusline("{}")

    assert rc == 0


def test_render_user_statusline_prints_user_script_stdout(tmp_path, load_script, capsys):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    script = tmp_path / "statusline.sh"
    script.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    script.chmod(0o755)

    with patch.object(statusline_capture, "USER_STATUSLINE", script):
        rc = statusline_capture.render_user_statusline("hello-input")

    assert rc == 0
    assert capsys.readouterr().out == "hello-input"


def test_main_reads_stdin_captures_and_renders(tmp_path, load_script, capsys, monkeypatch):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    state_path = tmp_path / "statusline-state.json"
    payload = {"session_id": "sid-1"}

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with patch.object(statusline_capture, "STATUSLINE_STATE", state_path), \
         patch.object(statusline_capture, "USER_STATUSLINE", tmp_path / "missing.sh"):
        rc = statusline_capture.main()

    assert rc == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["sessionId"] == "sid-1"
