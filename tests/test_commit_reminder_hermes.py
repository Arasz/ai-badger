"""Hermes wiring for the commit-reminder nudge (features/common/hooks/ai_badger_hooks.py).

Hermes' post_tool_call has no return channel into the model's context, so
post_tool_observer stashes a pending reminder and pre_llm_inject_context surfaces it on
the very next turn, then clears it. See docs/design/ for the sibling Claude/Copilot hook.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
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
    return path


@pytest.fixture
def fake_commit_reminder(hooks, monkeypatch):
    """Stub commit_reminder with an in-memory marker and controllable file list."""
    module = types.ModuleType(hooks.COMMIT_REMINDER_MODULE_NAME)
    module.files = []
    module.marker = 0

    def is_edit_tool(tool_name):
        if not isinstance(tool_name, str):
            return False
        if tool_name != tool_name.lower():
            return False
        return any(s in tool_name for s in ("write", "edit", "patch", "replace"))

    def uncommitted_files(root, timeout=5.0):  # pylint: disable=unused-argument
        return module.files  # pylint: disable=no-member

    def get_marker(root):  # pylint: disable=unused-argument
        return module.marker  # pylint: disable=no-member

    def set_marker(root, marker):  # pylint: disable=unused-argument
        module.marker = marker

    def should_remind(count, marker, threshold=5):
        fires = count >= threshold and count > marker
        return fires, (count if fires else marker)

    module.is_edit_tool = is_edit_tool
    module.uncommitted_files = uncommitted_files
    module.get_marker = get_marker
    module.set_marker = set_marker
    module.should_remind = should_remind
    monkeypatch.setitem(sys.modules, hooks.COMMIT_REMINDER_MODULE_NAME, module)
    return module


@pytest.fixture
def fake_impact_estimator(hooks, monkeypatch):
    """Stub impact_estimator with a deterministic, recognizable message."""
    module = types.ModuleType(hooks.IMPACT_ESTIMATOR_MODULE_NAME)
    module.estimate_impact = (
        lambda files, root, use_graph=False: f"impact:{len(files)}")
    monkeypatch.setitem(sys.modules, hooks.IMPACT_ESTIMATOR_MODULE_NAME, module)
    return module


def test_crossing_threshold_stashes_a_pending_reminder(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = [f"f{i}.py" for i in range(6)]

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    assert str(Path(tmp_path).resolve()) in pending
    assert "impact:6" in pending[str(Path(tmp_path).resolve())]


def test_pending_reminder_surfaces_on_the_next_pre_llm_call(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = [f"f{i}.py" for i in range(6)]
    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    result = hooks.pre_llm_inject_context(user_message="what next")

    assert result is not None
    assert "impact:6" in result["context"]


def test_pending_reminder_does_not_surface_a_second_time(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = [f"f{i}.py" for i in range(6)]
    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)
    hooks.pre_llm_inject_context(user_message="first turn")

    second = hooks.pre_llm_inject_context(user_message="second turn")

    assert "impact:6" not in (second or {}).get("context", "")


def test_non_edit_tool_never_calls_git_or_writes_pending(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    def _boom(*_args, **_kwargs):
        raise AssertionError("uncommitted_files must not be called for a non-edit tool")

    monkeypatch.setattr(fake_commit_reminder, "uncommitted_files", _boom)

    hooks.post_tool_observer(tool_name="terminal", result="ok", duration_ms=3,
                             cwd=str(tmp_path))

    assert not pending_file.exists()


def test_post_tool_observer_is_inert_without_commit_reminder_module(
        tmp_path, monkeypatch, hooks, pending_file):
    monkeypatch.setattr(hooks, "_load_commit_reminder", lambda: None)

    assert hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3,
                                     cwd=str(tmp_path)) is None
    assert not pending_file.exists()


def test_pre_llm_inject_context_is_inert_without_commit_reminder_module(
        tmp_path, monkeypatch, hooks, pending_file):
    monkeypatch.setattr(hooks, "_load_commit_reminder", lambda: None)
    monkeypatch.chdir(tmp_path)

    result = hooks.pre_llm_inject_context(user_message="hello")

    # Must not raise; a pending reminder never appears with no module to produce one.
    assert "impact:" not in (result or {}).get("context", "")


def test_fires_without_impact_estimator_module_using_a_fallback_message(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder):
    monkeypatch.setattr(hooks, "_load_impact_estimator", lambda: None)
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = [f"f{i}.py" for i in range(6)]

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    assert pending_file.exists()
    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    assert str(Path(tmp_path).resolve()) in pending


def test_below_threshold_never_stashes_a_pending_reminder(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = ["only_one.py"]

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    assert not pending_file.exists()


def test_threshold_env_var_lowers_the_bar(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    monkeypatch.setenv("AI_BADGER_COMMIT_REMINDER_THRESHOLD", "2")
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = ["a.py", "b.py"]

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    assert pending_file.exists()


def test_garbage_threshold_env_var_falls_back_to_default(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    monkeypatch.setenv("AI_BADGER_COMMIT_REMINDER_THRESHOLD", "not-a-number")
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = ["a.py", "b.py", "c.py", "d.py"]  # below default of 5

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    assert not pending_file.exists()
