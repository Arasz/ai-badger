"""`start` creates the worktree it records; `finish` refuses to remove a dirty one (D2).

`start --branch task/x` recorded a branch name and created nothing. Step 4 of the skill said
"create/switch to the task branch" in prose, which an agent can read and not do — twice in one
session on 2026-08-01, work landed on `main` and had to be recovered before it was pushed.

A recorded name that nothing creates is worse than no field at all: `status` reports the branch,
so the tracker looks like it is managing something it never touched.

So `start` creates a git worktree under `.claude/worktrees/<taskId>` on the recorded branch, and
`finish` removes it — unless it holds uncommitted changes or commits nothing else has, in which
case it refuses and says what it found. Cleanup that can silently destroy work is not cleanup.
"""
from __future__ import annotations

import subprocess

import pytest


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout


def _repo(tmp_path):
    """A real git repo with one commit — worktrees need a committed HEAD to branch from."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


@pytest.fixture(name="tracker")
def _tracker(load_script, root, monkeypatch):
    """task_tracker does a bare `import tracker_lib`, which importlib does not resolve for it.

    Unlike `test_task_tracker.py`'s fixture this does *not* stub `subprocess`: these functions
    exist to drive git, and a fake would make every assertion below vacuous.
    """
    monkeypatch.syspath_prepend(str(root / "features" / "common" / "skills" / "task" / "scripts"))
    return load_script("features/common/skills/task/scripts/task_tracker.py")


class TestTheWorktreeIsCreated:
    """The recorded branch has to exist on disk, not just in JSON."""

    def test_start_creates_a_worktree_on_the_recorded_branch(self, tmp_path, tracker):
        repo = _repo(tmp_path)

        path = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")

        assert path.is_dir()
        assert (path / ".git").exists()
        listing = _git(repo, "worktree", "list")
        assert str(path) in listing
        assert "task/issue-42-thing" in listing

    def test_the_worktree_lives_under_the_agent_worktree_directory(self, tmp_path, tracker):
        repo = _repo(tmp_path)

        path = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")

        assert path.parent == repo / ".claude" / "worktrees"

    def test_calling_it_twice_returns_the_same_worktree(self, tmp_path, tracker):
        """Re-running start after a resume must not fail on an existing worktree."""
        repo = _repo(tmp_path)

        first = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")
        second = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")

        assert first == second
        assert first.is_dir()

    def test_a_task_without_a_branch_gets_no_worktree(self, tmp_path, tracker):
        """Nothing is invented: no branch recorded means the caller did not ask for one."""
        repo = _repo(tmp_path)

        assert tracker.ensure_worktree(repo, "issue-42", "") is None


class TestATaskIdCannotEscapeTheWorktreeDirectory:
    """A task id reaches this from a CLI argument, so it is untrusted input on a path."""

    @pytest.mark.parametrize("hostile", ["..", "../..", "a/../../b", "/etc", "a/b"])
    def test_a_traversing_task_id_is_refused(self, tmp_path, tracker, hostile):
        repo = _repo(tmp_path)

        with pytest.raises(ValueError):
            tracker.worktree_path(repo, hostile)

    @pytest.mark.parametrize("ok", ["issue-42", "T02", "fix_thing.2", "266"])
    def test_an_ordinary_task_id_is_allowed(self, tmp_path, tracker, ok):
        repo = _repo(tmp_path)

        assert tracker.worktree_path(repo, ok).parent == repo / ".claude" / "worktrees"

    def test_the_refusal_reaches_ensure_and_release(self, tmp_path, tracker):
        """Both entry points validate; neither may be the one that forgot."""
        repo = _repo(tmp_path)

        with pytest.raises(ValueError):
            tracker.ensure_worktree(repo, "../escape", "task/x")
        with pytest.raises(ValueError):
            tracker.release_worktree(repo, "../escape")


class TestFinishRefusesToDestroyWork:
    """Cleanup that can silently lose a commit is not cleanup."""

    def test_a_clean_worktree_is_removed(self, tmp_path, tracker):
        repo = _repo(tmp_path)
        path = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")

        removed, reason = tracker.release_worktree(repo, "issue-42")

        assert removed is True
        assert reason == ""
        assert not path.exists()
        assert str(path) not in _git(repo, "worktree", "list")

    def test_an_uncommitted_file_blocks_removal(self, tmp_path, tracker):
        repo = _repo(tmp_path)
        path = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")
        (path / "wip.txt").write_text("half a thought\n", encoding="utf-8")

        removed, reason = tracker.release_worktree(repo, "issue-42")

        assert removed is False
        assert "wip.txt" in reason
        assert path.is_dir(), "the worktree was removed despite holding uncommitted work"

    def test_a_commit_no_other_branch_has_blocks_removal(self, tmp_path, tracker):
        """A committed-but-unpushed change is exactly what a dirty check on `status` misses."""
        repo = _repo(tmp_path)
        path = tracker.ensure_worktree(repo, "issue-42", "task/issue-42-thing")
        (path / "done.txt").write_text("finished\n", encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "real work")

        removed, reason = tracker.release_worktree(repo, "issue-42")

        assert removed is False
        assert "commit" in reason.lower()
        assert path.is_dir()

    def test_releasing_a_worktree_that_does_not_exist_is_not_an_error(self, tmp_path, tracker):
        """finish runs whether or not start made one; it must not fail the task."""
        repo = _repo(tmp_path)

        removed, reason = tracker.release_worktree(repo, "never-started")

        assert removed is False
        assert reason == ""


class TestTheBlockerIsAboutThisWorktreeOnly:
    """"Nowhere else" has to mean this branch, not "somewhere in the repo there is loose work"."""

    def test_another_branchs_unpushed_work_does_not_block_this_one(self, tmp_path, tracker):
        """The first implementation asked `--branches --not --remotes`, which is repo-wide.

        A worktree whose own branch is clean would then refuse to close because an unrelated
        branch had commits — a blocker nobody could act on from inside this worktree.
        """
        repo = _repo(tmp_path)
        noisy = tracker.ensure_worktree(repo, "noisy", "task/noisy")
        (noisy / "theirs.txt").write_text("elsewhere\n", encoding="utf-8")
        _git(noisy, "add", "-A")
        _git(noisy, "commit", "-q", "-m", "someone else's work")
        quiet = tracker.ensure_worktree(repo, "quiet", "task/quiet")

        assert tracker.worktree_blockers(quiet) == []
        assert tracker.worktree_blockers(noisy) != []

    def test_a_pushed_branch_does_not_block(self, tmp_path, tracker):
        """The case that killed the first implementation, reproduced with a real remote.

        `--branches --not --remotes` is repo-wide, so an unrelated branch's unpushed commit made
        it non-empty; combined with a `len(branches-containing-HEAD) == 1` test — which is true of
        any pushed branch — a fully-pushed worktree refused to close. Measured: old logic blocked,
        new logic does not.
        """
        repo = _repo(tmp_path)
        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        _git(repo, "remote", "add", "origin", str(remote))
        _git(repo, "push", "-q", "origin", "main")

        noisy = tracker.ensure_worktree(repo, "noisy", "task/noisy")
        (noisy / "theirs.txt").write_text("elsewhere\n", encoding="utf-8")
        _git(noisy, "add", "-A")
        _git(noisy, "commit", "-q", "-m", "someone else's unpushed work")

        pushed = tracker.ensure_worktree(repo, "pushed", "task/pushed")
        (pushed / "mine.txt").write_text("done\n", encoding="utf-8")
        _git(pushed, "add", "-A")
        _git(pushed, "commit", "-q", "-m", "my work")
        _git(pushed, "push", "-q", "-u", "origin", "task/pushed")

        assert tracker.worktree_blockers(pushed) == []
        assert tracker.worktree_blockers(noisy) != []

    def test_a_commit_that_another_branch_already_has_does_not_block(self, tmp_path, tracker):
        """Merged work is not lost by removing the directory that produced it."""
        repo = _repo(tmp_path)
        path = tracker.ensure_worktree(repo, "merged-one", "task/merged")
        (path / "done.txt").write_text("finished\n", encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "real work")
        _git(repo, "merge", "--ff-only", "task/merged")

        assert tracker.worktree_blockers(path) == []


class TestTheChecksCouldFail:
    """A dirty-check that cannot see dirt would silently delete every worktree."""

    def test_the_clean_case_and_the_dirty_case_disagree(self, tmp_path, tracker):
        repo = _repo(tmp_path)
        clean = tracker.ensure_worktree(repo, "clean-one", "task/clean")
        dirty = tracker.ensure_worktree(repo, "dirty-one", "task/dirty")
        (dirty / "wip.txt").write_text("x\n", encoding="utf-8")

        assert tracker.worktree_blockers(clean) == []
        assert tracker.worktree_blockers(dirty) != []
