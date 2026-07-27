"""Tests for the commit-reminder skill's pure logic: porcelain parsing, the edit-tool
heuristic, the debounce ratchet, and the state file it persists a per-project marker in.
"""
# pylint: disable=redefined-outer-name  # pytest fixtures reuse param names by design
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = "features/common/skills/commit-reminder/scripts/commit_reminder.py"


@pytest.fixture
def commit_reminder(load_script):
    return load_script(SCRIPT)


# ---------------------------------------------------------------------------
# parse_porcelain
# ---------------------------------------------------------------------------

def test_parse_porcelain_empty_input_returns_empty_list(commit_reminder):
    assert commit_reminder.parse_porcelain("") == []


def test_parse_porcelain_whitespace_only_input_returns_empty_list(commit_reminder):
    assert commit_reminder.parse_porcelain("   \n  \n") == []


def test_parse_porcelain_modified_file(commit_reminder):
    assert commit_reminder.parse_porcelain(" M path/to/file.py") == ["path/to/file.py"]


def test_parse_porcelain_untracked_file(commit_reminder):
    assert commit_reminder.parse_porcelain("?? new_file.txt") == ["new_file.txt"]


def test_parse_porcelain_added_file(commit_reminder):
    assert commit_reminder.parse_porcelain("A  staged_file.py") == ["staged_file.py"]


def test_parse_porcelain_rename_keeps_only_new_path(commit_reminder):
    assert commit_reminder.parse_porcelain("R  old.py -> new.py") == ["new.py"]


def test_parse_porcelain_quoted_path_strips_quotes(commit_reminder):
    assert commit_reminder.parse_porcelain('?? "my file.txt"') == ["my file.txt"]


def test_parse_porcelain_multiple_lines(commit_reminder):
    text = " M a.py\n?? b.txt\nA  c.py\n"
    assert commit_reminder.parse_porcelain(text) == ["a.py", "b.txt", "c.py"]


# ---------------------------------------------------------------------------
# is_edit_tool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_is_edit_tool_true_for_claude_copilot_names(commit_reminder, name):
    assert commit_reminder.is_edit_tool(name) is True


@pytest.mark.parametrize("name", ["Bash", "Read", "Grep", "terminal", "skill_manage", "", None])
def test_is_edit_tool_false_for_non_edit_names(commit_reminder, name):
    assert commit_reminder.is_edit_tool(name) is False


@pytest.mark.parametrize("name", [
    "apply_edit", "write_file", "patch_file", "replace_text", "str_replace",
])
def test_is_edit_tool_permissively_matches_unknown_hermes_tool_names(commit_reminder, name):
    """A false negative only delays a nudge; be permissive for unknown lowercase vocab."""
    assert commit_reminder.is_edit_tool(name) is True


# ---------------------------------------------------------------------------
# should_remind — the debounce ratchet
# ---------------------------------------------------------------------------

SHOULD_REMIND_CASES = [
    # count, marker_in, fires, marker_out, why
    (4, 0, False, 0, "below threshold"),
    (5, 0, True, 5, "crosses threshold first time"),
    (5, 5, False, 5, "plateau, no re-nag"),
    (6, 5, True, 6, "grew further, re-fire"),
    (2, 6, False, 2, "count dropped below marker (a commit happened): ratchet down, no fire"),
    (5, 2, True, 5, "crosses threshold again after the ratchet-down: must fire"),
    (0, 9, False, 0, "fully clean tree, marker ratchets to 0"),
]


@pytest.mark.parametrize("count, marker_in, fires, marker_out, why", SHOULD_REMIND_CASES)
def test_should_remind_ratchet_table(commit_reminder, count, marker_in, fires, marker_out, why):
    result = commit_reminder.should_remind(count, marker_in)
    assert result == (fires, marker_out), why


def test_should_remind_never_gets_permanently_stuck_firing(commit_reminder):
    """Once fired, a later drop-then-recross must fire again (not the group-C bug class)."""
    fires1, marker = commit_reminder.should_remind(5, 0)
    assert fires1 is True
    fires2, marker = commit_reminder.should_remind(5, marker)
    assert fires2 is False
    fires3, marker = commit_reminder.should_remind(1, marker)
    assert fires3 is False
    fires4, marker = commit_reminder.should_remind(5, marker)
    assert fires4 is True


# ---------------------------------------------------------------------------
# uncommitted_files
# ---------------------------------------------------------------------------

def test_uncommitted_files_parses_successful_git_output(commit_reminder, monkeypatch):
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=0, stdout=" M a.py\n?? b.txt\n", stderr="")
    monkeypatch.setattr(commit_reminder.subprocess, "run", lambda *a, **k: completed)

    assert commit_reminder.uncommitted_files("/some/root") == ["a.py", "b.txt"]


