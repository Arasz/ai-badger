"""Claude arm of the `tools` feature: one marked PreToolUse Bash handler in .claude/settings.json.

ADR-0039. The handler composes with HookWiring's framework hooks and the operator's own, and
every opt-out route removes it without leaving an empty group, event or `hooks` key behind.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARM = "features/claude/adjustments/adjust_tools.py"
COMMAND = "env AI_BADGER_TOOL=rtk RTK_TELEMETRY_DISABLED=1 sh -c 'rtk hook claude'"
OTHER = "env AI_BADGER_TOOL=other OTHER_TELEMETRY_DISABLED=1 sh -c 'other hook claude'"
MARKER = "AI_BADGER_TOOL="
SKILLS_WITH_HOOKS = ("git-work", "commit-reminder")


def _context(target: Path, commands=(COMMAND,), agents=("claude",)) -> dict:
    tools = {}
    for command in commands:
        name = command.split(MARKER, 1)[1].split()[0]
        tools[name] = {"meta": {"name": name}, "check_ok": None, "agents": {
            "claude": {"mode": "native", "arg": "claude", "command": command}}}
    return {"framework_root": ROOT, "target": target, "target_dir": target / ".ai-badger",
            "config": {"agents": list(agents)}, "tools": tools}


def _settings(target: Path) -> Path:
    return target / ".claude" / "settings.json"


def _write(target: Path, data) -> Path:
    path = _settings(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2) + "\n")
    return path


def _marked(data: dict) -> list:
    return [(group.get("matcher"), handler)
            for groups in (data.get("hooks") or {}).values() for group in groups
            for handler in group.get("hooks", []) if MARKER in handler.get("command", "")]


def _backups(target: Path) -> list:
    return sorted(_settings(target).parent.glob("settings.json.bak-*"))


@pytest.fixture(name="arm")
def arm_fixture(load_script):
    return load_script(ARM)


# -- s6-a1: the merge ---------------------------------------------------------------------

def test_one_marked_bash_handler_is_added_beside_user_keys_and_hooks(arm, tmp_path):
    user_hook = {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo mine"}]}
    _write(tmp_path, {"model": "opus", "hooks": {"PreToolUse": [user_hook]}})

    result = arm.adjust(_context(tmp_path))

    data = json.loads(_settings(tmp_path).read_text())
    assert result["applied"] is True
    assert result["files"] == []
    assert data["model"] == "opus"
    assert data["hooks"]["PreToolUse"][0] == user_hook
    assert _marked(data) == [("Bash", {"type": "command", "command": COMMAND, "timeout": 5})]


def test_the_marked_group_is_moved_last_after_a_framework_group_is_appended(arm, tmp_path):
    arm.adjust(_context(tmp_path))
    data = json.loads(_settings(tmp_path).read_text())
    framework = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo guard"}]}
    data["hooks"]["PreToolUse"].append(framework)
    _write(tmp_path, data)

    arm.adjust(_context(tmp_path))

    groups = json.loads(_settings(tmp_path).read_text())["hooks"]["PreToolUse"]
    assert groups[0] == framework
    assert [h["command"] for h in groups[-1]["hooks"]] == [COMMAND]
    assert len(_marked(json.loads(_settings(tmp_path).read_text()))) == 1


def test_a_rerun_changes_no_byte_and_leaves_no_backup(arm, tmp_path):
    _write(tmp_path, {"model": "opus"})
    arm.adjust(_context(tmp_path))
    before, backups = _settings(tmp_path).read_bytes(), _backups(tmp_path)

    arm.adjust(_context(tmp_path))

    assert _settings(tmp_path).read_bytes() == before
    assert _backups(tmp_path) == backups


def test_a_handler_already_last_is_left_untouched(arm, tmp_path):
    arm.adjust(_context(tmp_path))
    before = _settings(tmp_path).read_bytes()

    arm.adjust(_context(tmp_path))

    assert _settings(tmp_path).read_bytes() == before
    assert _backups(tmp_path) == []


def test_a_stale_marked_command_is_replaced_not_duplicated(arm, tmp_path):
    stale = COMMAND.replace("rtk hook claude", "rtk hook old")
    _write(tmp_path, {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": stale, "timeout": 5}]}]}})

    arm.adjust(_context(tmp_path))

    assert [h["command"] for _m, h in _marked(json.loads(_settings(tmp_path).read_text()))] \
        == [COMMAND]


def test_every_tool_with_a_claude_arm_is_wired(arm, tmp_path):
    arm.adjust(_context(tmp_path, commands=(COMMAND, OTHER)))

    commands = [h["command"] for _m, h in _marked(json.loads(_settings(tmp_path).read_text()))]
    assert sorted(commands) == sorted([COMMAND, OTHER])


def test_no_tools_and_no_file_writes_nothing(arm, tmp_path):
    result = arm.adjust(_context(tmp_path, commands=()))

    assert result["applied"] is False
    assert not _settings(tmp_path).exists()


# -- s6-a2: opt-out and refusal -----------------------------------------------------------

@pytest.mark.parametrize("original", [
    {"model": "opus"},
    {"model": "opus", "hooks": {"Stop": []}},
    {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "echo mine"}]}]}},
], ids=["no-hooks-key", "operator-empty-event", "user-bash-group"])
def test_opt_out_restores_the_settings_exactly(arm, tmp_path, original):
    _write(tmp_path, original)
    arm.adjust(_context(tmp_path))

    arm.adjust(_context(tmp_path, commands=()))

    assert json.loads(_settings(tmp_path).read_text()) == original


def test_an_empty_hooks_key_with_nothing_to_remove_is_left_alone(arm, tmp_path):
    _write(tmp_path, {"model": "opus", "hooks": {}})
    before = _settings(tmp_path).read_bytes()

    arm.adjust(_context(tmp_path, commands=()))

    assert _settings(tmp_path).read_bytes() == before


def test_opt_out_drops_only_the_marked_handler_from_a_shared_group(arm, tmp_path):
    mine = {"type": "command", "command": "echo mine"}
    marked = {"type": "command", "command": COMMAND, "timeout": 5}
    _write(tmp_path, {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine, marked]}]}})

    arm.adjust(_context(tmp_path, commands=()))

    assert json.loads(_settings(tmp_path).read_text()) == {
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine]}]}}


@pytest.mark.parametrize("content", [
    "{broken",
    "[]",
    '{"hooks": []}',
    '{"hooks": {"PreToolUse": {}}}',
    '{"hooks": {"PreToolUse": [1]}}',
    '{"hooks": {"PreToolUse": [{"hooks": "x"}]}}',
], ids=["not-json", "not-a-mapping", "hooks-list", "event-mapping", "group-int", "handlers-str"])
def test_malformed_settings_are_left_untouched_with_a_note(arm, tmp_path, content):
    _write(tmp_path, content)

    result = arm.adjust(_context(tmp_path))

    assert result["applied"] is False
    assert result["notes"]
    assert _settings(tmp_path).read_text() == content
    assert _backups(tmp_path) == []


def test_the_adjustment_is_declared_with_cleanup_on_deselection():
    manifest = json.loads((ROOT / "features/claude/adjustments/adjustment.json").read_text())

    [entry] = [a for a in manifest["adjustments"] if a["script"] == "adjust_tools.py"]
    assert entry["feature"] == "tools"
    assert entry["cleanupOnDeselection"] is True


# -- the whole scaffold -------------------------------------------------------------------

def _scaffold(load_script, root, target, monkeypatch, config):
    import badger_lib as bl  # pylint: disable=import-outside-toplevel
    from scaffold_helpers import build_scaffolder  # pylint: disable=import-outside-toplevel
    index = load_script("tooling/index_build.py").build_index(root)
    monkeypatch.setattr(bl, "read_index", lambda _: index)
    module = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    build_scaffolder(module, root=root, target=target, config=config,
                     skills=list(SKILLS_WITH_HOOKS)).run()
    return json.loads(_settings(target).read_text())


def _base_config(agents=("claude",), tools=None):
    from scaffold_helpers import _config  # pylint: disable=import-outside-toplevel
    config = _config(stacks=["python"], agents=list(agents))
    if tools is not None:
        config["tools"] = tools
    return config


@pytest.mark.parametrize("route", [
    {},
    {"tools": {}},
    {"tools": {"rtk": {"hooks": []}}},
    {"agents": ["codex"]},
], ids=["still-opted-in", "tool-removed", "claude-not-in-hooks", "claude-deselected"])
def test_a_scaffold_removes_the_handler_an_earlier_native_release_wired(
        load_script, root, tmp_path, monkeypatch, route):
    """rtk is propose-only for Claude, so a handler 0.194.0 wired goes on every refresh route."""
    before = _scaffold(load_script, root, tmp_path, monkeypatch, _base_config())
    before["model"] = "opus"
    before["hooks"].setdefault("Stop", []).append(
        {"hooks": [{"type": "command", "command": "echo operator"}]})
    wired = json.loads(json.dumps(before))
    wired["hooks"].setdefault("PreToolUse", []).append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": COMMAND, "timeout": 5}]})
    _write(tmp_path, wired)
    config = _base_config(tools={"rtk": {"hooks": ["claude"]}})
    config.update(route)

    after = _scaffold(load_script, root, tmp_path, monkeypatch, config)

    assert _marked(after) == []
    assert after == before


# -- propose mode: the rewrite escapes permissions.ask, so nothing is wired ------------------

def test_a_propose_arm_removes_the_wired_handler_and_says_why(arm, tmp_path):
    _write(tmp_path, {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": COMMAND}]}]}})
    context = _context(tmp_path)
    context["tools"]["rtk"]["agents"]["claude"] = {"mode": "propose", "arg": "claude"}

    result = arm.adjust(context)

    assert _marked(json.loads(_settings(tmp_path).read_text())) == []
    assert "permissions.ask" in result["notes"]
    # A local `rtk init` wires no Claude hook: only the user-wide init does, so say so.
    assert "`rtk init -g`" in result["notes"] and "user-wide" in result["notes"]
    assert "--agent" not in result["notes"] and "config.tools.rtk.hooks" in result["notes"]


def test_a_propose_arm_on_a_fresh_project_writes_no_settings_but_still_notes(arm, tmp_path):
    context = _context(tmp_path, commands=())
    context["tools"] = {"rtk": {"meta": {"name": "rtk"}, "check_ok": None, "agents": {
        "claude": {"mode": "propose", "arg": "claude"}}}}

    result = arm.adjust(context)

    assert not _settings(tmp_path).exists()
    assert "permissions.ask" in result["notes"]
