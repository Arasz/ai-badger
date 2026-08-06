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
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys

import pytest

ENV = "AI_BADGER_MEMORY_GRADE"


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


def _lines(log) -> list:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()]


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


def test_post_tool_observer_accepts_real_hermes_plugin_payload(
        tmp_path, hooks, fake_memory_grade, grade_paths, on, monkeypatch):
    """The plugin emitter sends function_name/function_args/session_id — the observer
    must map them to the internal tool_name/args contract and log the search."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(**_real_post_tool_payload())

    log, pending = grade_paths
    lines = _lines(log)
    assert len(lines) == 1
    line = lines[0]
    assert line["query"] == "q"
    assert line["projectId"] == "probe"
    assert line["host"] == "hermes"
    assert line["sessionId"] == "sess-1"
    assert pending.exists()  # the grade ask was stashed


def test_post_tool_observer_accepts_legacy_shell_hook_spelling(
        tmp_path, hooks, fake_memory_grade, grade_paths, on, monkeypatch):
    """Backward compat: the script-hook spelling (tool_name/args/cwd) still works."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(
        tool_name="mcp__ai_raccoon__memory_search",
        args={"projectId": "probe", "query": "q"},
        result='{"results": []}',
        duration_ms=3,
        cwd=str(tmp_path),
    )

    line = _lines(grade_paths[0])[0]
    assert line["query"] == "q"
    assert line["projectId"] == "probe"
    assert line["host"] == "hermes"
    assert line["sessionId"] is None


def test_post_tool_observer_non_search_tool_writes_nothing(
        tmp_path, hooks, fake_memory_grade, grade_paths, on, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(**_real_post_tool_payload(function_name="memory_write"))

    log, pending = grade_paths
    assert not log.exists()
    assert not pending.exists()


def test_pre_llm_inject_context_accepts_real_pre_llm_payload(
        tmp_path, hooks, fake_memory_grade, grade_paths, on, monkeypatch):
    """pre_llm_call arrives with session_id/user_message/model/platform — no cwd.
    The pop side must resolve the stash key via os.getcwd() and surface the ask once."""
    monkeypatch.chdir(tmp_path)
    hooks.post_tool_observer(**_real_post_tool_payload())
    _, pending = grade_paths
    assert pending.exists()

    context = hooks.pre_llm_inject_context(
        session_id="sess-1", user_message="hello", conversation_history=[],
        is_first_turn=True, model="gpt-4", platform="cli")
    assert context is not None
    assert "memory_search" in context["context"]
    assert "grade" in context["context"]

    # Inject-once: a second turn with no new search surfaces nothing.
    second = hooks.pre_llm_inject_context(session_id="sess-1", user_message="again")
    ask_text = "Rate that memory_search"
    assert second is None or ask_text not in (second.get("context") or "")


def test_on_session_start_drift_notice_accepts_session_only_payload(hooks):
    """on_session_start arrives with just session_id — the drift notice must not raise."""
    hooks.on_session_start_drift_notice(session_id="sess-1")
