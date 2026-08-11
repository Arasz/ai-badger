"""Hermes plugin callback payload adaptation (features/common/hooks/ai_badger_hooks.py).

Hermes invokes plugin callbacks with the payload shapes from model_tools
_emit_post_tool_call_hook / agent conversation loop / hooks.py _DEFAULT_PAYLOADS:
- post_tool_call: function_name, function_args, result, session_id, duration_ms, status, ...
  (the shell-hook spelling tool_name/args/cwd is NOT what the plugin emitter sends)
- pre_llm_call: session_id, user_message, conversation_history, is_first_turn, model, platform
- on_session_start: session_id

The observers must accept these verbatim (keyword args) and behave identically to
the legacy tool_name/args spelling. No cwd arrives in any payload — callbacks fall
back to os.getcwd() (the session process cwd), matching pre_llm's pop side.

The memory-grade file logging is gone (2026-08-11, task mem-cleanup): a memory_search
payload must unlock the memory-first gate and must NOT create any quality-log file.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import sys

import pytest


@pytest.fixture
def hooks(load_script):
    """Load a fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def fake_gate(hooks, monkeypatch, load_script, tmp_path):
    """The real gate module, injected under the hooks' module-name constant."""
    real = load_script(
        "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setitem(sys.modules, hooks.MEMORY_FIRST_GATE_MODULE_NAME, real)
    return real


@pytest.fixture
def fresh(hooks):
    """Reset the per-session gate state before each test."""
    hooks.reset_gate_state()


def _real_post_tool_payload(**overrides):
    payload = {
        "function_name": "mcp__ai_raccoon__memory_search",
        "function_args": {"projectId": "probe", "query": "q", "scope": "all"},
        "result": '{"results": [{"sourceFile": "a.md", "score": 0}]}',
        "session_id": "sess-1",
        "tool_call_id": "call-1",
        "turn_id": "turn-1",
        "duration_ms": 4,
        "status": "ok",
    }
    payload.update(overrides)
    return payload


def test_post_tool_observer_real_payload_unlocks_the_gate_without_file_logging(
        tmp_path, hooks, fake_gate, fresh, monkeypatch):
    """The plugin emitter sends function_name/function_args/session_id — the observer
    must map them to the internal contract, unlock the gate, and write no log file."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(**_real_post_tool_payload())

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t1") is None
    grade_dir = tmp_path / ".ai-badger" / "memory-grade"
    assert not grade_dir.exists()


def test_post_tool_observer_legacy_spelling_unlocks_the_gate(
        tmp_path, hooks, fake_gate, fresh, monkeypatch):
    """Backward compat: the script-hook spelling (tool_name/args/cwd) still works."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(
        tool_name="mcp__ai_raccoon__memory_search",
        args={"projectId": "probe", "query": "q"},
        result='{"results": []}',
        duration_ms=3,
        cwd=str(tmp_path),
    )

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t1") is None


def test_post_tool_observer_non_search_tool_writes_nothing_and_keeps_gate(
        tmp_path, hooks, fake_gate, fresh, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(**_real_post_tool_payload(function_name="memory_write"))

    out = hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t1")
    assert out is not None and out.get("action") == "block"
    grade_dir = tmp_path / ".ai-badger" / "memory-grade"
    assert not grade_dir.exists()


def test_pre_llm_inject_context_accepts_real_pre_llm_payload(
        tmp_path, hooks, fake_gate, fresh, monkeypatch):
    """pre_llm_call arrives with session_id/user_message/model/platform — no cwd.
    The injector must not raise and must not surface a grade ask."""
    monkeypatch.chdir(tmp_path)
    context = hooks.pre_llm_inject_context(
        session_id="sess-1", user_message="hello", conversation_history=[],
        is_first_turn=True, model="gpt-4", platform="cli")
    if context is not None:
        assert "Rate that memory_search" not in (context.get("context") or "")


def test_on_session_start_drift_notice_accepts_session_only_payload(hooks):
    """on_session_start arrives with just session_id — the drift notice must not raise."""
    hooks.on_session_start_drift_notice(session_id="sess-1")
