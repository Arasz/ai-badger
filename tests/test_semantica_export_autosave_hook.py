"""Tests for the Claude/Copilot PostToolUse shim (semantica_export_autosave_hook.py).

The shim transports a PostToolUse payload from stdin to the sibling export
module's autosave_export, which the Hermes plugin dispatches in-process. These
tests prove the transport works standalone — subprocess-level, with a real
stdin payload — and that it never fails a tool call (exit 0 on every path).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK_PATH = (
    Path(__file__).resolve().parent.parent
    / "features"
    / "common"
    / "skills"
    / "semantica-knowledge-graph"
    / "scripts"
    / "semantica_export_autosave_hook.py"
)


def _run_hook(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Run the shim with payload JSON on stdin, cwd set to cwd."""
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=30,
        check=False,
    )


def test_claude_spelling_writes_dump(tmp_path):
    """Claude Code payload (tool_name/tool_response/session_id) writes a dump."""
    payload = {
        "tool_name": "export_graph",
        "tool_response": '{"result": "{\\"nodes\\": [{\\"id\\": \\"n1\\"}]}"}',
        "session_id": "claude-sess-1",
    }
    result = _run_hook(payload, tmp_path)

    assert result.returncode == 0
    dumps = list((tmp_path / ".semantica").glob("claude-sess-1-*.json"))
    assert len(dumps) == 1
    data = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert data["nodes"] == [{"id": "n1"}]


def test_copilot_spelling_writes_dump(tmp_path):
    """Copilot payload (toolName/toolResponse/sessionId) writes a dump."""
    payload = {
        "toolName": "mcp__semantica__export_graph",
        "toolResponse": '{"result": "{\\"edges\\": []}"}',
        "sessionId": "copilot-sess-2",
    }
    result = _run_hook(payload, tmp_path)

    assert result.returncode == 0
    dumps = list((tmp_path / ".semantica").glob("copilot-sess-2-*.json"))
    assert len(dumps) == 1


def test_non_export_tool_writes_nothing(tmp_path):
    """A non-export tool payload writes nothing and exits 0."""
    payload = {"tool_name": "read_file", "tool_response": "{}", "session_id": "s"}
    result = _run_hook(payload, tmp_path)

    assert result.returncode == 0
    assert not (tmp_path / ".semantica").exists()


def test_error_payload_writes_nothing(tmp_path):
    """An error result inside the envelope writes nothing (U1 regression, transport level)."""
    payload = {
        "tool_name": "export_graph",
        "tool_response": '{"result": "{\\"error\\": \\"boom\\"}"}',
        "session_id": "s",
    }
    result = _run_hook(payload, tmp_path)

    assert result.returncode == 0
    assert not (tmp_path / ".semantica").exists()


def test_garbage_stdin_exits_zero(tmp_path):
    """Garbage stdin exits 0 — a broken payload must never fail the tool call."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not json {{{",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert not (tmp_path / ".semantica").exists()


def test_missing_sibling_module_exits_zero(tmp_path):
    """A hook copy without export_semantica_graph.py beside it exits 0 silently."""
    import shutil

    isolated = tmp_path / "isolated"
    isolated.mkdir()
    shutil.copy2(HOOK_PATH, isolated / "semantica_export_autosave_hook.py")

    payload = {"tool_name": "export_graph", "tool_response": "{}", "session_id": "s"}
    result = subprocess.run(
        [sys.executable, str(isolated / "semantica_export_autosave_hook.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert not (tmp_path / ".semantica").exists()


def test_non_dict_payload_exits_zero(tmp_path):
    """A JSON-array stdin payload exits 0 without touching the filesystem."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="[1, 2, 3]",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert not (tmp_path / ".semantica").exists()
