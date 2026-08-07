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
    marker.write_text("{}", encoding="utf-8")
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
    (tracking / "executed-tasks.json").write_text(json.dumps({"tasks": [{
        "taskId": task_id,
        "state": "IN_PROGRESS",
        "startedAt": "2026-08-07T00:00:00+00:00",
        "sessionId": "s-1",
    }]}), encoding="utf-8")
    (tracking / "token-usage.json").write_text(json.dumps({"tasks": [{
        "taskId": task_id,
        "sessionId": "s-1",
        "trackingSource": "claude",
        "checkpoints": {},
    }]}), encoding="utf-8")
    return tracking


def _tracker_env() -> dict:
    """The child's environment with CLAUDE_PROJECT_DIR removed, so the cwd walk decides.

    The suite points that variable at a scratch project; leaving it set would make the child
    resolve there and the test would prove nothing about worktrees.
    """
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
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
    # The write must land in the checkout's store, not a second one in the worktree.
    usage = json.loads((checkout / ".ai-badger" / "task-tracking"
                        / "token-usage.json").read_text(encoding="utf-8"))
    assert usage["tasks"][0]["taskId"] == "shared-store"
    assert not (worktree / ".ai-badger" / "task-tracking" / "token-usage.json").exists(), \
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
    (project / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
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
    (nested / ".ai-badger" / "config.json").write_text("{}", encoding="utf-8")
    tl = load_script(SOURCE)

    assert tl.resolve_project_root(env={}, cwd=nested) == nested
