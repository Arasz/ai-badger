"""Tests for features/copilot/adjustments/adjust_skills.py: .github/skills symlinking.

The property under test is ownership: `.github/skills/<name>` is Copilot's own convention,
so a hand-authored directory or file can legitimately sit exactly where this adjustment
wants to link. It may replace only what ai-badger placed there, and must report — not
destroy, and not crash on — anything else. Mirrors scaffold._owns_link's contract.
"""
from __future__ import annotations

import json


def _project(tmp_path, skills=("task",), manifest_targets=()):
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    for name in skills:
        skill = aib / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    entries = [{"feature": "adjustments", "stack": "copilot", "name": name,
                "source": "", "target": t, "frameworkVersion": "0.21.0", "hash": "0" * 64}
               for name, t in manifest_targets]
    (aib / "manifest.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return target


def _context(root, target, skills=("task",)):
    return {
        "framework_root": root,
        "config": {"agents": ["copilot"]},
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": list(skills),
    }


def test_skill_with_skill_md_is_symlinked(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path)

    result = adjust_skills.adjust(_context(root, target))

    link = target / ".github" / "skills" / "task"
    assert result["applied"]
    assert link.is_symlink()
    assert link.resolve() == (target / ".ai-badger" / "skills" / "task").resolve()


def test_foreign_github_skills_dir_is_preserved(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path)
    foreign = target / ".github" / "skills" / "task"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# hand-written by the user\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# hand-written by the user\n"
    assert not foreign.is_symlink()
    assert "task" in result["notes"]
    assert ".github/skills/task" not in result["files"]


def test_plain_file_destination_is_reported_not_crashed(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path)
    collision = target / ".github" / "skills" / "task"
    collision.parent.mkdir(parents=True)
    collision.write_text("not a directory\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert collision.read_text(encoding="utf-8") == "not a directory\n"
    assert "task" in result["notes"]


def test_our_own_stale_symlink_is_replaced(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path, skills=("task", "mcp-index"))
    link = target / ".github" / "skills" / "task"
    link.parent.mkdir(parents=True)
    link.symlink_to("../../.ai-badger/skills/mcp-index")

    result = adjust_skills.adjust(_context(root, target, skills=("task",)))

    assert link.resolve() == (target / ".ai-badger" / "skills" / "task").resolve()
    assert ".github/skills/task" in result["files"]


def test_symlink_pointing_outside_the_scaffold_is_preserved(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path)
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    link = target / ".github" / "skills" / "task"
    link.parent.mkdir(parents=True)
    link.symlink_to(elsewhere)

    result = adjust_skills.adjust(_context(root, target))

    assert link.resolve() == elsewhere.resolve()
    assert "task" in result["notes"]


def test_a_directory_the_manifest_records_as_ours_is_replaced(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path, manifest_targets=(("task", ".github/skills/task"),))
    ours = target / ".github" / "skills" / "task"
    ours.mkdir(parents=True)
    (ours / "SKILL.md").write_text("# stale copy we placed\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert ours.is_symlink()
    assert ".github/skills/task" in result["files"]


def test_a_link_to_a_skill_no_longer_delivered_is_pruned(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path, skills=("task", "call-behaviorist"))
    adjust_skills.adjust(_context(root, target, skills=("task", "call-behaviorist")))

    result = adjust_skills.adjust(_context(root, target, skills=("task",)))

    link = target / ".github" / "skills" / "call-behaviorist"
    assert not link.exists() and not link.is_symlink()
    assert (target / ".github" / "skills" / "task").is_symlink()
    assert "call-behaviorist" in result["notes"]


def test_an_empty_skill_list_prunes_nothing(tmp_path, load_script, root):
    """An empty skill list is not evidence the project stopped wanting its skills (#129)."""
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path, skills=("task", "den-refresh"))
    adjust_skills.adjust(_context(root, target, skills=("task", "den-refresh")))

    result = adjust_skills.adjust(_context(root, target, skills=()))

    github_skills = target / ".github" / "skills"
    assert (github_skills / "task").is_symlink()
    assert (github_skills / "den-refresh").is_symlink()
    assert not result["applied"]
    assert "config.exclude.skills" in result["notes"]
    assert "2" in result["notes"]


def test_noop_when_copilot_is_not_a_configured_agent(tmp_path, load_script, root):
    adjust_skills = load_script("features/copilot/adjustments/adjust_skills.py")
    target = _project(tmp_path)
    context = _context(root, target)
    context["config"]["agents"] = ["claude"]

    result = adjust_skills.adjust(context)

    assert not result["applied"]
    assert not (target / ".github" / "skills").exists()


def test_adjust_agents_degrades_with_a_note_when_yaml_is_missing(tmp_path, load_script, root,
                                                                  monkeypatch):
    """adjust_agents needs PyYAML; without it the scaffold notes the gap, not a traceback."""
    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    adjust_agents = load_script("features/copilot/adjustments/adjust_agents.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    result = adjust_agents.adjust({
        "framework_root": root,
        "config": {"agents": ["copilot"]},
        "target_dir": target / ".ai-badger",
        "target": target,
        "index": {"stacks": {"common": {"personas": [{"name": "architect",
                                                       "path": "features/common/personas/architect.md"}]}}},
    })

    assert not result["applied"]
    assert "yaml" in result["notes"].lower()
