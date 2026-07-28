"""Wiring for the commit-reminder hook: PostToolUse matcher must survive scaffolding.

Unlike SessionStart/UserPromptSubmit, this hook only makes sense scoped to edit-shaped tool
calls. The wiring's own auto-glob fallback (hook_wiring.py) never carries a matcher, so this
hook's manifest entry must have a matching source hooks.json entry with its own `matcher` —
these tests pin that it is actually preserved end to end, for both Claude and Copilot.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config

COMMIT_REMINDER_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"


def test_scaffold_wires_commit_reminder_posttooluse_with_matcher(make_scaffolder):
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["commit-reminder"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    post_tool_use = settings["hooks"]["PostToolUse"]
    assert len(post_tool_use) == 1
    entry = post_tool_use[0]
    assert entry.get("matcher") == COMMIT_REMINDER_MATCHER

    commands = [h["command"] for h in entry["hooks"]]
    assert len(commands) == 1
    command = commands[0]
    assert command.rstrip('"').endswith("commit_reminder_hook.py")
    assert "${CLAUDE_PROJECT_DIR}" in command
    assert "${CLAUDE_PLUGIN_ROOT}" not in command


def test_scaffold_commit_reminder_wiring_is_idempotent(make_scaffolder):
    target = make_scaffolder.target

    for _ in range(2):
        scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["commit-reminder"])
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    post_tool_use = settings["hooks"]["PostToolUse"]
    total_commands = sum(len(entry.get("hooks", [])) for entry in post_tool_use)
    assert total_commands == 1, f"Duplicate PostToolUse hooks: {total_commands}"


def test_copilot_wires_commit_reminder_with_matcher(tmp_path, load_script, root):
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    context = {
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["commit-reminder"],
    }
    result = adjust_hooks.adjust(context)
    assert result["applied"]

    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    post_tool_use = hooks["hooks"]["postToolUse"]
    assert len(post_tool_use) == 1
    entry = post_tool_use[0]
    assert entry["bash"].rsplit("/", 1)[-1] == "commit_reminder_hook.py"
    assert entry.get("matcher") == COMMIT_REMINDER_MATCHER


def test_badger_lib_declares_commit_reminder_as_a_default_skill(load_script):
    bl = load_script("engine/badger_lib.py")
    assert bl.skill_scope("commit-reminder") == bl.SKILL_SCOPE_DEFAULT
    assert "commit-reminder" in bl.default_skill_names()
