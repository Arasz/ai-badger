"""Tests for skills/feed-badger/scripts/open_pr.py: the mechanical git+gh steps that open a
draft PR to the framework repo.

The dry-run tests patch `subprocess.run` and assert it is never called. Every other test runs
real git in a tmp checkout whose `origin` is a local bare repo, with a stub `gh` first on PATH
that only records its arguments — no test here reaches GitHub or the network.
"""
# pylint: disable=redefined-outer-name  # pytest fixtures are injected by name
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import _test_write

SCRIPT = "features/common/skills/feed-badger/scripts/open_pr.py"
GIT_ENV_TO_CLEAR = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                    "GIT_PREFIX", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
                    "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS")
FAKE_GITHUB_TOKEN = "ghp_FAKEnotarealtoken" + "0" * 19


def _argv(checkout, branch="feed/my-feature", title="Add my-feature", body_file="body.md",
          repo=None, dry_run=False, paths=()):
    argv = [
        "--checkout", str(checkout),
        "--branch", branch,
        "--title", title,
        "--body-file", str(body_file),
    ]
    for rel in paths:
        argv += ["--path", rel]
    if repo is not None:
        argv += ["--repo", repo]
    if dry_run:
        argv.append("--dry-run")
    return argv


def _contribution(checkout, rel="features/common/skills/thing/SKILL.md", body="# thing\n"):
    path = checkout / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, body, encoding="utf-8")
    return rel


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          check=True).stdout


class World:
    """A real checkout, its bare `origin`, and the log the stub `gh` appends its argv to."""

    def __init__(self, root: Path):
        self.checkout = root / "checkout"
        self.remote = root / "remote.git"
        self.gh_log = root / "gh.log"

    def remote_files(self, branch):
        """Files on `branch` in the bare remote, or None when the branch never arrived."""
        proc = subprocess.run(["git", "--git-dir", str(self.remote), "ls-tree", "-r",
                               "--name-only", branch], capture_output=True, text=True,
                              check=False)
        return set(proc.stdout.split()) if proc.returncode == 0 else None

    def gh_calls(self):
        if not self.gh_log.exists():
            return []
        return self.gh_log.read_text(encoding="utf-8").splitlines()

    def staged(self):
        return _git(self.checkout, "diff", "--cached", "--name-only").split()


