"""Tests for gates/release_guard.py: shipped-surface-changed-without-a-bump gate.

Builds throwaway git repos under tmp_path (git init + commits + tags) since the guard is
inherently git-shaped; tests/conftest.py has no existing git-repo helpers to reuse.
"""
from __future__ import annotations

import subprocess

import pytest


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                           capture_output=True, text=True).stdout


def _init_repo(path):
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


def _commit_all(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _tag(repo, name):
    _git(repo, "tag", name)


def test_latest_release_tag_selects_highest_semver_not_lexicographic_or_latest_date(
    tmp_path, load_script,
):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)

    (repo / "VERSION").write_text("0.10.0\n", encoding="utf-8")
    _commit_all(repo, "v0.10.0")
    _tag(repo, "ai-badger--v0.10.0")  # tagged first (older), but the higher semver

    (repo / "VERSION").write_text("0.9.0\n", encoding="utf-8")
    _commit_all(repo, "v0.9.0")
    _tag(repo, "ai-badger--v0.9.0")  # tagged later (newer), but the lower semver

    tag = release_guard.latest_release_tag(repo)

    assert tag == "ai-badger--v0.10.0"


def test_no_release_tag_passes_with_explanatory_message(tmp_path, load_script, capsys):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    _commit_all(repo, "init")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "NO RELEASE TAG FOUND" in out


def test_fails_when_shipped_path_changed_without_version_bump(tmp_path, load_script, capsys):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    _commit_all(repo, "release 0.1.0")
    _tag(repo, "ai-badger--v0.1.0")

    (repo / "skills" / "a.md").write_text("changed\n", encoding="utf-8")
    _commit_all(repo, "tweak a skill, forgot to bump")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "skills/a.md" in out
    assert "bump VERSION" in out


def test_passes_when_shipped_path_changed_and_version_was_bumped(tmp_path, load_script, capsys):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    _commit_all(repo, "release 0.1.0")
    _tag(repo, "ai-badger--v0.1.0")

    (repo / "skills" / "a.md").write_text("changed\n", encoding="utf-8")
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "tweak a skill + bump")

    rc = release_guard.main(["--root", str(repo)])

    assert rc == 0


def test_passes_when_only_non_shipped_paths_changed_without_a_bump(tmp_path, load_script):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text("n\n", encoding="utf-8")
    _commit_all(repo, "release 0.1.0")
    _tag(repo, "ai-badger--v0.1.0")

    (repo / "docs" / "notes.md").write_text("edited\n", encoding="utf-8")
    _commit_all(repo, "docs only, no bump needed")

    rc = release_guard.main(["--root", str(repo)])

    assert rc == 0


def test_several_commits_can_land_at_one_unreleased_version_against_last_tag(
    tmp_path, load_script,
):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    _commit_all(repo, "release 0.1.0")
    _tag(repo, "ai-badger--v0.1.0")

    (repo / "skills" / "a.md").write_text("first PR change\n", encoding="utf-8")
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "PR1: bump + change")

    assert release_guard.main(["--root", str(repo)]) == 0

    (repo / "skills" / "a.md").write_text("second PR change, same unreleased version\n",
                                           encoding="utf-8")
    _commit_all(repo, "PR2: more change, still 0.2.0")

    # compared against the last release TAG (still 0.1.0), not the previous commit, so this
    # still passes: VERSION (0.2.0) still differs from the tag's version (0.1.0).
    assert release_guard.main(["--root", str(repo)]) == 0


