"""The ~/.hermes/skills/<project>/ namespace scaffold.py maintains: symlinks and containment."""
from __future__ import annotations

import os
from unittest.mock import patch

from scaffold_helpers import _config, SCAFFOLD_SCRIPT


def _hermes_skill(target, name):
    skill = target / ".ai-badger" / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


# ---------------------------------------------------------------------- hermes skill symlinks
def _hermes_scaffold(make_scaffolder, home, skills, agents=("hermes",)):
    """Scaffold with Path.home patched to *home*; return the hermes namespace dir."""
    scaf = make_scaffolder(config=_config(agents=list(agents)), skills=list(skills))
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-22T00:00:00Z")
    return home / ".hermes" / "skills" / "probe"


def _hermes_case(tmp_path, make_scaffolder):
    """Return (target, home) directories for a hermes symlink test."""
    target = make_scaffolder.target
    home = tmp_path / "hermes-home"
    home.mkdir()
    return target, home


def test_scaffold_creates_hermes_skill_symlinks(tmp_path, make_scaffolder):
    """Each scaffolded skill is symlinked into ~/.hermes/skills/<project>/ (ADR 0003)."""
    _, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task", "prompt-markers"])

    assert namespace.is_dir() and not namespace.is_symlink()
    for name in ("task", "prompt-markers"):
        link = namespace / name
        assert link.is_symlink()
        assert (link.resolve() / "SKILL.md").exists()


def test_scaffold_hermes_symlinks_are_relative(tmp_path, make_scaffolder):
    """Links are relative so no absolute home path is baked into the namespace."""
    _, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task"])

    raw = os.readlink(str(namespace / "task"))
    assert not os.path.isabs(raw)


def test_scaffold_no_symlinks_without_hermes_agent(tmp_path, make_scaffolder):
    """Scaffolding without hermes should not create ~/.hermes/skills/<project>/."""
    _, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task"], agents=("claude",))

    assert not namespace.exists()


def test_rescaffold_recreates_hermes_symlinks(tmp_path, make_scaffolder):
    """Re-scaffold leaves the namespace with a working link for every skill."""
    _, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task"])
    first_target = (namespace / "task").resolve()
    _hermes_scaffold(make_scaffolder, home, ["task"])

    assert (namespace / "task").is_symlink()
    assert (namespace / "task").resolve() == first_target


def test_scaffold_preserves_foreign_dirs_in_namespace(tmp_path, make_scaffolder):
    """A real directory ai-badger did not place survives a re-scaffold byte-identical."""
    _, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task"])
    foreign = namespace / "agent-skill-discovery"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("# hermes-authored\n", encoding="utf-8")

    _hermes_scaffold(make_scaffolder, home, ["task"])

    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# hermes-authored\n"


def test_scaffold_removes_stale_managed_symlinks(tmp_path, make_scaffolder):
    """A link for a skill no longer scaffolded is unlinked on re-scaffold."""
    _, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task", "prompt-markers"])
    assert (namespace / "prompt-markers").is_symlink()

    _hermes_scaffold(make_scaffolder, home, ["task"])

    assert not (namespace / "prompt-markers").is_symlink()
    assert (namespace / "task").is_symlink()


def test_scaffold_replaces_broken_symlink(tmp_path, make_scaffolder):
    """A dangling managed link is relinked rather than left broken."""
    target, home = _hermes_case(tmp_path, make_scaffolder)

    namespace = _hermes_scaffold(make_scaffolder, home, ["task"])
    link = namespace / "task"
    link.unlink()
    link.symlink_to(
        os.path.relpath(target / ".ai-badger" / "skills" / "task-gone", namespace)
    )
    assert not link.exists()

    _hermes_scaffold(make_scaffolder, home, ["task"])

    assert link.is_symlink() and (link.resolve() / "SKILL.md").exists()


