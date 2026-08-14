"""Hermes wiring for the commit-reminder nudge (features/common/hooks/ai_badger_hooks.py).

Hermes' post_tool_call has no return channel into the model's context, so
post_tool_observer stashes a pending reminder and pre_llm_inject_context surfaces it on
the very next turn, then clears it.
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
def fake_commit_reminder(hooks, monkeypatch, load_script):
    """The real commit_reminder logic, with its state and `git status` held in memory.

    Only the two things that touch the outside world are stubbed. The ratchet, the unanswered
    counter and the message text come from the real module: a hand-written copy of them here
    is what let the Hermes side keep calling a removed API and silently clear an escalation
    the Claude side had raised.
    """
    real = load_script("features/common/skills/commit-reminder/scripts/commit_reminder.py")
    module = types.ModuleType(hooks.COMMIT_REMINDER_MODULE_NAME)
    module.files = []
    module.entry = {"marker": 0, "fires": 0}

    def uncommitted_files(root, timeout=5.0):  # pylint: disable=unused-argument
        return module.files  # pylint: disable=no-member

    def get_entry(root):  # pylint: disable=unused-argument
        return dict(module.entry)  # pylint: disable=no-member

    def set_entry(root, entry):  # pylint: disable=unused-argument
        module.entry = dict(entry)

    module.uncommitted_files = uncommitted_files
    module.get_entry = get_entry
    module.set_entry = set_entry
    for name in ("is_edit_tool", "advance", "build_message", "should_remind",
                 "ESCALATE_AFTER", "CONVENTION_URL", "COMMIT_FORM"):
        setattr(module, name, getattr(real, name))
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


def test_non_edit_tool_writes_no_commit_reminder_audit_record(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder):
    """The skip branch fired on every non-edit tool call and flooded the audit log.

    Measured 2026-08-14: 3404 records, 68.1% of a 5000-record log, evicting every
    other component's evidence from the window.
    """
    seen = []
    monkeypatch.setattr(hooks, "_debug",
                        lambda component, event, **f: seen.append((component, event, f)))

    hooks.post_tool_observer(tool_name="terminal", result="ok", duration_ms=3,
                             cwd=str(tmp_path))

    assert [s for s in seen if s[0] == "ai_badger_hooks/commit_reminder"] == []


def test_commit_reminder_audit_records_always_name_their_project(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    """A record naming no project belongs to no project and is dropped from every analysis.

    3014 of 3404 records carried no `project` — 100% of the log's unattributed total.
    """
    seen = []
    monkeypatch.setattr(hooks, "_debug",
                        lambda component, event, **f: seen.append((component, event, f)))

    hooks.post_tool_observer(tool_name="Edit", result="ok", duration_ms=3,
                             cwd=str(tmp_path))

    records = [s for s in seen if s[0] == "ai_badger_hooks/commit_reminder"]
    assert records, "an edit tool must still be recorded"
    for _component, event, fields in records:
        assert fields.get("project"), f"{event} record names no project: {fields}"


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


def test_a_hermes_edit_never_clears_an_escalation_raised_elsewhere(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    """Both hooks share one entry; writing a bare marker here would drop the count (#234).

    A Hermes edit in a project where the Claude hook has already escalated must not silently
    take the work off the at-risk list.
    """
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.entry = {"marker": 9, "fires": 3, "since": "T0", "session": "s7"}
    # Same count as the marker: the ratchet is silent, so nothing legitimately increments
    # and any change to `fires` is the bug this pins.
    fake_commit_reminder.files = [f"f{i}.py" for i in range(9)]

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    entry = fake_commit_reminder.entry
    assert entry["fires"] == 3, "the unanswered count must survive a Hermes edit"
    assert entry["since"] == "T0", "and so must the clock a parent reads"


def test_the_hermes_message_commands_and_names_the_convention(
        tmp_path, monkeypatch, hooks, pending_file, fake_commit_reminder,
        fake_impact_estimator):
    """The two hooks must not disagree about what they ask for."""
    monkeypatch.chdir(tmp_path)
    fake_commit_reminder.files = [f"f{i}.py" for i in range(6)]

    hooks.post_tool_observer(tool_name="write_file", result="ok", duration_ms=3)

    message = json.loads(pending_file.read_text(encoding="utf-8"))[str(Path(tmp_path).resolve())]
    assert "Commit now" in message
    assert fake_commit_reminder.CONVENTION_URL in message
    assert "Consider committing" not in message
