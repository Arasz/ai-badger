"""Tests for skills/task/scripts/user_prompt_hook.py.

Covers: session refresh on every prompt; `/task <id>` auto-registers a tracked entry (and a
matching token-usage checkpoint) when one doesn't exist yet; a prompt with no task id, or no
`/task` prefix at all, is a no-op for registration; malformed stdin JSON never raises; a
finished task referenced again is left untouched; a session collision with another task's
entry is skipped rather than stolen; and a registration failure (e.g. a corrupt tracking file)
never blocks the prompt.

Isolation is purely about redirecting tracker_lib's module-level path constants (shared across
the whole test session) into tmp_path, and feeding the hook's stdin payload directly — no
subprocess or network involved.
"""
from __future__ import annotations

import io
import json
import sys

import pytest


@pytest.fixture
def prompt_hook(tmp_path, load_script, monkeypatch):
    module = load_script("skills/task/scripts/user_prompt_hook.py")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(module.lib, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module.lib, "DATA_DIR", data_dir)
    monkeypatch.setattr(module.lib, "EXECUTED_TASKS", data_dir / "executed-tasks.json")
    monkeypatch.setattr(module.lib, "TOKEN_USAGE", data_dir / "token-usage.json")
    monkeypatch.setattr(module.lib, "CURRENT_SESSION", data_dir / "current-session.json")
    monkeypatch.setattr(module.lib, "LOCK_FILE", data_dir / ".write.lock")
    return module


def _run(module, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def _write_state(module, tasks=None, usage=None):
    module.lib.save_json(module.lib.EXECUTED_TASKS, {"tasks": tasks or []})
    module.lib.save_json(module.lib.TOKEN_USAGE, {"tasks": usage or []})


class TestTaskIdFromPrompt:
    def test_extracts_id_from_leading_task_invocation(self, prompt_hook):
        assert prompt_hook.task_id_from_prompt("/task T17 do the thing") == "T17"

    def test_extracts_id_with_colon_suffix_form(self, prompt_hook):
        assert prompt_hook.task_id_from_prompt("/task:continue T17 keep going") == "T17"

    def test_extracts_id_from_namespaced_plugin_invocation(self, prompt_hook):
        assert prompt_hook.task_id_from_prompt("/ai-badger:task T17 do the thing") == "T17"

    def test_no_id_after_task_returns_none(self, prompt_hook):
        assert prompt_hook.task_id_from_prompt("/task") is None

    def test_non_task_prompt_returns_none(self, prompt_hook):
        assert prompt_hook.task_id_from_prompt("please review /task T17") is None


class TestSessionRefresh:
    def test_session_saved_on_every_prompt_regardless_of_task_id(self, prompt_hook, monkeypatch):
        calls = []
        monkeypatch.setattr(
            prompt_hook.lib, "save_current_session",
            lambda sid, transcript, cwd="": calls.append((sid, transcript, cwd)),
        )

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "/tmp/t.jsonl",
            "cwd": "/repo", "prompt": "just chatting, no task marker",
        })

        assert rc == 0
        assert calls == [("sid-1", "/tmp/t.jsonl", "/repo")]

    def test_missing_session_id_does_not_save_session(self, prompt_hook, monkeypatch):
        calls = []
        monkeypatch.setattr(
            prompt_hook.lib, "save_current_session", lambda *a, **k: calls.append(a)
        )

        rc = _run(prompt_hook, monkeypatch, {"prompt": "/task T17 do the thing"})

        assert rc == 0
        assert calls == []


class TestRegistration:
    def test_task_invocation_registers_new_entry(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "/task T17 do the thing",
        })

        assert rc == 0
        tasks = prompt_hook.lib.load_tasks()["tasks"]
        assert len(tasks) == 1
        entry = tasks[0]
        assert entry["taskId"] == "T17"
        assert entry["sessionId"] == "sid-1"
        assert entry["state"] == prompt_hook.lib.STATE_STARTED
        assert entry["resumeCommand"] == "claude --resume sid-1"
        usage = prompt_hook.lib.load_usage()["tasks"]
        assert usage[0]["taskId"] == "T17"
        assert "start" in usage[0]["checkpoints"]
        assert "latest" in usage[0]["checkpoints"]

    def test_namespaced_plugin_task_invocation_registers_new_entry(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "",
            "prompt": "/ai-badger:task T17 do the thing",
        })

        assert rc == 0
        tasks = prompt_hook.lib.load_tasks()["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["taskId"] == "T17"

    def test_prompt_with_no_task_id_is_a_noop(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "/task",
        })

        assert rc == 0
        assert not prompt_hook.lib.EXECUTED_TASKS.exists()

    def test_non_task_prompt_is_a_noop(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "what does this code do?",
        })

        assert rc == 0
        assert not prompt_hook.lib.EXECUTED_TASKS.exists()

    def test_finished_task_referenced_again_is_left_untouched(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)
        _write_state(prompt_hook, tasks=[{
            "taskId": "T17", "sessionId": "old-sid", "state": prompt_hook.lib.STATE_FINISHED,
        }])

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "new-sid", "transcript_path": "", "prompt": "/task T17 revisit",
        })

        assert rc == 0
        entry = prompt_hook.lib.load_tasks()["tasks"][0]
        assert entry["sessionId"] == "old-sid"

    def test_session_already_owned_by_another_unfinished_task_is_not_stolen(
        self, prompt_hook, monkeypatch
    ):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)
        _write_state(prompt_hook, tasks=[{
            "taskId": "T01", "sessionId": "sid-1", "state": prompt_hook.lib.STATE_IN_PROGRESS,
        }])

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "/task T17 new task",
        })

        assert rc == 0
        tasks = prompt_hook.lib.load_tasks()["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["taskId"] == "T01"

    def test_registration_is_idempotent_across_prompts(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)

        _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "/task T17 do the thing",
        })
        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "/task T17 keep going",
        })

        assert rc == 0
        tasks = prompt_hook.lib.load_tasks()["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["state"] == prompt_hook.lib.STATE_STARTED


class TestFailureHandling:
    def test_malformed_stdin_json_returns_zero_without_raising(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))

        assert prompt_hook.main() == 0

    def test_registration_failure_does_not_block_the_prompt(self, prompt_hook, monkeypatch):
        monkeypatch.setattr(prompt_hook.lib, "save_current_session", lambda *a, **k: None)

        def _boom(*_args, **_kwargs):
            raise OSError("tracking file is corrupt")

        monkeypatch.setattr(prompt_hook, "_register_task", _boom)

        rc = _run(prompt_hook, monkeypatch, {
            "session_id": "sid-1", "transcript_path": "", "prompt": "/task T17 do the thing",
        })

        assert rc == 0
