"""Tests for skills/task/scripts/stop_hook.py.

Covers: no session_id / invalid stdin JSON are no-ops; STARTED -> IN_PROGRESS promotion with a
token checkpoint; the two independent end-of-task nag branches (state.json never updated,
CLAUDE.md over its size budget) each firing on their own and setting their one-shot reminder
flag; the clean/no-nag path when everything is fine; already-sent reminder flags not re-firing;
and `stop_hook_active` suppressing the FINISHED-task enforcement entirely.

No subprocess is involved in this script, so nothing needs mocking there — isolation is purely
about redirecting tracker_lib's module-level path constants (shared across the whole test
session) into tmp_path, and feeding the hook's stdin payload directly.
"""
from __future__ import annotations

import io
import json
import sys

import pytest


@pytest.fixture
def stop_hook(tmp_path, load_script, monkeypatch):
    module = load_script("skills/task/scripts/stop_hook.py")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(module.lib, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module.lib, "DATA_DIR", data_dir)
    monkeypatch.setattr(module.lib, "EXECUTED_TASKS", data_dir / "executed-tasks.json")
    monkeypatch.setattr(module.lib, "TOKEN_USAGE", data_dir / "token-usage.json")
    monkeypatch.setattr(module.lib, "LOCK_FILE", data_dir / ".write.lock")
    monkeypatch.setattr(module.lib, "STATE_JSON", tmp_path / ".ai-badger" / "state.json")
    monkeypatch.setattr(module.lib, "CLAUDE_MD", tmp_path / "CLAUDE.md")
    # Snapshot so nothing here leaks the shared tracker_lib module's budget globals to other
    # test files (see test_claude_md_compact.py's fixture docstring for why this matters).
    monkeypatch.setattr(module.lib, "CLAUDE_MD_MAX_CHARS", module.lib.CLAUDE_MD_MAX_CHARS)
    monkeypatch.setattr(module.lib, "CLAUDE_MD_MAX_LINES", module.lib.CLAUDE_MD_MAX_LINES)
    return module


def _run_hook(module, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def _write_state(module, tasks=None, usage=None):
    module.lib.save_json(module.lib.EXECUTED_TASKS, {"tasks": tasks or []})
    module.lib.save_json(module.lib.TOKEN_USAGE, {"tasks": usage or []})


def test_no_session_id_returns_zero_without_touching_tasks(stop_hook, monkeypatch, capsys):
    rc = _run_hook(stop_hook, monkeypatch, {"transcript_path": "/tmp/x.jsonl"})

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert not stop_hook.lib.EXECUTED_TASKS.exists()


def test_invalid_stdin_json_returns_zero(stop_hook, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))

    assert stop_hook.main() == 0


def test_started_task_promotes_to_in_progress_with_checkpoint(stop_hook, monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("", encoding="utf-8")
    _write_state(
        stop_hook,
        tasks=[{
            "taskId": "T01", "sessionId": "sid-1", "state": "STARTED",
            "startedAt": stop_hook.lib.now_iso(),
        }],
        usage=[{"taskId": "T01", "checkpoints": {}}],
    )

    rc = _run_hook(stop_hook, monkeypatch, {
        "session_id": "sid-1", "transcript_path": str(transcript),
    })

    assert rc == 0
    tasks = stop_hook.lib.load_tasks()
    assert tasks["tasks"][0]["state"] == "IN_PROGRESS"
    usage = stop_hook.lib.load_usage()
    assert "latest" in usage["tasks"][0]["checkpoints"]


def test_finished_task_without_state_json_update_blocks_once(stop_hook, monkeypatch, tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("short\n", encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(),
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["decision"] == "block"
    assert "state.json was not updated" in payload["reason"]
    assert "CLAUDE.md" not in payload["reason"]
    entry = stop_hook.lib.load_tasks()["tasks"][0]
    assert entry["stateJsonReminderSent"] is True


def test_finished_task_claude_md_over_budget_blocks_with_compaction_reason(
    stop_hook, monkeypatch, tmp_path, capsys
):
    (tmp_path / "CLAUDE.md").write_text("x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(), "stateJsonUpdated": True,
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["decision"] == "block"
    assert "CLAUDE.md is over its size budget" in payload["reason"]
    assert "state.json was not updated" not in payload["reason"]
    entry = stop_hook.lib.load_tasks()["tasks"][0]
    assert entry["compactionReminderSent"] is True


def test_finished_task_clean_state_produces_no_nag(stop_hook, monkeypatch, tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("short\n", encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(), "stateJsonUpdated": True,
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_reminders_already_sent_do_not_nag_again(stop_hook, monkeypatch, tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(),
        "stateJsonReminderSent": True, "compactionReminderSent": True,
    }])

    rc = _run_hook(stop_hook, monkeypatch, {"session_id": "sid-1", "transcript_path": ""})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_stop_hook_active_flag_suppresses_finished_task_enforcement(
    stop_hook, monkeypatch, tmp_path, capsys
):
    (tmp_path / "CLAUDE.md").write_text("x" * 20000, encoding="utf-8")
    _write_state(stop_hook, tasks=[{
        "taskId": "T01", "sessionId": "sid-1", "state": "FINISHED",
        "startedAt": stop_hook.lib.now_iso(),
    }])

    rc = _run_hook(stop_hook, monkeypatch, {
        "session_id": "sid-1", "transcript_path": "", "stop_hook_active": True,
    })

    assert rc == 0
    assert capsys.readouterr().out == ""
    entry = stop_hook.lib.load_tasks()["tasks"][0]
    assert "stateJsonReminderSent" not in entry
