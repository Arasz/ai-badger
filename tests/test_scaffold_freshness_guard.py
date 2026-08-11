"""Tests for gates/scaffold_freshness_guard.py: the self-scaffold must be reproducible.

The defect (issue #206): a PR edits `features/**`, never re-scaffolds, and ships a
`.ai-badger/` that describes a tree that no longer exists. The gate re-runs the scaffolder in
a throwaway copy and fails on any non-stamp difference. Fixtures here are copies of this repo,
made fresh by construction (scaffolded once before the test mutates them), so a stale real
tree fails the gate's own lane rather than these tests.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _test_write

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
    _test_write(added, '"""Added after the last self-scaffold."""\n', encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "SCAFFOLD FRESHNESS GUARD FAILED" in done.stdout
    assert f"{SKILL_MIRROR}/scripts/added_after_scaffold.py" in done.stdout
    assert "welcome-ai-badger" in done.stdout  # the remediation names the scaffolder


def test_a_source_edit_without_rescaffold_is_reported_as_stale(mutable_repo):
    """The mirror still matches what the last scaffold wrote, so the change is upstream."""
    skill_md = mutable_repo / SKILL_SOURCE / "SKILL.md"
    _test_write(skill_md, skill_md.read_text(encoding="utf-8") + "\nMoved ahead.\n", encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert f"{SKILL_MIRROR}/SKILL.md" in done.stdout
    assert "stale" in done.stdout
    assert "hand-edited" not in done.stdout


def test_a_hand_edited_mirror_is_reported_as_such(mutable_repo):
    """The source never moved, so a mirror that re-scaffolds differently was edited here."""
    mirror_md = mutable_repo / SKILL_MIRROR / "SKILL.md"
    _test_write(mirror_md, mirror_md.read_text(encoding="utf-8") + "\nEdited in place.\n", encoding="utf-8")

    done = _run_gate(mutable_repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert f"{SKILL_MIRROR}/SKILL.md" in done.stdout
    assert "hand-edited" in done.stdout


def test_version_stamp_churn_alone_is_exempt(mutable_repo):
    """A version bump re-stamps manifest, config and agent docs; none of that is staleness."""
    index = mutable_repo / "index.json"
    _test_write(index, index.read_text(encoding="utf-8").replace(
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
    _test_write(mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py", '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    before = _git(mutable_repo, "status", "--porcelain")

    _run_gate(mutable_repo)

    assert _git(mutable_repo, "status", "--porcelain") == before


def _tree_digest(path: Path) -> dict:
    """Every entry under `path` by relative path and content — a byte-level snapshot."""
    if not path.exists():
        return {}
    out = {}
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            entry = Path(base) / name
            rel = entry.relative_to(path).as_posix()
            if entry.is_symlink():
                out[rel] = "-> " + os.readlink(str(entry))
            elif entry.is_file():
                out[rel] = hashlib.sha256(entry.read_bytes()).hexdigest()
            else:
                out[rel] = "dir"
    return out


def _seed_hermes_home(home: Path) -> None:
    """An operator's installed Hermes plugin, as the gate would find it on a real machine."""
    plugin = home / ".hermes" / "plugins" / "ai-badger"
    (plugin / ".ai-badger").mkdir(parents=True)
    _test_write(plugin / "ai_badger_hooks.py", "# the operator's install\n", encoding="utf-8")
    _test_write(plugin / ".ai-badger" / "manifest.json", '{"frameworkRoot": "/the/operators/checkout"}\n', encoding="utf-8")
    (home / ".hermes" / "skills" / "ai-badger").mkdir(parents=True)


def test_the_gate_never_writes_into_the_operators_hermes_home(fresh_repo, tmp_path):
    """A read-only gate must leave the user scope alone (theme B, B1).

    The gate re-scaffolds a throwaway copy, and that run installed the Hermes plugin and
    relinked the skill namespace into the real `$HOME`, recording the temp directory as
    `frameworkRoot` — so the operator's plugin pointed at a path the gate then deleted.
    """
    home = tmp_path / "home"
    _seed_hermes_home(home)
    before = _tree_digest(home / ".hermes")

    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    done = subprocess.run([sys.executable, str(GATE), "--root", str(fresh_repo)],
                          capture_output=True, text=True, check=False, env=env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert _tree_digest(home / ".hermes") == before


def _printed_remediation(stdout: str) -> str:
    """The command the gate told the operator to run, joined back into one line."""
    lines = stdout.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Re-scaffold this repo"))
    return " ".join(ln.strip().rstrip("\\").strip()
                    for ln in lines[start + 1:] if ln.strip())


def test_the_printed_remediation_produces_a_tree_the_gate_then_passes(mutable_repo):
    """The advice must be the gate's own command (theme B, B3).

    It printed the scaffolder invocation without `AI_BADGER_MCP_AVAILABILITY=all`, which the
    gate sets internally, so following it verbatim dropped every server the host cannot probe
    from `.github/mcp.json` and the gate rejected the tree its own message produced.

    The remediation runs on a minimal `PATH` — the machine the forced availability exists for.
    A developer with `hermes` and `ai-raccoon` installed probes the same answer either way, so
    on their PATH this test cannot fail for the reason it was written. Only the interpreter is
    substituted: `python3` on an operator's PATH has the dependencies.
    """
    _test_write(mutable_repo / SKILL_SOURCE / "scripts" / "added_after_scaffold.py", '"""Added after the last self-scaffold."""\n', encoding="utf-8")
    failed = _run_gate(mutable_repo)
    assert failed.returncode == 1, failed.stdout + failed.stderr

    command = _printed_remediation(failed.stdout).replace("python3", sys.executable, 1)
    bare = dict(os.environ, PATH="/usr/bin:/bin")
    bare.pop("AI_BADGER_MCP_AVAILABILITY", None)
    done = subprocess.run(command, shell=True, cwd=str(mutable_repo), env=bare,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, command + "\n" + done.stdout + done.stderr

    again = _run_gate(mutable_repo)
    assert again.returncode == 0, command + "\n" + again.stdout + again.stderr


def test_the_rescaffold_points_hermes_home_away_from_the_operators(tmp_path, load_script,
                                                                   monkeypatch):
    """The belt to `--no-install`'s braces, asserted on the mechanism because no outcome can.

    `test_the_gate_never_writes_into_the_operators_hermes_home` watches a seeded `~/.hermes`
    and passes with this line deleted: `--no-install` already skips every Hermes write, so the
    outcome is identical either way and only `--no-install` is really under test. `$HERMES_HOME`
    outranks `$HOME` wherever the user scope is resolved, so a future scaffolder that installs
    despite the flag would land here — but only if this env entry survives.
    """
    guard = load_script("gates/scaffold_freshness_guard.py")
    work = tmp_path / "copy" / "repo"
    seen = {}

    def _record(argv, **kwargs):  # pylint: disable=unused-argument
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(guard.subprocess, "run", _record)
    guard.rescaffold(work)

    hermes_home = Path(seen[guard.HERMES_HOME_ENV])
    assert hermes_home == work.parent / "hermes-home"
    assert Path.home() not in hermes_home.parents, \
        "the re-scaffold would resolve the operator's own Hermes user scope"
