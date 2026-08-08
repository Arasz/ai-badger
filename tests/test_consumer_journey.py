"""The parts of the consumer journey that can be pinned without running one.

The journey itself is proven by REGISTRY provocations in test_every_check_can_fail.py — it is
run twice per mutation, with the defect and without. What is tested here is the observation
machinery those runs depend on: the `$HOME` snapshot, its diff, the dangling-link sweep and the
refusal to run against a real home. Every one of those was the thing that lied in an earlier
incident, so each is pinned on its own rather than through the journey that consumes it.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import scaffold_helpers  # noqa: F401  (path bootstrap, same as the other suites)

JOURNEY = "gates/consumer_journey.py"


@pytest.fixture(name="cj")
def _consumer_journey(load_script):
    return load_script(JOURNEY)


def _link(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)


# ------------------------------------------------------------------------------- snapshot


def test_the_snapshot_records_an_empty_directory(cj, tmp_path):
    """The `~/.hermes` leak was declared fixed by an acceptance check that hashed files only.

    A namespace directory with nothing in it is still something `$HOME` gained, and a snapshot
    that only sees regular files reports the leak as clean.
    """
    home = tmp_path / "home"
    (home / ".hermes" / "skills" / "proj").mkdir(parents=True)

    assert ".hermes/skills/proj" in cj.snapshot(home)


def test_the_snapshot_records_a_symlink_without_following_it(cj, tmp_path):
    """The leak was 14 symlinks. A snapshot that resolves them reports the target, not the link.

    Following would also walk the linked tree, so a namespace of links into the project would
    read as hundreds of files in `$HOME` — and a link retargeted in place would read as no
    change at all, because the file it now points at is the same size.
    """
    home = tmp_path / "home"
    real = tmp_path / "elsewhere" / "task"
    (real / "nested").mkdir(parents=True)
    (real / "nested" / "SKILL.md").write_text("# task\n", encoding="utf-8")
    _link(home / ".hermes" / "skills" / "proj" / "task", str(real))

    shot = cj.snapshot(home)

    assert shot[".hermes/skills/proj/task"] == f"link -> {real}"
    assert not [key for key in shot if key.endswith("SKILL.md")], \
        "the snapshot followed the link into the project tree"


def test_the_snapshot_distinguishes_a_link_from_the_directory_it_replaced(cj, tmp_path):
    """Kind is part of the value, so a directory swapped for a link to one is a change."""
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    as_directory = cj.snapshot(home)

    (home / ".claude" / "skills").rmdir()
    _link(home / ".claude" / "skills", str(tmp_path / "somewhere"))

    assert cj.gained(as_directory, cj.snapshot(home)) == [
        f".claude/skills: link -> {tmp_path / 'somewhere'}"]


def test_the_snapshot_ignores_bytecode(cj, tmp_path):
    """Running the scaffolder out of a plugin cache writes `__pycache__` into it.

    That is the interpreter's noise, not the framework's write, and it is the only thing a
    read-only cache install adds. Left unfiltered it drowns the diff every run.
    """
    home = tmp_path / "home"
    cache = home / ".claude" / "plugins" / "cache" / "ai-badger" / "tooling"
    (cache / "__pycache__").mkdir(parents=True)
    (cache / "__pycache__" / "validate.cpython-311.pyc").write_bytes(b"\x00")
    (cache / "validate.py").write_text("x = 1\n", encoding="utf-8")

    assert sorted(cj.snapshot(home)) == [
        ".claude", ".claude/plugins", ".claude/plugins/cache",
        ".claude/plugins/cache/ai-badger", ".claude/plugins/cache/ai-badger/tooling",
        ".claude/plugins/cache/ai-badger/tooling/validate.py",
    ]


def test_the_snapshot_of_a_missing_home_is_empty(cj, tmp_path):
    """The `before` snapshot is taken before anything creates the scratch home."""
    assert cj.snapshot(tmp_path / "never-created") == {}


# ---------------------------------------------------------------------------------- gained


def test_gained_reports_a_file_a_link_and_a_directory_added_at_once(cj, tmp_path):
    """All three kinds in one run: a real install adds a plugin dir, its files and its links."""
    home = tmp_path / "home"
    home.mkdir()
    before = cj.snapshot(home)
    (home / ".hermes" / "plugins" / "ai-badger").mkdir(parents=True)
    (home / ".hermes" / "plugins" / "ai-badger" / "plugin.yaml").write_text("a\n",
                                                                           encoding="utf-8")
    (home / ".hermes" / "skills" / "proj").mkdir(parents=True)
    _link(home / ".hermes" / "skills" / "proj" / "task", str(tmp_path / "proj" / "task"))

    lines = cj.gained(before, cj.snapshot(home))

    assert [line.split(": ", 1)[0] for line in lines] == [
        ".hermes", ".hermes/plugins", ".hermes/plugins/ai-badger",
        ".hermes/plugins/ai-badger/plugin.yaml", ".hermes/skills", ".hermes/skills/proj",
        ".hermes/skills/proj/task",
    ]
    assert lines[3].startswith(".hermes/plugins/ai-badger/plugin.yaml: file ")
    assert lines[-1] == f".hermes/skills/proj/task: link -> {tmp_path / 'proj' / 'task'}"


def test_gained_reports_a_file_whose_content_changed_but_not_its_length(cj, tmp_path):
    """`~/.claude/settings.json` is edited in place, and a size-only kind reads that as clean."""
    home = tmp_path / "home"
    home.mkdir()
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {"a": 1}}\n', encoding="utf-8")
    before = cj.snapshot(home)

    settings.write_text('{"hooks": {"b": 2}}\n', encoding="utf-8")

    assert [line.split(": ", 1)[0] for line in cj.gained(before, cj.snapshot(home))] == [
        ".claude/settings.json"]


def test_gained_ignores_a_removal(cj, tmp_path):
    """What `$HOME` lost is the teardown's business; this answers what it gained."""
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    before = cj.snapshot(home)
    (home / ".hermes").rmdir()

    assert cj.gained(before, cj.snapshot(home)) == []


