"""Tests for gates/scaffold_freshness_guard.py: the self-scaffold must be reproducible.

The defect (issue #206): a PR edits `features/**`, never re-scaffolds, and ships a
`.ai-badger/` that describes a tree that no longer exists. The gate re-runs the scaffolder in
a throwaway copy and fails on any non-stamp difference. Fixtures here are copies of this repo,
made fresh by construction (scaffolded once before the test mutates them), so a stale real
tree fails the gate's own lane rather than these tests.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "gates" / "scaffold_freshness_guard.py"
SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
SKILL_SOURCE = "features/common/skills/welcome-ai-badger"
SKILL_MIRROR = ".ai-badger/skills/welcome-ai-badger"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True).stdout


def _copy_working_tree(dest: Path) -> Path:
    """Copy this repo's tracked + untracked-unignored files into `dest`, symlinks preserved."""
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"],
                         cwd=str(ROOT), check=True, capture_output=True).stdout
    for rel in (p.decode("utf-8") for p in out.split(b"\0") if p):
        src, dst = ROOT / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(str(src)), str(dst))
        elif src.is_file():
            shutil.copy2(src, dst)
    return dest


def _freshen(repo: Path) -> None:
    """Scaffold `repo` against itself and commit, making it fresh by construction.

    Runs with AI_BADGER_MCP_AVAILABILITY=all to mirror the gate's own re-scaffold env: the
    scaffold's MCP availability gate probes the host PATH, and the fixture must commit the
    same tree the gate would regenerate or every test fails on a machine with hermes.
    """
    env = dict(os.environ)
    env["AI_BADGER_MCP_AVAILABILITY"] = "all"
    proc = subprocess.run(
        [sys.executable, str(repo / SCAFFOLD), "--config", str(repo / ".ai-badger/config.json"),
         "--target", str(repo), "--root", str(repo), "--no-install", "--skills", ""],
        cwd=str(repo), capture_output=True, text=True, check=False, env=env)
    assert proc.returncode == 0, f"fixture self-scaffold failed:\n{proc.stdout}{proc.stderr}"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "self-scaffold")


@pytest.fixture(scope="module", name="fresh_repo")
def fresh_repo_fixture(tmp_path_factory) -> Path:
    """A git copy of this repo, freshly self-scaffolded. Never mutated — clone it instead."""
    repo = _copy_working_tree(tmp_path_factory.mktemp("fresh") / "repo")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _freshen(repo)
    return repo


@pytest.fixture(name="mutable_repo")
def mutable_repo_fixture(fresh_repo: Path, tmp_path: Path) -> Path:
    """A throwaway clone of the fresh fixture for tests that provoke staleness."""
    clone = tmp_path / "repo"
    shutil.copytree(fresh_repo, clone, symlinks=True)
    return clone


def _run_gate(repo: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([sys.executable, str(GATE), "--root", str(repo)],
                          capture_output=True, text=True, check=False)


def test_a_fresh_tree_passes(fresh_repo):
    done = _run_gate(fresh_repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS" in done.stdout


def test_a_skill_source_gaining_a_file_fails_naming_the_missing_mirror_path(mutable_repo):
    """The #204 incident: a file lands in a skill's source and nothing re-scaffolds."""
    added = mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py"
    added.write_text('"""Added after the last self-scaffold."""\n', encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "SCAFFOLD FRESHNESS GUARD FAILED" in done.stdout
    assert f"{SKILL_MIRROR}/scripts/added_after_scaffold.py" in done.stdout
    assert "welcome-ai-badger" in done.stdout  # the remediation names the scaffolder


def test_a_source_edit_without_rescaffold_is_reported_as_stale(mutable_repo):
    """The mirror still matches what the last scaffold wrote, so the change is upstream."""
    skill_md = mutable_repo / SKILL_SOURCE / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nMoved ahead.\n",
                        encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert f"{SKILL_MIRROR}/SKILL.md" in done.stdout
    assert "stale" in done.stdout
    assert "hand-edited" not in done.stdout


def test_a_hand_edited_mirror_is_reported_as_such(mutable_repo):
    """The source never moved, so a mirror that re-scaffolds differently was edited here."""
    mirror_md = mutable_repo / SKILL_MIRROR / "SKILL.md"
    mirror_md.write_text(mirror_md.read_text(encoding="utf-8") + "\nEdited in place.\n",
                         encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert f"{SKILL_MIRROR}/SKILL.md" in done.stdout
    assert "hand-edited" in done.stdout


def test_version_stamp_churn_alone_is_exempt(mutable_repo):
    """A version bump re-stamps manifest, config and agent docs; none of that is staleness."""
    index = mutable_repo / "index.json"
    index.write_text(index.read_text(encoding="utf-8").replace(
        '"frameworkVersion": "', '"frameworkVersion": "9', 1), encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS" in done.stdout


def test_an_unscaffolded_root_refuses_loudly(tmp_path):
    """No config, nothing to compare — that is a refusal, never a pass."""
    repo = tmp_path / "bare"
    repo.mkdir()
    _git(repo, "init", "-q")

    done = _run_gate(repo)

    assert done.returncode != 0
    assert "PASS" not in done.stdout
    assert ".ai-badger/config.json" in done.stdout + done.stderr


def test_a_root_git_cannot_enumerate_refuses_loudly(tmp_path):
    """An empty file list proves nothing about freshness, so the gate must not read it as clean."""
    done = _run_gate(tmp_path / "not-a-repo")

    assert done.returncode != 0
    assert "PASS" not in done.stdout
    assert "GIT COMMAND FAILED" in done.stdout + done.stderr


def test_the_gate_never_mutates_the_tree_it_checks(mutable_repo):
    """The comparison must happen in a throwaway copy, even when it finds staleness."""
    (mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py").write_text(
        '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    before = _git(mutable_repo, "status", "--porcelain")

    _run_gate(mutable_repo)

    assert _git(mutable_repo, "status", "--porcelain") == before