def test_uncommitted_files_returns_empty_on_nonzero_exit(commit_reminder, monkeypatch):
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=128, stdout="", stderr="fatal: not a git repository")
    monkeypatch.setattr(commit_reminder.subprocess, "run", lambda *a, **k: completed)

    assert commit_reminder.uncommitted_files("/some/root") == []


def test_uncommitted_files_returns_empty_when_git_binary_missing(commit_reminder, monkeypatch):
    def _raise(*_a, **_k):
        raise FileNotFoundError("git not found")
    monkeypatch.setattr(commit_reminder.subprocess, "run", _raise)

    assert commit_reminder.uncommitted_files("/some/root") == []


def test_uncommitted_files_returns_empty_on_timeout(commit_reminder, monkeypatch):
    def _raise(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5.0)
    monkeypatch.setattr(commit_reminder.subprocess, "run", _raise)

    assert commit_reminder.uncommitted_files("/some/root") == []


def test_uncommitted_files_returns_empty_on_other_os_error(commit_reminder, monkeypatch):
    def _raise(*_a, **_k):
        raise OSError("permission denied")
    monkeypatch.setattr(commit_reminder.subprocess, "run", _raise)

    assert commit_reminder.uncommitted_files("/some/root") == []


def test_uncommitted_files_never_uses_shell_true(commit_reminder, monkeypatch):
    captured = {}

    def _fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(commit_reminder.subprocess, "run", _fake_run)
    commit_reminder.uncommitted_files("/some/root")

    assert captured.get("shell") is not True


# ---------------------------------------------------------------------------
# load_state / save_state
# ---------------------------------------------------------------------------

def test_load_state_missing_file_returns_empty_dict(commit_reminder, tmp_path, monkeypatch):
    monkeypatch.setattr(commit_reminder, "STATE_FILE", tmp_path / "nope" / "state.json")
    assert commit_reminder.load_state() == {}


def test_load_state_corrupt_json_returns_empty_dict(commit_reminder, tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(commit_reminder, "STATE_FILE", state_file)
    assert commit_reminder.load_state() == {}


def test_load_state_non_dict_json_returns_empty_dict(commit_reminder, tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(commit_reminder, "STATE_FILE", state_file)
    assert commit_reminder.load_state() == {}


def test_save_state_then_load_state_round_trips(commit_reminder, tmp_path, monkeypatch):
    state_file = tmp_path / "nested" / "state.json"
    monkeypatch.setattr(commit_reminder, "STATE_FILE", state_file)

    commit_reminder.save_state({"/proj/a": 5})

    assert state_file.exists()
    assert commit_reminder.load_state() == {"/proj/a": 5}


def test_save_state_creates_parent_dirs(commit_reminder, tmp_path, monkeypatch):
    state_file = tmp_path / "a" / "b" / "c" / "state.json"
    monkeypatch.setattr(commit_reminder, "STATE_FILE", state_file)

    commit_reminder.save_state({"/proj": 1})

    assert state_file.is_file()
    assert json.loads(state_file.read_text(encoding="utf-8")) == {"/proj": 1}


def test_two_project_keys_do_not_clobber_each_other(commit_reminder, tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(commit_reminder, "STATE_FILE", state_file)

    commit_reminder.save_state({"/proj/one": 3})
    state = commit_reminder.load_state()
    state["/proj/two"] = 7
    commit_reminder.save_state(state)

    result = commit_reminder.load_state()
    assert result == {"/proj/one": 3, "/proj/two": 7}


# ---------------------------------------------------------------------------
# get_marker / set_marker
# ---------------------------------------------------------------------------

def test_get_marker_for_unseen_project_returns_zero(commit_reminder, tmp_path, monkeypatch):
    monkeypatch.setattr(commit_reminder, "STATE_FILE", tmp_path / "state.json")
    assert commit_reminder.get_marker(str(tmp_path)) == 0


def test_set_marker_then_get_marker_round_trips(commit_reminder, tmp_path, monkeypatch):
    monkeypatch.setattr(commit_reminder, "STATE_FILE", tmp_path / "state.json")
    project = tmp_path / "proj"
    project.mkdir()

    commit_reminder.set_marker(str(project), 8)

    assert commit_reminder.get_marker(str(project)) == 8


def test_get_marker_collapses_relative_path_variance(commit_reminder, tmp_path, monkeypatch):
    monkeypatch.setattr(commit_reminder, "STATE_FILE", tmp_path / "state.json")
    project = tmp_path / "proj"
    project.mkdir()

    commit_reminder.set_marker(str(project), 4)
    resolved_key = str(Path(project).resolve())

    assert commit_reminder.load_state() == {resolved_key: 4}
    assert commit_reminder.get_marker(str(project) + "/./") == 4