def _released_repo(path):
    """A repo at 0.1.0 with one shipped file, tagged — the guard's happy starting state."""
    repo = _init_repo(path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    _commit_all(repo, "release 0.1.0")
    _tag(repo, "ai-badger--v0.1.0")
    return repo


def _break_git_subcommand(monkeypatch, release_guard, subcommand):
    """Make one git subcommand exit non-zero; every other git call runs for real."""
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if list(cmd[:2]) == ["git", subcommand]:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: bad object HEAD\n")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(release_guard.subprocess, "run", fake_run)


def test_git_failure_is_not_reported_as_no_changes(tmp_path, load_script, capsys, monkeypatch):
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _break_git_subcommand(monkeypatch, release_guard, "diff")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "GIT COMMAND FAILED" in out
    assert "no shipped-surface changes" not in out


def test_git_failure_listing_tags_is_not_reported_as_no_release_tag(
    tmp_path, load_script, capsys, monkeypatch,
):
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _break_git_subcommand(monkeypatch, release_guard, "tag")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "GIT COMMAND FAILED" in out
    assert "NO RELEASE TAG FOUND" not in out


def test_git_failure_reports_the_command_and_stderr(tmp_path, load_script, capsys, monkeypatch):
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _break_git_subcommand(monkeypatch, release_guard, "diff")

    release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert "git diff" in out
    assert "fatal: bad object HEAD" in out


def _changelog(repo, *versions):
    (repo / "docs" / "changelog").mkdir(parents=True, exist_ok=True)
    for version in versions:
        (repo / "docs" / "changelog" / f"{version}-slug.md").write_text("x\n", encoding="utf-8")


def test_versions_documented_but_never_tagged_fail_the_guard(tmp_path, load_script, capsys):
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _changelog(repo, "0.1.0", "0.2.0", "0.3.0", "0.4.0")
    (repo / "VERSION").write_text("0.4.0\n", encoding="utf-8")
    (repo / "skills" / "a.md").write_text("changed\n", encoding="utf-8")
    _commit_all(repo, "several releases documented, none tagged")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "UNTAGGED RELEASES" in out
    assert "0.2.0" in out and "0.3.0" in out
    assert "0.4.0" not in out.split("UNTAGGED RELEASES")[1]  # in flight, not skipped


def test_an_untagged_release_fails_even_when_the_shipped_surface_is_unchanged(
    tmp_path, load_script, capsys,
):
    """The shape that let 0.35.0-0.35.2 ship untagged: a docs-only push after a release."""
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _changelog(repo, "0.1.0", "0.2.0", "0.3.0")
    (repo / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    _commit_all(repo, "docs-only follow-up; skills/ untouched since 0.1.0")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "UNTAGGED RELEASES" in out
    assert "0.2.0" in out


def test_a_changelog_entry_for_the_tagged_version_is_not_reported(tmp_path, load_script, capsys):
    """`low < version` is strict: the last released version is tagged, by definition."""
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _changelog(repo, "0.1.0", "0.2.0")
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "one release in flight, its predecessor tagged")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "UNTAGGED RELEASES" not in out


def test_the_version_in_flight_alone_is_not_reported_as_untagged(tmp_path, load_script, capsys):
    release_guard = load_script("gates/release_guard.py")
    repo = _released_repo(tmp_path)
    _changelog(repo, "0.1.0", "0.2.0")
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (repo / "skills" / "a.md").write_text("changed\n", encoding="utf-8")
    _commit_all(repo, "one unreleased version, the normal case")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "UNTAGGED RELEASES" not in out


def test_git_helper_raises_rather_than_returning_empty_output(tmp_path, load_script):
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)

    with pytest.raises(release_guard.GitCommandFailed):
        release_guard._git(repo, "rev-parse", "definitely-not-a-ref")


# ── a tag that exists only locally ──────────────────────────────────────────────
#
# latest_release_tag reads `git tag -l`, which is local. On 2026-08-01 a push of
# ai-badger--v0.61.3 reported success and never landed the tag; the guard passed on the
# machine that held it locally, and failed in CI on the next two PRs, where a fresh clone has
# only remote tags. The symptom appeared on a later PR than the cause, which is why it took two
# red lanes to find.


def _add_remote(repo, remote_path):
    _git(repo, "remote", "add", "origin", str(remote_path))


def _bare_remote(tmp_path):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    return remote


