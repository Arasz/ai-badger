"""A task worktree and its checkout must read and write one task-tracking store.

The /task skill runs every command inside the worktree it created, and `resolve_project_root`
walked up from the cwd to the nearest `.ai-badger/config.json` — which a worktree carries a
copy of. Eleven consecutive tasks recorded `tokens=0` because `finish` looked in the
worktree's empty store (B12).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _test_write

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "features" / "common" / "skills" / "task" / "scripts" / "task_tracker.py"
SOURCE = "features/common/skills/task/scripts/tracker_lib.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture(name="checkout_and_worktree")
def _checkout_and_worktree(tmp_path):
    """A real git checkout carrying the ai-badger marker, plus a real linked worktree of it.

    Both directories hold `.ai-badger/config.json`, which is what makes the cwd walk stop at
    the wrong one — a plain subdirectory would not reproduce the bug.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-b", "main")
    _git(checkout, "config", "user.email", "test@example.invalid")
    _git(checkout, "config", "user.name", "Test")
    marker = checkout / ".ai-badger" / "config.json"
    marker.parent.mkdir(parents=True)
    _test_write(marker, "{}", encoding="utf-8")
    _git(checkout, "add", ".ai-badger/config.json")
    _git(checkout, "commit", "-m", "marker")

    worktree = checkout / ".ai-badger" / "worktrees" / "task-x"
    _git(checkout, "worktree", "add", "-b", "task/x", str(worktree))
    assert (worktree / ".ai-badger" / "config.json").is_file(), \
        "the worktree must carry its own marker, or the bug is not reproduced"

    yield checkout, worktree

    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                   cwd=str(checkout), check=False, capture_output=True)


def _register(checkout: Path, task_id: str) -> Path:
    """Seed the checkout's store with one registered task, as `start` would leave it.

    Both files: `status` reads executed-tasks.json and `subagent` reads token-usage.json.
    """
    tracking = checkout / ".ai-badger" / "task-tracking"
    tracking.mkdir(parents=True, exist_ok=True)
    _test_write(tracking / "executed-tasks.json", json.dumps({"tasks": [{
        "taskId": task_id,
        "state": "IN_PROGRESS",
        "startedAt": "2026-08-07T00:00:00+00:00",
        "sessionId": "s-1",
    }]}), encoding="utf-8")
    _test_write(tracking / "token-usage.json", json.dumps({"tasks": [{
        "taskId": task_id,
        "sessionId": "s-1",
        "trackingSource": "claude",
        "checkpoints": {},
    }]}), encoding="utf-8")
    return tracking


def _tracker_env() -> dict:
    """The child's environment with the project overrides removed, so the cwd walk decides.

    The suite points CLAUDE_PROJECT_DIR at a scratch project; leaving it set would make the
    child resolve there and the test would prove nothing about worktrees. AI_BADGER_TRACKING_ROOT
    gets the same treatment (P0.3): the store must resolve from the checkout the child itself
    computes, not from whatever root the parent process last synced (D9 call-time resolution).
    """
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("AI_BADGER_TRACKING_ROOT", None)
    return env


def test_status_from_a_worktree_lists_a_task_registered_in_the_checkout(checkout_and_worktree):
    """The gate for B12: register in the checkout, read it back from the worktree."""
    checkout, worktree = checkout_and_worktree
    _register(checkout, "shared-store")

    result = subprocess.run([sys.executable, str(TRACKER), "status"], cwd=str(worktree),
                            capture_output=True, text=True, check=True, env=_tracker_env())

    assert "shared-store" in result.stdout, \
        f"the worktree read a different store: {result.stdout!r}"
    assert "No tracked tasks" not in result.stdout


