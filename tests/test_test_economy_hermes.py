"""Hermes wiring for the test-economy nudge (features/common/hooks/ai_badger_hooks.py).

Hermes' post_tool_call has no return channel into the model's context, so
post_tool_observer stashes a pending reminder and pre_llm_inject_context surfaces it on
the very next turn, then clears it — the same channel the commit reminder uses.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def hooks(load_script):
    """Load a fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def pending_file(tmp_path, hooks, monkeypatch):
    """Redirect the pending-reminder store away from the real ~/.ai-badger/."""
    path = tmp_path / "pending.json"
    monkeypatch.setattr(hooks, "PENDING_REMINDER_FILE", path)
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    return path


@pytest.fixture
def fake_test_economy(hooks, monkeypatch, load_script):
    """The real test_economy logic, with its state held in memory.

    Same discipline as the commit-reminder Hermes tests: only the two things that touch
    the outside world are stubbed (the store and gate detection); the counting rule and
    message text come from the real module.
    """
    real = load_script("features/common/skills/test-economy/scripts/suite_economy.py")
    module = types.ModuleType(hooks.TEST_ECONOMY_MODULE_NAME)
    module.store = {}
    module.gates = ["lefthook"]

    def get_entry(root):  # pylint: disable=unused-argument
        return dict(module.store.get(root, {"sessions": {}}))

    def set_entry(root, entry):  # pylint: disable=unused-argument
        module.store[root] = dict(entry)

    module.get_entry = get_entry
    module.set_entry = set_entry
    module.detect_local_gates = lambda root: list(module.gates)
    for name in ("is_shell_tool", "extract_command", "is_test_run", "advance",
                 "build_message", "new_session_entry", "session_entry", "advance_session",
                 "MAX_FULL", "ESCALATE_AT"):
        if hasattr(real, name):
            setattr(module, name, getattr(real, name))
    monkeypatch.setitem(sys.modules, hooks.TEST_ECONOMY_MODULE_NAME, module)
    return module


def test_repeated_bash_test_runs_stash_a_pending_reminder(
        tmp_path, monkeypatch, hooks, pending_file, fake_test_economy):
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        hooks.post_tool_observer(tool_name="execute",
                                 args={"command": "pytest"},
                                 result="ok", duration_ms=10)

    pending = hooks._load_pending_reminders()
    project = str(Path(tmp_path).resolve())
    assert project in pending
    assert "full-suite run #3" in pending[project]


def test_pending_reminder_surfaces_on_the_next_pre_llm_call(
        tmp_path, monkeypatch, hooks, pending_file, fake_test_economy):
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        hooks.post_tool_observer(tool_name="bash",
                                 args={"command": "dotnet test"},
                                 result="ok", duration_ms=10)

    result = hooks.pre_llm_inject_context(user_message="what next")

    assert result is not None
    assert "full-suite run #3" in result["context"]


def test_non_shell_tool_never_enters_the_economy(
        tmp_path, monkeypatch, hooks, pending_file, fake_test_economy):
    def _boom(*_args, **_kwargs):
        raise AssertionError("test-run counting must not run for a non-shell tool")

    monkeypatch.setattr(fake_test_economy, "is_test_run", _boom)

    hooks.post_tool_observer(tool_name="write_file",
                             args={"content": "pytest"},
                             result="ok", duration_ms=3, cwd=str(tmp_path))

    assert hooks._load_pending_reminders() == {}


def test_shell_tool_running_a_non_test_command_is_silent(
        tmp_path, monkeypatch, hooks, pending_file, fake_test_economy):
    monkeypatch.chdir(tmp_path)
    for _ in range(5):
        hooks.post_tool_observer(tool_name="execute",
                                 args={"command": "git status --porcelain"},
                                 result="ok", duration_ms=10)

    assert hooks._load_pending_reminders() == {}


def test_a_missing_sibling_module_fails_open(
        tmp_path, monkeypatch, hooks, pending_file):
    monkeypatch.delitem(sys.modules, hooks.TEST_ECONOMY_MODULE_NAME, raising=False)

    hooks.post_tool_observer(tool_name="execute",
                             args={"command": "pytest"},
                             result="ok", duration_ms=10, cwd=str(tmp_path))

    assert hooks._load_pending_reminders() == {}
