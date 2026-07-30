"""Tests for features/claude/adjustments/adjust_mcp.py — approve declared, deny declined.

Project `.claude/settings.json` is the one MCP route beside `.mcp.json` that ai-badger owns
(ADR-0014 §0). Every settings key asserted here is documented Claude Code surface:
`enabledMcpjsonServers` / `disabledMcpjsonServers` (settings.md) and `permissions.allow` /
`permissions.deny` with `mcp__<server>__*` where deny beats allow (permissions.md).
"""
from __future__ import annotations

import json
from pathlib import Path

ADJUSTER = "features/claude/adjustments/adjust_mcp.py"


def _context(root: Path, target: Path, *, agents=("claude",), servers=("code-review-graph",),
             mcp=None) -> dict:
    config = {"agents": list(agents)}
    if mcp is not None:
        config["mcp"] = mcp
    return {
        "framework_root": root,
        "config": config,
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": [],
        "index": {},
        "mcp_servers": list(servers),
    }


def _settings(target: Path) -> dict:
    return json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _write_settings(target: Path, payload) -> Path:
    path = target / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_a_declared_server_is_approved_and_its_tools_allowed(tmp_path, root, load_script):
    """The whole point: a server ai-badger declared stops prompting."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(_context(root, target))

    assert result["applied"]
    settings = _settings(target)
    assert settings["enabledMcpjsonServers"] == ["code-review-graph"]
    assert settings["permissions"]["allow"] == ["mcp__code-review-graph__*"]


def test_nothing_is_recorded_as_an_ai_badger_owned_file(tmp_path, root, load_script):
    """`.claude/settings.json` is merged into, never owned — so it is never recorded."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(_context(root, target))

    assert result["files"] == []


def test_existing_settings_content_survives_and_is_backed_up(tmp_path, root, load_script):
    """Hook wiring, env and hand-written permission rules all survive the merge."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()
    original = {
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "true"}]}]},
        "env": {"FOO": "bar"},
        "permissions": {"allow": ["Bash(git status)"], "deny": ["Bash(rm:*)"]},
    }
    path = _write_settings(target, original)

    adjust_mcp.adjust(_context(root, target))

    settings = _settings(target)
    assert settings["hooks"] == original["hooks"]
    assert settings["env"] == original["env"]
    assert settings["permissions"]["allow"] == ["Bash(git status)", "mcp__code-review-graph__*"]
    assert settings["permissions"]["deny"] == ["Bash(rm:*)"]
    backups = list(path.parent.glob("settings.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_a_declined_server_is_denied_and_never_allowed(tmp_path, root, load_script):
    """Issue #186's Claude half: `config.mcp.decline` stops a declared server's tools."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(
        _context(root, target, mcp={"decline": ["code-review-graph"]}))

    assert result["applied"]
    settings = _settings(target)
    assert settings["permissions"]["deny"] == ["mcp__code-review-graph__*"]
    assert settings["disabledMcpjsonServers"] == ["code-review-graph"]
    assert settings["permissions"].get("allow", []) == []
    assert settings.get("enabledMcpjsonServers", []) == []


def test_declining_reaches_a_server_ai_badger_never_declared(tmp_path, root, load_script):
    """`permissions.deny` works whatever route a server arrived by — plugin, user-global, CLI."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(
        _context(root, target, servers=(), mcp={"decline": ["rider"]}))

    assert result["applied"]
    assert _settings(target)["permissions"]["deny"] == ["mcp__rider__*"]


def test_approve_false_still_denies_but_approves_nothing(tmp_path, root, load_script):
    """`mcp.approve: false` keeps the prompt; declining is a separate, louder statement."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(_context(
        root, target, servers=("code-review-graph", "hermes"),
        mcp={"approve": False, "decline": ["hermes"]}))

    assert result["applied"]
    settings = _settings(target)
    assert "enabledMcpjsonServers" not in settings
    assert settings["permissions"].get("allow", []) == []
    assert settings["permissions"]["deny"] == ["mcp__hermes__*"]