def test_a_task_started_in_the_checkout_is_known_to_subagent_from_the_worktree(
        checkout_and_worktree):
    """`subagent` refused with `Unknown task <id>` — the visible face of the split store."""
    checkout, worktree = checkout_and_worktree
    _register(checkout, "shared-store")

    result = subprocess.run(
        [sys.executable, str(TRACKER), "subagent", "shared-store", "1234",
         "--description", "probe"],
        cwd=str(worktree), capture_output=True, text=True, check=False, env=_tracker_env())

    assert "Unknown task" not in (result.stdout + result.stderr), \
        f"rc={result.returncode} out={result.stdout!r} err={result.stderr!r}"
    assert result.returncode == 0
    # The write must land in the checkout's store, not a second one in the worktree. Rows are
    # read from the checkout's tracking.db (P0.3/D18 flagged rewrite: the legacy
    # token-usage.json this used to read is renamed away by the migration the write ran).
    import sqlite3  # pylint: disable=import-outside-toplevel

    conn = sqlite3.connect(checkout / ".ai-badger" / "task-tracking" / "tracking.db")
    try:
        rows = conn.execute("SELECT task_id FROM token_usage").fetchall()
    finally:
        conn.close()
    assert rows == [("shared-store",)]
    assert not (worktree / ".ai-badger" / "task-tracking" / "token-usage.json").exists(), \
        "the worktree grew a store of its own"
    assert not (worktree / ".ai-badger" / "task-tracking" / "tracking.db").exists(), \
        "the worktree grew a store of its own"


def test_resolve_project_root_collapses_a_worktree_to_its_checkout(
        load_script, checkout_and_worktree):
    checkout, worktree = checkout_and_worktree
    tl = load_script(SOURCE)

    assert tl.resolve_project_root(env={}, cwd=worktree) == checkout


def test_resolve_project_root_leaves_the_checkout_itself_alone(
        load_script, checkout_and_worktree):
    checkout, _ = checkout_and_worktree
    tl = load_script(SOURCE)

    assert tl.resolve_project_root(env={}, cwd=checkout / ".ai-badger") == checkout


def test_claude_project_dir_still_wins_over_the_worktree_collapse(
        load_script, checkout_and_worktree, tmp_path):
    """The explicit override is the escape hatch the suite's own isolation depends on."""
    _, worktree = checkout_and_worktree
    override = tmp_path / "override"
    override.mkdir()
    tl = load_script(SOURCE)

    resolved = tl.resolve_project_root(
        env={"CLAUDE_PROJECT_DIR": str(override)}, cwd=worktree)

    assert resolved == override


def test_a_project_that_is_not_a_git_repo_resolves_to_itself(load_script, tmp_path):
    """No git, no collapse — and no traceback either."""
    project = tmp_path / "plain"
    (project / ".ai-badger").mkdir(parents=True)
    _test_write(project / ".ai-badger" / "config.json", "{}", encoding="utf-8")
    tl = load_script(SOURCE)

    assert tl.resolve_project_root(env={}, cwd=project) == project


def test_a_git_checkout_without_the_marker_above_it_is_not_adopted(load_script, tmp_path):
    """A nested project inside an unrelated repo must not be dragged out to that repo's root.

    The collapse only applies when the resolved checkout is itself an ai-badger project.
    """
    outer = tmp_path / "outer-repo"
    outer.mkdir()
    _git(outer, "init", "-b", "main")
    nested = outer / "vendor" / "nested-project"
    (nested / ".ai-badger").mkdir(parents=True)
    _test_write(nested / ".ai-badger" / "config.json", "{}", encoding="utf-8")
    tl = load_script(SOURCE)

    assert tl.resolve_project_root(env={}, cwd=nested) == nested


def test_a_worktree_of_a_repo_that_is_not_an_ai_badger_project_stays_where_it_is(
        tmp_path, load_script):
    """Only a linked worktree whose *checkout* is itself an ai-badger project is collapsed.

    Every other fixture here builds a checkout that already carries the marker, so deleting
    the marker guard from `collapse_worktree` changed no verdict — a vendored project nested
    in someone else's repo would have had its tracking writes redirected into that repo.
    """
    tracker = load_script(SOURCE)
    host = tmp_path / "host"
    host.mkdir()
    _git(host, "init", "-b", "main")
    _git(host, "config", "user.email", "test@example.invalid")
    _git(host, "config", "user.name", "Test")
    _test_write(host / "README.md", "# not an ai-badger project\n", encoding="utf-8")
    _git(host, "add", "README.md")
    _git(host, "commit", "-m", "host")
    vendored = host / "vendor" / "proj"
    _git(host, "worktree", "add", "-b", "vendored", str(vendored))
    marker = vendored / ".ai-badger" / "config.json"
    marker.parent.mkdir(parents=True)
    _test_write(marker, "{}", encoding="utf-8")

    assert not (host / ".ai-badger" / "config.json").is_file(), "the host must not be a project"
    assert tracker.collapse_worktree(vendored) == vendored

    subprocess.run(["git", "worktree", "remove", "--force", str(vendored)],
                   cwd=str(host), check=False, capture_output=True)
