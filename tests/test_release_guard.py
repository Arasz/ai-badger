"""Tests for scripts/release_guard.py: shipped-surface-changed-without-a-bump gate.

Builds throwaway git repos under tmp_path (git init + commits + tags) since the guard is
inherently git-shaped; tests/conftest.py has no existing git-repo helpers to reuse.
"""
from __future__ import annotations

import subprocess


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
    release_guard = load_script("scripts/release_guard.py")
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
    release_guard = load_script("scripts/release_guard.py")
    repo = _init_repo(tmp_path)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    _commit_all(repo, "init")

    rc = release_guard.main(["--root", str(repo)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "NO RELEASE TAG FOUND" in out


def test_fails_when_shipped_path_changed_without_version_bump(tmp_path, load_script, capsys):
    release_guard = load_script("scripts/release_guard.py")
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
    release_guard = load_script("scripts/release_guard.py")
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
    release_guard = load_script("scripts/release_guard.py")
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
    release_guard = load_script("scripts/release_guard.py")
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
