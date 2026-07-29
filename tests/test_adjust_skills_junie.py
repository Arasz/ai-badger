"""Tests for features/junie/adjustments/adjust_skills.py: .junie/skills symlinking.

Junie discovers project-scope skills from <projectRoot>/.junie/skills/<name>/SKILL.md
(JetBrains docs, quoted in #137); user scope (~/.junie/skills/) is out of scope here. The
property under test is ownership, mirroring the Copilot/Claude siblings: only what ai-badger
placed may be replaced, everything else survives untouched and unpruned.
"""
from __future__ import annotations

import json

SCRIPT = "features/junie/adjustments/adjust_skills.py"


def _project(tmp_path, skills=("task",), manifest_targets=()):
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    for name in skills:
        skill = aib / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    entries = [{"feature": "adjustments", "stack": "junie", "name": name,
                "source": "", "target": t, "frameworkVersion": "0.47.0", "hash": "0" * 64}
               for name, t in manifest_targets]
    (aib / "manifest.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return target


def _context(root, target, skills=("task",)):
    return {
        "framework_root": root,
        "config": {"agents": ["junie"]},
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": list(skills),
    }


def test_skill_with_skill_md_is_symlinked_into_junie_skills(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)

    result = adjust_skills.adjust(_context(root, target))

    link = target / ".junie" / "skills" / "task"
    assert result["applied"]
    assert link.is_symlink()
    assert link.resolve() == (target / ".ai-badger" / "skills" / "task").resolve()
    assert ".junie/skills/task" in result["files"]


def test_link_resolves_to_the_managed_copy_not_a_snapshot(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)

    adjust_skills.adjust(_context(root, target))

    managed = target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    managed.write_text("# task, refreshed\n", encoding="utf-8")
    through_link = target / ".junie" / "skills" / "task" / "SKILL.md"
    assert through_link.read_text(encoding="utf-8") == "# task, refreshed\n"


def test_foreign_directory_is_not_clobbered(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    foreign = target / ".junie" / "skills" / "task"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# hand-written by the user\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# hand-written by the user\n"
    assert not foreign.is_symlink()
    assert "task" in result["notes"]
    assert ".junie/skills/task" not in result["files"]


def test_plain_file_destination_is_reported_not_crashed(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    collision = target / ".junie" / "skills" / "task"
    collision.parent.mkdir(parents=True)
    collision.write_text("not a directory\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert collision.read_text(encoding="utf-8") == "not a directory\n"
    assert "task" in result["notes"]


def test_our_own_stale_symlink_is_replaced(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "mcp-index"))
    link = target / ".junie" / "skills" / "task"
    link.parent.mkdir(parents=True)
    link.symlink_to("../../.ai-badger/skills/mcp-index")

    result = adjust_skills.adjust(_context(root, target, skills=("task",)))

    assert link.resolve() == (target / ".ai-badger" / "skills" / "task").resolve()
    assert ".junie/skills/task" in result["files"]


def test_symlink_pointing_outside_the_scaffold_is_preserved(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    link = target / ".junie" / "skills" / "task"
    link.parent.mkdir(parents=True)
    link.symlink_to(elsewhere)

    result = adjust_skills.adjust(_context(root, target))

    assert link.resolve() == elsewhere.resolve()
    assert "task" in result["notes"]


def test_a_directory_the_manifest_records_as_ours_is_replaced(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, manifest_targets=(("task", ".junie/skills/task"),))
    ours = target / ".junie" / "skills" / "task"
    ours.mkdir(parents=True)
    (ours / "SKILL.md").write_text("# stale copy we placed\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert ours.is_symlink()
    assert ".junie/skills/task" in result["files"]


def test_a_link_to_a_skill_no_longer_delivered_is_pruned(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "call-behaviorist"))
    adjust_skills.adjust(_context(root, target, skills=("task", "call-behaviorist")))

    result = adjust_skills.adjust(_context(root, target, skills=("task",)))

    link = target / ".junie" / "skills" / "call-behaviorist"
    assert not link.exists() and not link.is_symlink()
    assert (target / ".junie" / "skills" / "task").is_symlink()
    assert "call-behaviorist" in result["notes"]


def test_an_empty_skill_list_prunes_nothing(tmp_path, load_script, root):
    """An empty skill list is not evidence the project stopped wanting its skills (#129)."""
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "den-refresh"))
    adjust_skills.adjust(_context(root, target, skills=("task", "den-refresh")))

    result = adjust_skills.adjust(_context(root, target, skills=()))

    junie_skills = target / ".junie" / "skills"
    assert (junie_skills / "task").is_symlink()
    assert (junie_skills / "den-refresh").is_symlink()
    assert not result["applied"]
    assert "config.exclude.skills" in result["notes"]
    assert "2" in result["notes"]


def test_a_foreign_entry_survives_an_empty_skill_list(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task",))
    adjust_skills.adjust(_context(root, target, skills=("task",)))
    foreign = target / ".junie" / "skills" / "explore-codebase"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# hand-made\n", encoding="utf-8")

    adjust_skills.adjust(_context(root, target, skills=()))

    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# hand-made\n"
    assert (target / ".junie" / "skills" / "task").is_symlink()


def test_noop_when_junie_is_not_a_configured_agent(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    context = _context(root, target)
    context["config"]["agents"] = ["claude"]

    result = adjust_skills.adjust(context)

    assert not result["applied"]
    assert not (target / ".junie" / "skills").exists()


def test_junie_adjustment_is_registered(root):
    """The scaffold only runs adjustments declared in adjustment.json."""
    manifest = json.loads(
        (root / "features" / "junie" / "adjustments" / "adjustment.json")
        .read_text(encoding="utf-8"))

    assert manifest["agent"] == "junie"
    assert any(a["script"] == "adjust_skills.py" for a in manifest["adjustments"])
