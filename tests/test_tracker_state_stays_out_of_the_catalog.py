"""Tracker state belongs to the project, never to the `features/` catalog it was copied from.

A checkout carried `features/.ai-badger/task-tracking/poll_limit.pid` and `poll_limit.log`:
untracked, unignored, and enough to turn `validate.py --all` red (0.93.1 fixed the symptom).
`collapse_worktree()` (0.88.6) did not prevent it because the two live on different branches
of `resolve_project_root`: the collapse only ever runs on the *cwd walk*, and this leak comes
from the fallback the walk falls through to — `script_dir.parents[3]`, which for the catalog
copy at `features/common/skills/task/scripts/` is `features/` itself.

Every fixture here is a replica under tmp_path. Running the real catalog copy against the real
checkout is what wrote the state this test exists to stop.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG_SCRIPTS = ROOT / "features" / "common" / "skills" / "task" / "scripts"
SCRIPTS_RELATIVE = "features/common/skills/task/scripts"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture(name="replica")
def _replica(tmp_path):
    """A repo carrying the marker plus a real copy of the catalog's task scripts.

    The scripts are copied, not imported in place: `resolve_project_root` reads
    `Path(__file__).resolve().parent`, so only a copy at the same relative depth reproduces
    the fallback that lands in `features/`.
    """
    repo = tmp_path / "repo"
    scripts = repo / SCRIPTS_RELATIVE
    scripts.parent.mkdir(parents=True)
    shutil.copytree(CATALOG_SCRIPTS, scripts,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    marker = repo / ".ai-badger" / "config.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "replica")

    outside = tmp_path / "outside"
    outside.mkdir()
    return repo, scripts, outside


def _child_env() -> dict:
    """The suite points CLAUDE_PROJECT_DIR at a scratch project; the resolver must decide alone."""
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _resolved_root(scripts: Path, cwd: Path) -> Path:
    """`tracker_lib.PROJECT_ROOT` as a fresh child interpreter computes it from *cwd*."""
    result = subprocess.run(
        [sys.executable, "-c", "import tracker_lib; print(tracker_lib.PROJECT_ROOT)"],
        cwd=str(cwd), env={**_child_env(), "PYTHONPATH": str(scripts)},
        capture_output=True, text=True, check=True)
    return Path(result.stdout.strip())


def test_a_cwd_with_no_marker_above_it_does_not_make_the_catalog_the_project(replica):
    """The N3 leak, at its source: the fallback resolved `features/`, one level too deep."""
    repo, scripts, outside = replica

    resolved = _resolved_root(scripts, outside)

    assert resolved == repo, f"the catalog copy adopted {resolved} as the project root"


def test_the_store_is_the_same_from_the_checkout_a_worktree_and_the_catalog_directory(replica):
    """One store, whichever of the three directories the process happens to start in."""
    repo, scripts, _ = replica
    worktree = repo / ".ai-badger" / "worktrees" / "task-x"
    _git(repo, "worktree", "add", "-b", "task/x", str(worktree))
    try:
        roots = {
            "checkout": _resolved_root(scripts, repo),
            "worktree": _resolved_root(scripts, worktree),
            "features": _resolved_root(scripts, repo / "features"),
        }
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                       cwd=str(repo), check=False, capture_output=True)

    assert set(roots.values()) == {repo}, f"three cwds, {len(set(roots.values()))} stores: {roots}"


def test_writing_a_poller_pid_from_an_unmarked_cwd_leaves_the_catalog_untouched(replica):
    """`poll_limit.pid` and `poll_limit.log` are the two files the leak actually deposited."""
    repo, scripts, outside = replica
    code = ("import poll_limit\n"
            "poll_limit.write_pid()\n"
            "poll_limit.log('probe')\n")

    subprocess.run([sys.executable, "-c", code], cwd=str(outside),
                   env={**_child_env(), "PYTHONPATH": str(scripts)},
                   capture_output=True, text=True, check=True)

    strays = sorted(str(p.relative_to(repo)) for p in (repo / "features").rglob("*")
                    if p.is_file() and ".ai-badger" in p.parts)
    assert not strays, f"the poller wrote into the catalog: {strays}"
    assert (repo / ".ai-badger" / "task-tracking" / "poll_limit.pid").is_file(), \
        "the pid file has to land somewhere — this test is about where, not whether"
