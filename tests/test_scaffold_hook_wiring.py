"""Hook wiring: which commands scaffold.py writes into .claude/settings.json, and once only."""
from __future__ import annotations

import json
import re

from scaffold_helpers import _config
from conftest import _test_write


# ---------------------------------------------------------------------- hook wiring
def test_scaffold_wires_claude_hooks_into_settings_json(make_scaffolder):
    """Scaffolding with claude agent should wire hooks into .claude/settings.json."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["claude"]), skills=["task", "prompt-markers"])
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
    return [(re.search(r"([\w.-]+\.py)", h.get("command", "")) or [""])[0].rsplit("/", 1)[-1]
            for entry in settings.get("hooks", {}).get(event, [])
            for h in entry.get("hooks", [])]


def test_session_start_hook_is_the_wired_session_start_command(make_scaffolder):
    """The scaffolded SessionStart hook must be session_start_hook.py itself (F-07).

    Asserting only that *some* SessionStart hook exists is what let a hook that cannot
    resolve its plugin root in a consumer pass as the session-recording feature.
    """
    target = make_scaffolder.target

    make_scaffolder(config=_config(agents=["claude"]), skills=["task"]).run(
        generated_at="2026-07-24T00:00:00Z")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    scripts = _wired_scripts(settings, "SessionStart")
    assert "session_start_hook.py" in scripts, scripts


def test_consumer_settings_do_not_wire_the_plugin_only_drift_hook(make_scaffolder):
    """Drift notice runs from the plugin's own hooks.json; a consumer copy can never
    locate the plugin root, so wiring it there only looks like the feature works (F-07)."""
    target = make_scaffolder.target

    make_scaffolder(config=_config(agents=["claude"]), skills=["task"]).run(
        generated_at="2026-07-24T00:00:00Z")

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


def test_scaffold_hook_wiring_is_idempotent(make_scaffolder):
    """Running scaffold twice should not duplicate hooks in settings.json."""
    target = make_scaffolder.target

    for _ in range(2):
        scaf = make_scaffolder(config=_config(agents=["claude"]),
                               skills=["task", "prompt-markers"])
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


# ------------------------------------------------------- checkout-independent commands
_CRG_ENTRY = {
    "matcher": "",
    "hooks": [{"type": "command", "command": "code-review-graph status", "timeout": 10}],
}


def _all_commands(settings: dict) -> list:
    return [h.get("command", "")
            for event_hooks in settings.get("hooks", {}).values()
            for entry in event_hooks
            for h in entry.get("hooks", [])]


def _scaffold(make_scaffolder, target, skills=("task", "prompt-markers")):
    target.mkdir(parents=True, exist_ok=True)
    make_scaffolder(target=target, config=_config(agents=["claude"]),
                    skills=list(skills)).run(generated_at="2026-07-24T00:00:00Z")
    return json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_wired_hook_commands_carry_no_absolute_checkout_path(tmp_path, root, make_scaffolder):
    """A wired command must survive being read from another checkout of the same project."""
    target = tmp_path / "proj"

    settings = _scaffold(make_scaffolder, target)

    commands = _all_commands(settings)
    assert commands
    for cmd in commands:
        assert str(target) not in cmd, f"absolute checkout path baked into command: {cmd}"
        assert str(root) not in cmd, f"absolute framework path baked into command: {cmd}"
        assert "CLAUDE_PROJECT_DIR" in cmd, cmd


def _commands_by_event(settings: dict) -> dict:
    return {event: [h.get("command", "") for entry in event_hooks
                    for h in entry.get("hooks", [])]
            for event, event_hooks in settings.get("hooks", {}).items()}


def test_wiring_from_a_second_checkout_does_not_append_a_duplicate(tmp_path, make_scaffolder):
    """The same project scaffolded from two checkouts must leave one command per hook.

    Uniqueness is per event, not global: since #141 `stop_hook.py` is deliberately wired on
    both `Stop` and `SessionEnd`, so the same command string appearing twice across events is
    the feature, and only a repeat *within* one event is the duplication this pins.
    """
    first = tmp_path / "main-checkout"
    second = tmp_path / "worktree-checkout"

    first_settings = _scaffold(make_scaffolder, first)
    (second / ".claude").mkdir(parents=True)
    _test_write(second / ".claude" / "settings.json", json.dumps(first_settings), encoding="utf-8")

    by_event = _commands_by_event(_scaffold(make_scaffolder, second))
    for event, commands in by_event.items():
        assert len(commands) == len(set(commands)), (event, commands)
    assert by_event == _commands_by_event(first_settings)


def test_merge_collapses_a_pre_existing_absolute_command(load_script):
    """A stale absolute entry for the same script is replaced, not duplicated."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    portable = 'python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/task/scripts/session_start_hook.py"'
    existing = {"SessionStart": [
        dict(_CRG_ENTRY),
        {"matcher": "startup|resume", "hooks": [
            {"type": "command",
             "command": 'python3 "/Users/a/proj/.ai-badger/skills/task/scripts/session_start_hook.py"'},
        ]},
        {"matcher": "startup|resume", "hooks": [
            {"type": "command",
             "command": 'python3 "/Users/a/wt/.ai-badger/skills/task/scripts/session_start_hook.py"'},
        ]},
    ]}

    scaffold.merge_hooks(existing, {"SessionStart": [
        {"matcher": "startup|resume",
         "hooks": [{"type": "command", "command": portable}]},
    ]})

    commands = [h["command"] for e in existing["SessionStart"] for h in e["hooks"]]
    assert commands.count(portable) == 1, commands
    assert not [c for c in commands if "session_start_hook.py" in c and c != portable], commands


