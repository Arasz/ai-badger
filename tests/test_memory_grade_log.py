"""Hermes post_tool_call logging for memory_search (features/common/hooks/ai_badger_hooks.py).

The framework checkout never carries memory_grade.py beside ai_badger_hooks.py, so the
sibling must be injected into sys.modules under the module-name constant (F8), with the
module-level log/pending path constants redirected to tmp_path — same discipline as
test_commit_reminder_hermes.py.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ENV = "AI_BADGER_MEMORY_GRADE"
MANUAL_JSONL = "docs/work/2026-08-05-ai-raccoon-memory-quality.jsonl"


@pytest.fixture
def hooks(load_script):
    """Load a fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def fake_memory_grade(hooks, monkeypatch, load_script):
    """The real memory_grade module, injected under the hooks' module-name constant (F8)."""
    real = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_grade.py")
    monkeypatch.setitem(sys.modules, hooks.MEMORY_GRADE_MODULE_NAME, real)
    return real


@pytest.fixture
def grade_paths(tmp_path, fake_memory_grade, monkeypatch):
    """Redirect the log and pending store away from the real ~/.ai-badger/."""
    log = tmp_path / "memory-quality.jsonl"
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(fake_memory_grade, "LOG_FILE", log)
    monkeypatch.setattr(fake_memory_grade, "PENDING_FILE", pending)
    return log, pending


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(ENV, "1")


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _lines(log: Path) -> list:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _search(hooks, tmp_path, tool_name="mcp__ai_raccoon__memory_search", result="{}",
            args=None):
    hooks.post_tool_observer(
        tool_name=tool_name, result=result, duration_ms=3, cwd=str(tmp_path),
        args=args or {"projectId": "probe", "query": "q", "scope": "all"})


def test_search_call_appends_one_line_with_all_fields(
        tmp_path, hooks, fake_memory_grade, grade_paths, on):
    _search(hooks, tmp_path, result='{"results": [{"sourceFile": "a.md", "score": 0}]}',
            args={"projectId": "probe", "query": "how do I", "scope": "all",
                  "workspaceId": "ws-1"})

    log, _ = grade_paths
    lines = _lines(log)
    assert len(lines) == 1
    line = lines[0]
    assert line["ts"]
    assert line["query"] == "how do I"
    assert line["scope"] == "all"
    assert line["projectId"] == "probe"
    assert line["workspaceId"] == "ws-1"
    assert line["result"] == {"results": [{"sourceFile": "a.md", "score": 0}]}
    assert line["usefulness"] is None
    assert line["note"] is None


def test_snake_case_args_are_read_defensively(
        tmp_path, hooks, fake_memory_grade, grade_paths, on):
    """F4: the tool's documented interface is memory_search(project_id, scope=all)."""
    _search(hooks, tmp_path, args={"project_id": "probe", "query": "q", "scope": "project",
                                   "workspace_id": "ws-2"})

    line = _lines(grade_paths[0])[0]
    assert line["projectId"] == "probe"
    assert line["workspaceId"] == "ws-2"
    assert line["scope"] == "project"


def test_missing_workspace_id_logs_null(tmp_path, hooks, fake_memory_grade, grade_paths, on):
    _search(hooks, tmp_path, args={"projectId": "probe", "query": "q"})

    line = _lines(grade_paths[0])[0]
    assert line["workspaceId"] is None


def test_result_not_json_logs_raw_payload(tmp_path, hooks, fake_memory_grade, grade_paths, on):
    _search(hooks, tmp_path, result="not json at all")

    line = _lines(grade_paths[0])[0]
    assert line["result"] == {"raw": "not json at all"}


def test_non_search_tool_writes_nothing(tmp_path, hooks, fake_memory_grade, grade_paths, on):
    for name in ("memory_write", "terminal", "write_file"):
        _search(hooks, tmp_path, tool_name=name)

    log, pending = grade_paths
    assert not log.exists()
    assert not pending.exists()


def test_disabled_config_writes_nothing(tmp_path, hooks, fake_memory_grade, grade_paths, off):
    _search(hooks, tmp_path)

    log, pending = grade_paths
    assert not log.exists()
    assert not pending.exists()


def test_line_shape_matches_manual_jsonl(root, tmp_path, hooks, fake_memory_grade,
                                         grade_paths, on):
    """Top-level keys are a superset of the session's manual lines (F6)."""
    manual_keys = set()
    for line in (root / MANUAL_JSONL).read_text(encoding="utf-8").splitlines():
        if line.strip():
            manual_keys |= set(json.loads(line).keys())
    assert {"ts", "query", "scope", "projectId", "result", "usefulness", "note"} <= manual_keys

    _search(hooks, tmp_path, result='{"results": [{"hash": "h", "ranking": 1}]}')

    hook_keys = set(_lines(grade_paths[0])[0].keys())
    assert manual_keys <= hook_keys
    assert "workspaceId" in hook_keys


def test_log_line_carries_host_and_session(tmp_path, hooks, fake_memory_grade,
                                           grade_paths, on):
    """The hook line is a superset of the manual shape: host + sessionId attribute the
    telemetry to a host, so 'no usage' vs 'no capture' is answerable from the log."""
    _search(hooks, tmp_path, session_id="sess-1")

    line = _lines(grade_paths[0])[0]
    assert line["host"] == "hermes"
    assert line["sessionId"] == "sess-1"


def test_log_line_defaults_host_and_session_to_null(tmp_path, hooks, fake_memory_grade,
                                                    grade_paths, on):
    """Manual logs (no host context) stay valid: both fields present, null."""
    _search(hooks, tmp_path)

    line = _lines(grade_paths[0])[0]
    assert line["host"] is None
    assert line["sessionId"] is None
