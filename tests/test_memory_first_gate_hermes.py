"""Hermes plugin memory-first gate (features/common/hooks/ai_badger_hooks.py).

The plugin blocks text-search tools until the session's first memory_search call,
using in-process state keyed by project cwd (plugin callbacks carry no session_id —
a documented limitation: a gateway handling several sessions for one project shares
the flag until the next on_session_start reset).
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
def fake_memory_grade(hooks, monkeypatch, load_script):
    """The real memory_grade module (the single is_memory_search matcher)."""
    real = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_grade.py")
    monkeypatch.setitem(sys.modules, hooks.MEMORY_GRADE_MODULE_NAME, real)
    return real


@pytest.fixture
def fresh(hooks):
    """Reset the per-session gate state before each test."""
    hooks.reset_gate_state()


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


def test_register_wires_pre_tool_call(hooks, fresh):
    ctx = _FakeCtx()
    hooks.register(ctx)

    assert ("pre_tool_call", hooks.pre_tool_call_memory_gate) in ctx.hooks


def test_search_files_blocked_before_memory_consulted(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)

    out = hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "MemorySearch"}, task_id="t1")

    assert _block(out)
    assert "memory_search" in out["message"]


def test_memory_search_call_unblocks_text_search(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    hooks.post_tool_observer(
        function_name="mcp__ai_raccoon__memory_search",
        function_args={"projectId": "probe", "query": "q"},
        result='{"results": []}', session_id="sess-1")

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t2") is None


def test_colon_spelling_of_memory_search_also_unblocks(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    hooks.post_tool_observer(tool_name="ai-raccoon:memory_search", args={}, result="")

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t2") is None


def test_non_search_tools_never_blocked(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    for tool_name, args in (("read_file", {"path": "a.cs"}),
                            ("write_file", {"path": "a.cs"}),
                            ("memory_search", {"query": "q"}),):
        assert hooks.pre_tool_call_memory_gate(
            tool_name=tool_name, args=args, task_id="t1") is None


def test_terminal_grep_blocked_build_passes(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)

    out = hooks.pre_tool_call_memory_gate(
        tool_name="terminal", args={"command": "grep -r foo src/"}, task_id="t1")
    assert _block(out)

    assert hooks.pre_tool_call_memory_gate(
        tool_name="terminal", args={"command": "dotnet build"}, task_id="t2") is None


def test_three_strikes_pass_through(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    for _ in range(fake_gate.MAX_DENIALS):
        out = hooks.pre_tool_call_memory_gate(
            tool_name="search_files", args={"pattern": "x"}, task_id="t1")
        assert _block(out)

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t2") is None


def test_session_start_resets_the_gate(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    hooks.post_tool_observer(
        function_name="mcp__ai_raccoon__memory_search", function_args={}, result="")

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={}, task_id="t2") is None

    hooks.on_session_start_drift_notice(session_id="sess-new")

    out = hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t3")
    assert _block(out)


def test_missing_gate_module_fails_open(
        hooks, fake_memory_grade, fresh, proj_a, monkeypatch):
    monkeypatch.chdir(proj_a)
    monkeypatch.setattr(hooks, "_load_memory_first_gate", lambda: None)

    assert hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t1") is None


def test_unblocked_state_is_keyed_per_project(
        hooks, fake_gate, fake_memory_grade, fresh, proj_a, proj_b, monkeypatch):
    monkeypatch.chdir(proj_a)
    hooks.post_tool_observer(
        function_name="mcp__ai_raccoon__memory_search", function_args={}, result="")

    monkeypatch.chdir(proj_b)
    out = hooks.pre_tool_call_memory_gate(
        tool_name="search_files", args={"pattern": "x"}, task_id="t2")
    assert _block(out)