def test_a_tag_only_on_this_machine_is_reported(tmp_path, load_script):
    guard = load_script("gates/release_guard.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "first")
    _tag(repo, "ai-badger--v0.1.0")
    remote = _bare_remote(tmp_path)
    _add_remote(repo, remote)
    _git(repo, "push", "-q", "origin", "HEAD")

    # Nothing published above it, so it reads as a release mid-push and is not reported.
    assert guard.unpushed_release_tags(repo) == []


def test_a_tag_on_the_remote_is_not_reported(tmp_path, load_script):
    guard = load_script("gates/release_guard.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "first")
    _tag(repo, "ai-badger--v0.1.0")
    remote = _bare_remote(tmp_path)
    _add_remote(repo, remote)
    _git(repo, "push", "-q", "origin", "HEAD")
    _git(repo, "push", "-q", "origin", "refs/tags/ai-badger--v0.1.0")

    assert guard.unpushed_release_tags(repo) == []


def test_no_remote_is_not_a_failure(tmp_path, load_script):
    """A clone with no reachable origin must not fail; the check adds signal or stays quiet."""
    guard = load_script("gates/release_guard.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "first")
    _tag(repo, "ai-badger--v0.1.0")

    assert guard.unpushed_release_tags(repo) == []


def test_only_release_tags_are_considered(tmp_path, load_script):
    """An unrelated local tag is not a release and must not be reported as unpushed."""
    guard = load_script("gates/release_guard.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    _commit_all(repo, "first")
    _tag(repo, "scratch-marker")
    remote = _bare_remote(tmp_path)
    _add_remote(repo, remote)
    _git(repo, "push", "-q", "origin", "HEAD")

    assert guard.unpushed_release_tags(repo) == []


def test_the_newest_local_tag_is_never_reported(tmp_path, load_script):
    """Otherwise the guard blocks the push that would satisfy it.

    Merged as 0.64.3, this check refused any local-only release tag — including the one being
    cut right now, whose push runs the same pre-push hook. Circular: the tag cannot reach the
    remote because it is not on the remote.

    The rule is now about the *sequence*, not about VERSION: a tag is reported only when the
    remote already has a higher one, meaning the release order skipped it. A tag above
    everything published is indistinguishable from one mid-push, so it is never reported.
    """
    guard = load_script("gates/release_guard.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    _commit_all(repo, "first")
    _tag(repo, "ai-badger--v0.3.0")
    remote = _bare_remote(tmp_path)
    _add_remote(repo, remote)
    _git(repo, "push", "-q", "origin", "HEAD")

    assert guard.unpushed_release_tags(repo) == []


def test_a_tag_the_remote_moved_past_is_reported(tmp_path, load_script):
    """The exact shape of the real failure: 0.61.3 lost, then 0.62.0 published without it."""
    guard = load_script("gates/release_guard.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    _commit_all(repo, "first")
    _tag(repo, "ai-badger--v0.2.0")
    _tag(repo, "ai-badger--v0.3.0")
    remote = _bare_remote(tmp_path)
    _add_remote(repo, remote)
    _git(repo, "push", "-q", "origin", "HEAD")
    _git(repo, "push", "-q", "origin", "refs/tags/ai-badger--v0.3.0")

    assert guard.unpushed_release_tags(repo) == ["ai-badger--v0.2.0"]


def test_fails_when_version_goes_backwards(tmp_path, load_script, capsys):
    """A bump is upward. Inequality is not ordering (main went 0.70.0 -> 0.69.3 and passed).

    Two PRs merged out of order on 2026-08-01: 0.70.0 landed, then a 0.69.3 branch merged and
    wrote VERSION backwards. The guard reported "VERSION was bumped (0.70.0 -> 0.69.3) — PASS",
    because it only asked whether the strings differed.
    """
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    _commit_all(repo, "release 0.2.0")
    _tag(repo, "ai-badger--v0.2.0")

    (repo / "skills" / "a.md").write_text("changed\n", encoding="utf-8")
    (repo / "VERSION").write_text("0.1.9\n", encoding="utf-8")
    _commit_all(repo, "tweak a skill + move VERSION backwards")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "0.1.9" in out and "0.2.0" in out


def test_fails_when_version_equals_an_older_released_tag(tmp_path, load_script):
    """Re-using a released version is the same defect wearing a different number."""
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (repo / "skills").mkdir()
    (repo / "skills" / "a.md").write_text("a\n", encoding="utf-8")
    _commit_all(repo, "release 0.2.0")
    _tag(repo, "ai-badger--v0.2.0")

    (repo / "skills" / "a.md").write_text("changed\n", encoding="utf-8")
    _commit_all(repo, "tweak a skill, VERSION untouched")

    assert release_guard.main(["--root", str(repo)]) == 1


def test_a_tagged_repo_with_no_version_file_fails_with_a_message_not_a_traceback(
    tmp_path, load_script, capsys,
):
    """`(root / "VERSION").read_text()` raised FileNotFoundError straight out of the gate (D7)."""
    release_guard = load_script("gates/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    _commit_all(repo, "release 0.1.0")
    _tag(repo, "ai-badger--v0.1.0")
    (repo / "VERSION").unlink()
    _commit_all(repo, "lose the version marker")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "VERSION" in out
