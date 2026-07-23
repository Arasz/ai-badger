"""Tests for skills/feed-badger/scripts/open_pr.py: the mechanical git+gh steps that open a
draft PR to the framework repo.

CRITICAL: `subprocess.run` is patched in every test — no test in this file may ever invoke a
real git/gh command or touch the network. Tests that hit the non-dry-run path always patch
`subprocess.run` before calling `main()`.
"""
from __future__ import annotations

from unittest.mock import Mock, patch


def _argv(checkout, branch="feed/my-feature", title="Add my-feature", body_file="body.md",
          repo=None, dry_run=False):
    argv = [
        "--checkout", str(checkout),
        "--branch", branch,
        "--title", title,
        "--body-file", str(body_file),
    ]
    if repo is not None:
        argv += ["--repo", repo]
    if dry_run:
        argv.append("--dry-run")
    return argv


def test_dry_run_makes_zero_subprocess_calls(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    with patch("subprocess.run") as mock_run:
        rc = open_pr.main(_argv(checkout, dry_run=True))

    assert rc == 0
    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "dry-run=True" in out
    # every step is still reported, just not executed
    assert "$ git checkout -b feed/my-feature" in out
    assert "$ git add -A" in out
    assert "$ git commit -m Add my-feature" in out
    assert "$ git push -u origin feed/my-feature" in out
    assert "$ gh pr create --draft --repo Arasz/ai-badger" in out


def test_typical_flow_issues_expected_commands_in_order(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    body_file = tmp_path / "body.md"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        rc = open_pr.main(_argv(checkout, branch="feed/xyz", title="Add xyz feature",
                                 body_file=body_file, repo="Someone/fork"))

    assert rc == 0
    assert mock_run.call_count == 5
    calls = mock_run.call_args_list

    def cmd_and_cwd(call):
        args, kwargs = call
        return args[0], kwargs.get("cwd")

    resolved_checkout = str(checkout.resolve())

    cmd0, cwd0 = cmd_and_cwd(calls[0])
    assert cmd0 == ["git", "checkout", "-b", "feed/xyz"]
    assert cwd0 == resolved_checkout

    cmd1, cwd1 = cmd_and_cwd(calls[1])
    assert cmd1 == ["git", "add", "-A"]
    assert cwd1 == resolved_checkout

    cmd2, _ = cmd_and_cwd(calls[2])
    assert cmd2 == ["git", "commit", "-m", "Add xyz feature"]

    cmd3, _ = cmd_and_cwd(calls[3])
    assert cmd3 == ["git", "push", "-u", "origin", "feed/xyz"]

    cmd4, _ = cmd_and_cwd(calls[4])
    assert cmd4 == ["gh", "pr", "create", "--draft", "--repo", "Someone/fork",
                     "--title", "Add xyz feature", "--body-file", str(body_file)]

    for call in calls:
        _, kwargs = call
        assert kwargs.get("check") is False


def test_default_repo_is_used_when_not_specified(tmp_path, load_script):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        open_pr.main(_argv(checkout))

    gh_cmd = mock_run.call_args_list[-1][0][0]
    assert "--repo" in gh_cmd
    assert gh_cmd[gh_cmd.index("--repo") + 1] == "Arasz/ai-badger"


def test_stops_and_returns_failure_code_when_a_step_fails(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    # git checkout -b and git add -A succeed, git commit fails (e.g. nothing to commit)
    responses = [Mock(returncode=0), Mock(returncode=0), Mock(returncode=1)]
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = responses
        rc = open_pr.main(_argv(checkout))

    assert rc == 1
    assert mock_run.call_count == 3  # push and gh pr create never attempted
    out = capsys.readouterr().out
    assert "step failed" in out


def test_no_real_subprocess_invoked_without_patch_would_be_caught(tmp_path, load_script):
    """Sanity check on the test harness itself: confirms `run()` really delegates to
    `subprocess.run` (so patching it is sufficient to guarantee no real process starts)."""
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        rc = open_pr.run(["git", "status"], checkout, dry=False)

    assert rc == 0
    mock_run.assert_called_once_with(["git", "status"], cwd=str(checkout), check=False)
