"""The grade round-trip: post_tool_call stashes the ask keyed by project, and
pre_llm_inject_context surfaces it exactly once on the very next turn (Hermes).
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import sys
from pathlib import Path

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


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _search(hooks, tmp_path, args=None):
    hooks.post_tool_observer(
        tool_name="memory_search", result="{}", duration_ms=3, cwd=str(tmp_path),
        args=args or {"projectId": "probe", "query": "q", "scope": "all"})


def test_search_stashes_pending_ask_keyed_by_project(
        tmp_path, monkeypatch, hooks, fake_memory_grade, grade_paths, on):
    monkeypatch.chdir(tmp_path)
    _search(hooks, tmp_path)

    pending = json.loads(grade_paths[1].read_text(encoding="utf-8"))
    assert str(Path(tmp_path).resolve()) in pending
    assert "memory_grade.py grade" in pending[str(Path(tmp_path).resolve())]


def test_ask_injected_once_on_next_pre_llm_call(
        tmp_path, monkeypatch, hooks, fake_memory_grade, grade_paths, on):
    monkeypatch.chdir(tmp_path)
    _search(hooks, tmp_path)

    result = hooks.pre_llm_inject_context(user_message="next turn")

    assert result is not None
    assert "usefulness 1-5" in result["context"]


def test_ask_not_injected_a_second_time(
        tmp_path, monkeypatch, hooks, fake_memory_grade, grade_paths, on):
    monkeypatch.chdir(tmp_path)
    _search(hooks, tmp_path)
    hooks.pre_llm_inject_context(user_message="first turn")

    second = hooks.pre_llm_inject_context(user_message="second turn")

    assert "usefulness" not in (second or {}).get("context", "")


def test_ask_injection_is_inert_when_disabled(
        tmp_path, monkeypatch, hooks, fake_memory_grade, grade_paths, off):
    monkeypatch.chdir(tmp_path)
    _search(hooks, tmp_path)

    result = hooks.pre_llm_inject_context(user_message="hello")

    assert "usefulness" not in (result or {}).get("context", "")


def test_ask_contains_helper_command_and_ts(
        tmp_path, monkeypatch, hooks, fake_memory_grade, grade_paths, on):
    monkeypatch.chdir(tmp_path)
    _search(hooks, tmp_path)
    ts = json.loads(grade_paths[0].read_text(encoding="utf-8").splitlines()[0])["ts"]

    result = hooks.pre_llm_inject_context(user_message="x")

    assert result is not None
    assert f"grade {ts}" in result["context"]
    assert "memory_grade.py" in result["context"]


def test_post_tool_observer_is_inert_without_memory_grade_module(
        tmp_path, monkeypatch, hooks, on):
    """F2: no sibling module (older scaffold) → the observer never raises, never writes."""
    monkeypatch.setattr(hooks, "_load_memory_grade", lambda: None)
    monkeypatch.chdir(tmp_path)

    assert hooks.post_tool_observer(
        tool_name="memory_search", result="{}", duration_ms=3, cwd=str(tmp_path),
        args={"projectId": "probe", "query": "q"}) is None
    assert not (tmp_path / "memory-quality.jsonl").exists()


def test_pre_llm_inject_context_is_inert_without_memory_grade_module(
        tmp_path, monkeypatch, hooks, on):
    """F2: no sibling module → pre_llm never raises and never injects a grade ask."""
    monkeypatch.setattr(hooks, "_load_memory_grade", lambda: None)
    monkeypatch.chdir(tmp_path)

    result = hooks.pre_llm_inject_context(user_message="hello")

    assert "usefulness" not in (result or {}).get("context", "")


def test_two_searches_before_one_turn_last_wins(
        tmp_path, monkeypatch, hooks, fake_memory_grade, grade_paths, on):
    """F7: two searches before an LLM turn → the later ask is the one injected; the
    earlier line stays logged with usefulness null (honest data, not loss)."""
    monkeypatch.chdir(tmp_path)
    _search(hooks, tmp_path, args={"projectId": "p1", "query": "first", "scope": "all"})
    _search(hooks, tmp_path, args={"projectId": "p1", "query": "second", "scope": "all"})

    lines = [json.loads(raw) for raw in
             grade_paths[0].read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["query"] == "first"
    assert lines[0]["usefulness"] is None
    assert lines[1]["query"] == "second"
    assert lines[1]["usefulness"] is None

    result = hooks.pre_llm_inject_context(user_message="x")

    assert result is not None
    assert f"grade {lines[1]['ts']}" in result["context"]
    assert f"grade {lines[0]['ts']}" not in result["context"]