def test_merge_collapses_framework_cache_and_plugin_root_forms(load_script):
    """The framework-cache and ${CLAUDE_PLUGIN_ROOT} spellings name the same script."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    portable = 'python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py"'
    existing = {"UserPromptSubmit": [
        {"hooks": [
            {"type": "command",
             "command": 'python3 "/Users/a/.ai-badger/framework/features/common/skills/'
                        'prompt-markers/scripts/user_prompt_hook.py"'},
            {"type": "command",
             "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/'
                        'prompt-markers/scripts/user_prompt_hook.py"'},
        ]},
    ]}

    scaffold.merge_hooks(existing, {"UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": portable}]},
    ]})

    commands = [h["command"] for e in existing["UserPromptSubmit"] for h in e["hooks"]]
    assert commands == [portable], commands


def test_merge_leaves_third_party_hook_entries_untouched(load_script):
    """Hooks the framework does not own are never rewritten, reordered, or collapsed."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    existing = {"SessionStart": [
        dict(_CRG_ENTRY),
        {"matcher": "", "hooks": [{"type": "command", "command": "code-review-graph status"}]},
    ]}

    scaffold.merge_hooks(existing, {"SessionStart": [
        {"matcher": "startup|resume", "hooks": [{
            "type": "command",
            "command": 'python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/task/scripts/'
                       'session_start_hook.py"'}]},
    ]})

    assert existing["SessionStart"][:2] == [
        _CRG_ENTRY,
        {"matcher": "", "hooks": [{"type": "command", "command": "code-review-graph status"}]},
    ], existing["SessionStart"]


def test_merge_keeps_distinct_scripts_of_the_same_skill(load_script):
    """Two different scripts under one skill must not collapse into one another."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    drift = 'python3 "/Users/a/proj/.ai-badger/skills/task/scripts/drift_notice_hook.py"'
    existing = {"SessionStart": [{"hooks": [{"type": "command", "command": drift}]}]}
    session = ('python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/task/scripts/'
               'session_start_hook.py"')

    scaffold.merge_hooks(existing, {"SessionStart": [
        {"hooks": [{"type": "command", "command": session}]},
    ]})

    commands = [h["command"] for e in existing["SessionStart"] for h in e["hooks"]]
    assert commands == [drift, session], commands


def test_scaffold_no_hooks_without_claude_agent(make_scaffolder):
    """Scaffolding without claude agent should not create hooks."""
    target = make_scaffolder.target

    scaf = make_scaffolder(config=_config(agents=["hermes"]), skills=["task"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    settings_path = target / ".claude" / "settings.json"
    assert not settings_path.exists()
    hooks_json = target / ".ai-badger" / "hooks" / "hooks.json"
    assert not hooks_json.exists()
