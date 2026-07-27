"""Hook wiring: which commands scaffold.py writes into .claude/settings.json, and once only."""
from __future__ import annotations

import json

from scaffold_helpers import _config


# ---------------------------------------------------------------------- hook wiring
def test_scaffold_wires_claude_hooks_into_settings_json(tmp_path, load_script, root):
    """Scaffolding with claude agent should wire hooks into .claude/settings.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task", "prompt-markers"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    # .claude/settings.json should exist with hooks
    settings_path = target / ".claude" / "settings.json"
    assert settings_path.exists(), ".claude/settings.json not created"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" in settings

    hooks = settings["hooks"]
    # SessionStart hook (session-start-tracking) should be wired
    assert "SessionStart" in hooks
    # UserPromptSubmit hook (prompt-markers) should be wired
    assert "UserPromptSubmit" in hooks

    # Verify paths point to .ai-badger/skills/ not framework paths
    for event_hooks in hooks.values():
        for entry in event_hooks:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                assert "${CLAUDE_PLUGIN_ROOT}" not in cmd, \
                    f"Unresolved plugin root variable in command: {cmd}"
                assert ".ai-badger/skills/" in cmd or "user_prompt_hook" in cmd

    # .ai-badger/hooks/hooks.json should also exist
    hooks_json = target / ".ai-badger" / "hooks" / "hooks.json"
    assert hooks_json.exists(), ".ai-badger/hooks/hooks.json not created"


def _wired_scripts(settings: dict, event: str) -> list:
    """The script each wired command for one event ends in.

    Compared by trailing filename, never by substring of the whole command: a
    command embeds an absolute path, and under pytest that path carries the test's
    own name.
    """
    return [h.get("command", "").rstrip('"').rsplit("/", 1)[-1]
            for entry in settings.get("hooks", {}).get(event, [])
            for h in entry.get("hooks", [])]


def test_session_start_hook_is_the_wired_session_start_command(tmp_path, load_script, root):
    """The scaffolded SessionStart hook must be session_start_hook.py itself (F-07).

    Asserting only that *some* SessionStart hook exists is what let a hook that cannot
    resolve its plugin root in a consumer pass as the session-recording feature.
    """
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaffold.Scaffolder(root=root, target=target, config=_config(agents=["claude"]),
                        skills=["task"], install=False).run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    scripts = _wired_scripts(settings, "SessionStart")
    assert "session_start_hook.py" in scripts, scripts


def test_consumer_settings_do_not_wire_the_plugin_only_drift_hook(tmp_path, load_script, root):
    """Drift notice runs from the plugin's own hooks.json; a consumer copy can never
    locate the plugin root, so wiring it there only looks like the feature works (F-07)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaffold.Scaffolder(root=root, target=target, config=_config(agents=["claude"]),
                        skills=["task"], install=False).run(generated_at="2026-07-24T00:00:00Z")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "drift_notice_hook.py" not in _wired_scripts(settings, "SessionStart")


def test_plugin_registers_drift_notice_from_its_own_hooks_json(root):
    """The plugin-provided hooks.json is what actually fires drift notice for consumers."""
    plugin_hooks = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    commands = [h["command"]
                for entry in plugin_hooks["hooks"]["SessionStart"]
                for h in entry["hooks"]]
    assert any("${CLAUDE_PLUGIN_ROOT}" in cmd and "drift_notice_hook.py" in cmd
               for cmd in commands), commands


def test_scaffold_hook_wiring_is_idempotent(tmp_path, load_script, root):
    """Running scaffold twice should not duplicate hooks in settings.json."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    for _ in range(2):
        scaf = scaffold.Scaffolder(
            root=root, target=target,
            config=_config(agents=["claude"]),
            skills=["task", "prompt-markers"], install=False,
        )
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings_path = target / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    # Count total hook entries — should be exactly 1 per event
    for event, event_hooks in settings.get("hooks", {}).items():
        total_commands = sum(
            len(h.get("hooks", []))
            for entry in event_hooks
            for h in [entry]
        )
        assert total_commands == 1, f"Duplicate hooks for {event}: {total_commands}"


def test_scaffold_hook_dedup_does_not_duplicate_multi_hook_entries(tmp_path, load_script, root):
    """Dedup must not re-append an entry when only some of its hooks are new.

    Regression: the old code checked each inner hook individually but appended
    the entire outer entry, so an entry with N hooks could be appended with
    hooks that already existed in another entry — producing duplicates.
    """
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    # existing: one entry with hook-a
    existing = {"SessionStart": [
        {"matcher": "", "hooks": [{"type": "command", "command": "hook-a"}]},
    ]}
    # new: entry with hook-a + hook-b — only hook-b should be appended
    new = {"SessionStart": [
        {"matcher": "m", "hooks": [
            {"type": "command", "command": "hook-a"},
            {"type": "command", "command": "hook-b"},
        ]},
    ]}
    scaffold.merge_hooks(existing, new)
    entries = existing["SessionStart"]
    all_cmds = [h["command"] for e in entries for h in e["hooks"]]
    assert all_cmds.count("hook-a") == 1, f"hook-a duplicated: {all_cmds}"
    assert "hook-b" in all_cmds


def test_scaffold_no_hooks_without_claude_agent(tmp_path, load_script, root):
    """Scaffolding without claude agent should not create hooks."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["hermes"]),
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings_path = target / ".claude" / "settings.json"
    assert not settings_path.exists()
    hooks_json = target / ".ai-badger" / "hooks" / "hooks.json"
    assert not hooks_json.exists()
