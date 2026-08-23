"""Tests for skills/prompt-markers/scripts/grounded_feedback_hook.py (PostToolUse hook).

Covers: non-Bash tools are silent, zero exit is silent, non-zero exit captures output,
output truncation, malformed payloads, and internal error handling.
"""
from __future__ import annotations

import io
import json

import pytest


def _call_main(module, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return module.main()


def test_non_bash_tool_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Edit",
        "tool_result": {"exit_code": 1, "output": "error"},
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_zero_exit_code_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_result": {"exit_code": 0, "output": "all good"},
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_non_zero_exit_captures_output(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_result": {"exit_code": 1, "output": "FAILED: test_foo broke\nAssertionError: 1 != 2"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "GROUNDED FEEDBACK" in ctx
    assert "exited with code 1" in ctx
    assert "test_foo broke" in ctx


def test_empty_output_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_result": {"exit_code": 1, "output": ""},
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_output_truncated_to_max_lines(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    long_output = "\n".join(f"line {i}" for i in range(100))
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_result": {"exit_code": 1, "output": long_output},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "line 99" in ctx  # last line preserved
    assert "line 0" not in ctx  # first line truncated


def test_malformed_payload_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    rc = hook.main()
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_tool_name_variant_toolName(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "toolName": "Bash",
        "tool_result": {"exit_code": 2, "output": "command not found"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "GROUNDED FEEDBACK" in out["hookSpecificOutput"]["additionalContext"]


def test_exit_code_variant_exitCode(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_result": {"exitCode": 127, "output": "not found"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "exited with code 127" in out["hookSpecificOutput"]["additionalContext"]
