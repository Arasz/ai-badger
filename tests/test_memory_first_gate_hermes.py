"""Hermes plugin memory-first gate (features/common/hooks/ai_badger_hooks.py).

The plugin runs the shared gate: a search tool call passes once every pattern it searches
for was memory-searched for the project (gate.project_id(cwd)). Searched patterns persist in the same store
the Claude/Copilot hooks use; session start clears nothing.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import os
import sys

import badger_store
import pytest


@pytest.fixture
def hooks(load_script):
    """Load a fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def fake_gate(hooks, monkeypatch, load_script, tmp_path):
    """The real gate module, injected under the hooks' module-name constant; search faked."""
    monkeypatch.setenv(badger_store.DEBUG_DIR_ENV, str(tmp_path / "debug"))
    monkeypatch.setenv(badger_store.USER_ROOT_ENV, str(tmp_path / "user-root"))
    monkeypatch.delenv("AI_BADGER_PROJECT_ID", raising=False)
    real = load_script(
        "features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    monkeypatch.setattr(real, "SEARCHED_DIR", tmp_path / "memory-first-searched", raising=False)
    monkeypatch.setattr(real, "memory_hits", lambda *_a, **_k: None, raising=False)
    monkeypatch.setitem(sys.modules, hooks.MEMORY_FIRST_GATE_MODULE_NAME, real)
    return real


@pytest.fixture
def proj_a(tmp_path):
    (d := tmp_path / "ai-raccoon").mkdir()
    return d


@pytest.fixture
def proj_b(tmp_path):
    (d := tmp_path / "other-repo").mkdir()
    return d


class _FakeCtx:
    def __init__(self):
        self.hooks = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


def _block(out):
    return out is not None and out.get("action") == "block"


def _search(hooks, query, **extra):
    """A query for the project the cwd resolves to, as Hermes reports it."""
    gate = sys.modules[hooks.MEMORY_FIRST_GATE_MODULE_NAME]
    hooks.post_tool_observer(
        function_name="mcp__ai_raccoon__memory_search",
        function_args={"projectId": gate.project_id(os.getcwd()), "query": query},
        result='{"results": []}', session_id="sess-1", **extra)


def test_register_wires_pre_tool_call(hooks):
    ctx = _FakeCtx()
    hooks.register(ctx)

    assert ("pre_tool_call", hooks.pre_tool_call_memory_gate) in ctx.hooks


def test_search_files_blocked_on_first_sighting(hooks, fake_gate, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)

    out = hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "MemorySearch"}, task_id="t1")

    assert _block(out)
    assert "MemorySearch" in out["message"]
    assert "{" not in out["message"]


def test_memory_search_with_the_pattern_unblocks_search_files(
        hooks, fake_gate, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    _search(hooks, "where is MemorySearch")

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "MemorySearch"}, task_id="t2") is None
    assert _block(hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "unrelated"}, task_id="t3"))


def test_colon_spelling_of_memory_search_also_records(
        hooks, fake_gate, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    hooks.post_tool_observer(tool_name="ai-raccoon:query",
                             args={"projectId": fake_gate.project_id(os.getcwd()), "query": "x"},
                             result="")

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t2") is None


def test_non_search_tools_never_blocked(hooks, fake_gate, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    for tool_name, args in (("read_file", {"path": "a.cs"}),
                            ("write_file", {"path": "a.cs"}),
                            ("query", {"query": "q"}),):
        assert hooks.pre_tool_call_memory_gate(
            tool_name=tool_name, args=args, task_id="t1") is None


def test_terminal_grep_needs_search_but_no_marker(
        hooks, fake_gate, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    assert _block(hooks.pre_tool_call_memory_gate(
        tool_name="terminal", args={"command": "grep -r foo src/"}, task_id="t1"))
    _search(hooks, "foo")
    assert hooks.pre_tool_call_memory_gate(
        tool_name="terminal", args={"command": "grep -r foo src/"}, task_id="t2") is None
    assert hooks.pre_tool_call_memory_gate(
        tool_name="terminal", args={"command": "dotnet build"}, task_id="t4") is None


def test_fourth_denial_still_denies(hooks, fake_gate, proj_a, monkeypatch):
    """Mutation: restore the 3-strike pass-through."""
    monkeypatch.chdir(proj_a)
    for _ in range(4):
        assert _block(hooks.pre_tool_call_memory_gate(
            tool_name="search_files", args={"pattern": "x"}, task_id="t1"))


def test_session_start_clears_nothing(hooks, fake_gate, proj_a, monkeypatch):
    """Mutation: clear the searched set on session start."""
    monkeypatch.chdir(proj_a)
    _search(hooks, "x")
    assert not hasattr(hooks, "reset_gate_state")

    hooks.on_session_start_drift_notice(session_id="sess-new")

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t3") is None


def test_missing_gate_module_fails_open(hooks, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    monkeypatch.setattr(hooks, "_load_memory_first_gate", lambda: None)

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t1") is None


def test_searched_state_is_keyed_per_project(
        hooks, fake_gate, proj_a, proj_b, monkeypatch):
    monkeypatch.chdir(proj_a)
    _search(hooks, "x")

    monkeypatch.chdir(proj_b)
    out = hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t2")
    assert _block(out)


def test_a_failed_memory_search_credits_nothing(hooks, fake_gate, proj_a, monkeypatch):
    """Mutation: record the query whatever Hermes' status says -> red."""
    monkeypatch.chdir(proj_a)
    _search(hooks, "MemorySearch", status="error")

    assert _block(hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "MemorySearch"}, task_id="t1"))


def test_a_memory_search_for_another_project_credits_nothing(
        hooks, fake_gate, proj_a, monkeypatch):
    """Mutation: ignore the call's projectId -> red."""
    monkeypatch.chdir(proj_a)
    hooks.post_tool_observer(
        function_name="mcp__ai_raccoon__memory_search",
        function_args={"projectId": "other-project", "query": "MemorySearch"},
        result='{"results": []}', session_id="sess-1")

    assert _block(hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "MemorySearch"}, task_id="t1"))
