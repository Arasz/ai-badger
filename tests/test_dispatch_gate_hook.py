"""Tests for features/common/skills/task/scripts/dispatch_gate_hook.py (PreToolUse gate).

Covers the deny path (a dispatch naming no model whose subagent type has no model lane),
both silent paths (an explicit model; a lane file whose frontmatter declares one), the
fail-open paths (garbage stdin, a shapeless payload, a non-Agent tool), and namespaced
subagent types, which own no lane file and so must always name a model themselves.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import io
import json

import pytest
from conftest import _test_write

HOOK_PATH = "features/common/skills/task/scripts/dispatch_gate_hook.py"

LANE = "---\nname: {name}\ndescription: a persona\nmodel: sonnet\n---\n\nBody.\n"
NO_LANE = "---\nname: {name}\ndescription: a persona\n---\n\nBody.\n"


@pytest.fixture
def hook(load_script, monkeypatch, tmp_path):
    """The hook with `$CLAUDE_PROJECT_DIR` cleared, so the fabricated payload `cwd` decides.

    The dispatch ledger is redirected into tmp_path as well: the gate records every dispatch
    it sees, and these tests reuse one session id, so a shared ledger would let each test's
    dispatch count as the next test's parallel sibling.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    module = load_script(HOOK_PATH)
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))
    return module


def _run(hook, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return hook.main()


def _dispatch(cwd, subagent_type="architect", tool_name="Agent", **tool_input):
    payload = {
        "session_id": "sess_1",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_use_id": "toolu_1",
        "cwd": str(cwd),
        "tool_input": {"prompt": "do a thing", "description": "a thing",
                       "subagent_type": subagent_type},
    }
    payload["tool_input"].update(tool_input)
    return payload


def _agent_file(project, name, template=LANE):
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{name}.md"
    _test_write(path, template.format(name=name), encoding="utf-8")
    return path


def _all_keys(obj):
    """Every dict key anywhere in a parsed JSON object, for a blanket assertion."""
    keys = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for value in obj.values():
            keys.update(_all_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_all_keys(item))
    return keys


def test_no_model_and_no_lane_is_denied_with_a_reason_that_names_the_fix(
        hook, monkeypatch, capsys, tmp_path):
    rc = _run(hook, monkeypatch, _dispatch(tmp_path, subagent_type="architect"))

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    reason = specific["permissionDecisionReason"]
    assert "architect" in reason
    for alias in ("haiku", "sonnet", "opus"):
        assert alias in reason, reason
    assert ".ai-badger/delegation.md" in reason


def test_the_deny_uses_no_deprecated_or_auto_approving_field(
        hook, monkeypatch, capsys, tmp_path):
    """`decision`/`reason` are deprecated, and `updatedInput` would override a persona lane."""
    _run(hook, monkeypatch, _dispatch(tmp_path))

    out = json.loads(capsys.readouterr().out)
    assert _all_keys(out) & {"decision", "reason", "updatedInput", "continue"} == set()


def test_an_explicit_model_passes_silently(hook, monkeypatch, capsys, tmp_path):
    rc = _run(hook, monkeypatch, _dispatch(tmp_path, model="sonnet"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_null_model_counts_as_undeclared(hook, monkeypatch, capsys, tmp_path):
    """The docs do not say whether an omitted model arrives absent or null — both are undeclared."""
    rc = _run(hook, monkeypatch, _dispatch(tmp_path, model=None))

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_an_empty_model_counts_as_undeclared(hook, monkeypatch, capsys, tmp_path):
    _run(hook, monkeypatch, _dispatch(tmp_path, model="   "))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_subagent_type_whose_lane_file_declares_a_model_passes_silently(
        hook, monkeypatch, capsys, tmp_path):
    _agent_file(tmp_path, "foo")

    rc = _run(hook, monkeypatch, _dispatch(tmp_path, subagent_type="foo"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_lane_file_is_found_from_a_subdirectory(hook, monkeypatch, capsys, tmp_path):
    """`cwd` is the session's directory, which is not always the project root."""
    _agent_file(tmp_path, "foo")
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)

    rc = _run(hook, monkeypatch, _dispatch(nested, subagent_type="foo"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_user_level_lane_file_counts(hook, monkeypatch, capsys, tmp_path):
    """Claude Code reads ~/.claude/agents/ too; denying one that has a lane is a false alarm."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _agent_file(home, "foo")
    project = tmp_path / "proj"
    project.mkdir()

    rc = _run(hook, monkeypatch, _dispatch(project, subagent_type="foo"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_lane_file_without_a_model_key_is_still_denied(hook, monkeypatch, capsys, tmp_path):
    _agent_file(tmp_path, "foo", template=NO_LANE)

    _run(hook, monkeypatch, _dispatch(tmp_path, subagent_type="foo"))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "foo" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_namespaced_subagent_type_must_name_a_model(hook, monkeypatch, capsys, tmp_path):
    """`plugin:reviewer` owns no `.claude/agents/` file, so nothing can default it."""
    _run(hook, monkeypatch, _dispatch(tmp_path, subagent_type="plugin:reviewer"))

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "plugin:reviewer" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_garbage_stdin_is_silent(hook, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_payload_that_is_not_an_object_is_silent(hook, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([1, 2, 3])))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_payload_with_no_subagent_type_is_silent(hook, monkeypatch, capsys, tmp_path):
    payload = _dispatch(tmp_path)
    del payload["tool_input"]["subagent_type"]

    rc = _run(hook, monkeypatch, payload)

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_a_non_agent_tool_is_never_gated(hook, monkeypatch, capsys, tmp_path):
    """A widened matcher must not turn this into a gate on every tool call."""
    rc = _run(hook, monkeypatch, _dispatch(tmp_path, tool_name="Bash"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_the_deny_is_recorded_against_the_project_it_came_from(
        hook, monkeypatch, capsys, tmp_path):
    """An unattributed record pools into every project's analysis and skews all of them.

    `why` joined the deny record when the isolation half landed: the gate now denies for two
    different reasons and a log that cannot tell them apart cannot answer which one fired.
    """
    calls = []

    class FakeDebugLog:
        @staticmethod
        def resolve_project_root(payload):
            return payload.get("cwd")

        @staticmethod
        def log_event(component, event, project=None, **fields):
            calls.append((component, event, project, fields))

    monkeypatch.setattr(hook, "debug_log", FakeDebugLog)

    _run(hook, monkeypatch, _dispatch(tmp_path))
    capsys.readouterr()

    assert calls == [("dispatch_gate_hook", "deny", str(tmp_path),
                      {"subagentType": "architect", "why": "no_model"})], calls


def test_a_tool_name_the_matcher_never_sends_stays_ungated(hook, monkeypatch, capsys, tmp_path):
    """Only `Agent` is registered; anything else reaching the script is a matcher change."""
    rc = _run(hook, monkeypatch, _dispatch(tmp_path, tool_name="Task"))

    assert rc == 0
    assert capsys.readouterr().out == ""
