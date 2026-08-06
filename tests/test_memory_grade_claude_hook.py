"""Claude PostToolUse entry for memory-grade: stdin payload → logged line + grade ask.

Advisory only: `additionalContext` alone, exit 0, never `decision`/`permissionDecision`/
`continue` — same discipline as commit_reminder_hook.py (docs/changelog/0.33.0).
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json
import sys

import pytest

ENV = "AI_BADGER_MEMORY_GRADE"


@pytest.fixture
def hook(load_script, monkeypatch, tmp_path):
    """The real hook module, with the memory_grade sibling redirected to tmp paths."""
    real = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_grade.py")
    monkeypatch.setattr(real, "LOG_FILE", tmp_path / "memory-quality.jsonl")
    monkeypatch.setattr(real, "PENDING_FILE", tmp_path / "pending.json")
    monkeypatch.setitem(sys.modules, "memory_grade", real)
    return load_script("features/common/skills/ai-raccoon-memory/scripts/memory_grade_hook.py")


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(ENV, "1")


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _run(hook, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return hook.main()


def _all_keys(obj):
    """Flatten every dict key anywhere in a parsed JSON object."""
    keys = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for value in obj.values():
            keys.update(_all_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_all_keys(item))
    return keys


def test_claude_hook_stdin_payload_appends_line_and_emits_additional_context(
        hook, monkeypatch, tmp_path, capsys, on):
    payload = {
        "tool_name": "memory_search",
        "tool_input": {"project_id": "probe", "query": "q", "scope": "all"},
        "tool_response": {"results": [{"sourceFile": "a.md", "score": 1}]},
        "session_id": "claude-sess-1",
    }

    rc = _run(hook, monkeypatch, payload)

    assert rc == 0
    lines = (tmp_path / "memory-quality.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert line["projectId"] == "probe"
    assert line["result"] == {"results": [{"sourceFile": "a.md", "score": 1}]}
    assert line["host"] == "claude"
    assert line["sessionId"] == "claude-sess-1"
    assert line["usefulness"] is None

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    ask = out["hookSpecificOutput"]["additionalContext"]
    assert f"grade {line['ts']}" in ask
    forbidden = {"decision", "permissionDecision", "continue"}
    assert _all_keys(out) & forbidden == set()


def test_claude_hook_silent_on_non_search_tool(hook, monkeypatch, tmp_path, capsys, on):
    rc = _run(hook, monkeypatch, {"tool_name": "terminal", "tool_input": {},
                                  "tool_response": {}})

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "memory-quality.jsonl").exists()


def test_claude_hook_silent_when_disabled(hook, monkeypatch, tmp_path, capsys, off):
    rc = _run(hook, monkeypatch, {"tool_name": "memory_search", "tool_input": {},
                                  "tool_response": {}})

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "memory-quality.jsonl").exists()


def test_hooks_json_post_tool_use_wires_the_script(root):
    hooks_json = json.loads(
        (root / "features" / "common" / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    entries = [e for e in hooks_json["hooks"]["PostToolUse"]
               if e.get("matcher") == "memory_search"]
    assert len(entries) == 1
    commands = [h["command"] for h in entries[0]["hooks"]]
    assert len(commands) == 1
    assert "memory_grade_hook.py" in commands[0]


def test_claude_hook_does_not_stash_a_pending_ask(
        hook, monkeypatch, tmp_path, capsys, on):
    """F1: the Claude transport returns the ask directly — it must not leave a
    pending ask that a later Hermes session in the same project would pop."""
    payload = {
        "tool_name": "memory_search",
        "tool_input": {"projectId": "probe", "query": "q"},
        "tool_response": {"results": []},
        "cwd": str(tmp_path),
    }

    rc = _run(hook, monkeypatch, payload)

    assert rc == 0
    assert not (tmp_path / "pending.json").exists()
    out = json.loads(capsys.readouterr().out)
    assert "additionalContext" in out["hookSpecificOutput"]