def test_scaffold_symlinks_learned_skills_dir(tmp_path, make_scaffolder):
    """The learned/ tree is reachable through the namespace (one link covers it)."""
    target, home = _hermes_case(tmp_path, make_scaffolder)
    learned = target / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes"
    learned.mkdir(parents=True)
    (learned / "SKILL.md").write_text("# apple-notes\n", encoding="utf-8")

    namespace = _hermes_scaffold(make_scaffolder, home, ["task"])

    link = namespace / "learned"
    assert link.is_symlink()
    assert (link.resolve() / "apple" / "apple-notes" / "SKILL.md").exists()


# ------------------------------------------------------------------- hermes adjustment path
def test_scaffold_hermes_adjust_task_does_not_fail_with_absolute_path(make_scaffolder):
    """adjust_task.py must not pass absolute paths to record() — causes ValueError."""

    scaf = make_scaffolder(config=_config(agents=["hermes"]), skills=["task"])
    result = scaf.run(generated_at="2026-07-24T00:00:00Z")

    # The adjustment should succeed without raising ValueError
    adj_notes = [n for n in result["notes"]
                 if "adjustment" in n.lower() and "task" in n.lower()]
    assert adj_notes, f"Expected adjustment note for task, got: {result['notes']}"
    # Must NOT contain a failure message
    assert not any("failed" in n.lower() for n in adj_notes), (
        f"adjust_task.py should not fail: {adj_notes}"
    )


# --------------------------------------------------------- containment (security I1)
def test_a_traversing_project_name_cannot_escape_the_hermes_namespace(
        tmp_path, monkeypatch, make_scaffolder):
    """project.name is interpolated into ~/.hermes/skills/<name> and the schema allows
    any non-empty string, so containment has to be asserted at the join (WP41)."""
    home = tmp_path / "home"
    (home / ".hermes" / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    config = _config(agents=["hermes"])
    config["project"]["name"] = "../../escaped"

    scaf = make_scaffolder(config=config, skills=["task"])
    result = scaf.run(generated_at="2026-07-27T00:00:00Z")

    assert not (tmp_path / "home" / "escaped").exists()
    assert not (home / ".hermes" / "escaped").exists()
    assert any("project name" in n for n in result["notes"])


# ------------------------------------------------------------ empty skill list guard (#129)
def test_an_empty_skill_list_leaves_the_hermes_namespace_intact(tmp_path, load_script, root):
    """An empty list is not evidence the project stopped wanting its skills — see adjust_skills."""
    scaffold = load_script(SCAFFOLD_SCRIPT)
    target = tmp_path / "proj"
    for name in ("task", "prompt-markers"):
        _hermes_skill(target, name)
    home = tmp_path / "home"
    home.mkdir()
    config = _config(agents=["hermes"])

    with patch("pathlib.Path.home", return_value=home):
        scaffold.relink_hermes_skills(target, config, ["task", "prompt-markers"])
        scaffold.relink_hermes_skills(target, config, [])

    namespace = home / ".hermes" / "skills" / "probe"
    assert (namespace / "task").is_symlink()
    assert (namespace / "prompt-markers").is_symlink()


def test_removed_hermes_links_are_reported(tmp_path, load_script, root):
    scaffold = load_script(SCAFFOLD_SCRIPT)
    target = tmp_path / "proj"
    for name in ("task", "prompt-markers"):
        _hermes_skill(target, name)
    home = tmp_path / "home"
    home.mkdir()
    config = _config(agents=["hermes"])

    with patch("pathlib.Path.home", return_value=home):
        scaffold.relink_hermes_skills(target, config, ["task", "prompt-markers"])
        result = scaffold.relink_hermes_skills(target, config, ["task"])

    assert result["removed"] == ["prompt-markers"]


def test_a_scaffolder_run_reports_a_hermes_link_removal(tmp_path, make_scaffolder):
    """The same transition through the full Scaffolder puts a removal line in notes."""
    home = tmp_path / "hermes-home"
    home.mkdir()
    config = _config(agents=["hermes"])

    with patch("pathlib.Path.home", return_value=home):
        make_scaffolder(config=config, skills=["task", "prompt-markers"]).run(
            generated_at="2026-07-29T00:00:00Z")
        result = make_scaffolder(config=config, skills=["task"]).run(
            generated_at="2026-07-29T00:01:00Z")

    assert any("prompt-markers" in n for n in result["notes"])