def test_not_applied_when_claude_is_not_configured(tmp_path, root, load_script):
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(_context(root, target, agents=("hermes",)))

    assert not result["applied"]
    assert not (target / ".claude").exists()


def test_not_applied_when_nothing_is_declared_or_declined(tmp_path, root, load_script):
    """No settings.json is created for a project with no MCP servers at all."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()

    result = adjust_mcp.adjust(_context(root, target, servers=()))

    assert not result["applied"]
    assert not (target / ".claude" / "settings.json").exists()


def test_a_second_run_adds_nothing_and_rewrites_nothing(tmp_path, root, load_script):
    """Idempotent: the same approval is not appended twice and the file is not rewritten."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()
    adjust_mcp.adjust(_context(root, target))
    first = (target / ".claude" / "settings.json").read_bytes()

    result = adjust_mcp.adjust(_context(root, target))

    assert not result["applied"]
    assert (target / ".claude" / "settings.json").read_bytes() == first
    assert list((target / ".claude").glob("settings.json.bak-*")) == []


def test_unparseable_settings_are_never_rewritten(tmp_path, root, load_script):
    """An unparseable project settings.json is left byte-identical and reported."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()
    original = b'{"permissions":{"deny":["Bash"]}},,,'
    path = _write_settings(target, original)

    result = adjust_mcp.adjust(_context(root, target))

    assert not result["applied"]
    assert path.read_bytes() == original
    assert "refused" in result["notes"]


def test_permissions_that_is_not_a_mapping_is_refused(tmp_path, root, load_script):
    """`permissions: []` is someone else's shape; refuse rather than clobber it."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()
    path = _write_settings(target, {"permissions": []})
    original = path.read_bytes()

    result = adjust_mcp.adjust(_context(root, target))

    assert not result["applied"]
    assert path.read_bytes() == original
    assert "refused" in result["notes"]


def test_an_allow_key_that_is_not_a_list_is_left_alone_and_reported(tmp_path, root, load_script):
    """One unusable key must not cost the others: deny still lands, allow is reported."""
    adjust_mcp = load_script(ADJUSTER)
    target = tmp_path / "proj"
    target.mkdir()
    _write_settings(target, {"permissions": {"allow": "everything"}})

    result = adjust_mcp.adjust(
        _context(root, target, servers=("a",), mcp={"decline": ["b"]}))

    settings = _settings(target)
    assert settings["permissions"]["allow"] == "everything"
    assert settings["permissions"]["deny"] == ["mcp__b__*"]
    assert "allow" in result["notes"]


def test_the_tool_pattern_is_the_documented_server_wildcard(load_script):
    """`mcp__<server>__*` — the form permissions.md documents for allow and deny rules."""
    adjust_mcp = load_script(ADJUSTER)

    assert adjust_mcp.tool_pattern("code-review-graph") == "mcp__code-review-graph__*"


# ── config.mcp, the project-side signal the adjuster reads ────────────────────

def _validate(root, load_script, config_fragment):
    bl = load_script("engine/badger_lib.py")
    schema = bl.load_json(root / "schemas" / "config.schema.json")
    config = {
        "frameworkVersion": "0.1.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": ["claude"],
    }
    config.update(config_fragment)
    return bl.validate(config, schema)


def test_config_mcp_accepts_approve_and_decline(root, load_script):
    assert _validate(root, load_script,
                     {"mcp": {"approve": False, "decline": ["rider"]}}) == []


def test_config_mcp_is_optional(root, load_script):
    assert _validate(root, load_script, {}) == []


def test_config_mcp_refuses_an_unknown_key(root, load_script):
    assert _validate(root, load_script, {"mcp": {"prune": ["rider"]}}) != []


def test_config_mcp_refuses_a_blank_declined_name(root, load_script):
    assert _validate(root, load_script, {"mcp": {"decline": [""]}}) != []