@pytest.fixture
def world(tmp_path, monkeypatch):
    for name in GIT_ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    w = World(tmp_path)
    _git(tmp_path, "init", "-q", "--bare", str(w.remote))
    _git(tmp_path, "init", "-q", "-b", "main", str(w.checkout))
    for key, value in (("user.email", "t@t.co"), ("user.name", "t"),
                       ("commit.gpgsign", "false")):
        _git(w.checkout, "config", key, value)
    _test_write(w.checkout / "README.md", "# framework\n", encoding="utf-8")
    _git(w.checkout, "add", "README.md")
    _git(w.checkout, "commit", "-q", "-m", "init")
    _git(w.checkout, "remote", "add", "origin", str(w.remote))
    _git(w.checkout, "push", "-q", "origin", "main")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    _test_write(gh, f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> '{w.gh_log}'\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return w


@pytest.fixture
def open_pr(load_script):
    return load_script(SCRIPT)


# ── dry run: prints, never executes ───────────────────────────────────────────


def test_dry_run_makes_zero_subprocess_calls(tmp_path, open_pr, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    rel = _contribution(checkout)

    with patch("subprocess.run") as mock_run:
        rc = open_pr.main(_argv(checkout, dry_run=True, paths=[rel]))

    assert rc == 0
    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "dry-run=True" in out
    # every step is still reported, just not executed
    assert "$ git checkout -b feed/my-feature" in out
    assert f"$ git add -- {rel}" in out
    assert "$ git commit -m Add my-feature" in out
    assert "$ git push -u origin feed/my-feature" in out
    assert "$ gh pr create --draft --repo Arasz/ai-badger" in out


def test_a_secret_shaped_literal_blocks_the_pr(tmp_path, open_pr, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    rel = _contribution(checkout, body=f"token: {FAKE_GITHUB_TOKEN}\n")

    with patch("subprocess.run") as mock_run:
        rc = open_pr.main(_argv(checkout, dry_run=True) + ["--path", rel])

    out = capsys.readouterr().out
    assert rc == 1
    mock_run.assert_not_called()
    assert rel in out
    assert "github token" in out
    assert "git push" not in out


def test_the_blocked_output_never_prints_the_matched_text(tmp_path, open_pr, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    rel = _contribution(checkout, body=f"token: {FAKE_GITHUB_TOKEN}\n")

    with patch("subprocess.run"):
        open_pr.main(_argv(checkout, dry_run=True) + ["--path", rel])

    assert FAKE_GITHUB_TOKEN not in capsys.readouterr().out


def test_omitting_path_is_a_usage_error_rather_than_staging_everything(tmp_path, open_pr):
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    with patch("subprocess.run") as mock_run:
        with pytest.raises(SystemExit):
            open_pr.main(_argv(checkout))

    mock_run.assert_not_called()


def test_a_declared_directory_is_scanned_recursively(tmp_path, open_pr, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _contribution(checkout, rel="features/common/skills/thing/SKILL.md")
    _contribution(checkout, rel="features/common/skills/thing/notes.md",
                  body=f"api_key = {FAKE_GITHUB_TOKEN}\n")

    with patch("subprocess.run") as mock_run:
        rc = open_pr.main(_argv(checkout, dry_run=True)
                          + ["--path", "features/common/skills/thing"])

    assert rc == 1
    mock_run.assert_not_called()
    assert "notes.md" in capsys.readouterr().out


# ── real git: a local bare origin and a stub gh ───────────────────────────────


def test_a_clean_contribution_reaches_origin_with_only_the_declared_paths(open_pr, world,
                                                                          tmp_path):
    rel = _contribution(world.checkout)
    _test_write(world.checkout / "index.json", "{}\n", encoding="utf-8")
    _test_write(world.checkout / "unrelated-local-note.md", "private\n", encoding="utf-8")
    body_file = tmp_path / "body.md"

    rc = open_pr.main(_argv(world.checkout, branch="feed/xyz", title="Add xyz feature",
                            body_file=body_file, repo="Someone/fork",
                            paths=[rel, "index.json"]))

    assert rc == 0
    assert world.remote_files("feed/xyz") == {"README.md", rel, "index.json"}
    assert world.gh_calls() == ["pr", "create", "--draft", "--repo", "Someone/fork",
                                "--title", "Add xyz feature", "--body-file", str(body_file)]


def test_the_default_repo_is_the_framework(open_pr, world):
    rel = _contribution(world.checkout)

    open_pr.main(_argv(world.checkout, paths=[rel]))

    calls = world.gh_calls()
    assert calls[calls.index("--repo") + 1] == "Arasz/ai-badger"


def test_a_failed_push_stops_before_the_pr_is_opened(open_pr, world, capsys):
    rel = _contribution(world.checkout)
    _git(world.checkout, "remote", "set-url", "origin", str(world.remote) + "-missing")

    rc = open_pr.main(_argv(world.checkout, paths=[rel]))

    assert rc != 0
    assert world.gh_calls() == []
    assert "step failed" in capsys.readouterr().out


def test_a_glob_path_is_taken_literally_and_refused(open_pr, world):
    """L9-1: git expanded `features/**` while the scanner saw one missing file and skipped it."""
    _contribution(world.checkout, rel="features/common/skills/thing/SKILL.md")
    _contribution(world.checkout, rel="features/private/notes.md")

    rc = open_pr.main(_argv(world.checkout, paths=["features/**"]))

    assert rc != 0
    assert world.remote_files("feed/my-feature") is None
    assert world.gh_calls() == []
    assert world.staged() == []


def test_a_secret_reached_through_a_glob_never_leaves(open_pr, world, capsys):
    _contribution(world.checkout, rel="features/private/notes.md",
                  body=f"token: {FAKE_GITHUB_TOKEN}\n")

    rc = open_pr.main(_argv(world.checkout, paths=["features/**"]))

    assert rc != 0
    assert world.remote_files("feed/my-feature") is None
    assert world.gh_calls() == []
    assert FAKE_GITHUB_TOKEN not in capsys.readouterr().out


def test_a_file_staged_before_the_run_refuses_the_pr(open_pr, world, capsys):
    """L9-1: `git commit` took everything in the index, declared or not."""
    rel = _contribution(world.checkout)
    _test_write(world.checkout / "staged-earlier.md", "not declared\n", encoding="utf-8")
    _git(world.checkout, "add", "staged-earlier.md")

    rc = open_pr.main(_argv(world.checkout, paths=[rel]))

    assert rc != 0
    assert world.remote_files("feed/my-feature") is None
    assert world.gh_calls() == []
    assert world.staged() == ["staged-earlier.md"], "the user's index is left as it was"
    assert "staged-earlier.md" in capsys.readouterr().out


def test_an_oversized_declared_file_is_refused(open_pr, world, capsys):
    """R15: the scanner skips files over its size cap, so an outbound PR must not carry one."""
    limit = open_pr.ul.LITERAL_SCAN_MAX_BYTES
    rel = _contribution(world.checkout, rel="features/big.md",
                        body=f"token: {FAKE_GITHUB_TOKEN}\n" + "x" * limit)

    rc = open_pr.main(_argv(world.checkout, paths=[rel]))

    assert rc != 0
    assert world.remote_files("feed/my-feature") is None
    assert world.gh_calls() == []
    assert "features/big.md" in capsys.readouterr().out


def test_a_finding_in_the_staged_set_refuses_and_unstages(open_pr, world):
    _contribution(world.checkout, rel="features/common/skills/thing/SKILL.md")
    _contribution(world.checkout, rel="features/common/skills/thing/notes.md",
                  body=f"api_key = {FAKE_GITHUB_TOKEN}\n")

    rc = open_pr.main(_argv(world.checkout, paths=["features/common/skills/thing"]))

    assert rc == 1
    assert world.remote_files("feed/my-feature") is None
    assert world.gh_calls() == []
    assert world.staged() == []
    assert _git(world.checkout, "branch", "--show-current").strip() == "main"
