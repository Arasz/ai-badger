"""The pending-feedback stash is one pending_feedback-table row (kvdoc, key 'pending').

Covers the P1.3 store rewiring: the legacy pending-feedback.json migrates to its single row
on first write and is renamed; set/pop round-trip per project; a pop removes exactly its own
project's message; the pop is one atomic read-modify-write.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import _test_write

SCRIPT = "features/common/hooks/grounded_feedback.py"


@pytest.fixture
def grounded_feedback(load_script):
    return load_script(SCRIPT)


@pytest.fixture(autouse=True)
def _user_store_root(tmp_path, monkeypatch):
    """Rows land in a redirected user DB; the real ~/.ai-badger/ai-badger.db is never touched."""
    monkeypatch.setenv("AI_BADGER_USER_ROOT", str(tmp_path / "user-root"))


@pytest.fixture
def legacy_file(tmp_path, monkeypatch, grounded_feedback):
    path = tmp_path / "pending-feedback.json"
    monkeypatch.setattr(grounded_feedback, "PENDING_FEEDBACK_FILE", path)
    return path


def test_legacy_pending_feedback_file_migrates_to_its_row(grounded_feedback, legacy_file):
    legacy = {"/repo/a": "evidence A", "/repo/b": "evidence B"}
    _test_write(legacy_file, json.dumps(legacy), encoding="utf-8")

    grounded_feedback.set_pending_feedback("/repo/c", "evidence C")

    assert grounded_feedback.load_pending_feedback() == {**legacy, "/repo/c": "evidence C"}
    assert not legacy_file.exists()
    assert (legacy_file.parent / "pending-feedback.migrated.json").exists()


def test_set_then_pop_round_trips_one_projects_message(grounded_feedback, tmp_path):
    project = str(tmp_path / "proj")

    grounded_feedback.set_pending_feedback(project, "the failing output")
    message = grounded_feedback.pop_pending_feedback(project)

    assert message == "the failing output"
    assert grounded_feedback.pop_pending_feedback(project) is None


def test_pop_removes_only_its_own_project_and_leaves_the_others(grounded_feedback, tmp_path):
    """Intersecting properties: two stashed projects, one popped — the survivor stays."""
    first, second = str(tmp_path / "one"), str(tmp_path / "two")

    grounded_feedback.set_pending_feedback(first, "msg one")
    grounded_feedback.set_pending_feedback(second, "msg two")
    assert grounded_feedback.pop_pending_feedback(first) == "msg one"

    assert grounded_feedback.load_pending_feedback() == {second: "msg two"}
    assert grounded_feedback.pop_pending_feedback(second) == "msg two"


def test_pop_of_an_unstashed_project_returns_none(grounded_feedback, tmp_path):
    assert grounded_feedback.pop_pending_feedback(str(tmp_path)) is None


def test_stash_if_failure_lands_in_the_store_row(grounded_feedback, monkeypatch, tmp_path):
    grounded_feedback.stash_if_failure("Terminal", "boom: exit 1", str(tmp_path),
                                       status="error", error_type="ShellExit")

    pending = grounded_feedback.load_pending_feedback()
    assert pending[str(Path(tmp_path).resolve())].startswith("GROUNDED FEEDBACK")
