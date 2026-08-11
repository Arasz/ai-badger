"""Tests for skills/feed-badger/scripts/open_pr.py: the mechanical git+gh steps that open a
draft PR to the framework repo.

CRITICAL: `subprocess.run` is patched in every test — no test in this file may ever invoke a
real git/gh command or touch the network. Tests that hit the non-dry-run path always patch
`subprocess.run` before calling `main()`.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from conftest import _test_write


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


def test_dry_run_makes_zero_subprocess_calls(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
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


def test_typical_flow_issues_expected_commands_in_order(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    body_file = tmp_path / "body.md"
    rel = _contribution(checkout)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        rc = open_pr.main(_argv(checkout, branch="feed/xyz", title="Add xyz feature",
                                 body_file=body_file, repo="Someone/fork", paths=[rel]))

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
    assert cmd1 == ["git", "add", "--", rel]
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
    rel = _contribution(checkout)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        open_pr.main(_argv(checkout, paths=[rel]))

    gh_cmd = mock_run.call_args_list[-1][0][0]
    assert "--repo" in gh_cmd
    assert gh_cmd[gh_cmd.index("--repo") + 1] == "Arasz/ai-badger"


def test_stops_and_returns_failure_code_when_a_step_fails(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    # git checkout -b and git add succeed, git commit fails (e.g. nothing to commit)
    rel = _contribution(checkout)
    responses = [Mock(returncode=0), Mock(returncode=0), Mock(returncode=1)]
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = responses
        rc = open_pr.main(_argv(checkout, paths=[rel]))

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


# ── outbound content guard + explicit pathspec (security I4) ──────────────────

FAKE_GITHUB_TOKEN = "ghp_FAKEnotarealtoken" + "0" * 19


def test_a_secret_shaped_literal_blocks_the_pr(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
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


def test_the_blocked_output_never_prints_the_matched_text(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    rel = _contribution(checkout, body=f"token: {FAKE_GITHUB_TOKEN}\n")

    with patch("subprocess.run"):
        open_pr.main(_argv(checkout, dry_run=True) + ["--path", rel])

    assert FAKE_GITHUB_TOKEN not in capsys.readouterr().out


def test_a_clean_contribution_stages_only_the_declared_paths(tmp_path, load_script):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    rel = _contribution(checkout)
    _test_write(checkout / "index.json", "{}\n", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        rc = open_pr.main(_argv(checkout) + ["--path", rel, "--path", "index.json"])

    assert rc == 0
    add_cmd = [c[0][0] for c in mock_run.call_args_list if c[0][0][:2] == ["git", "add"]][0]
    assert add_cmd == ["git", "add", "--", rel, "index.json"]
    assert "-A" not in add_cmd


def test_an_unrelated_dirty_file_is_not_staged(tmp_path, load_script):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    rel = _contribution(checkout)
    _test_write(checkout / "unrelated-local-note.md", "private\n", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        open_pr.main(_argv(checkout) + ["--path", rel])

    add_cmd = [c[0][0] for c in mock_run.call_args_list if c[0][0][:2] == ["git", "add"]][0]
    assert "unrelated-local-note.md" not in add_cmd


def test_omitting_path_is_a_usage_error_rather_than_staging_everything(tmp_path, load_script):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    with patch("subprocess.run") as mock_run:
        with pytest.raises(SystemExit):
            open_pr.main(_argv(checkout))

    mock_run.assert_not_called()


def test_a_declared_directory_is_scanned_recursively(tmp_path, load_script, capsys):
    open_pr = load_script("features/common/skills/feed-badger/scripts/open_pr.py")
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
