"""Tests for features/claude/adjustments/adjust_skills.py: .claude/skills symlinking.

Claude Code discovers skills from .claude/skills/*/SKILL.md, a directory projects commonly
populate by hand and share with other tools. The adjustment may replace only what ai-badger
placed there; a hand-committed skill shadowing a managed one must survive and be named.
"""
from __future__ import annotations

import json

SCRIPT = "features/claude/adjustments/adjust_skills.py"


def _project(tmp_path, skills=("task",), manifest_targets=()):
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    for name in skills:
        skill = aib / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    entries = [{"feature": "adjustments", "stack": "claude", "name": name,
                "source": "", "target": t, "frameworkVersion": "0.33.0", "hash": "0" * 64}
               for name, t in manifest_targets]
    (aib / "manifest.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return target


def _context(root, target, skills=("task",)):
    return {
        "framework_root": root,
        "config": {"agents": ["claude"]},
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": list(skills),
    }


def test_skill_with_skill_md_is_symlinked_into_claude_skills(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)

    result = adjust_skills.adjust(_context(root, target))

    link = target / ".claude" / "skills" / "task"
    assert result["applied"]
    assert link.is_symlink()
    assert link.resolve() == (target / ".ai-badger" / "skills" / "task").resolve()
    assert ".claude/skills/task" in result["files"]


def test_link_resolves_to_the_managed_copy_not_a_snapshot(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)

    adjust_skills.adjust(_context(root, target))

    managed = target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    managed.write_text("# task, refreshed\n", encoding="utf-8")
    through_link = target / ".claude" / "skills" / "task" / "SKILL.md"
    assert through_link.read_text(encoding="utf-8") == "# task, refreshed\n"


def test_hand_committed_skill_directory_is_not_clobbered(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    shadow = target / ".claude" / "skills" / "task"
    shadow.mkdir(parents=True)
    (shadow / "SKILL.md").write_text("# 0.18.1-era snapshot\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert (shadow / "SKILL.md").read_text(encoding="utf-8") == "# 0.18.1-era snapshot\n"
    assert not shadow.is_symlink()
    assert ".claude/skills/task" in result["notes"]
    assert ".claude/skills/task" not in result["files"]


def test_a_shadowed_skill_does_not_stop_the_rest(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "den-refresh"))
    shadow = target / ".claude" / "skills" / "task"
    shadow.mkdir(parents=True)
    (shadow / "SKILL.md").write_text("# hand-committed\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target, skills=("task", "den-refresh")))

    assert result["applied"]
    assert (target / ".claude" / "skills" / "den-refresh").is_symlink()
    assert ".claude/skills/den-refresh" in result["files"]
    assert ".claude/skills/task" in result["notes"]


def test_unrelated_third_party_skills_survive(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    foreign = target / ".claude" / "skills" / "explore-codebase"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# code-review-graph\n", encoding="utf-8")

    adjust_skills.adjust(_context(root, target))

    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# code-review-graph\n"


def test_rerunning_is_idempotent(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "den-refresh"))
    context = _context(root, target, skills=("task", "den-refresh"))

    first = adjust_skills.adjust(context)
    second = adjust_skills.adjust(context)

    claude_skills = target / ".claude" / "skills"
    assert first["files"] == second["files"]
    assert sorted(p.name for p in claude_skills.iterdir()) == ["den-refresh", "task"]
    for entry in claude_skills.iterdir():
        assert entry.is_symlink()
        assert entry.resolve().is_dir()


def test_plain_file_destination_is_reported_not_crashed(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    collision = target / ".claude" / "skills" / "task"
    collision.parent.mkdir(parents=True)
    collision.write_text("not a directory\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert collision.read_text(encoding="utf-8") == "not a directory\n"
    assert ".claude/skills/task" in result["notes"]


def test_our_own_stale_symlink_is_replaced(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "mcp-index"))
    link = target / ".claude" / "skills" / "task"
    link.parent.mkdir(parents=True)
    link.symlink_to("../../.ai-badger/skills/mcp-index")

    result = adjust_skills.adjust(_context(root, target, skills=("task",)))

    assert link.resolve() == (target / ".ai-badger" / "skills" / "task").resolve()
    assert ".claude/skills/task" in result["files"]


def test_symlink_pointing_outside_the_scaffold_is_preserved(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    link = target / ".claude" / "skills" / "task"
    link.parent.mkdir(parents=True)
    link.symlink_to(elsewhere)

    result = adjust_skills.adjust(_context(root, target))

    assert link.resolve() == elsewhere.resolve()
    assert ".claude/skills/task" in result["notes"]


def test_a_directory_the_manifest_records_as_ours_is_replaced(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, manifest_targets=(("task", ".claude/skills/task"),))
    ours = target / ".claude" / "skills" / "task"
    ours.mkdir(parents=True)
    (ours / "SKILL.md").write_text("# stale copy we placed\n", encoding="utf-8")

    result = adjust_skills.adjust(_context(root, target))

    assert ours.is_symlink()
    assert ".claude/skills/task" in result["files"]


def test_a_link_to_a_skill_no_longer_delivered_is_pruned(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "call-behaviorist"))
    adjust_skills.adjust(_context(root, target, skills=("task", "call-behaviorist")))

    result = adjust_skills.adjust(_context(root, target, skills=("task",)))

    link = target / ".claude" / "skills" / "call-behaviorist"
    assert not link.exists() and not link.is_symlink()
    assert (target / ".claude" / "skills" / "task").is_symlink()
    assert "call-behaviorist" in result["notes"]
    # Lock: a legitimate prune must stay loud — see the empty-list guard below.
    assert "removed" in result["notes"]


def test_an_empty_skill_list_prunes_nothing(tmp_path, load_script, root):
    """An empty skill list is not evidence the project stopped wanting its skills (#129)."""
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task", "den-refresh"))
    adjust_skills.adjust(_context(root, target, skills=("task", "den-refresh")))

    result = adjust_skills.adjust(_context(root, target, skills=()))

    claude_skills = target / ".claude" / "skills"
    assert (claude_skills / "task").is_symlink()
    assert (claude_skills / "den-refresh").is_symlink()
    assert not result["applied"]
    assert "config.exclude.skills" in result["notes"]
    assert "2" in result["notes"]


def test_a_foreign_entry_survives_an_empty_skill_list(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path, skills=("task",))
    adjust_skills.adjust(_context(root, target, skills=("task",)))
    foreign = target / ".claude" / "skills" / "explore-codebase"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# code-review-graph\n", encoding="utf-8")

    adjust_skills.adjust(_context(root, target, skills=()))

    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# code-review-graph\n"
    assert (target / ".claude" / "skills" / "task").is_symlink()


def test_a_dangling_link_we_placed_is_pruned(tmp_path, load_script, root):
    """The defect deletion leaves behind today: a link whose target is gone."""
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    dangling = target / ".claude" / "skills" / "mcp-index"
    dangling.parent.mkdir(parents=True, exist_ok=True)
    dangling.symlink_to("../../.ai-badger/skills/mcp-index")

    adjust_skills.adjust(_context(root, target))

    assert not dangling.is_symlink()


def test_noop_when_claude_is_not_a_configured_agent(tmp_path, load_script, root):
    adjust_skills = load_script(SCRIPT)
    target = _project(tmp_path)
    context = _context(root, target)
    context["config"]["agents"] = ["copilot"]

    result = adjust_skills.adjust(context)

    assert not result["applied"]
    assert not (target / ".claude" / "skills").exists()


def test_claude_adjustment_is_registered(root):
    """The scaffold only runs adjustments declared in adjustment.json."""
    manifest = json.loads(
        (root / "features" / "claude" / "adjustments" / "adjustment.json")
        .read_text(encoding="utf-8"))

    assert manifest["agent"] == "claude"
    assert any(a["script"] == "adjust_skills.py" for a in manifest["adjustments"])
