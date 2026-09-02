"""Wiring for the test-economy hook: the PostToolUse Bash matcher must survive scaffolding.

The hook only makes sense scoped to shell-shaped tool calls. The wiring's own auto-glob
fallback (hook_wiring.py) never carries a matcher, so the manifest entry must have a matching
source hooks.json entry with its own `matcher` — these tests pin that it is preserved end to
end, for Claude and Copilot, and that it coexists with the commit-reminder matcher.
"""
from __future__ import annotations

import json
import re

from scaffold_helpers import _config

TEST_ECONOMY_MATCHER = "Bash"


def test_scaffold_wires_test_economy_posttooluse_with_matcher(make_scaffolder):
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["test-economy"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    post_tool_use = settings["hooks"]["PostToolUse"]
    assert len(post_tool_use) == 1
    entry = post_tool_use[0]
    assert entry.get("matcher") == TEST_ECONOMY_MATCHER

    commands = [h["command"] for h in entry["hooks"]]
    assert len(commands) == 1
    command = commands[0]
    assert 'suite_economy_hook.py"' in command
    assert "${CLAUDE_PROJECT_DIR}" in command
    assert "${CLAUDE_PLUGIN_ROOT}" not in command


def test_scaffold_test_economy_wiring_is_idempotent(make_scaffolder):
    target = make_scaffolder.target

    for _ in range(2):
        scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["test-economy"])
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    post_tool_use = settings["hooks"]["PostToolUse"]
    total_commands = sum(len(entry.get("hooks", [])) for entry in post_tool_use)
    assert total_commands == 1, f"Duplicate PostToolUse hooks: {total_commands}"


def test_test_economy_and_commit_reminder_matchers_coexist(make_scaffolder):
    """Two PostToolUse hook families, two matchers: edit-shaped for the reminder, Bash for
    the economy. A scaffold that collapsed them into one entry would drop one behavior."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]),
                           skills=["test-economy", "commit-reminder"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = {entry.get("matcher") for entry in settings["hooks"]["PostToolUse"]}
    assert {"Edit|Write|MultiEdit|NotebookEdit", "Bash"} <= matchers


def test_copilot_wires_test_economy_with_lowercase_bash_matcher(tmp_path, load_script, root):
    """Copilot matchers are case-sensitive against runtime tool names (lowercase `bash`);
    the manifest's per-agent matcher override must survive the rewrite."""
    adjust_hooks = load_script("features/copilot/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)

    context = {
        "framework_root": root,
        "config": {"agents": ["copilot"], "stacks": ["python"]},
        "feature_dir": root / "features" / "copilot" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["test-economy"],
    }
    result = adjust_hooks.adjust(context)
    assert result["applied"]

    hooks = json.loads(
        (target / ".github" / "hooks" / "ai-badger-hooks.json").read_text(encoding="utf-8"))
    post_tool_use = hooks["hooks"]["postToolUse"]

    def _script_name(bash: str) -> str:
        """The guarded row's script: the if -f arm's quoted path tail (the guard wraps
        every rewritten row, so the bare tail idiom reads the skip message instead)."""
        match = re.search(r'-f "([^"]+)"', bash)
        return (match.group(1) if match else bash.rstrip('"')).rsplit("/", 1)[-1]

    economy_entries = [
        e for e in post_tool_use
        if _script_name(e["bash"]) == "suite_economy_hook.py"
    ]
    assert economy_entries, post_tool_use
    assert any(e.get("matcher") == "bash|Bash" for e in economy_entries)


def test_manifest_entry_names_all_three_agents(root):
    manifest = json.loads(
        (root / "features" / "common" / "hooks" / "hooks-manifest.json")
        .read_text(encoding="utf-8"))
    entry = next(h for h in manifest["hooks"] if h["name"] == "test-run-economy")
    assert set(entry["agents"]) == {"claude", "hermes", "copilot"}
    assert entry["agents"]["hermes"]["method"] == "post_tool_call"
