"""PreToolUse/PostToolUse hook for the memory-first gate: stdin payload -> deny JSON.

Exit 0 on every path is a hard requirement: Copilot command preToolUse hooks are
fail-closed, so a crash would deny the tool call it was only meant to gate.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json
import sys

import pytest


@pytest.fixture
def hook(load_script, monkeypatch, tmp_path):
    """The real hook module, with the gate sibling redirected to tmp marker paths."""
    real = load_script(
        "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setitem(sys.modules, "memory_first_gate", real)
    return load_script(
        "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate_hook.py")


def _run(hook, monkeypatch, payload, argv=None):
    monkeypatch.setattr("sys.stdin", io.StringIO(
        payload if isinstance(payload, str) else json.dumps(payload)))
    return hook.main(argv or [])


def _out(capsys):
    return json.loads(capsys.readouterr().out)


# ------------------------------------------------------------------ gate mode
def test_claude_grep_without_marker_is_denied(hook, monkeypatch, capsys):
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "t1",
        "cwd": "/Users/arasz/RiderProjects/ai-raccoon",
        "tool_name": "Grep",
        "tool_input": {"pattern": "MemorySearch"},
    }

    rc = _run(hook, monkeypatch, payload)

    assert rc == 0
    out = _out(capsys)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "memory_search" in out["permissionDecisionReason"]


def test_claude_search_after_marker_passes(hook, monkeypatch, capsys, tmp_path):
    (tmp_path / "memory-first").mkdir()
    (tmp_path / "memory-first" / "t1").touch()
    payload = {"hook_event_name": "PreToolUse", "session_id": "t1",
               "tool_name": "Grep", "tool_input": {"pattern": "x"}}

    rc = _run(hook, monkeypatch, payload)

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_claude_non_search_tool_passes(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, {
        "hook_event_name": "PreToolUse", "session_id": "t1",
        "tool_name": "Read", "tool_input": {"file_path": "a.cs"}})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_copilot_camelcase_payload_is_denied(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, {
        "hookEventName": "preToolUse",
        "sessionId": "c1",
        "cwd": "/Users/arasz/RiderProjects/ai-raccoon",
        "toolName": "grep",
        "toolArgs": {"pattern": "x"}})

    assert rc == 0
    out = _out(capsys)
    assert out["permissionDecision"] == "deny"
    assert "memory_search" in out["permissionDecisionReason"]


def test_copilot_bash_search_command_is_denied(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, {
        "hookEventName": "preToolUse", "sessionId": "c1",
        "toolName": "bash", "toolArgs": {"command": "grep -r foo src/"}})

    assert rc == 0
    assert _out(capsys)["permissionDecision"] == "deny"


def test_copilot_bash_build_command_passes(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, {
        "hookEventName": "preToolUse", "sessionId": "c1",
        "toolName": "bash", "toolArgs": {"command": "dotnet build"}})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_copilot_view_passes(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, {
        "hookEventName": "preToolUse", "sessionId": "c1",
        "toolName": "view", "toolArgs": {"path": "a.cs"}})

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_three_strikes_pass_through(hook, monkeypatch, capsys):
    """After MAX_DENIALS denials the gate stops blocking — an agent cannot stall."""
    payload = {"hook_event_name": "PreToolUse", "session_id": "strike",
               "tool_name": "Grep", "tool_input": {"pattern": "x"}}
    for _ in range(3):
        rc = _run(hook, monkeypatch, payload)
        assert rc == 0
        assert _out(capsys)["hookSpecificOutput"]["permissionDecision"] == "deny"

    rc = _run(hook, monkeypatch, payload)
    assert rc == 0
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ recorder mode
def test_record_mode_touches_marker(hook, monkeypatch, capsys, tmp_path):
    rc = _run(hook, monkeypatch, {
        "hook_event_name": "PostToolUse", "session_id": "sess-r",
        "tool_name": "memory_search", "tool_input": {"query": "q"}}, argv=["--record"])

    assert rc == 0
    assert (tmp_path / "memory-first" / "sess-r").is_file()
    assert capsys.readouterr().out == ""


def test_record_mode_ignores_non_search_tools(hook, monkeypatch, capsys, tmp_path):
    rc = _run(hook, monkeypatch, {
        "hook_event_name": "PostToolUse", "session_id": "sess-r",
        "tool_name": "terminal", "tool_input": {"command": "dotnet build"}},
        argv=["--record"])

    assert rc == 0
    assert not (tmp_path / "memory-first").exists()
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ crash safety
def test_malformed_json_exits_zero_with_empty_output(hook, monkeypatch, capsys):
    rc = _run(hook, monkeypatch, "not json at all")

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_never_raises_on_bizarre_payloads(hook, monkeypatch, capsys):
    for payload in (None, 42, [], {"tool_name": 7}, {"toolName": {"nested": True}}):
        rc = _run(hook, monkeypatch, payload)
        assert rc == 0
        assert capsys.readouterr().out == ""
