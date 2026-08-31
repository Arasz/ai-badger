"""Tests for skills/task/scripts/statusline_capture.py.

Ported from the originating job-search-ai-assistant repo's test_statusline_capture.py to this
repo's pytest + load_script pattern. P0.3e: the capture writes the statusline KV row (and
reads the delegate row) through tracker_lib's store accessors, so state assertions read the
store and the DATA_DIR redirect (D9) replaces the per-path patches.
"""
from __future__ import annotations

import io
import importlib.util
import json
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from conftest import _test_write

ROOT = Path(__file__).resolve().parents[1]

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


def _statusline_state(data_dir):
    """The captured state KV row ('state') from the store over *data_dir*.

    Same two-family registration tracker_lib._task_families() uses; the legacy file, when
    it still exists (pre-migration), dual-reads as the weaker source (D5a).
    """
    spec = importlib.util.spec_from_file_location(
        "statusline_capture_test_badger_store",
        ROOT / "features/common/skills/task/scripts/badger_store.py")
    store_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(store_mod)
    os.environ[store_mod.TRACKING_ROOT_ENV] = str(data_dir)
    families = {
        "statusline": store_mod.Family(
            table="statusline", db="tracking",
            legacy_path=lambda: data_dir / "statusline-state.json",
            legacy_kind="kvdoc", row_key="state"),
        "statusline_delegate": store_mod.Family(
            table="statusline", db="tracking",
            legacy_path=lambda: data_dir / "statusline-delegate.json",
            legacy_kind="kvdoc", row_key="delegate"),
    }
    with closing(store_mod.open_tracking(families=families)) as store:
        return store.kv_get("statusline", "state", {})


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
    state = _statusline_state(data_dir)
    assert state["rateLimits"]["five_hour"]["resets_at"] == 2000000000
    assert state["sessionId"] == REALISTIC_PAYLOAD["session_id"]


def test_capture_persists_rate_limit_metadata(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
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

    with patch.object(statusline_capture.lib, "DATA_DIR", tmp_path):
        statusline_capture.capture_statusline(json.dumps(payload))

    state = _statusline_state(tmp_path)
    assert state["sessionId"] == "sid-1"
    assert state["rateLimits"]["five_hour"]["resets_at"] == 2000000000
    assert state["rateLimits"]["five_hour"]["used_percentage"] == 91
    assert state["contextWindow"] == {"used_percentage": 12}
    assert state["model"] == {"display_name": "Claude"}


def test_capture_falls_back_to_workspace_current_dir_for_cwd(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")
    payload = {"workspace": {"current_dir": "/repo"}}

    with patch.object(statusline_capture.lib, "DATA_DIR", tmp_path):
        statusline_capture.capture_statusline(json.dumps(payload))

    assert _statusline_state(tmp_path)["cwd"] == "/repo"


def test_capture_silently_ignores_invalid_json(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")

    with patch.object(statusline_capture.lib, "DATA_DIR", tmp_path):
        statusline_capture.capture_statusline("not json")

    assert not _statusline_state(tmp_path)


def _record(module, tmp_path, command):
    """Point the module's tracking dir at *tmp_path* holding a delegate record for *command*."""
    path = tmp_path / "statusline-delegate.json"
    _test_write(path, json.dumps({"command": command}), encoding="utf-8")
    return patch.object(module.lib, "DATA_DIR", tmp_path)


def test_render_user_statusline_returns_zero_when_the_delegate_is_missing(tmp_path, load_script):
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")

    with patch.object(statusline_capture.lib, "DATA_DIR", tmp_path):
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
    payload = {"session_id": "sid-1"}

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with _record(statusline_capture, tmp_path, None):
        rc = statusline_capture.main()

    assert rc == 0
    assert _statusline_state(tmp_path)["sessionId"] == "sid-1"


def test_no_maintainer_path_is_shipped_as_the_default(load_script, tmp_path):
    """A personal absolute path as the default made the feature dead for everyone else (F-20)."""
    statusline_capture = load_script("features/common/skills/task/scripts/statusline_capture.py")

    with patch.object(statusline_capture.lib, "DATA_DIR", tmp_path):
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
    _test_write(tmp_path / "statusline-delegate.json", "{ not json", encoding="utf-8")

    with patch.object(statusline_capture.lib, "DATA_DIR", tmp_path):
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
