"""Tests for skills/prompt-markers/scripts/grounded_feedback_hook.py (PostToolUse hook).

Covers: non-Bash tools are silent, zero exit is silent, non-zero exit captures output,
output truncation, malformed payloads, and internal error handling.

Also covers the PostToolUseFailure arm (P11, owner ruling D5=A): Claude's PostToolUse "Runs
immediately after a tool completes successfully" (hooks.md) and never fires on failure, so a
second, claude-only manifest entry wires this same script onto PostToolUseFailure, whose input
carries `error` (a leading `Exit code N` line, optionally, then the output) and `is_interrupt`
instead of `tool_response`/`exit_code`.
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
        "tool_response": {"exit_code": 1, "output": "error"},
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_zero_exit_code_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_response": {"exit_code": 0, "output": "all good"},
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_non_zero_exit_captures_output(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_response": {"exit_code": 1, "output": "FAILED: test_foo broke\nAssertionError: 1 != 2"},
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
        "tool_response": {"exit_code": 1, "output": ""},
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_output_truncated_to_max_lines(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    long_output = "\n".join(f"line {i}" for i in range(100))
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_response": {"exit_code": 1, "output": long_output},
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
        "toolResponse": {"exit_code": 2, "output": "command not found"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "GROUNDED FEEDBACK" in out["hookSpecificOutput"]["additionalContext"]


def test_exit_code_variant_exitCode(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_response": {"exitCode": 127, "output": "not found"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "exited with code 127" in out["hookSpecificOutput"]["additionalContext"]


def test_stderr_combined_with_stdout(load_script, monkeypatch, capsys):
    """Both streams are preserved when stdout has progress and stderr the diagnostic."""
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_response": {
            "exit_code": 1,
            "stdout": "running tests...\n",
            "stderr": "E   AssertionError: 1 != 2",
        },
    })
    assert rc == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "running tests..." in ctx
    assert "AssertionError: 1 != 2" in ctx


def test_lowercase_bash_tool_name_matches(load_script, monkeypatch, capsys):
    """Copilot's runtime tool name is lowercase `bash` (Copilot review)."""
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "bash",
        "tool_response": {"exit_code": 1, "output": "boom"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "GROUNDED FEEDBACK" in out["hookSpecificOutput"]["additionalContext"]


def test_post_tool_use_echoes_post_tool_use_as_hook_event_name(load_script, monkeypatch, capsys):
    """The existing PostToolUse arm is untouched: the payload names no event (Claude's real
    PostToolUse input never carries one back out) and the echo still defaults to PostToolUse."""
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "tool_name": "Bash",
        "tool_response": {"exit_code": 1, "output": "boom"},
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


# ----------------------------------------------------------- PostToolUseFailure arm (P11)

def test_post_tool_use_failure_with_exit_code_line_captures_output(load_script, monkeypatch,
                                                                     capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "error": "Exit code 1\nAssertionError: 1 != 2",
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUseFailure"
    ctx = hso["additionalContext"]
    assert "GROUNDED FEEDBACK" in ctx
    assert "exited with code 1" in ctx
    assert "AssertionError: 1 != 2" in ctx


def test_post_tool_use_failure_without_exit_code_line_uses_unknown_marker(load_script,
                                                                           monkeypatch, capsys):
    """No leading `Exit code N` line: the exit code is `?`, not fabricated, and the whole
    error string still becomes the advisory's evidence."""
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "error": "npm ERR! network request failed",
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "exited with code ?" in ctx
    assert "npm ERR! network request failed" in ctx


def test_post_tool_use_failure_is_interrupt_is_silent(load_script, monkeypatch, capsys):
    """An interrupted call is not a failure to report — no advisory."""
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "error": "Exit code 130\nInterrupted",
        "is_interrupt": True,
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_post_tool_use_failure_preserves_a_trailing_truncation_marker(load_script, monkeypatch,
                                                                       capsys):
    """Our own tail-trim only cuts from the front, so a marker Claude appended at the end of
    a long `error` string survives verbatim rather than being cut into."""
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    long_body = "\n".join(f"line {i}" for i in range(100)) + "\n... [truncated]"
    rc = _call_main(hook, monkeypatch, {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "error": f"Exit code 1\n{long_body}",
    })
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "... [truncated]" in ctx
    assert "line 99" in ctx
    assert "line 0" not in ctx


def test_post_tool_use_failure_non_bash_tool_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Edit",
        "error": "Exit code 1\nboom",
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_post_tool_use_failure_empty_error_is_silent(load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/prompt-markers/scripts/grounded_feedback_hook.py")
    rc = _call_main(hook, monkeypatch, {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "error": "",
    })
    assert rc == 0
    assert capsys.readouterr().out == ""
