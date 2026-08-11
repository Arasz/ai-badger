"""project_id from inside a linked git worktree: must resolve to the MAIN checkout.

This project's standard workflow is worktree-per-task (worktrees live at
<repo>/.ai-badger/worktrees/<name>), and `project_id` feeds a memory bank id. Before this
fix it took `Path(cwd).name`, which names the worktree directory itself — a bank the
project never wrote to.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import subprocess

import pytest
from conftest import _test_write

_GIT_ENV = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _git(*args, cwd):
    subprocess.run(["git", *_GIT_ENV, *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def gate(load_script, monkeypatch, tmp_path):
    """The real module, with the marker dir redirected to tmp paths."""
    real = load_script("features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")
    monkeypatch.setattr(real, "MARKER_DIR", tmp_path / "memory-first")
    return real


@pytest.fixture
def repo_with_worktree(tmp_path):
    """A real git repo (basename `main-repo`) with a real linked worktree, cleaned up after."""
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _git("init", "-q", cwd=main_repo)
    _test_write(main_repo / "README.md", "hello\n", encoding="utf-8")
    _git("add", "README.md", cwd=main_repo)
    _git("commit", "-q", "-m", "initial commit", cwd=main_repo)

    worktree_path = tmp_path / "worktrees" / "task-branch"
    worktree_path.parent.mkdir(parents=True)
    _git("worktree", "add", "-q", "-b", "task-branch", str(worktree_path), cwd=main_repo)

    yield main_repo, worktree_path

    _git("worktree", "remove", "--force", str(worktree_path), cwd=main_repo)


def test_project_id_from_worktree_resolves_to_main_checkout(gate, repo_with_worktree):
    main_repo, worktree_path = repo_with_worktree
    assert gate.project_id(str(worktree_path)) == main_repo.name


def test_deny_reason_names_main_checkout_from_worktree_cwd(gate, repo_with_worktree):
    main_repo, worktree_path = repo_with_worktree
    decision = gate.build_decision("claude", "Grep", {}, "s1", cwd=str(worktree_path))
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert f"project_id={main_repo.name}" in reason
    assert worktree_path.name not in reason


def test_env_override_wins_from_worktree(gate, monkeypatch, repo_with_worktree):
    _, worktree_path = repo_with_worktree
    monkeypatch.setenv("AI_RACCOON_PROJECT_ID", "custom-bank")
    assert gate.project_id(str(worktree_path)) == "custom-bank"


def test_project_id_non_git_dir_falls_back_to_basename(gate, tmp_path):
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()
    assert gate.project_id(str(plain_dir)) == "not-a-repo"


def test_project_id_empty_cwd_falls_back_to_unknown(gate):
    assert gate.project_id("") == "unknown"