# ------------------------------------------------------------------- attributable namespaces


def test_a_write_to_a_namespace_no_consumer_can_name_is_a_stray(cj):
    """The framework's own install and a project-named namespace are the only two shapes.

    A skills root of its own — the flat `~/.badger-skills/<skill>` an earlier design used —
    cannot be attributed to a project, which is how 31 links accumulated with nobody able to
    say which repo had asked for them.
    """
    assert cj.strays([".badger-skills/task: link -> /elsewhere"]) == \
        [".badger-skills/task: link -> /elsewhere"]


def test_the_frameworks_own_install_and_the_projects_namespace_are_not_strays(cj):
    """The other answer: a check that rejects everything rejects the install it must allow."""
    assert cj.strays([
        ".hermes: dir",
        ".hermes/plugins/ai-badger/plugin.yaml: file 0123456789abcdef",
        f".hermes/skills/{cj.PROJECT}/task: link -> /elsewhere",
        ".claude/settings.json: file 0123456789abcdef",
    ]) == []


def test_a_namespace_named_for_another_project_is_a_stray(cj):
    """Prefix matching, not substring: `~/.hermes/skills/<other>` is another repo's business."""
    assert cj.strays([f".hermes/skills/{cj.PROJECT}-old/task: link -> /elsewhere"]) == \
        [f".hermes/skills/{cj.PROJECT}-old/task: link -> /elsewhere"]


# -------------------------------------------------------------------------- dangling links


def test_dangling_links_finds_a_link_whose_target_is_gone(cj, tmp_path):
    """The teardown check: 31 links into a project directory that no longer exists."""
    home = tmp_path / "home"
    live = tmp_path / "proj" / "kept"
    live.mkdir(parents=True)
    _link(home / ".hermes" / "skills" / "proj" / "kept", str(live))
    _link(home / ".hermes" / "skills" / "proj" / "gone", str(tmp_path / "proj" / "gone"))

    assert cj.dangling_links(home) == [".hermes/skills/proj/gone"]


def test_dangling_links_reports_a_link_to_a_link_that_ends_nowhere(cj, tmp_path):
    """A namespace rebuilt over a stale one leaves chains, and `exists()` resolves the chain."""
    home = tmp_path / "home"
    _link(home / ".hermes" / "skills" / "proj" / "hop", str(tmp_path / "proj" / "gone"))
    _link(home / ".hermes" / "skills" / "proj" / "task", str(home / ".hermes" / "skills"
                                                            / "proj" / "hop"))

    assert cj.dangling_links(home) == [".hermes/skills/proj/hop",
                                       ".hermes/skills/proj/task"]


def test_dangling_links_does_not_walk_into_a_live_symlinked_directory(cj, tmp_path):
    """A live namespace link points at the project; its contents are the project's, not home's."""
    home = tmp_path / "home"
    project_skill = tmp_path / "proj" / ".ai-badger" / "skills" / "task"
    project_skill.mkdir(parents=True)
    _link(project_skill / "broken", str(tmp_path / "proj" / "nothing"))
    _link(home / ".hermes" / "skills" / "proj" / "task", str(project_skill))

    assert cj.dangling_links(home) == []


# ------------------------------------------------------------------- refusing the real home


def test_the_journey_refuses_a_scratch_home_that_is_the_real_one(cj, tmp_path, monkeypatch):
    """A script that wrote to a real `~/.hermes` destroyed a Hermes install. Never again."""
    monkeypatch.setenv("HOME", str(tmp_path / "real"))

    with pytest.raises(cj.Refusal):
        cj.check_scratch_home(Path(os.path.expanduser("~")))


def test_the_journey_refuses_a_scratch_home_inside_the_real_one(cj, tmp_path, monkeypatch):
    """`$TMPDIR` under `$HOME` is a real macOS shape, and a subdirectory is still the real home."""
    monkeypatch.setenv("HOME", str(tmp_path / "real"))

    with pytest.raises(cj.Refusal):
        cj.check_scratch_home(Path(os.path.expanduser("~")) / "scratch" / "home")


def test_the_journey_accepts_a_scratch_home_outside_the_real_one(cj, tmp_path, monkeypatch):
    """The other answer: the check must be able to say yes, or it can never run at all."""
    monkeypatch.setenv("HOME", str(tmp_path / "real"))

    assert cj.check_scratch_home(tmp_path / "scratch" / "home") is None


def test_the_child_environment_redirects_every_home_a_write_could_follow(cj, tmp_path):
    """`HOME` alone is not enough: `$HERMES_HOME` and `$XDG_*` each reroute a write past it."""
    scratch = tmp_path / "scratch-home"

    env = cj.child_env(scratch)

    assert env["HOME"] == str(scratch)
    assert env["HERMES_HOME"] == str(scratch / ".hermes")
    assert env["XDG_CONFIG_HOME"] == str(scratch / ".config")
    assert env["XDG_DATA_HOME"] == str(scratch / ".local" / "share")


def test_the_child_environment_drops_the_git_variables_a_hook_exports(cj, tmp_path):
    """`GIT_DIR` broke three call sites; a journey run from a pre-push hook inherits it."""
    env = cj.child_env(tmp_path / "scratch-home",
                       base={"GIT_DIR": "/real/.git", "GIT_WORK_TREE": "/real", "PATH": "/bin"})

    assert "GIT_DIR" not in env and "GIT_WORK_TREE" not in env
    assert env["PATH"] == "/bin"
