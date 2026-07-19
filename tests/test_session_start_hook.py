"""Tests for skills/task/scripts/session_start_hook.py.

The script (as it exists in this repo) does exactly two things and nothing more — no
background poller is launched here (verified by reading the source: it's a plain stdin-in,
stdout-out hook with a single `lib.save_current_session` call):

1. Records the invoking session (id, transcript path, cwd) via tracker_lib.save_current_session,
   whenever session_id is present on the SessionStart payload.
2. On `source == "resume"` with unfinished tracked tasks, prints a SessionStart
   hookSpecificOutput/additionalContext nudge listing them; otherwise prints nothing.

save_current_session is mocked so no real .ai-badger/task-tracking file is ever touched outside
tmp_path, and to assert the exact arguments the hook passes it.
"""
from __future__ import annotations

import io
import json
import sys

import pytest


@pytest.fixture
def session_start(tmp_path, load_script, monkeypatch):
    module = load_script("skills/task/scripts/session_start_hook.py")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(module.lib, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module.lib, "DATA_DIR", data_dir)
    monkeypatch.setattr(module.lib, "EXECUTED_TASKS", data_dir / "executed-tasks.json")
    return module


def _run(module, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def test_saves_current_session_with_payload_fields(session_start, monkeypatch):
    calls = []
    monkeypatch.setattr(
        session_start.lib, "save_current_session",
        lambda sid, transcript, cwd="": calls.append((sid, transcript, cwd)),
    )

    rc = _run(session_start, monkeypatch, {
        "session_id": "sid-1", "transcript_path": "/tmp/t.jsonl", "cwd": "/repo",
    })

    assert rc == 0
    assert calls == [("sid-1", "/tmp/t.jsonl", "/repo")]


def test_missing_session_id_does_not_save_session(session_start, monkeypatch):
    calls = []
    monkeypatch.setattr(
        session_start.lib, "save_current_session", lambda *a, **k: calls.append(a)
    )

    rc = _run(session_start, monkeypatch, {"transcript_path": "/tmp/t.jsonl"})

    assert rc == 0
    assert calls == []


def test_invalid_stdin_json_returns_zero_without_saving(session_start, monkeypatch):
    calls = []
    monkeypatch.setattr(
        session_start.lib, "save_current_session", lambda *a, **k: calls.append(a)
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))

    assert session_start.main() == 0
    assert calls == []


def test_resume_source_with_unfinished_tasks_prints_additional_context(
    session_start, monkeypatch, capsys
):
    monkeypatch.setattr(session_start.lib, "save_current_session", lambda *a, **k: None)
    session_start.lib.save_json(session_start.lib.EXECUTED_TASKS, {"tasks": [
        {"taskId": "T01", "state": "IN_PROGRESS"},
        {"taskId": "T02", "state": "FINISHED"},
    ]})

    rc = _run(session_start, monkeypatch, {"session_id": "sid-1", "source": "resume"})

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "T01" in out["hookSpecificOutput"]["additionalContext"]
    assert "T02" not in out["hookSpecificOutput"]["additionalContext"]


def test_resume_source_without_unfinished_tasks_prints_nothing(session_start, monkeypatch, capsys):
    monkeypatch.setattr(session_start.lib, "save_current_session", lambda *a, **k: None)
    session_start.lib.save_json(session_start.lib.EXECUTED_TASKS, {"tasks": [
        {"taskId": "T01", "state": "FINISHED"},
    ]})

    rc = _run(session_start, monkeypatch, {"session_id": "sid-1", "source": "resume"})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_non_resume_source_prints_nothing_even_with_unfinished_tasks(
    session_start, monkeypatch, capsys
):
    monkeypatch.setattr(session_start.lib, "save_current_session", lambda *a, **k: None)
    session_start.lib.save_json(session_start.lib.EXECUTED_TASKS, {"tasks": [
        {"taskId": "T01", "state": "IN_PROGRESS"},
    ]})

    rc = _run(session_start, monkeypatch, {"session_id": "sid-1", "source": "startup"})

    assert rc == 0
    assert capsys.readouterr().out == ""
